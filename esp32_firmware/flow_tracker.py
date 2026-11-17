# DHARAA Flow Tracker — MicroPython
# Maintains a session-level cumulative flow pulse counter,
# separate from the per-interval counter in SensorManager.
# Resets only when the pump stops; allows quantity-based stopping.

class FlowTracker:
    def __init__(self):
        self.session_pulses = 0      # Cumulative pulses this pump session
        self.target_pulses  = 0      # 0 = no target (time-based only)
        self.session_active = False

    def start_session(self, target_pulses=0):
        """Call when pump turns ON."""
        self.session_pulses = 0
        self.target_pulses  = int(target_pulses) if target_pulses else 0
        self.session_active = True
        print(f"[FlowTracker] Session started. Target: {self.target_pulses} pulses"
              f" (~{self.target_pulses / 450.0:.2f} L)" if self.target_pulses else
              f"[FlowTracker] Session started. Time-based mode (no pulse target).")

    def add_pulses(self, new_pulses):
        """Add pulses from the latest telemetry interval."""
        if self.session_active and new_pulses > 0:
            self.session_pulses += int(new_pulses)

    def has_target(self):
        """Return True if a pulse target is set."""
        return self.target_pulses > 0

    def target_reached(self):
        """Return True when accumulated pulses meet or exceed target."""
        if not self.has_target():
            return False
        return self.session_pulses >= self.target_pulses

    def end_session(self):
        """Call when pump stops for any reason."""
        total = self.session_pulses
        ml    = round(total / 450.0 * 1000.0, 1) if total > 0 else 0.0
        if self.session_active:
            print(f"[FlowTracker] Session ended. Delivered: {total} pulses (~{ml} ml)")
        self.session_pulses = 0
        self.target_pulses  = 0
        self.session_active = False
        return total, ml

    def get_ml_delivered(self):
        return round(self.session_pulses / 450.0 * 1000.0, 1)
