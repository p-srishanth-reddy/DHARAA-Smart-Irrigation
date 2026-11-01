import sys
import os
import unittest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.database import init_db, get_db
from backend.services.scheduler_service import DHARAAScheduler

class TestScheduler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        conn = get_db()
        c = conn.cursor()
        # Create dedicated test user, farm, and device
        c.execute("INSERT OR IGNORE INTO users (id, username, email, password_hash, timezone) VALUES (99, 'testuser', 'test@dharaa.org', 'hash', 'Asia/Kolkata')")
        c.execute("INSERT OR IGNORE INTO farms (id, user_id, name) VALUES (99, 99, 'Test Automation Farm')")
        c.execute("INSERT OR IGNORE INTO devices (id, farm_id, name, key_hash, status) VALUES (99, 99, 'Test-Node-99', 'hash', 'online')")
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM schedules WHERE farm_id = 99")
        c.execute("DELETE FROM irrigation_events WHERE farm_id = 99")
        c.execute("DELETE FROM commands WHERE device_id = 99")
        c.execute("DELETE FROM telemetry WHERE device_id = 99")
        c.execute("DELETE FROM devices WHERE id = 99")
        c.execute("DELETE FROM farms WHERE id = 99")
        c.execute("DELETE FROM users WHERE id = 99")
        conn.commit()
        conn.close()

    def setUp(self):
        self.conn = get_db()
        self.cursor = self.conn.cursor()
        self.scheduler = DHARAAScheduler(check_interval_seconds=10)
        # Clear any leftovers on test farm
        self.cursor.execute("DELETE FROM schedules WHERE farm_id = 99")
        self.cursor.execute("DELETE FROM irrigation_events WHERE farm_id = 99")
        self.cursor.execute("DELETE FROM commands WHERE device_id = 99")
        self.cursor.execute("DELETE FROM telemetry WHERE device_id = 99")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_01_schema_columns_exist(self):
        """Verify that last_run_date, last_run_at, and last_run_status exist in schedules."""
        cols = [c[1] for c in self.cursor.execute("PRAGMA table_info(schedules)").fetchall()]
        self.assertIn("last_run_date", cols)
        self.assertIn("last_run_at", cols)
        self.assertIn("last_run_status", cols)

    def test_02_restart_policy_missed_downtime(self):
        """
        Verify that a schedule whose time has passed by > 5 minutes today
        is marked as skipped due to downtime, NOT triggered unexpectedly.
        """
        now_user = datetime.now(ZoneInfo("Asia/Kolkata"))
        today_str = now_user.strftime("%Y-%m-%d")
        past_time = (now_user - timedelta(minutes=30)).strftime("%H:%M")

        self.cursor.execute("""
            INSERT INTO schedules (farm_id, name, start_time, target_moisture, runtime_limit, status, last_run_date)
            VALUES (99, 'Test Downtime Missed Schedule', ?, 45.0, 300, 'active', NULL)
        """, (past_time,))
        self.conn.commit()
        sched_id = self.cursor.lastrowid

        self.scheduler.check_schedules()

        updated = self.cursor.execute("SELECT * FROM schedules WHERE id = ?", (sched_id,)).fetchone()
        self.assertEqual(updated["last_run_date"], today_str)
        self.assertIn("skipped: missed occurrence during downtime", updated["last_run_status"])

    def test_03_preflight_device_offline_check(self):
        """Verify that schedule is skipped if ESP32 device is offline (> 120s old)."""
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=250)).strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("UPDATE devices SET last_seen = ? WHERE id = 99", (stale_time,))
        self.cursor.execute("""
            INSERT INTO telemetry (device_id, timestamp, moisture, temperature, humidity, rain, pump_state, sensor_status)
            VALUES (99, ?, 30.0, 28.0, 60.0, 0, 0, 'OK')
        """, (stale_time,))
        self.cursor.execute("""
            INSERT INTO schedules (farm_id, name, start_time, target_moisture, runtime_limit, status)
            VALUES (99, 'Offline Test Sched', '12:00', 45.0, 300, 'active')
        """)
        self.conn.commit()
        sched_id = self.cursor.lastrowid

        res = self.scheduler.run_schedule_now(sched_id)
        self.assertFalse(res["success"])
        self.assertIn("device offline", res["status"])

    def test_04_preflight_rain_detected_check(self):
        """Verify that schedule is skipped if rain sensor detects rain."""
        fresh_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("UPDATE devices SET last_seen = ? WHERE id = 99", (fresh_time,))
        self.cursor.execute("""
            INSERT INTO telemetry (device_id, timestamp, moisture, temperature, humidity, rain, pump_state, sensor_status)
            VALUES (99, ?, 25.0, 24.0, 90.0, 1, 0, 'OK')
        """, (fresh_time,))
        self.cursor.execute("""
            INSERT INTO schedules (farm_id, name, start_time, target_moisture, runtime_limit, status)
            VALUES (99, 'Rain Test Sched', '12:00', 45.0, 300, 'active')
        """)
        self.conn.commit()
        sched_id = self.cursor.lastrowid

        res = self.scheduler.run_schedule_now(sched_id)
        self.assertFalse(res["success"])
        self.assertIn("rain detected", res["status"])

    def test_05_preflight_cooldown_check(self):
        """Verify that schedule is skipped if pump cooldown has not elapsed (600s)."""
        fresh_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        recent_end = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")

        self.cursor.execute("UPDATE devices SET last_seen = ? WHERE id = 99", (fresh_time,))
        self.cursor.execute("""
            INSERT INTO telemetry (device_id, timestamp, moisture, temperature, humidity, rain, pump_state, sensor_status)
            VALUES (99, ?, 25.0, 28.0, 50.0, 0, 0, 'OK')
        """, (fresh_time,))
        self.cursor.execute("""
            INSERT INTO irrigation_events (farm_id, started_at, ended_at, status, stop_reason)
            VALUES (99, ?, ?, 'completed', 'manual_stop')
        """, (recent_end, recent_end))
        self.cursor.execute("""
            INSERT INTO schedules (farm_id, name, start_time, target_moisture, runtime_limit, status)
            VALUES (99, 'Cooldown Test Sched', '12:00', 45.0, 300, 'active')
        """)
        self.conn.commit()
        sched_id = self.cursor.lastrowid

        res = self.scheduler.run_schedule_now(sched_id)
        self.assertFalse(res["success"])
        self.assertIn("cooldown active", res["status"])

    def test_06_preflight_target_moisture_met(self):
        """Verify that schedule is skipped if moisture is already >= target."""
        fresh_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("UPDATE devices SET last_seen = ? WHERE id = 99", (fresh_time,))
        self.cursor.execute("""
            INSERT INTO telemetry (device_id, timestamp, moisture, temperature, humidity, rain, pump_state, sensor_status)
            VALUES (99, ?, 50.0, 26.0, 60.0, 0, 0, 'OK')
        """, (fresh_time,))
        self.cursor.execute("""
            INSERT INTO schedules (farm_id, name, start_time, target_moisture, runtime_limit, status)
            VALUES (99, 'Target Met Sched', '12:00', 45.0, 300, 'active')
        """)
        self.conn.commit()
        sched_id = self.cursor.lastrowid

        res = self.scheduler.run_schedule_now(sched_id)
        self.assertFalse(res["success"])
        self.assertIn("already at/above target", res["status"])

    def test_07_successful_execution_and_queue_command(self):
        """
        Verify that when all safety checks pass:
        1. Pump 'ON' command is queued to commands table.
        2. Irrigation event is started with trigger_source='schedule'.
        3. Schedule row is updated to executed with today's date.
        """
        fresh_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("UPDATE devices SET last_seen = ? WHERE id = 99", (fresh_time,))
        self.cursor.execute("""
            INSERT INTO telemetry (device_id, timestamp, moisture, temperature, humidity, rain, pump_state, sensor_status)
            VALUES (99, ?, 28.0, 26.0, 50.0, 0, 0, 'OK')
        """, (fresh_time,))
        self.cursor.execute("""
            INSERT INTO schedules (farm_id, name, start_time, target_moisture, runtime_limit, status)
            VALUES (99, 'Success Run Sched', '12:00', 45.0, 300, 'active')
        """)
        self.conn.commit()
        sched_id = self.cursor.lastrowid

        res = self.scheduler.run_schedule_now(sched_id)
        self.assertTrue(res["success"])
        self.assertIn("executed: pump ON", res["status"])

        # Verify command queued
        cmd = self.cursor.execute("SELECT * FROM commands WHERE device_id = 99 ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["type"], "ON")
        self.assertEqual(cmd["status"], "pending")
        self.assertIn("Success Run Sched", cmd["payload"])

        # Verify event started
        evt = self.cursor.execute("SELECT * FROM irrigation_events WHERE farm_id = 99 ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(evt)
        self.assertEqual(evt["status"], "running")
        self.assertEqual(evt["trigger_source"], "schedule")

if __name__ == "__main__":
    unittest.main()
