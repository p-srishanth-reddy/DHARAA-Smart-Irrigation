from flask import Blueprint, request, jsonify
from backend.database import get_db
from backend.services.geo_service import (
    resolve_timezone,
    reverse_geocode_location,
    format_locality_hierarchy,
    is_valid_iana_timezone
)

farms_bp = Blueprint("farms", __name__)

@farms_bp.route("/api/farms/lookup-coordinates", methods=["POST"])
def lookup_coordinates():
    """
    Looks up locality hierarchy (village, mandal/taluk, district, state)
    and resolves the IANA timezone from latitude and longitude.
    """
    data = request.get_json() or {}
    lat = data.get("lat")
    lon = data.get("lon")

    if lat is None or lon is None:
        return jsonify({"error": "Latitude and longitude are required"}), 400

    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid coordinate format"}), 400

    tz = resolve_timezone(lat, lon)
    geo_data = reverse_geocode_location(lat, lon)
    geo_data["timezone"] = tz

    return jsonify(geo_data)

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

        result = []
        for f in farms:
            f_dict = dict(f)
            f_dict["location_hierarchy"] = format_locality_hierarchy(
                f_dict.get("village_locality"),
                f_dict.get("mandal_taluk"),
                f_dict.get("district"),
                f_dict.get("state")
            )
            result.append(f_dict)
        return jsonify(result)

    elif request.method == "POST":
        data = request.get_json() or {}
        user_id = data.get("user_id", 1)
        name = data.get("name", "").strip()
        lat = float(data.get("lat", 17.3850))
        lon = float(data.get("lon", 78.4867))
        area = float(data.get("area", 1.0))
        area_unit = data.get("area_unit", "acre")
        crop = data.get("crop", "Wheat")
        soil_type = data.get("soil_type", "Loamy")
        season = data.get("season", "Rabi")
        water_source = data.get("water_source", "Borewell")

        if not name:
            conn.close()
            return jsonify({"error": "Farm name is required"}), 400

        # Location Hierarchy & Timezone Resolution
        village_locality = (data.get("village_locality") or "").strip()
        mandal_taluk = (data.get("mandal_taluk") or "").strip()
        district = (data.get("district") or "").strip()
        state = (data.get("state") or "").strip()
        tz_input = (data.get("timezone") or "").strip()

        # Resolve IANA timezone from coordinates if not manually provided/valid
        if tz_input and is_valid_iana_timezone(tz_input):
            timezone = tz_input
        else:
            timezone = resolve_timezone(lat, lon)

        # Reverse geocode place details if any levels are missing
        if not (village_locality and mandal_taluk and district and state):
            geo = reverse_geocode_location(lat, lon)
            village_locality = village_locality or geo.get("village_locality", "")
            mandal_taluk = mandal_taluk or geo.get("mandal_taluk", "")
            district = district or geo.get("district", "")
            state = state or geo.get("state", "")

        state_district = format_locality_hierarchy(village_locality, mandal_taluk, district, state)

        cursor.execute("""
            INSERT INTO farms (
                user_id, name, state_district, village_locality, mandal_taluk,
                district, state, timezone, lat, lon, area, area_unit,
                crop, soil_type, season, water_source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, name, state_district, village_locality, mandal_taluk,
            district, state, timezone, lat, lon, area, area_unit,
            crop, soil_type, season, water_source
        ))
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

        return jsonify({
            "message": "Farm created successfully",
            "farm_id": farm_id,
            "timezone": timezone,
            "location_hierarchy": state_district
        }), 201

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
        result["location_hierarchy"] = format_locality_hierarchy(
            result.get("village_locality"),
            result.get("mandal_taluk"),
            result.get("district"),
            result.get("state")
        )
        result["devices"] = [dict(d) for d in devices]
        result["schedules"] = [dict(s) for s in schedules]
        return jsonify(result)

    elif request.method == "PUT":
        data = request.get_json() or {}
        old_lat = farm["lat"]
        old_lon = farm["lon"]
        new_lat = data.get("lat")
        new_lon = data.get("lon")

        # Determine effective coordinates
        lat = float(new_lat) if new_lat is not None else old_lat
        lon = float(new_lon) if new_lon is not None else old_lon

        coords_changed = (new_lat is not None and abs(float(new_lat) - old_lat) > 0.0001) or \
                         (new_lon is not None and abs(float(new_lon) - old_lon) > 0.0001)

        # Timezone Handling: Manual override vs automatic recalculation on coordinate change
        manual_tz = data.get("timezone")
        if manual_tz and is_valid_iana_timezone(manual_tz):
            # Operator manual correction
            effective_tz = manual_tz.strip()
        elif coords_changed:
            # Coordinates changed, recalculate IANA timezone
            effective_tz = resolve_timezone(lat, lon)
        else:
            effective_tz = farm["timezone"] or resolve_timezone(lat, lon)

        # Location Hierarchy Handling
        village_locality = data.get("village_locality")
        mandal_taluk = data.get("mandal_taluk")
        district = data.get("district")
        state = data.get("state")

        # If coordinates changed and user didn't specify location hierarchy, auto-lookup
        if coords_changed and not any([village_locality, mandal_taluk, district, state]):
            geo = reverse_geocode_location(lat, lon)
            village_locality = geo.get("village_locality") or farm["village_locality"]
            mandal_taluk = geo.get("mandal_taluk") or farm["mandal_taluk"]
            district = geo.get("district") or farm["district"]
            state = geo.get("state") or farm["state"]
        else:
            village_locality = village_locality if village_locality is not None else farm["village_locality"]
            mandal_taluk = mandal_taluk if mandal_taluk is not None else farm["mandal_taluk"]
            district = district if district is not None else farm["district"]
            state = state if state is not None else farm["state"]

        formatted_loc = format_locality_hierarchy(village_locality, mandal_taluk, district, state)

        cursor.execute("""
            UPDATE farms
            SET name = COALESCE(?, name),
                state_district = ?,
                village_locality = ?,
                mandal_taluk = ?,
                district = ?,
                state = ?,
                timezone = ?,
                lat = ?,
                lon = ?,
                area = COALESCE(?, area),
                area_unit = COALESCE(?, area_unit),
                crop = COALESCE(?, crop),
                soil_type = COALESCE(?, soil_type),
                season = COALESCE(?, season),
                water_source = COALESCE(?, water_source)
            WHERE id = ?
        """, (
            data.get("name"), formatted_loc, village_locality, mandal_taluk,
            district, state, effective_tz, lat, lon,
            data.get("area"), data.get("area_unit"), data.get("crop"),
            data.get("soil_type"), data.get("season"), data.get("water_source"),
            farm_id
        ))
        conn.commit()
        conn.close()
        return jsonify({
            "message": "Farm updated successfully",
            "timezone": effective_tz,
            "location_hierarchy": formatted_loc
        })

    elif request.method == "DELETE":
        cursor.execute("UPDATE farms SET archived = 1 WHERE id = ?", (farm_id,))
        conn.commit()
        conn.close()
        return jsonify({"message": "Farm archived successfully"})
