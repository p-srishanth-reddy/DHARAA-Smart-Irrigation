from flask import Blueprint, request, jsonify
from backend.database import get_db

schedules_bp = Blueprint("schedules", __name__)

@schedules_bp.route("/api/schedules", methods=["GET", "POST"])
def list_create_schedules():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "GET":
        farm_id = request.args.get("farm_id", type=int)
        if farm_id:
            schedules = cursor.execute("""
                SELECT s.*, f.name as farm_name FROM schedules s
                JOIN farms f ON s.farm_id = f.id
                WHERE s.farm_id = ?
                ORDER BY s.id DESC
            """, (farm_id,)).fetchall()
        else:
            schedules = cursor.execute("""
                SELECT s.*, f.name as farm_name FROM schedules s
                JOIN farms f ON s.farm_id = f.id
                ORDER BY s.id DESC
            """).fetchall()
        conn.close()
        return jsonify([dict(s) for s in schedules])

    elif request.method == "POST":
        data = request.get_json() or {}
        farm_id = data.get("farm_id")
        name = data.get("name", "Scheduled Irrigation").strip()
        start_time = data.get("start_time", "06:00")
        target_moisture = float(data.get("target_moisture", 45.0))
        runtime_limit = int(data.get("runtime_limit", 300))
        status = data.get("status", "active")
        notes = data.get("notes", "")

        if not farm_id:
            conn.close()
            return jsonify({"error": "farm_id is required"}), 400

        cursor.execute("""
            INSERT INTO schedules (farm_id, name, start_time, target_moisture, runtime_limit, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (farm_id, name, start_time, target_moisture, runtime_limit, status, notes))
        conn.commit()
        sched_id = cursor.lastrowid
        conn.close()

        return jsonify({"message": "Schedule created", "schedule_id": sched_id}), 201

@schedules_bp.route("/api/schedules/<int:sched_id>", methods=["PUT", "DELETE"])
def update_delete_schedule(sched_id):
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "PUT":
        data = request.get_json() or {}
        cursor.execute("""
            UPDATE schedules
            SET name = COALESCE(?, name),
                start_time = COALESCE(?, start_time),
                target_moisture = COALESCE(?, target_moisture),
                runtime_limit = COALESCE(?, runtime_limit),
                status = COALESCE(?, status),
                notes = COALESCE(?, notes)
            WHERE id = ?
        """, (
            data.get("name"), data.get("start_time"), data.get("target_moisture"),
            data.get("runtime_limit"), data.get("status"), data.get("notes"), sched_id
        ))
        conn.commit()
        conn.close()
        return jsonify({"message": "Schedule updated"})

    elif request.method == "DELETE":
        cursor.execute("DELETE FROM schedules WHERE id = ?", (sched_id,))
        conn.commit()
        conn.close()
        return jsonify({"message": "Schedule deleted"})
