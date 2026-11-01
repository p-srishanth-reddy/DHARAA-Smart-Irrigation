from flask import Blueprint, request, jsonify
from backend.database import get_db

analytics_bp = Blueprint("analytics", __name__)

@analytics_bp.route("/api/analytics/summary", methods=["GET"])
def get_analytics_summary():
    farm_id = request.args.get("farm_id", 1, type=int)

    conn = get_db()
    cursor = conn.cursor()

    # Find primary device for this farm
    dev = cursor.execute("SELECT id FROM devices WHERE farm_id = ? LIMIT 1", (farm_id,)).fetchone()
    device_id = dev["id"] if dev else 1

    # 1. Total Telemetry readings recorded
    telemetry_count = cursor.execute("""
        SELECT COUNT(*) as count, MIN(timestamp) as first_seen, MAX(timestamp) as last_seen
        FROM telemetry WHERE device_id = ?
    """, (device_id,)).fetchone()

    # 2. Daily average moisture over past 7 days
    daily_moisture = cursor.execute("""
        SELECT DATE(timestamp) as date, AVG(moisture) as avg_moisture, MIN(moisture) as min_moisture, MAX(moisture) as max_moisture
        FROM telemetry
        WHERE device_id = ? AND moisture IS NOT NULL
        GROUP BY DATE(timestamp)
        ORDER BY date DESC LIMIT 7
    """, (device_id,)).fetchall()

    # 3. Daily pump runtime (minutes) over past 7 days
    daily_runtime = cursor.execute("""
        SELECT DATE(started_at) as date,
               COUNT(id) as session_count,
               SUM(CASE 
                   WHEN ended_at IS NOT NULL THEN (strftime('%s', ended_at) - strftime('%s', started_at)) / 60.0
                   ELSE 5.0
               END) as total_runtime_minutes,
               SUM(estimated_litres) as total_litres
        FROM irrigation_events
        WHERE farm_id = ?
        GROUP BY DATE(started_at)
        ORDER BY date DESC LIMIT 7
    """, (farm_id,)).fetchall()

    # 4. Total lifetime stats
    total_events = cursor.execute("SELECT COUNT(*) as cnt FROM irrigation_events WHERE farm_id = ?", (farm_id,)).fetchone()

    conn.close()

    return jsonify({
        "device_id": device_id,
        "farm_id": farm_id,
        "telemetry_stats": {
            "total_readings": telemetry_count["count"] if telemetry_count else 0,
            "first_reading": telemetry_count["first_seen"] if telemetry_count else None,
            "last_reading": telemetry_count["last_seen"] if telemetry_count else None
        },
        "total_irrigation_sessions": total_events["cnt"] if total_events else 0,
        "daily_moisture_trend": [dict(r) for r in reversed(daily_moisture)],
        "daily_runtime_trend": [dict(r) for r in reversed(daily_runtime)],
        "calibration_notice": "Water volume estimates (litres) require completed physical flow sensor pulse calibration."
    })
