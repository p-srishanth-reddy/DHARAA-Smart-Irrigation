from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from backend.database import get_db
from backend.services.scheduler_service import dharaa_scheduler

schedules_bp = Blueprint("schedules", __name__)

@schedules_bp.route("/api/schedules", methods=["GET", "POST"])
def list_create_schedules():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "GET":
        farm_id = request.args.get("farm_id", type=int)
        query = """
            SELECT s.*, f.name as farm_name, u.timezone as user_timezone
            FROM schedules s
            JOIN farms f ON s.farm_id = f.id
            JOIN users u ON f.user_id = u.id
        """
        if farm_id:
            query += " WHERE s.farm_id = ? ORDER BY s.id DESC"
            schedules = cursor.execute(query, (farm_id,)).fetchall()
        else:
            query += " ORDER BY s.id DESC"
            schedules = cursor.execute(query).fetchall()
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
            INSERT INTO schedules (farm_id, name, start_time, target_moisture, runtime_limit, status, notes, last_run_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
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
        reset_state = data.get("reset_run_state", False)

        if reset_state:
            cursor.execute("""
                UPDATE schedules
                SET name = COALESCE(?, name),
                    start_time = COALESCE(?, start_time),
                    target_moisture = COALESCE(?, target_moisture),
                    runtime_limit = COALESCE(?, runtime_limit),
                    status = COALESCE(?, status),
                    notes = COALESCE(?, notes),
                    last_run_date = NULL,
                    last_run_status = 'reset to pending'
                WHERE id = ?
            """, (
                data.get("name"), data.get("start_time"), data.get("target_moisture"),
                data.get("runtime_limit"), data.get("status"), data.get("notes"), sched_id
            ))
        else:
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

@schedules_bp.route("/api/schedules/<int:sched_id>/run-now", methods=["POST"])
def run_schedule_now_endpoint(sched_id):
    """
    Manually triggers immediate pre-flight safety evaluation and pump execution
    for a given schedule, without waiting for the daily clock time.
    """
    res = dharaa_scheduler.run_schedule_now(sched_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@schedules_bp.route("/api/schedules/scheduler-status", methods=["GET"])
def get_scheduler_status():
    """
    Returns the real-time background scheduler thread state and metrics.
    """
    return jsonify({
        "is_running": dharaa_scheduler.is_running(),
        "check_interval_seconds": dharaa_scheduler.check_interval,
        "last_check_at": dharaa_scheduler.last_check_at,
        "server_utc_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    })
