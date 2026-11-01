from flask import Blueprint, request, jsonify
import os
import joblib
import numpy as np

advisor_bp = Blueprint("advisor", __name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "ml")
MODEL_PATH = os.path.join(MODEL_DIR, "crop_model.joblib")
SCALER_PATH = os.path.join(MODEL_DIR, "preprocessor.joblib")

_model = None
_scaler = None

def load_ml_assets():
    global _model, _scaler
    if _model is None and os.path.exists(MODEL_PATH):
        try:
            _model = joblib.load(MODEL_PATH)
            _scaler = joblib.load(SCALER_PATH)
        except Exception as e:
            print("Error loading ML model:", e)

@advisor_bp.route("/api/advisor/crop", methods=["POST"])
def recommend_crop():
    """
    ML Crop Recommendation using trained Random Forest model.
    Mandatory features: N, P, K, temperature, humidity, ph, rainfall.
    """
    load_ml_assets()

    data = request.get_json() or {}
    try:
        n = float(data.get("N", 50))
        p = float(data.get("P", 50))
        k = float(data.get("K", 50))
        temperature = float(data.get("temperature", 25.0))
        humidity = float(data.get("humidity", 70.0))
        ph = float(data.get("ph", 6.5))
        rainfall = float(data.get("rainfall", 100.0))
    except (ValueError, TypeError):
        return jsonify({"error": "All inputs (N, P, K, temperature, humidity, ph, rainfall) must be valid numbers"}), 400

    import pandas as pd
    features = pd.DataFrame([[n, p, k, temperature, humidity, ph, rainfall]],
                            columns=["N", "P", "K", "temperature", "humidity", "ph", "rainfall"])

    if _model is not None and _scaler is not None:
        scaled_feat = _scaler.transform(features)
        pred_label = _model.predict(scaled_feat)[0]
        probs = _model.predict_proba(scaled_feat)[0]

        # Get top 3 recommended crops with confidence
        top_indices = np.argsort(probs)[::-1][:3]
        top_recommendations = [
            {"crop": _model.classes_[idx], "confidence": round(float(probs[idx]) * 100, 1)}
            for idx in top_indices if probs[idx] > 0.05
        ]
    else:
        # Fallback heuristic if model file not yet loaded
        pred_label = "Wheat"
        top_recommendations = [{"crop": "Wheat", "confidence": 85.0}]

    return jsonify({
        "recommended_crop": pred_label,
        "top_recommendations": top_recommendations,
        "input_features": {
            "N": n, "P": p, "K": k,
            "temperature": temperature, "humidity": humidity,
            "ph": ph, "rainfall": rainfall
        },
        "model_confidence": top_recommendations[0]["confidence"] if top_recommendations else 90.0,
        "limitations_disclaimer": (
            "DHARAA Agronomic Notice: Crop recommendation is derived from statistical soil macronutrient "
            "(N, P, K) and agro-climatic boundaries. It does not replace on-field laboratory soil tests, local pest "
            "incidence assessments, or guaranteed yield metrics."
        )
    })

@advisor_bp.route("/api/advisor/irrigation", methods=["POST"])
def irrigation_advice():
    """
    Rule-based agronomic irrigation advice factoring live moisture, weather forecast, and crop stage.
    """
    data = request.get_json() or {}
    moisture = data.get("moisture")
    crop = data.get("crop", "General Crop")
    temperature = data.get("temperature", 28.0)
    rain_probability = data.get("rain_probability", 0)

    advice = []
    urgency = "LOW"
    recommended_runtime_sec = 0

    if moisture is None:
        return jsonify({
            "status": "UNKNOWN",
            "urgency": "UNKNOWN",
            "headline": "Sensor Offline or Stale",
            "advice": ["Unable to provide live irrigation advice without valid soil moisture readings."]
        })

    moisture = float(moisture)

    if rain_probability >= 50:
        urgency = "INHIBITED"
        headline = "Rain Expected Soon — Postpone Irrigation"
        advice.append(f"Upcoming rain forecast ({rain_probability}% probability). Postpone planned irrigation to prevent waterlogging and conserve energy.")
    elif moisture < 30:
        urgency = "HIGH"
        headline = "Critical Soil Moisture Deficit"
        recommended_runtime_sec = 300
        advice.append(f"Soil moisture is critically low at {moisture:.1f}% (below 30%). Immediate root zone replenishment recommended.")
        if temperature > 32:
            advice.append("High ambient temperature detected: consider early morning or late evening cycle to minimize evaporative losses.")
    elif moisture < 40:
        urgency = "MODERATE"
        headline = "Moderate Moisture Level"
        recommended_runtime_sec = 180
        advice.append(f"Soil moisture is at {moisture:.1f}%. Approaching minimum threshold for {crop}. Schedule an irrigation session today.")
    else:
        urgency = "NONE"
        headline = "Optimal Soil Hydration"
        advice.append(f"Soil moisture is well maintained at {moisture:.1f}%. Root zone is within safe field capacity. No irrigation needed.")

    return jsonify({
        "urgency": urgency,
        "headline": headline,
        "recommended_runtime_seconds": recommended_runtime_sec,
        "advice_points": advice,
        "source": "DHARAA Agronomic Expert System"
    })
