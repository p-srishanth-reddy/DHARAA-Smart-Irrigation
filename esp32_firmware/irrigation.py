# DHARAA Irrigation Policy Module for MicroPython
# Enhanced with AI quantity-based stopping via FlowTracker.
# All existing command types and behaviour are fully preserved.

import config

try:
    import ujson as json
except ImportError:
    import json

from flow_tracker import FlowTracker

class IrrigationController:
    def __init__(self, safety_manager):
        self.safety      = safety_manager
        self.mode        = "AUTO"   # "AUTO" or "MANUAL"
        self.flow        = FlowTracker()

    def execute_command(self, cmd_dict):
        """
        Process a command dictionary:
        { 'id': 1, 'type': 'ON'|'OFF'|'EMERGENCY_STOP'|'SET_MODE_AUTO'|'SET_MODE_MANUAL',
          'payload': '...' }

        For AI-guided ON commands, payload is a JSON string containing:
          { "target_pulses": int, "target_ml": float, "reason": str, ... }
        For standard ON commands, payload may be a plain reason string.
        """
        if not cmd_dict:
            return False

        cmd_type = cmd_dict.get("type")
        cmd_id   = cmd_dict.get("id")
        payload  = cmd_dict.get("payload", "")
        print(f"[Irrigation] Executing command #{cmd_id}: {cmd_type}")

        if cmd_type == "EMERGENCY_STOP":
            self.mode = "MANUAL"  # Lock out auto-mode
            self.flow.end_session()
            self.safety.trigger_emergency_stop()
            return True

        elif cmd_type == "SET_MODE_AUTO":
            self.mode = "AUTO"
            return True

        elif cmd_type == "SET_MODE_MANUAL":
            self.mode = "MANUAL"
            return True

        elif cmd_type == "ON":
            self.mode = "MANUAL"
            ok, msg = self.safety.start_pump("COMMAND_MANUAL_ON")
            if ok:
                # Parse target_pulses from payload (JSON or plain string)
                target_pulses = 0
                if payload:
                    try:
                        payload_data  = json.loads(payload)
                        target_pulses = int(payload_data.get("target_pulses", 0) or 0)
                        if target_pulses > 0:
                            print(f"[Irrigation] AI target: {target_pulses} pulses"
                                  f" (~{target_pulses / 450.0:.2f} L)")
                    except Exception:
                        pass  # Plain string payload — no target, time-based only
                self.flow.start_session(target_pulses=target_pulses)
            return ok

        elif cmd_type == "OFF":
            self.mode = "MANUAL"
            self.flow.end_session()
            self.safety.force_pump_off("COMMAND_MANUAL_OFF")
            return True

        return False

    def check_quantity_target(self, new_pulses_this_interval):
        """
        Called each loop tick with pulses accumulated since last tick.
        Adds to session total and stops pump if AI target is reached.
        Returns True if the pump was stopped due to quantity target.
        """
        if self.safety.pump_state != 1:
            return False

        self.flow.add_pulses(new_pulses_this_interval)

        if self.flow.has_target() and self.flow.target_reached():
            total, ml = self.flow.end_session()
            self.safety.force_pump_off(
                f"AI_QUANTITY_TARGET_REACHED_{total}_PULSES_{ml}ml"
            )
            print(f"[Irrigation] AI quantity target reached: {total} pulses, {ml} ml delivered.")
            return True

        return False

    def check_automated_rules(self, moisture, rain_detected, sensor_status):
        """
        Local fallback automated hysteresis loop in AUTO mode:
        - If moisture < 35%: Turn ON (subject to cooldown, rain, safety)
        - If moisture >= 45%: Turn OFF
        Unchanged from original firmware.
        """
        if self.mode != "AUTO":
            return

        if self.safety.pump_state == 0:
            if moisture is not None and moisture < config.MOISTURE_START_THRESHOLD:
                if sensor_status == "OK" and not rain_detected:
                    ok, _ = self.safety.start_pump(
                        f"LOCAL_AUTO_THRESHOLD_CROSS_{moisture}%"
                    )
                    if ok:
                        self.flow.start_session(target_pulses=0)  # time-based

        elif self.safety.pump_state == 1:
            if moisture is not None and moisture >= config.MOISTURE_STOP_THRESHOLD:
                self.flow.end_session()
                self.safety.force_pump_off(
                    f"LOCAL_AUTO_RECOVERY_TARGET_{moisture}%"
                )

    def on_pump_stopped(self):
        """
        Call whenever the safety watchdog or any external mechanism stops the pump,
        to ensure the flow session is cleanly ended.
        """
        if self.flow.session_active:
            self.flow.end_session()
