# DHARAA Irrigation Policy Module for MicroPython
import config

class IrrigationController:
    def __init__(self, safety_manager):
        self.safety = safety_manager
        self.mode = "AUTO"  # "AUTO" or "MANUAL"

    def execute_command(self, cmd_dict):
        """
        Process a command dictionary: { 'id': 1, 'type': 'ON'|'OFF'|'EMERGENCY_STOP'|'SET_MODE_AUTO'|'SET_MODE_MANUAL' }
        """
        if not cmd_dict:
            return False

        cmd_type = cmd_dict.get("type")
        cmd_id = cmd_dict.get("id")
        print(f"[Irrigation] Executing received command #{cmd_id}: {cmd_type}")

        if cmd_type == "EMERGENCY_STOP":
            self.mode = "MANUAL"  # Lock out auto-mode
            self.safety.trigger_emergency_stop()
            return True

        elif cmd_type == "SET_MODE_AUTO":
            self.mode = "AUTO"
            return True

        elif cmd_type == "SET_MODE_MANUAL":
            self.mode = "MANUAL"
            return True

        elif cmd_type == "ON":
            # Manual ON should explicitly set mode to MANUAL to prevent
            # the auto-logic from fighting if moisture is actually high
            self.mode = "MANUAL"
            ok, msg = self.safety.start_pump("COMMAND_MANUAL_ON")
            return ok

        elif cmd_type == "OFF":
            self.mode = "MANUAL" # Enter manual mode to inhibit auto-restart
            self.safety.force_pump_off("COMMAND_MANUAL_OFF")
            return True

        return False


    def check_automated_rules(self, moisture, rain_detected, sensor_status):
        """
        Local fallback automated hysteresis loop in AUTO mode:
        - If moisture < 35%: Turn ON (subject to cooldown, rain, safety)
        - If moisture >= 45%: Turn OFF
        """
        if self.mode != "AUTO":
            return

        if self.safety.pump_state == 0:
            if moisture is not None and moisture < config.MOISTURE_START_THRESHOLD:
                if sensor_status == "OK" and not rain_detected:
                    self.safety.start_pump(f"LOCAL_AUTO_THRESHOLD_CROSS_{moisture}%")

        elif self.safety.pump_state == 1:
            if moisture is not None and moisture >= config.MOISTURE_STOP_THRESHOLD:
                self.safety.force_pump_off(f"LOCAL_AUTO_RECOVERY_TARGET_{moisture}%")
