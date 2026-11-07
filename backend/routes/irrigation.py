from flask import Blueprint, request, jsonify
from backend.database import get_db
from backend.services.irrigation_service import queue_pump_command, start_irrigation_event, stop_active_irrigation_event
from backend.services.notification_service import create_notification

irrigation_bp = Blueprint("irrigation", __name__)

@irrigation_bp.route("/api/irrigation/command", methods=["POST"])
def post_command():
    """
    Queue an authenticated control command for the ESP32 node.
    Types: 'ON', 'OFF', 'EMERGENCY_STOP', 'SET_MODE_AUTO', 'SET_MODE_MANUAL'
    """
    data = request.get_json() or {}
    device_id = data.get("device_id", 1)
    cmd_type = data.get("type", "").upper()
    reason = data.get("reason", "User command via web dashboard")

    if cmd_type not in ["ON", "OFF", "EMERGENCY_STOP", "SET_MODE_AUTO", "SET_MODE_MANUAL"]:
        return jsonify({"error": f"Invalid command type: '{cmd_type}'"}), 400

    conn = get_db()
    cursor = conn.cursor()
    device = cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not device:
        conn.close()
        return jsonify({"error": "Device not found"}), 404

    farm_id = device["farm_id"]
    farm = cursor.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
    user_id = farm["user_id"] if farm else 1
    conn.close()

    # Special handling for EMERGENCY STOP: Immediate fail-safe override
    if cmd_type == "EMERGENCY_STOP":
        cmd_id = queue_pump_command(device_id, "EMERGENCY_STOP", "EMERGENCY STOP TRIGGERED")
        stop_active_irrigation_event(farm_id, "emergency_stop")
        create_notification(user_id, f"EMERGENCY STOP issued on '{device['name']}'. All pump operations halted immediately.", "critical")
        return jsonify({
            "message": "EMERGENCY STOP executed and queued to hardware node",
            "command_id": cmd_id,
            "status": "emergency_halt"
        }), 200

    # Queue standard commands
    cmd_id = queue_pump_command(device_id, cmd_type, reason)

    if cmd_type == "ON":
        start_irrigation_event(farm_id, trigger_source="manual_dashboard")
        create_notification(user_id, f"Manual pump ON command queued for '{farm['name']}'.", "info")
    elif cmd_type == "OFF":
        stop_active_irrigation_event(farm_id, stop_reason="manual_stop")
        create_notification(user_id, f"Manual pump OFF command queued for '{farm['name']}'.", "info")

    return jsonify({
        "message": f"Command '{cmd_type}' queued successfully",
        "command_id": cmd_id,
        "device_id": device_id,
        "status": "pending"
    }), 202

@irrigation_bp.route("/api/irrigation/events", methods=["GET"])
def get_irrigation_events():
    farm_id = request.args.get("farm_id", type=int)
    limit = request.args.get("limit", 20, type=int)

    conn = get_db()
    cursor = conn.cursor()
    if farm_id:
        rows = cursor.execute("""
            SELECT * FROM irrigation_events
            WHERE farm_id = ?
            ORDER BY started_at DESC LIMIT ?
        """, (farm_id, limit)).fetchall()
    else:
        rows = cursor.execute("""
            SELECT * FROM irrigation_events
            ORDER BY started_at DESC LIMIT ?
        """, (limit,)).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows])

@irrigation_bp.route("/api/commands/poll", methods=["GET"])
def poll_commands():
    """
    Called by ESP32 MicroPython node to retrieve any queued commands.
    """
    device_id = request.args.get("device_id", 1, type=int)

    conn = get_db()
    cursor = conn.cursor()
    cmd = cursor.execute("""
        SELECT * FROM commands
        WHERE device_id = ? AND status = 'pending'
        ORDER BY created_at ASC LIMIT 1
    """, (device_id,)).fetchone()

    if not cmd:
        conn.close()
        return jsonify({"has_command": False, "command": None})

    # Enforce command expiry (e.g., 60 seconds)
    from backend.services.irrigation_service import COMMAND_EXPIRY_SECONDS
    created_at_str = cmd["created_at"]
    try:
        from datetime import datetime
        created_at = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
        age = (datetime.utcnow() - created_at).total_seconds()
        if age > COMMAND_EXPIRY_SECONDS:
            cursor.execute("UPDATE commands SET status = 'expired' WHERE id = ?", (cmd["id"],))
            conn.commit()
            conn.close()
            return jsonify({"has_command": False, "command": None, "status": "expired"})
    except Exception as e:
        print(f"Command expiry check error: {e}")

    cmd_dict = dict(cmd)
    cursor.execute("""
        UPDATE commands
        SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (cmd["id"],))
    conn.commit()
    conn.close()

    return jsonify({"has_command": True, "command": cmd_dict})


@irrigation_bp.route("/api/commands/ack", methods=["POST"])
def acknowledge_command():
    """
    Called by ESP32 node to acknowledge execution of a command.
    """
    data = request.get_json() or {}
    cmd_id = data.get("command_id")
    reported_pump_state = data.get("reported_pump_state", 0)
    exec_status = data.get("status", "completed")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE commands
        SET status = ?, acknowledged_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (exec_status, cmd_id))
    conn.commit()
    conn.close()

    return jsonify({"message": "Command acknowledgement recorded", "reported_state": reported_pump_state})
