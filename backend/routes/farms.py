from flask import Blueprint, request, jsonify
from backend.database import get_db

farms_bp = Blueprint("farms", __name__)

@farms_bp.route("/api/farms", methods=["GET", "POST"])
def list_create_farms():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "GET":
        user_id = request.args.get("user_id", 1, type=int)
        farms = cursor.execute("""
            SELECT * FROM farms
            WHERE user_id = ? AND archived = 0
            ORDER BY created_at DESC
        """, (user_id,)).fetchall()
        conn.close()
        return jsonify([dict(f) for f in farms])

    elif request.method == "POST":
        data = request.get_json() or {}
        user_id = data.get("user_id", 1)
        name = data.get("name", "").strip()
        state_district = data.get("state_district", "")
        lat = data.get("lat", 17.3850)
        lon = data.get("lon", 78.4867)
        area = data.get("area", 1.0)
        area_unit = data.get("area_unit", "acre")
        crop = data.get("crop", "Wheat")
        soil_type = data.get("soil_type", "Loamy")
        season = data.get("season", "Rabi")
        water_source = data.get("water_source", "Borewell")

        if not name:
            conn.close()
            return jsonify({"error": "Farm name is required"}), 400

        cursor.execute("""
            INSERT INTO farms (user_id, name, state_district, lat, lon, area, area_unit, crop, soil_type, season, water_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, name, state_district, lat, lon, area, area_unit, crop, soil_type, season, water_source))
        conn.commit()
        farm_id = cursor.lastrowid

        # Also create a default device for this farm
        from werkzeug.security import generate_password_hash
        dev_key = generate_password_hash(f"dev-key-farm-{farm_id}")
        cursor.execute("""
            INSERT INTO devices (farm_id, name, key_hash, status)
            VALUES (?, ?, ?, 'offline')
        """, (farm_id, f"ESP32-{name[:12]}", dev_key))
        conn.commit()
        conn.close()

        return jsonify({"message": "Farm created successfully", "farm_id": farm_id}), 201

@farms_bp.route("/api/farms/<int:farm_id>", methods=["GET", "PUT", "DELETE"])
def farm_detail(farm_id):
    conn = get_db()
    cursor = conn.cursor()

    farm = cursor.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
    if not farm:
        conn.close()
        return jsonify({"error": "Farm not found"}), 404

    if request.method == "GET":
        devices = cursor.execute("SELECT id, name, status, last_seen, firmware_version FROM devices WHERE farm_id = ?", (farm_id,)).fetchall()
        schedules = cursor.execute("SELECT * FROM schedules WHERE farm_id = ?", (farm_id,)).fetchall()
        conn.close()
        result = dict(farm)
        result["devices"] = [dict(d) for d in devices]
        result["schedules"] = [dict(s) for s in schedules]
        return jsonify(result)

    elif request.method == "PUT":
        data = request.get_json() or {}
        cursor.execute("""
            UPDATE farms
            SET name = COALESCE(?, name),
                state_district = COALESCE(?, state_district),
                lat = COALESCE(?, lat),
                lon = COALESCE(?, lon),
                area = COALESCE(?, area),
                area_unit = COALESCE(?, area_unit),
                crop = COALESCE(?, crop),
                soil_type = COALESCE(?, soil_type),
                season = COALESCE(?, season),
                water_source = COALESCE(?, water_source)
            WHERE id = ?
        """, (
            data.get("name"), data.get("state_district"), data.get("lat"), data.get("lon"),
            data.get("area"), data.get("area_unit"), data.get("crop"), data.get("soil_type"),
            data.get("season"), data.get("water_source"), farm_id
        ))
        conn.commit()
        conn.close()
        return jsonify({"message": "Farm updated successfully"})

    elif request.method == "DELETE":
        cursor.execute("UPDATE farms SET archived = 1 WHERE id = ?", (farm_id,))
        conn.commit()
        conn.close()
        return jsonify({"message": "Farm archived successfully"})
