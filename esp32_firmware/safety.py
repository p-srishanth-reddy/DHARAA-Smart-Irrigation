# DHARAA Local Safety Module for ESP32
import time
import config

try:
    import machine
    MICROPYTHON = True
except ImportError:
    MICROPYTHON = False

class SafetyManager:
    def __init__(self, relay_pin_num=config.PIN_RELAY, led_pin_num=config.PIN_STATUS_LED):
        self.relay_pin = None
        self.led_pin = None
        self.pump_state = 0         # 0 = OFF, 1 = ON
        self.pump_start_time = None
        self.last_off_time = 0
        self.emergency_stop = False
        self.mode = "AUTO"          # "AUTO" or "MANUAL"

        if MICROPYTHON:
            try:
                self.relay_pin = machine.Pin(relay_pin_num, machine.Pin.OUT)
                self.led_pin = machine.Pin(led_pin_num, machine.Pin.OUT)
            except Exception as e:
                print("Safety GPIO setup error:", e)

        # Enforce startup OFF guarantee
        self.force_pump_off("STARTUP_INIT")

    def force_pump_off(self, reason="SAFETY_STOP"):
        """
        Immediately drives relay LOW (pump OFF) and updates internal state.
        """
        if self.relay_pin:
            self.relay_pin.value(0)
        if self.led_pin:
            self.led_pin.value(0)

        if self.pump_state == 1:
            self.last_off_time = time.time()
            print(f"[SAFETY] Pump switched OFF. Reason: {reason}")

        self.pump_state = 0
        self.pump_start_time = None

    def start_pump(self, reason="COMMAND_START"):
        """
        Attempts to turn pump ON after validating local safety pre-flight checks.
        """
        can_run, fault_msg = self.can_run_pump()
        if not can_run:
            print(f"[SAFETY REJECT] Cannot start pump: {fault_msg}")
            return False, fault_msg

        if self.relay_pin:
            self.relay_pin.value(1)
        if self.led_pin:
            self.led_pin.value(1)

        self.pump_state = 1
        self.pump_start_time = time.time()
        print(f"[SAFETY] Pump switched ON. Reason: {reason}")
        return True, "OK"

    def can_run_pump(self, current_moisture=None, is_raining=False):
        """
        Pre-flight safety checks:
        1. Emergency stop active
        2. Cooldown period elapsed
        3. Rain sensor wet
        4. Sensor health
        """
        now = time.time()

        if self.emergency_stop:
            return False, "Emergency stop is active"

        if is_raining:
            return False, "Local rain sensor detected moisture on surface"

        if current_moisture is not None and (current_moisture < 0 or current_moisture > 100):
            return False, "Moisture reading invalid"

        # Check cooldown
        if self.pump_state == 0 and self.last_off_time > 0:
            elapsed_cooldown = now - self.last_off_time
            if elapsed_cooldown < config.COOLDOWN_SECONDS:
                remaining = int(config.COOLDOWN_SECONDS - elapsed_cooldown)
                return False, f"Cooldown in effect ({remaining}s remaining)"

        return True, "OK"

    def check_runtime_watchdog(self):
        """
        Local runtime limit watchdog: If pump has run longer than MAX_RUNTIME_SECONDS,
        forces pump OFF locally even if network connection to backend is broken!
        """
        if self.pump_state == 1 and self.pump_start_time is not None:
            runtime = time.time() - self.pump_start_time
            if runtime >= config.MAX_RUNTIME_SECONDS:
                self.force_pump_off("MAX_RUNTIME_LOCAL_WATCHDOG_EXCEEDED")
                return True
        return False

    def trigger_emergency_stop(self):
        self.emergency_stop = True
        self.force_pump_off("EMERGENCY_STOP_TRIGGERED")
        print("[SAFETY CRITICAL] EMERGENCY STOP ACTIVATED. All irrigation locked out.")

    def clear_emergency_stop(self):
        self.emergency_stop = False
        print("[SAFETY] Emergency stop cleared by operator.")
