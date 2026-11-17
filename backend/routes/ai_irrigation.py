"""
DHARAA AI Irrigation Routes
============================
New REST API endpoints for AI-based water prediction and intelligent pump control.
All existing /api/irrigation/* endpoints remain completely unchanged.
"""

import json
from flask import Blueprint, request, jsonify
from backend.database import get_db
from backend.services.water_prediction_service import water_predictor, FLOW_PULSES_PER_LITRE
from backend.services.water_model_trainer import train_water_model, MIN_RECORDS_TO_TRAIN, record_irrigation_outcome
from backend.services.irrigation_service import (
    queue_pump_command, start_irrigation_event, stop_active_irrigation_event
)
from backend.services.weather_service import get_weather_forecast
from backend.services.notification_service import create_notification

ai_irrigation_bp = Blueprint("ai_irrigation", __name__)

# ---------------------------------------------------------------------------
# Safety limits (additive — does not replace existing safety mechanisms)
# ---------------------------------------------------------------------------
MAX_AI_WATER_ML_PER_CYCLE = 200_000   # 200 L absolute cap
MAX_AI_RUNTIME_SECONDS    = 300       # 5-minute cap (matches existing firmware limit)


# ---------------------------------------------------------------------------
# GET /api/ai-irrigation/predict
# ---------------------------------------------------------------------------

@ai_irrigation_bp.route("/api/ai-irrigation/predict", methods=["POST"])
def ai_predict():
    """
    Generate an AI water requirement prediction.
    Request body: { "farm_id": int, "device_id": int (optional) }
    """
    data      = request.get_json() or {}
    farm_id   = data.get("farm_id", 1)
    device_id = data.get("device_id")

    conn   = get_db()
    cursor = conn.cursor()

    # Resolve device_id if not supplied
    if not device_id:
        dev = cursor.execute(
            "SELECT id FROM devices WHERE farm_id = ? LIMIT 1", (farm_id,)
        ).fetchone()
        device_id = dev["id"] if dev else 1

    # Fetch latest telemetry
    telemetry_row = cursor.execute("""
        SELECT t.* FROM telemetry t
        JOIN devices d ON t.device_id = d.id
        WHERE d.farm_id = ? OR t.device_id = ?
        ORDER BY t.timestamp DESC LIMIT 1
    """, (farm_id, device_id)).fetchone()

    # Fetch farm for weather coordinates
    farm = cursor.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
    conn.close()

    telemetry = dict(telemetry_row) if telemetry_row else {}
    weather   = {}
    if farm and farm["lat"] and farm["lon"]:
        try:
            weather = get_weather_forecast(farm["lat"], farm["lon"])
        except Exception as e:
            print(f"[AI Predict] Weather fetch error: {e}")

    prediction = water_predictor.predict(farm_id, device_id, telemetry, weather)
    return jsonify(prediction), 200


# ---------------------------------------------------------------------------
# POST /api/ai-irrigation/start
# ---------------------------------------------------------------------------

@ai_irrigation_bp.route("/api/ai-irrigation/start", methods=["POST"])
def ai_start_irrigation():
    """
    Start an AI-guided irrigation cycle.
    Request body: { "farm_id": int, "device_id": int, "prediction_id": int (optional) }

    Flow:
    1. Run (or reuse) prediction
    2. Safety pre-flight checks
    3. Queue ON command with target_pulses in payload JSON
    4. Create irrigation_event linked to prediction
    """
    data      = request.get_json() or {}
    farm_id   = data.get("farm_id", 1)
    device_id = data.get("device_id")
    pred_id   = data.get("prediction_id")

    conn   = get_db()
    cursor = conn.cursor()

    # Resolve device
    if not device_id:
        dev = cursor.execute(
            "SELECT id FROM devices WHERE farm_id = ? LIMIT 1", (farm_id,)
        ).fetchone()
        device_id = dev["id"] if dev else 1

    farm = cursor.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
    if not farm:
        conn.close()
        return jsonify({"error": "Farm not found"}), 404

    user_id = farm["user_id"]

    # Pre-flight: check for existing running event
    active = cursor.execute(
        "SELECT id FROM irrigation_events WHERE farm_id = ? AND status = 'running' LIMIT 1",
        (farm_id,)
    ).fetchone()
    if active:
        conn.close()
        return jsonify({
            "error": "Irrigation already in progress",
            "active_event_id": active["id"]
        }), 409

    # Pre-flight: rain sensor check
    latest_tel = cursor.execute("""
        SELECT t.rain, t.moisture, t.temperature, t.humidity, t.sensor_status
        FROM telemetry t JOIN devices d ON t.device_id = d.id
        WHERE d.farm_id = ? ORDER BY t.timestamp DESC LIMIT 1
    """, (farm_id,)).fetchone()

    if latest_tel and latest_tel["rain"] == 1:
        conn.close()
        return jsonify({
            "error": "Rain detected on field. AI irrigation inhibited.",
            "safety": "rain_inhibit"
        }), 422

    if latest_tel and latest_tel["sensor_status"] not in ("OK", None, ""):
        conn.close()
        return jsonify({
            "error": f"Sensor fault: {latest_tel['sensor_status']}. Cannot start irrigation.",
            "safety": "sensor_fault"
        }), 422

    conn.close()

    # Fetch prediction (run fresh if no pred_id)
    if pred_id:
        conn2  = get_db()
        pred_row = conn2.execute(
            "SELECT * FROM ai_predictions WHERE id = ?", (pred_id,)
        ).fetchone()
        conn2.close()
        prediction = dict(pred_row) if pred_row else None
        if not prediction:
            pred_id  = None

    if not pred_id:
        # Run fresh prediction
        telemetry = dict(latest_tel) if latest_tel else {}
        weather   = {}
        if farm["lat"] and farm["lon"]:
            try:
                weather = get_weather_forecast(farm["lat"], farm["lon"])
            except Exception:
                pass
        prediction = water_predictor.predict(farm_id, device_id, telemetry, weather)
        pred_id = prediction.get("prediction_id")

    if not prediction:
        return jsonify({"error": "Could not generate prediction"}), 500

    # Respect weather-based postpone from prediction
    if not prediction.get("recommended_irrigate", False):
        return jsonify({
            "error": "AI does not recommend irrigation at this time.",
            "explanation": prediction.get("explanation", ""),
            "priority": prediction.get("priority", "LOW"),
            "prediction": prediction,
        }), 422

    # Determine target quantity and pulses
    target_ml     = min(float(prediction.get("predicted_water_ml", 0) or 0), MAX_AI_WATER_ML_PER_CYCLE)
    target_pulses = int(prediction.get("target_pulses", 0) or round(target_ml / (1000.0 / FLOW_PULSES_PER_LITRE)))

    if target_ml < 100:
        return jsonify({
            "error": "Predicted water requirement too low to trigger irrigation.",
            "predicted_water_ml": target_ml,
        }), 422

    # Build command payload (JSON so firmware can parse target_pulses)
    cmd_payload = json.dumps({
        "reason":        f"AI irrigation: {target_ml:.0f}ml target",
        "target_pulses": target_pulses,
        "target_ml":     round(target_ml, 1),
        "prediction_id": pred_id,
    })

    # Queue the pump ON command
    cmd_id = queue_pump_command(device_id, "ON", cmd_payload)

    # Create irrigation event linked to this prediction
    conn3  = get_db()
    cursor3 = conn3.cursor()

    # Close any lingering running events first
    cursor3.execute("""
        UPDATE irrigation_events
        SET status = 'completed', ended_at = CURRENT_TIMESTAMP, stop_reason = 'superseded'
        WHERE farm_id = ? AND status = 'running'
    """, (farm_id,))

    cursor3.execute("""
        INSERT INTO irrigation_events
            (farm_id, trigger_source, status, ai_prediction_id, target_water_ml, target_pulses)
        VALUES (?, 'ai_prediction', 'running', ?, ?, ?)
    """, (farm_id, pred_id, round(target_ml, 2), target_pulses))
    conn3.commit()
    event_id = cursor3.lastrowid
    conn3.close()

    create_notification(
        user_id,
        f"AI Irrigation started on '{farm['name']}': targeting {target_ml/1000:.2f}L "
        f"(priority: {prediction.get('priority','?')}). Command #{cmd_id}.",
        "info"
    )

    return jsonify({
        "message":        "AI irrigation command queued",
        "command_id":     cmd_id,
        "event_id":       event_id,
        "prediction_id":  pred_id,
        "target_water_ml":    round(target_ml, 2),
        "target_pulses":      target_pulses,
        "predicted_duration_s": prediction.get("predicted_duration_s", 0),
        "priority":       prediction.get("priority", "LOW"),
        "explanation":    prediction.get("explanation", ""),
        "estimator_type": prediction.get("estimator_type", "baseline"),
    }), 202


# ---------------------------------------------------------------------------
# POST /api/ai-irrigation/complete
# ---------------------------------------------------------------------------

@ai_irrigation_bp.route("/api/ai-irrigation/complete", methods=["POST"])
def ai_complete_irrigation():
    """
    Called (by telemetry route or manually) when an AI session ends.
    Records actual delivery and stores learning record.
    Request body: {
        "farm_id": int, "event_id": int,
        "actual_pulses": int, "stop_reason": str,
        "final_moisture": float (optional)
    }
    """
    data           = request.get_json() or {}
    farm_id        = data.get("farm_id", 1)
    event_id       = data.get("event_id")
    actual_pulses  = data.get("actual_pulses", 0)
    stop_reason    = data.get("stop_reason", "completed")
    final_moisture = data.get("final_moisture")

    actual_water_ml = round(actual_pulses * (1000.0 / FLOW_PULSES_PER_LITRE), 1)

    conn   = get_db()
    cursor = conn.cursor()

    # Update irrigation_event with actual values
    cursor.execute("""
        UPDATE irrigation_events
        SET status = 'completed', ended_at = CURRENT_TIMESTAMP,
            stop_reason = ?, actual_water_ml = ?, actual_pulses = ?,
            estimated_litres = ?
        WHERE id = ? AND farm_id = ?
    """, (
        stop_reason, actual_water_ml, actual_pulses,
        round(actual_water_ml / 1000.0, 3),
        event_id, farm_id
    ))
    conn.commit()

    # Fetch event details to build learning record
    event = cursor.execute(
        "SELECT * FROM irrigation_events WHERE id = ?", (event_id,)
    ).fetchone()
    conn.close()

    if event:
        # Fetch initial moisture from first telemetry near session start
        conn2  = get_db()
        tel = conn2.execute("""
            SELECT t.moisture, t.temperature, t.humidity, t.rain
            FROM telemetry t JOIN devices d ON t.device_id = d.id
            WHERE d.farm_id = ?
            ORDER BY ABS(strftime('%s', t.timestamp) - strftime('%s', ?)) ASC LIMIT 1
        """, (farm_id, event["started_at"] or "2000-01-01")).fetchone()
        conn2.close()

        init_moisture = tel["moisture"] if tel else None
        temperature   = tel["temperature"] if tel else None
        humidity      = tel["humidity"] if tel else None
        rain          = tel["rain"] if tel else 0

        # Calculate actual duration
        actual_dur_s = None
        if event["started_at"] and event["ended_at"]:
            try:
                from datetime import datetime
                ts = datetime.strptime(event["started_at"], "%Y-%m-%d %H:%M:%S")
                te = datetime.strptime(event["ended_at"],   "%Y-%m-%d %H:%M:%S")
                actual_dur_s = (te - ts).total_seconds()
            except Exception:
                pass

        # Fetch prediction details
        pred_water_ml  = None
        pred_dur_s     = None
        if event["ai_prediction_id"]:
            conn3 = get_db()
            pred  = conn3.execute(
                "SELECT predicted_water_ml, predicted_duration_s FROM ai_predictions WHERE id = ?",
                (event["ai_prediction_id"],)
            ).fetchone()
            conn3.close()
            if pred:
                pred_water_ml = pred["predicted_water_ml"]
                pred_dur_s    = pred["predicted_duration_s"]

        record_irrigation_outcome(
            farm_id=farm_id,
            irrigation_event_id=event_id,
            initial_moisture=init_moisture,
            final_moisture=final_moisture,
            predicted_water_ml=pred_water_ml,
            actual_water_ml=actual_water_ml,
            predicted_duration_s=pred_dur_s,
            actual_duration_s=actual_dur_s,
            temperature=temperature,
            humidity=humidity,
            rain=rain,
            stop_reason=stop_reason,
            started_at=event["started_at"],
            ended_at=event["ended_at"],
        )

    return jsonify({
        "message":        "AI irrigation cycle recorded",
        "actual_water_ml": actual_water_ml,
        "actual_pulses":   actual_pulses,
        "stop_reason":     stop_reason,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/ai-irrigation/history
# ---------------------------------------------------------------------------

@ai_irrigation_bp.route("/api/ai-irrigation/history", methods=["GET"])
def ai_history():
    """
    Returns AI irrigation learning records for a farm.
    Query params: farm_id, limit (default 20)
    """
    farm_id = request.args.get("farm_id", 1, type=int)
    limit   = request.args.get("limit", 20, type=int)

    conn = get_db()
    rows = conn.execute("""
        SELECT ilr.*, p.priority, p.estimator_type, p.explanation
        FROM irrigation_learning_records ilr
        LEFT JOIN ai_predictions p ON ilr.irrigation_event_id = p.id
        WHERE ilr.farm_id = ?
        ORDER BY ilr.created_at DESC LIMIT ?
    """, (farm_id, limit)).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows]), 200


# ---------------------------------------------------------------------------
# GET /api/ai-irrigation/predictions
# ---------------------------------------------------------------------------

@ai_irrigation_bp.route("/api/ai-irrigation/predictions", methods=["GET"])
def ai_predictions_list():
    """
    Returns recent AI predictions for a farm.
    Query params: farm_id, limit (default 10)
    """
    farm_id = request.args.get("farm_id", 1, type=int)
    limit   = request.args.get("limit", 10, type=int)

    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM ai_predictions
        WHERE farm_id = ?
        ORDER BY created_at DESC LIMIT ?
    """, (farm_id, limit)).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows]), 200


# ---------------------------------------------------------------------------
# GET /api/ai-irrigation/model-status
# ---------------------------------------------------------------------------

@ai_irrigation_bp.route("/api/ai-irrigation/model-status", methods=["GET"])
def ai_model_status():
    """Returns current water prediction model status and performance metrics."""
    return jsonify(water_predictor.get_model_status()), 200


# ---------------------------------------------------------------------------
# POST /api/ai-irrigation/model-train
# ---------------------------------------------------------------------------

@ai_irrigation_bp.route("/api/ai-irrigation/model-train", methods=["POST"])
def ai_model_train():
    """
    Trigger adaptive model retraining.
    Requires sufficient learning records. Safe to call; will not train if data insufficient.
    """
    result = train_water_model()
    status = 200 if result.get("success") else 422
    return jsonify(result), status
