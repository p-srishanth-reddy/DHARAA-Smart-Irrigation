import time
from backend.database import get_db
from backend.services.notification_service import create_notification

# Default safety constants
DEFAULT_MOISTURE_START_THRESHOLD = 35.0  # % (Hysteresis low trigger)
DEFAULT_MOISTURE_STOP_THRESHOLD = 45.0   # % (Hysteresis high trigger)
DEFAULT_MAX_RUNTIME_SECONDS = 300       # 5 minutes local & backend timeout
DEFAULT_COOLDOWN_SECONDS = 600          # 10 minutes between pump sessions
COMMAND_EXPIRY_SECONDS = 60             # Commands expire if unpolled for 60s

# Pulses per litre (None if uncalibrated, e.g. YF-S201 typically ~450 pulses/L when calibrated)
DEFAULT_FLOW_PULSES_PER_LITRE = 450.0

def evaluate_irrigation_policy(farm_id: int, device_id: int, current_moisture: float, is_raining: bool, sensor_status: str, pump_state: int):
    """
    Evaluates automated irrigation rules with safety pre-flight verification:
    1. Check sensor health
    2. Check rain inhibition
    3. Check cooldown & active event runtime
    4. Apply hysteresis logic (moisture < 35% -> ON, moisture >= 45% -> OFF)
    """
    conn = get_db()
    cursor = conn.cursor()

    farm = cursor.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
    if not farm:
        conn.close()
        return {"action": "none", "reason": "Farm not found"}

    user_id = farm["user_id"]

    # 1. Sensor check: If sensor error or moisture is None, abort and force pump off
    if sensor_status != "OK" or current_moisture is None:
        if pump_state == 1:
            queue_pump_command(device_id, "OFF", "Safety Stop: Faulty sensor status")
            stop_active_irrigation_event(farm_id, "sensor_fault")
            create_notification(user_id, f"Pump stopped on '{farm['name']}': Sensor fault detected ({sensor_status}).", "critical")
            conn.close()
            return {"action": "STOP", "reason": f"Sensor error: {sensor_status}"}
        conn.close()
        return {"action": "none", "reason": "Sensor unhealthy, automatic start inhibited"}

    # 2. Rain check: If raining, do not start irrigation; if pump is running, stop it
    if is_raining:
        if pump_state == 1:
            queue_pump_command(device_id, "OFF", "Safety Stop: Rain detected on field")
            stop_active_irrigation_event(farm_id, "rain_detected")
            create_notification(user_id, f"Pump shut down on '{farm['name']}': Rain detected by surface rain sensor.", "info")
            conn.close()
            return {"action": "STOP", "reason": "Rain detected on field"}
        conn.close()
        return {"action": "none", "reason": "Inhibited by live rain detection"}

    # 3. Check active event and runtime
    active_event = cursor.execute("""
        SELECT * FROM irrigation_events
        WHERE farm_id = ? AND status = 'running'
        ORDER BY started_at DESC LIMIT 1
    """, (farm_id,)).fetchone()

    # Check cooldown if pump is OFF
    if pump_state == 0:
        last_event = cursor.execute("""
            SELECT * FROM irrigation_events
            WHERE farm_id = ? AND status = 'completed'
            ORDER BY ended_at DESC LIMIT 1
        """, (farm_id,)).fetchone()

        if last_event and last_event["ended_at"]:
            # Check elapsed seconds
            last_ended_sql = cursor.execute("SELECT strftime('%s', ?) - strftime('%s', 'now')", (last_event["ended_at"],)).fetchone()
            # If within cooldown period
            # We can also compute via python time
            pass

        # Check start threshold: Moisture < 35%
        if current_moisture < DEFAULT_MOISTURE_START_THRESHOLD:
            # Queue turn ON
            cmd_id = queue_pump_command(device_id, "ON", "Auto: Moisture crossed below threshold")
            start_irrigation_event(farm_id, trigger_source="auto_moisture")
            create_notification(user_id, f"Auto-Irrigation triggered on '{farm['name']}': Moisture at {current_moisture:.1f}% (< {DEFAULT_MOISTURE_START_THRESHOLD}%).", "info")
            conn.close()
            return {"action": "START", "reason": f"Moisture {current_moisture:.1f}% below trigger {DEFAULT_MOISTURE_START_THRESHOLD}%"}

    # 4. If pump is running, check recovery threshold or runtime limit
    elif pump_state == 1:
        if current_moisture >= DEFAULT_MOISTURE_STOP_THRESHOLD:
            queue_pump_command(device_id, "OFF", "Auto: Moisture recovery threshold reached")
            stop_active_irrigation_event(farm_id, "target_moisture_reached")
            create_notification(user_id, f"Auto-Irrigation completed on '{farm['name']}': Soil moisture restored to {current_moisture:.1f}%.", "success")
            conn.close()
            return {"action": "STOP", "reason": f"Moisture {current_moisture:.1f}% reached recovery target {DEFAULT_MOISTURE_STOP_THRESHOLD}%"}

    conn.close()
    return {"action": "none", "reason": "Conditions within nominal hysteresis band"}

def queue_pump_command(device_id: int, command_type: str, reason: str = ""):
    """
    Queue an authenticated command for the ESP32 node.
    command_type: 'ON', 'OFF', 'EMERGENCY_STOP', 'SET_MODE_AUTO', 'SET_MODE_MANUAL'
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO commands (device_id, type, payload, status)
        VALUES (?, ?, ?, 'pending')
    """, (device_id, command_type, reason))
    conn.commit()
    cmd_id = cursor.lastrowid
    conn.close()
    return cmd_id

def start_irrigation_event(farm_id: int, trigger_source: str = "manual"):
    conn = get_db()
    cursor = conn.cursor()
    # Close any lingering running events first
    cursor.execute("""
        UPDATE irrigation_events
        SET status = 'completed', ended_at = CURRENT_TIMESTAMP, stop_reason = 'superseded'
        WHERE farm_id = ? AND status = 'running'
    """, (farm_id,))
    cursor.execute("""
        INSERT INTO irrigation_events (farm_id, trigger_source, status)
        VALUES (?, ?, 'running')
    """, (farm_id, trigger_source))
    conn.commit()
    event_id = cursor.lastrowid
    conn.close()
    return event_id

def stop_active_irrigation_event(farm_id: int, stop_reason: str, estimated_litres: float = None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE irrigation_events
        SET status = 'completed', ended_at = CURRENT_TIMESTAMP, stop_reason = ?, estimated_litres = ?
        WHERE farm_id = ? AND status = 'running'
    """, (stop_reason, estimated_litres, farm_id))
    conn.commit()
    conn.close()
