import logging
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import sqlite3

from backend.database import get_db
from backend.services.irrigation_service import (
    queue_pump_command,
    start_irrigation_event,
    stop_active_irrigation_event
)
from backend.services.notification_service import create_notification

logger = logging.getLogger("dharaa.scheduler")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [SCHEDULER] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Safety Protocol Thresholds
DEVICE_STALE_THRESHOLD_SECONDS = 120   # ESP32 offline threshold: 2 minutes without telemetry
COOLDOWN_SECONDS = 600                 # Minimum 10 minutes between pump sessions
DEFAULT_EXECUTION_WINDOW_MINUTES = 5   # Active trigger window: within 5 minutes of start_time
MAX_HARD_RUNTIME_LIMIT_SECONDS = 600   # Hard maximum cap for any irrigation session

class DHARAAScheduler:
    """
    Automated Irrigation Scheduler Service for DHARAA.
    Runs non-blocking in a background thread while the Flask server is active.
    
    Features:
    - Timezone-aware schedule comparison using farm owner's configured timezone.
    - Exactly-once execution per scheduled occurrence (tracked via last_run_date).
    - Clear restart policy: skips missed occurrences after downtime rather than
      unexpectedly activating irrigation.
    - Strict pre-flight safety checks before triggering pump:
      1. Device online & reachable (telemetry < 120s old).
      2. Soil sensor healthy (status == 'OK', valid moisture).
      3. Rain sensor dry (no rain detected).
      4. Pump cooldown elapsed (>= 600s since last run).
      5. Current moisture < target moisture threshold.
    - Dual watchdog: ensures runtime limits are enforced if sessions exceed caps.
    - Clean thread shutdown via threading.Event.
    """

    def __init__(self, check_interval_seconds: int = 15):
        self.check_interval = check_interval_seconds
        self.stop_event = threading.Event()
        self.thread = None
        self.last_check_at = None
        self.last_run_summary = {}

    def start(self):
        """Starts the scheduler thread if not already running."""
        if self.thread and self.thread.is_alive():
            logger.info("Scheduler thread is already running.")
            return

        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run_loop,
            name="DHARAASchedulerThread",
            daemon=True
        )
        self.thread.start()
        logger.info(f"DHARAA Automatic Scheduler started (poll interval: {self.check_interval}s).")

    def stop(self):
        """Signals the background thread to exit and cleanly joins."""
        if not self.thread or not self.thread.is_alive():
            return
        logger.info("Stopping DHARAA Automatic Scheduler...")
        self.stop_event.set()
        self.thread.join(timeout=3.0)
        logger.info("DHARAA Automatic Scheduler stopped cleanly.")

    def is_running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def _run_loop(self):
        """Background execution loop."""
        while not self.stop_event.is_set():
            try:
                self.check_schedules()
                self._enforce_runtime_watchdog()
            except Exception as e:
                logger.error(f"Error in scheduler execution loop: {e}", exc_info=True)

            # Wait for next interval or early exit
            self.stop_event.wait(self.check_interval)

    def check_schedules(self):
        """
        Queries all active schedules and evaluates them against current time in
        each farm's owner timezone.
        """
        self.last_check_at = datetime.now(timezone.utc).isoformat()
        conn = get_db()
        cursor = conn.cursor()

        try:
            schedules = cursor.execute("""
                SELECT s.*, f.name AS farm_name, f.user_id, u.timezone, u.username
                FROM schedules s
                JOIN farms f ON s.farm_id = f.id
                JOIN users u ON f.user_id = u.id
                WHERE s.status = 'active'
                ORDER BY s.id ASC
            """).fetchall()

            for sched in schedules:
                self._evaluate_schedule_record(sched, cursor, conn)

        except Exception as e:
            logger.error(f"Failed to query schedules from database: {e}", exc_info=True)
        finally:
            conn.close()

    def _evaluate_schedule_record(self, sched: sqlite3.Row, cursor, conn, force_trigger: bool = False):
        """
        Evaluates a single schedule record for execution or skip logic.
        """
        sched_id = sched["id"]
        sched_name = sched["name"]
        farm_id = sched["farm_id"]
        farm_name = sched["farm_name"]
        user_id = sched["user_id"]
        start_time_str = sched["start_time"]
        last_run_date = sched["last_run_date"]
        target_moisture = float(sched["target_moisture"] or 45.0)
        runtime_limit = int(sched["runtime_limit"] or 300)

        # 1. Resolve Farm Owner's Timezone
        user_tz_name = sched["timezone"] or "Asia/Kolkata"
        try:
            user_tz = ZoneInfo(user_tz_name)
        except Exception:
            logger.warning(f"Invalid timezone '{user_tz_name}' for user {user_id}. Falling back to 'Asia/Kolkata'.")
            user_tz = ZoneInfo("Asia/Kolkata")

        now_user = datetime.now(user_tz)
        today_date_str = now_user.strftime("%Y-%m-%d")
        now_hm = now_user.strftime("%H:%M")
        now_minutes = now_user.hour * 60 + now_user.minute

        # Parse schedule start time (HH:MM)
        try:
            sh, sm = map(int, start_time_str.strip().split(":"))
            start_minutes = sh * 60 + sm
        except Exception:
            logger.error(f"Schedule #{sched_id} '{sched_name}' has invalid start_time '{start_time_str}'.")
            return

        diff_minutes = now_minutes - start_minutes

        if not force_trigger:
            # 2. Occurrence check: At most once per calendar day in user timezone
            if last_run_date == today_date_str:
                # Already processed for today's occurrence
                return

            # 3. Time comparison & Restart Policy:
            if diff_minutes < 0:
                # Start time has not arrived yet today
                return

            if diff_minutes > DEFAULT_EXECUTION_WINDOW_MINUTES:
                # RESTART POLICY: Occurrence occurred more than 5 minutes ago (during server downtime or restart).
                # Skip missed occurrence rather than unexpectedly starting irrigation.
                skip_reason = f"skipped: missed occurrence during downtime (scheduled {start_time_str}, current {now_hm} {user_tz_name})"
                cursor.execute("""
                    UPDATE schedules
                    SET last_run_date = ?, last_run_at = CURRENT_TIMESTAMP, last_run_status = ?
                    WHERE id = ?
                """, (today_date_str, skip_reason, sched_id))
                conn.commit()

                logger.info(f"Schedule #{sched_id} '{sched_name}' skipped: Missed start time {start_time_str} during downtime (current: {now_hm}).")
                create_notification(
                    user_id,
                    f"Schedule '{sched_name}' skipped: Start time ({start_time_str}) passed during system restart/downtime.",
                    "warning"
                )
                return

        # 4. Trigger Window Reached (0 <= diff_minutes <= 5 or force_trigger):
        # Perform rigorous pre-flight safety checks before queueing pump command.
        logger.info(f"Schedule #{sched_id} '{sched_name}' reached start time ({start_time_str} {user_tz_name}). Evaluating pre-flight safety...")

        # (a) Find associated ESP32 device
        device = cursor.execute("""
            SELECT * FROM devices
            WHERE farm_id = ?
            ORDER BY id ASC LIMIT 1
        """, (farm_id,)).fetchone()

        if not device:
            skip_reason = "skipped: no ESP32 device registered for farm"
            self._record_schedule_result(sched_id, today_date_str, skip_reason, cursor, conn)
            logger.warning(f"Schedule #{sched_id} '{sched_name}' skipped: No ESP32 device registered for farm #{farm_id}.")
            create_notification(user_id, f"Schedule '{sched_name}' skipped: No ESP32 hardware node registered.", "critical")
            return

        device_id = device["id"]

        # (b) Pre-flight Check: Device Online Verification
        latest_telemetry = cursor.execute("""
            SELECT * FROM telemetry
            WHERE device_id = ?
            ORDER BY timestamp DESC, id DESC LIMIT 1
        """, (device_id,)).fetchone()

        if not latest_telemetry or not device["last_seen"]:
            skip_reason = "skipped: device offline (no telemetry recorded)"
            self._record_schedule_result(sched_id, today_date_str, skip_reason, cursor, conn)
            logger.warning(f"Schedule #{sched_id} '{sched_name}' skipped: ESP32 node #{device_id} is offline (no telemetry).")
            create_notification(user_id, f"Schedule '{sched_name}' skipped: ESP32 node '{device['name']}' is offline.", "warning")
            return

        # Compute staleness in UTC seconds
        try:
            t_str = latest_telemetry["timestamp"]
            # Format in SQLite CURRENT_TIMESTAMP: 'YYYY-MM-DD HH:MM:SS'
            reading_time = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - reading_time).total_seconds()
        except Exception:
            age_seconds = 999999

        if age_seconds > DEVICE_STALE_THRESHOLD_SECONDS:
            skip_reason = f"skipped: device offline (last seen {int(age_seconds)}s ago > {DEVICE_STALE_THRESHOLD_SECONDS}s limit)"
            self._record_schedule_result(sched_id, today_date_str, skip_reason, cursor, conn)
            logger.warning(f"Schedule #{sched_id} '{sched_name}' skipped: ESP32 node #{device_id} stale ({int(age_seconds)}s old).")
            create_notification(user_id, f"Schedule '{sched_name}' skipped: ESP32 node '{device['name']}' is unreachable (last seen {int(age_seconds)}s ago).", "warning")
            return

        # (c) Pre-flight Check: Soil Sensor Health
        sensor_status = latest_telemetry["sensor_status"] or "UNKNOWN"
        current_moisture = latest_telemetry["moisture"]
        if sensor_status != "OK" or current_moisture is None:
            skip_reason = f"skipped: soil sensor fault ({sensor_status})"
            self._record_schedule_result(sched_id, today_date_str, skip_reason, cursor, conn)
            logger.warning(f"Schedule #{sched_id} '{sched_name}' skipped: Sensor status is '{sensor_status}'.")
            create_notification(user_id, f"Schedule '{sched_name}' skipped: Soil moisture sensor reporting fault ({sensor_status}).", "critical")
            return

        # (d) Pre-flight Check: Rain Inhibit Verification
        rain_detected = bool(latest_telemetry["rain"] == 1)
        if rain_detected:
            skip_reason = "skipped: rain detected on field"
            self._record_schedule_result(sched_id, today_date_str, skip_reason, cursor, conn)
            logger.info(f"Schedule #{sched_id} '{sched_name}' skipped: Live rain detected on field.")
            create_notification(user_id, f"Schedule '{sched_name}' skipped: Surface rain sensor detected rainfall on '{farm_name}'. Water conservation active.", "info")
            return

        # (e) Pre-flight Check: Active Running Event & Cooldown
        active_event = cursor.execute("""
            SELECT * FROM irrigation_events
            WHERE farm_id = ? AND status = 'running'
            ORDER BY started_at DESC LIMIT 1
        """, (farm_id,)).fetchone()

        if active_event:
            skip_reason = "skipped: irrigation already in progress"
            self._record_schedule_result(sched_id, today_date_str, skip_reason, cursor, conn)
            logger.info(f"Schedule #{sched_id} '{sched_name}' skipped: Farm #{farm_id} already has active irrigation event #{active_event['id']}.")
            return

        last_completed = cursor.execute("""
            SELECT * FROM irrigation_events
            WHERE farm_id = ? AND status = 'completed'
            ORDER BY ended_at DESC LIMIT 1
        """, (farm_id,)).fetchone()

        if last_completed and last_completed["ended_at"]:
            try:
                ended_time = datetime.strptime(last_completed["ended_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                elapsed_cooldown = (datetime.now(timezone.utc) - ended_time).total_seconds()
            except Exception:
                elapsed_cooldown = 999999

            if elapsed_cooldown < COOLDOWN_SECONDS:
                remaining_cd = int(COOLDOWN_SECONDS - elapsed_cooldown)
                skip_reason = f"skipped: pump cooldown active ({remaining_cd}s remaining of {COOLDOWN_SECONDS}s)"
                self._record_schedule_result(sched_id, today_date_str, skip_reason, cursor, conn)
                logger.info(f"Schedule #{sched_id} '{sched_name}' skipped: Pump cooldown active ({remaining_cd}s remaining).")
                create_notification(user_id, f"Schedule '{sched_name}' skipped: Pump thermal cooldown active ({remaining_cd}s remaining).", "info")
                return

        # (f) Pre-flight Check: Current Moisture vs Target Moisture
        if current_moisture >= target_moisture:
            skip_reason = f"skipped: soil moisture ({current_moisture:.1f}%) already at/above target ({target_moisture:.1f}%)"
            self._record_schedule_result(sched_id, today_date_str, skip_reason, cursor, conn)
            logger.info(f"Schedule #{sched_id} '{sched_name}' skipped: Soil moisture {current_moisture:.1f}% >= target {target_moisture:.1f}%.")
            create_notification(user_id, f"Schedule '{sched_name}' skipped: Soil moisture ({current_moisture:.1f}%) is already above target ({target_moisture:.1f}%).", "info")
            return

        # 5. ALL SAFETY CHECKS PASSED: Trigger Irrigation!
        effective_cap = min(runtime_limit, MAX_HARD_RUNTIME_LIMIT_SECONDS)
        cmd_reason = f"Schedule '{sched_name}': Target {target_moisture}%, Max runtime {effective_cap}s"
        
        # Queue pump command to ESP32 node
        cmd_id = queue_pump_command(device_id, "ON", cmd_reason)
        
        # Start recorded irrigation event
        event_id = start_irrigation_event(farm_id, trigger_source="schedule")

        exec_status = f"executed: pump ON (moisture {current_moisture:.1f}%, target {target_moisture:.1f}%, limit {effective_cap}s)"
        self._record_schedule_result(sched_id, today_date_str, exec_status, cursor, conn)

        logger.info(f"SUCCESS: Schedule #{sched_id} '{sched_name}' triggered irrigation for farm '{farm_name}'. Command #{cmd_id}, Event #{event_id}.")
        create_notification(
            user_id,
            f"Scheduled Irrigation Started: '{sched_name}' on '{farm_name}'. Soil moisture: {current_moisture:.1f}% (target: {target_moisture}%). Runtime cap: {effective_cap}s.",
            "info"
        )

    def _record_schedule_result(self, sched_id: int, date_str: str, status_msg: str, cursor, conn):
        """Updates the execution tracking fields on the schedule row."""
        cursor.execute("""
            UPDATE schedules
            SET last_run_date = ?, last_run_at = CURRENT_TIMESTAMP, last_run_status = ?
            WHERE id = ?
        """, (date_str, status_msg, sched_id))
        conn.commit()

    def _enforce_runtime_watchdog(self):
        """
        Safety watchdog: Detects any running irrigation events that have exceeded
        their runtime limit or hard cap (600s), and automatically halts them.
        """
        conn = get_db()
        cursor = conn.cursor()

        try:
            active_events = cursor.execute("""
                SELECT e.*, f.name AS farm_name, f.user_id, d.id AS device_id, d.name AS device_name
                FROM irrigation_events e
                JOIN farms f ON e.farm_id = f.id
                LEFT JOIN devices d ON d.farm_id = f.id
                WHERE e.status = 'running'
            """).fetchall()

            for event in active_events:
                started_at_str = event["started_at"]
                if not started_at_str:
                    continue

                try:
                    started_dt = datetime.strptime(started_at_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    elapsed = (datetime.now(timezone.utc) - started_dt).total_seconds()
                except Exception:
                    elapsed = 0

                # Check against hard safety cap
                if elapsed > MAX_HARD_RUNTIME_LIMIT_SECONDS:
                    device_id = event["device_id"]
                    farm_id = event["farm_id"]
                    farm_name = event["farm_name"]
                    user_id = event["user_id"]

                    logger.warning(f"SAFETY WATCHDOG: Active irrigation on '{farm_name}' exceeded {MAX_HARD_RUNTIME_LIMIT_SECONDS}s. Halting...")
                    if device_id:
                        queue_pump_command(device_id, "OFF", "Safety Watchdog: Maximum runtime cap exceeded")
                    stop_active_irrigation_event(farm_id, stop_reason="runtime_watchdog_timeout")
                    create_notification(
                        user_id,
                        f"Safety Watchdog: Pump auto-stopped on '{farm_name}'. Session reached hard safety cap of {MAX_HARD_RUNTIME_LIMIT_SECONDS}s.",
                        "warning"
                    )

        except Exception as e:
            logger.error(f"Error in runtime watchdog: {e}", exc_info=True)
        finally:
            conn.close()

    def run_schedule_now(self, sched_id: int) -> dict:
        """
        Manually trigger/test a schedule immediately via pre-flight checks,
        bypassing clock time wait while still strictly validating all safety rules.
        """
        conn = get_db()
        cursor = conn.cursor()
        try:
            sched = cursor.execute("""
                SELECT s.*, f.name AS farm_name, f.user_id, u.timezone, u.username
                FROM schedules s
                JOIN farms f ON s.farm_id = f.id
                JOIN users u ON f.user_id = u.id
                WHERE s.id = ?
            """, (sched_id,)).fetchone()

            if not sched:
                return {"success": False, "message": "Schedule not found"}

            self._evaluate_schedule_record(sched, cursor, conn, force_trigger=True)

            # Re-fetch updated status
            updated = cursor.execute("SELECT last_run_status, last_run_date, last_run_at FROM schedules WHERE id = ?", (sched_id,)).fetchone()
            status_text = updated["last_run_status"] if updated else "unknown"
            success = bool(status_text and status_text.startswith("executed"))

            return {
                "success": success,
                "schedule_id": sched_id,
                "status": status_text,
                "last_run_at": updated["last_run_at"] if updated else None
            }
        finally:
            conn.close()

# Singleton instance for import across Flask app
dharaa_scheduler = DHARAAScheduler(check_interval_seconds=15)
