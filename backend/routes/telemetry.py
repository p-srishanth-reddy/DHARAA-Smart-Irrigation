from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
import json
import time
from backend.database import get_db
from backend.services.irrigation_service import evaluate_irrigation_policy, queue_pump_command

telemetry_bp = Blueprint("telemetry", __name__)

STALE_THRESHOLD_SECONDS = 15  # Mark stale if no telemetry for >15 seconds

@telemetry_bp.route("/api/telemetry", methods=["POST"])
def post_telemetry():
    """
    Endpoint for ESP32 / Simulator to ingest sensor telemetry.
    Validates payload types and ranges, preserves sensor errors, updates device status,
    and runs the irrigation hysteresis rule engine.
    """
    data = request.get_json() or {}

    device_id = data.get("device_id", 1)
    raw_moisture = data.get("moisture")
    temperature = data.get("temperature")
    humidity = data.get("humidity")
    rain = data.get("rain", 0)
    flow_pulses = data.get("flow_pulses", 0)
    pump_state = data.get("pump_state", 0)
    sensor_status = data.get("sensor_status", "OK")

    # Validation: clamp moisture if numeric, or preserve None if sensor error
    moisture = None
    if raw_moisture is not None:
        try:
            moisture = float(raw_moisture)
            moisture = max(0.0, min(100.0, moisture))
        except (ValueError, TypeError):
            sensor_status = "MOISTURE_PARSE_ERROR"

    conn = get_db()
    cursor = conn.cursor()

    # Verify device exists and find farm_id
    device = cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not device:
        conn.close()
        return jsonify({"error": f"Device {device_id} not registered"}), 404

    # Attribution Logic: Use active_farm_id if set, otherwise fallback to static farm_id
    farm_id = device["active_farm_id"] or device["farm_id"]

    if not farm_id:
        conn.close()
        return jsonify({"error": "No farm attributed to this device"}), 422

    # Update device online state and last seen
    cursor.execute("""
        UPDATE devices
        SET last_seen = CURRENT_TIMESTAMP, status = 'online'
        WHERE id = ?
    """, (device_id,))

    # Insert telemetry reading
    cursor.execute("""
        INSERT INTO telemetry (device_id, moisture, temperature, humidity, rain, flow_pulses, pump_state, sensor_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (device_id, moisture, temperature, humidity, rain, flow_pulses, pump_state, sensor_status))
    conn.commit()
    conn.close()

    # -----------------------------------------------------------------------
    # AI FLOW QUANTITY CHECK (additive — does not interfere with existing policy)
    # Checks if an active AI-guided event has reached its target pulse count.
    # -----------------------------------------------------------------------
    ai_flow_action = None
    if pump_state == 1 and flow_pulses and flow_pulses > 0:
        try:
            conn_ai   = get_db()
            cursor_ai = conn_ai.cursor()
            active_ai_event = cursor_ai.execute(
                "SELECT * FROM irrigation_events"
                " WHERE farm_id = ? AND status = 'running'"
                " AND ai_prediction_id IS NOT NULL"
                " AND target_pulses IS NOT NULL AND target_pulses > 0"
                " ORDER BY started_at DESC LIMIT 1",
                (farm_id,)
            ).fetchone()

            if active_ai_event:
                current_total = (active_ai_event["actual_pulses"] or 0) + flow_pulses
                target_p      = active_ai_event["target_pulses"]
                cursor_ai.execute(
                    "UPDATE irrigation_events SET actual_pulses = ? WHERE id = ?",
                    (current_total, active_ai_event["id"])
                )
                conn_ai.commit()

                if current_total >= target_p:
                    actual_ml = round(current_total * (1000.0 / 450.0), 1)
                    queue_pump_command(
                        device_id, "OFF",
                        json.dumps({"reason": "AI target quantity reached",
                                    "actual_ml": actual_ml,
                                    "actual_pulses": current_total})
                    )
                    cursor_ai.execute(
                        "UPDATE irrigation_events"
                        " SET status = 'completed', ended_at = CURRENT_TIMESTAMP,"
                        "     stop_reason = 'ai_target_quantity_reached',"
                        "     actual_water_ml = ?, actual_pulses = ?,"
                        "     estimated_litres = ?"
                        " WHERE id = ?",
                        (actual_ml, current_total,
                         round(actual_ml / 1000.0, 3), active_ai_event["id"])
                    )
                    conn_ai.commit()
                    ai_flow_action = {
                        "action": "STOP",
                        "reason": "AI target quantity reached",
                        "actual_water_ml": actual_ml,
                        "actual_pulses": current_total,
                        "target_pulses": target_p,
                    }
                    try:
                        from backend.services.water_model_trainer import record_irrigation_outcome
                        record_irrigation_outcome(
                            farm_id=farm_id,
                            irrigation_event_id=active_ai_event["id"],
                            initial_moisture=None,
                            final_moisture=moisture,
                            predicted_water_ml=active_ai_event["target_water_ml"],
                            actual_water_ml=actual_ml,
                            predicted_duration_s=None,
                            actual_duration_s=None,
                            temperature=temperature,
                            humidity=humidity,
                            rain=(1 if rain == 1 else 0),
                            stop_reason="ai_target_quantity_reached",
                        )
                    except Exception as le:
                        print(f"[Telemetry] Learning record save error: {le}")

            conn_ai.close()
        except Exception as ai_err:
            print(f"[Telemetry] AI flow check error (non-fatal): {ai_err}")
    # -----------------------------------------------------------------------

    # Evaluate automated irrigation policy with safety pre-flight checks
    policy_result = evaluate_irrigation_policy(
        farm_id=farm_id,
        device_id=device_id,
        current_moisture=moisture,
        is_raining=(rain == 1),
        sensor_status=sensor_status,
        pump_state=pump_state
    )

    # Check if there are any immediate pending commands for the device
    conn = get_db()
    cursor = conn.cursor()

    # Enforce command expiry for the telemetry-injected command as well
    from backend.services.irrigation_service import COMMAND_EXPIRY_SECONDS
    pending_cmd = cursor.execute("""
        SELECT * FROM commands
        WHERE device_id = ? AND status = 'pending'
        ORDER BY created_at ASC LIMIT 1
    """, (device_id,)).fetchone()

    pending_cmd_dict = None
    if pending_cmd:
        try:
            from datetime import datetime
            created_at = datetime.strptime(pending_cmd["created_at"], "%Y-%m-%d %H:%M:%S")
            age = (datetime.utcnow() - created_at).total_seconds()
            if age > COMMAND_EXPIRY_SECONDS:
                cursor.execute("UPDATE commands SET status = 'expired' WHERE id = ?", (pending_cmd["id"],))
                conn.commit()
            else:
                pending_cmd_dict = dict(pending_cmd)
                cursor.execute("UPDATE commands SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP WHERE id = ?", (pending_cmd["id"],))
                conn.commit()
        except Exception as e:
            print(f"Telemetry command expiry check error: {e}")
            # Fallback: just deliver it if we can't parse time
            pending_cmd_dict = dict(pending_cmd)
            cursor.execute("UPDATE commands SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP WHERE id = ?", (pending_cmd["id"],))
            conn.commit()
    conn.close()


    return jsonify({
        "status": "success",
        "policy_evaluation": policy_result,
        "pending_command": pending_cmd_dict
    }), 201

@telemetry_bp.route("/api/telemetry/latest", methods=["GET"])
def get_latest_telemetry():
    device_id = request.args.get("device_id", 1, type=int)
    farm_id = request.args.get("farm_id", type=int)

    conn = get_db()
    cursor = conn.cursor()

    if farm_id:
        dev = cursor.execute("SELECT id FROM devices WHERE farm_id = ? LIMIT 1", (farm_id,)).fetchone()
        if not dev:
            conn.close()
            return jsonify({"error": "Device not found for farm"}), 404
        device_id = dev["id"]

    device = cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not device:
        conn.close()
        return jsonify({"error": "Device not found"}), 404

    reading = cursor.execute("""
        SELECT * FROM telemetry
        WHERE device_id = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (device_id,)).fetchone()

    # Also check latest command to know requested vs reported pump state
    latest_cmd = cursor.execute("""
        SELECT * FROM commands
        WHERE device_id = ?
        ORDER BY created_at DESC LIMIT 1
    """, (device_id,)).fetchone()

    conn.close()

    if not reading:
        return jsonify({
            "device": dict(device),
            "telemetry": None,
            "status": "NO_DATA",
            "is_stale": True,
            "message": "No telemetry recorded yet for this device."
        })

    reading_dict = dict(reading)

    # Compute staleness
    # SQLite CURRENT_TIMESTAMP is UTC format 'YYYY-MM-DD HH:MM:SS'
    is_stale = False
    age_seconds = 0
    try:
        t_str = reading_dict["timestamp"]
        parsed_time = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")
        age_seconds = (datetime.utcnow() - parsed_time).total_seconds()
        if age_seconds > STALE_THRESHOLD_SECONDS:
            is_stale = True
    except Exception:
        pass

    # Distinct requested vs reported pump state
    # Only treat a command as "requested" if it is still in-flight (pending or delivered).
    # Once the ESP32 acknowledges it (completed/rejected/expired), use the reported hardware state.
    reported_state = "ON" if reading_dict.get("pump_state") == 1 else "OFF"

    requested_state = reported_state  # Default: mirror hardware truth
    if latest_cmd:
        cmd_type   = latest_cmd["type"]
        cmd_status = latest_cmd["status"]
        if cmd_type in ["ON", "OFF", "EMERGENCY_STOP"] and cmd_status in ("pending", "delivered"):
            requested_state = cmd_type   # Command in-flight: show what was commanded

    return jsonify({
        "device": dict(device),
        "telemetry": reading_dict,
        "is_stale": is_stale,
        "age_seconds": round(max(0, age_seconds)),
        "status": "STALE" if is_stale else reading_dict.get("sensor_status", "OK"),
        "pump_control": {
            "requested_state": requested_state,
            "reported_state": reported_state,
            "last_command": dict(latest_cmd) if latest_cmd else None
        }
    })

@telemetry_bp.route("/api/telemetry/history", methods=["GET"])
def get_telemetry_history():
    device_id = request.args.get("device_id", 1, type=int)
    limit = request.args.get("limit", 60, type=int)

    conn = get_db()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT timestamp, moisture, temperature, humidity, rain, flow_pulses, pump_state, sensor_status
        FROM telemetry
        WHERE device_id = ?
        ORDER BY timestamp DESC LIMIT ?
    """, (device_id, limit)).fetchall()
    conn.close()

    # Reverse so it's chronologically ascending for Chart.js
    results = [dict(r) for r in reversed(rows)]
    return jsonify(results)
