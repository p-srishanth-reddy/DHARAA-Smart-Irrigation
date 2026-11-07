from flask import Blueprint, request, jsonify
from backend.database import get_db

devices_bp = Blueprint("devices", __name__)

@devices_bp.route("/api/devices/set_active_farm", methods=["POST"])
def set_active_farm():
    """
    Sets the currently active farm for a specific ESP32 device.
    Telemetry from this device will be attributed to this farm.
    """
    data = request.get_json() or {}
    device_id = data.get("device_id")
    farm_id = data.get("farm_id")

    if not device_id or not farm_id:
        return jsonify({"error": "Missing device_id or farm_id"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Validate farm exists
    farm = cursor.execute("SELECT id FROM farms WHERE id = ?", (farm_id,)).fetchone()
    if not farm:
        conn.close()
        return jsonify({"error": f"Farm ID {farm_id} not found"}), 404

    # Validate device exists
    device = cursor.execute("SELECT id FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not device:
        conn.close()
        return jsonify({"error": f"Device ID {device_id} not found"}), 404

    # Update active_farm_id
    cursor.execute("""
        UPDATE devices
        SET active_farm_id = ?
        WHERE id = ?
    """, (farm_id, device_id))

    conn.commit()
    conn.close()

    return jsonify({
        "message": f"Device {device_id} is now attributed to Farm {farm_id}",
        "device_id": device_id,
        "active_farm_id": farm_id
    }), 200
