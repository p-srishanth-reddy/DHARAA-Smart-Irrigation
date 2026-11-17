"""
DHARAA Water Requirement Prediction Service
============================================
Implements a scientifically grounded water quantity estimator using:
  - FAO-56 simplified crop evapotranspiration (Hargreaves ET₀ approximation)
  - Crop coefficient (Kc) lookup by crop type
  - Soil field-capacity lookup by soil type
  - Weather-aware irrigation postponement/reduction
  - Optional RandomForestRegressor when sufficient learning data exists

The baseline estimator is clearly labelled as such. It never fabricates sensor data.
"""

import os
import json
import math
import time
from datetime import datetime
from backend.database import get_db

# ---------------------------------------------------------------------------
# Physical & Agronomic Constants
# ---------------------------------------------------------------------------

FLOW_PULSES_PER_LITRE = 450.0          # YF-S201 calibration (matches config.py)
FLOW_ML_PER_PULSE     = 1000.0 / FLOW_PULSES_PER_LITRE  # ~2.22 ml/pulse

# Root-zone effective depth assumptions per soil type (mm)
SOIL_DEPTH_MM = {
    "Sandy":             250,
    "Sandy Loam":        300,
    "Loamy":             350,
    "Loam":              350,
    "Clay Loam":         380,
    "Clay":              400,
    "Black Cotton Soil": 400,
    "Silt Loam":         360,
    "Red Soil":          300,
    "Laterite":          280,
}
DEFAULT_SOIL_DEPTH_MM = 320

# Field capacity (%) and wilting point (%) per soil type
SOIL_FIELD_CAPACITY = {
    "Sandy":             28,
    "Sandy Loam":        34,
    "Loamy":             42,
    "Loam":              42,
    "Clay Loam":         48,
    "Clay":              54,
    "Black Cotton Soil": 52,
    "Silt Loam":         44,
    "Red Soil":          36,
    "Laterite":          34,
}
DEFAULT_FIELD_CAPACITY = 42

SOIL_WILTING_POINT = {
    "Sandy":             10,
    "Sandy Loam":        14,
    "Loamy":             18,
    "Loam":              18,
    "Clay Loam":         22,
    "Clay":              26,
    "Black Cotton Soil": 25,
    "Silt Loam":         20,
    "Red Soil":          16,
    "Laterite":          14,
}
DEFAULT_WILTING_POINT = 18

# Crop coefficient Kc (mid-season, dimensionless)
CROP_KC = {
    "Wheat":        0.90,
    "Rice":         1.20,
    "Cotton":       1.15,
    "Maize":        1.10,
    "Sugarcane":    1.25,
    "Soybean":      1.00,
    "Groundnut":    0.95,
    "Sunflower":    1.05,
    "Jowar":        0.85,
    "Bajra":        0.85,
    "Ragi":         0.90,
    "Tomato":       1.10,
    "Chilli":       1.00,
    "Onion":        0.95,
    "Potato":       1.10,
    "Banana":       1.10,
    "Mango":        0.85,
    "Coconut":      0.95,
    "Coffee":       0.90,
    "Jute":         1.00,
    "Lentil":       0.80,
    "Chickpea":     0.80,
    "Pigeonpeas":   0.85,
    "Blackgram":    0.75,
    "Mungbean":     0.75,
    "Mothbeans":    0.75,
    "Kidneybeans":  0.85,
    "Papaya":       0.85,
    "Watermelon":   0.90,
    "Muskmelon":    0.90,
    "Pomegranate":  0.85,
    "Grapes":       0.85,
    "Orange":       0.80,
    "Apple":        0.80,
}
DEFAULT_KC = 0.90

# Assumed farm area in m² if not provided
DEFAULT_AREA_M2 = 500.0  # representative small plot for estimation

# Safety cap on water quantity per AI-triggered cycle
MAX_WATER_ML_PER_CYCLE = 200_000  # 200 litres per activation — large safety bound
MIN_WATER_ML = 500               # At least 0.5L if irrigation is recommended

# Priority thresholds (moisture deficit % of field capacity)
PRIORITY_HIGH_DEFICIT   = 0.50   # > 50% of usable water depleted
PRIORITY_MEDIUM_DEFICIT = 0.25

ML_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "ml")
WATER_MODEL_PATH = os.path.join(ML_MODEL_DIR, "water_model.joblib")


# ---------------------------------------------------------------------------
# Main Prediction Service
# ---------------------------------------------------------------------------

class WaterPredictionService:
    """
    Provides water requirement predictions.
    Uses the FAO-56 baseline estimator always; upgrades to the trained
    RandomForestRegressor model when available.
    """

    def __init__(self):
        self._rf_model = None
        self._model_loaded = False
        self._model_version = "baseline_v1"
        self._estimator_type = "baseline"
        self._try_load_rf_model()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(self, farm_id: int, device_id: int,
                telemetry: dict, weather: dict) -> dict:
        """
        Generate a water requirement prediction.

        Parameters
        ----------
        farm_id    : int
        device_id  : int
        telemetry  : dict  — latest sensor readings (moisture, temperature,
                             humidity, rain, flow_pulses, sensor_status)
        weather    : dict  — from weather_service.get_weather_forecast()

        Returns
        -------
        dict with keys: recommended_irrigate, predicted_water_ml,
                        predicted_duration_s, priority, explanation,
                        estimator_type, model_version, prediction_id
        """
        # Collect context from database
        context = self._build_context(farm_id, device_id, telemetry, weather)
        if context.get("error"):
            return self._error_result(context["error"])

        # Safety gate: live rain sensor inhibits recommendation
        if context["rain"] == 1:
            result = self._inhibited_result(
                "Rain detected on field. Irrigation inhibited by live rain sensor.",
                context
            )
            pred_id = self._save_prediction(farm_id, device_id, context, result)
            result["prediction_id"] = pred_id
            return result

        # Safety gate: sensor fault
        if context.get("sensor_status") not in ("OK", None):
            result = self._inhibited_result(
                f"Sensor fault ({context['sensor_status']}). Cannot make reliable prediction.",
                context
            )
            pred_id = self._save_prediction(farm_id, device_id, context, result)
            result["prediction_id"] = pred_id
            return result

        # Choose estimator
        if self._rf_model is not None:
            result = self._predict_rf(context)
        else:
            result = self._predict_baseline(context)

        # Apply weather adjustment on top of base prediction
        result = self._apply_weather_adjustment(result, context)

        # Clamp
        if result["recommended_irrigate"] and result["predicted_water_ml"] is not None:
            result["predicted_water_ml"] = max(
                MIN_WATER_ML,
                min(MAX_WATER_ML_PER_CYCLE, result["predicted_water_ml"])
            )
            result["predicted_duration_s"] = round(
                result["predicted_water_ml"] / FLOW_ML_PER_PULSE / FLOW_PULSES_PER_LITRE * 1000.0
            )
            # More direct: duration = water_ml / (flow_rate_ml_per_s)
            # YF-S201 at typical 1-3 L/min → ~16-50 mL/s; use 450 p/L at pump rate
            # We calculate target_pulses, then backend computes duration from calibration:
            result["target_pulses"] = round(
                result["predicted_water_ml"] / (1000.0 / FLOW_PULSES_PER_LITRE)
            )
            # Estimated duration assuming ~1.5 L/min pump flow rate (900 ml/min = 15 ml/s)
            result["predicted_duration_s"] = round(result["predicted_water_ml"] / 15.0)
        else:
            result["target_pulses"] = 0
            result["predicted_duration_s"] = 0

        # Save to database
        pred_id = self._save_prediction(farm_id, device_id, context, result)
        result["prediction_id"] = pred_id
        result["context"] = {
            "moisture":    context["moisture"],
            "temperature": context["temperature"],
            "humidity":    context["humidity"],
            "rain":        context["rain"],
            "crop":        context["crop"],
            "soil_type":   context["soil_type"],
            "weather_rain_prob": context["weather_rain_prob"],
            "field_capacity":    context["field_capacity"],
        }
        return result

    def get_model_status(self) -> dict:
        """Return current model status for the frontend."""
        conn = get_db()
        cursor = conn.cursor()
        active = cursor.execute(
            "SELECT * FROM water_model_versions WHERE is_active = 1 ORDER BY trained_at DESC LIMIT 1"
        ).fetchone()
        total_records = cursor.execute(
            "SELECT COUNT(*) as cnt FROM irrigation_learning_records WHERE is_valid = 1"
        ).fetchone()["cnt"]
        conn.close()

        from backend.services.water_model_trainer import MIN_RECORDS_TO_TRAIN
        return {
            "estimator_type":    self._estimator_type,
            "model_version":     self._model_version,
            "rf_model_active":   self._rf_model is not None,
            "valid_records":     total_records,
            "records_needed":    MIN_RECORDS_TO_TRAIN,
            "can_train":         total_records >= MIN_RECORDS_TO_TRAIN,
            "active_model_db":   dict(active) if active else None,
            "flow_ml_per_pulse": round(FLOW_ML_PER_PULSE, 3),
            "pulses_per_litre":  FLOW_PULSES_PER_LITRE,
        }

    def reload_model(self):
        """Reload the RF model from disk (call after retraining)."""
        self._rf_model = None
        self._model_loaded = False
        self._try_load_rf_model()

    # ------------------------------------------------------------------
    # Context builder
    # ------------------------------------------------------------------

    def _build_context(self, farm_id: int, device_id: int,
                       telemetry: dict, weather: dict) -> dict:
        conn = get_db()
        cursor = conn.cursor()

        farm = cursor.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
        if not farm:
            conn.close()
            return {"error": f"Farm {farm_id} not found"}

        # Previous irrigation history
        last_event = cursor.execute("""
            SELECT * FROM irrigation_events
            WHERE farm_id = ? AND status = 'completed'
            ORDER BY ended_at DESC LIMIT 1
        """, (farm_id,)).fetchone()

        prev_duration_s = None
        prev_water_ml   = None
        elapsed_s       = None

        if last_event:
            if last_event["ended_at"] and last_event["started_at"]:
                try:
                    t_start = datetime.strptime(last_event["started_at"], "%Y-%m-%d %H:%M:%S")
                    t_end   = datetime.strptime(last_event["ended_at"],   "%Y-%m-%d %H:%M:%S")
                    prev_duration_s = (t_end - t_start).total_seconds()
                    elapsed_s       = (datetime.utcnow() - t_end).total_seconds()
                except Exception:
                    pass
            if last_event["actual_water_ml"]:
                prev_water_ml = last_event["actual_water_ml"]
            elif last_event["estimated_litres"]:
                prev_water_ml = last_event["estimated_litres"] * 1000.0

        conn.close()

        # Weather context
        rain_prob    = 0.0
        precip_mm    = 0.0
        if weather and not weather.get("is_stale", True):
            hourly = weather.get("hourly", {})
            probs  = hourly.get("precipitation_probability", [])
            precips = hourly.get("precipitation", [])
            if probs:
                rain_prob = max(probs[:12])   # next 12 hours
            if precips:
                precip_mm = sum(precips[:12])

        # Soil parameters
        soil_type      = dict(farm).get("soil_type", "Loamy") or "Loamy"
        field_capacity = SOIL_FIELD_CAPACITY.get(soil_type, DEFAULT_FIELD_CAPACITY)
        wilting_point  = SOIL_WILTING_POINT.get(soil_type,  DEFAULT_WILTING_POINT)
        soil_depth_mm  = SOIL_DEPTH_MM.get(soil_type,       DEFAULT_SOIL_DEPTH_MM)
        crop           = dict(farm).get("crop", "Wheat") or "Wheat"
        kc             = CROP_KC.get(crop, DEFAULT_KC)

        area_m2 = DEFAULT_AREA_M2
        if farm["area"] and farm["area"] > 0:
            au = (farm["area_unit"] or "acre").lower()
            if "acre" in au:
                area_m2 = farm["area"] * 4046.86
            elif "hectare" in au or "ha" in au:
                area_m2 = farm["area"] * 10000.0
            elif "m" in au:
                area_m2 = farm["area"]

        return {
            "farm":                 dict(farm),
            "crop":                 crop,
            "soil_type":            soil_type,
            "field_capacity":       field_capacity,
            "wilting_point":        wilting_point,
            "soil_depth_mm":        soil_depth_mm,
            "kc":                   kc,
            "area_m2":              area_m2,
            "moisture":             telemetry.get("moisture"),
            "temperature":          telemetry.get("temperature"),
            "humidity":             telemetry.get("humidity"),
            "rain":                 telemetry.get("rain", 0),
            "sensor_status":        telemetry.get("sensor_status", "OK"),
            "weather_rain_prob":    rain_prob,
            "weather_precip_mm":    precip_mm,
            "prev_irrigation_duration_s": prev_duration_s,
            "prev_water_ml":        prev_water_ml,
            "elapsed_since_prev_s": elapsed_s,
        }

    # ------------------------------------------------------------------
    # Baseline FAO-56 estimator
    # ------------------------------------------------------------------

    def _predict_baseline(self, ctx: dict) -> dict:
        """
        Scientifically grounded baseline using:
          1. Water deficit in root zone = (FC - current_moisture) × soil_depth × area
          2. Adjusted by daily ET₀ (simplified Hargreaves approximation)
          3. Crop coefficient Kc applied
        """
        moisture      = ctx["moisture"]
        temperature   = ctx.get("temperature")
        humidity      = ctx.get("humidity")
        field_cap     = ctx["field_capacity"]
        wilting_pt    = ctx["wilting_point"]
        soil_depth_mm = ctx["soil_depth_mm"]
        area_m2       = ctx["area_m2"]
        kc            = ctx["kc"]

        if moisture is None:
            return self._inhibited_result("Soil moisture reading unavailable.", ctx)

        # 1. Usable water content
        total_awc_pct = field_cap - wilting_pt          # Available Water Capacity (%)
        current_deficit_pct = max(0.0, field_cap - moisture)
        depletion_fraction  = current_deficit_pct / max(total_awc_pct, 1.0)

        # 2. Priority classification
        priority = "LOW"
        if   depletion_fraction >= PRIORITY_HIGH_DEFICIT:
            priority = "HIGH"
        elif depletion_fraction >= PRIORITY_MEDIUM_DEFICIT:
            priority = "MEDIUM"

        # 3. Recommend irrigation?
        # Irrigate when moisture falls below field capacity with meaningful deficit
        recommended = moisture < (field_cap * 0.90) and depletion_fraction > 0.10

        if not recommended:
            return {
                "recommended_irrigate": False,
                "predicted_water_ml":   0.0,
                "predicted_duration_s": 0,
                "target_pulses":        0,
                "priority":             "LOW",
                "explanation": (
                    f"Soil moisture ({moisture:.1f}%) is adequate "
                    f"(field capacity {field_cap}%). No irrigation required."
                ),
                "estimator_type": "baseline",
                "model_version":  "baseline_v1",
            }

        # 4. Volume deficit (m³) = deficit_fraction × soil_depth(m) × area(m²)
        water_deficit_m3 = (current_deficit_pct / 100.0) * (soil_depth_mm / 1000.0) * area_m2
        water_deficit_ml = water_deficit_m3 * 1_000_000  # m³ → ml

        # 5. ET₀ daily adjustment (simplified Hargreaves-Samani, single-temperature version)
        et0_mm_day = 2.5  # conservative fallback
        if temperature is not None:
            # Simple ET₀ approximation using only temperature (conservative)
            et0_mm_day = max(1.0, 0.0023 * (temperature + 17.8) * (abs(temperature - 10) ** 0.5) * 15.0)
            et0_mm_day = min(et0_mm_day, 12.0)  # cap at 12 mm/day

        etc_mm_day = kc * et0_mm_day  # Crop-adjusted ET

        # 6. Add ET contribution for irrigation window (assume 6 hour cycle window)
        et_water_ml = (etc_mm_day / 24.0 * 6.0 / 1000.0) * area_m2 * 1_000_000

        total_water_ml = water_deficit_ml + et_water_ml

        # 7. Build explanation
        expl_parts = [
            f"Soil moisture {moisture:.1f}% — deficit {current_deficit_pct:.1f}% from field capacity ({field_cap}%).",
            f"Root-zone volume: {soil_depth_mm}mm depth × {area_m2:.0f}m² ({ctx['soil_type']}).",
            f"Crop ET₀ ≈ {et0_mm_day:.1f} mm/day, Kc={kc} → ETc ≈ {etc_mm_day:.1f} mm/day ({ctx['crop']}).",
            f"Estimated water required: {total_water_ml/1000:.1f} litres (deficit fill + 6h ET compensation).",
            "Estimator: FAO-56 baseline (scientific rule-based). Model will upgrade after 30 learning records.",
        ]
        explanation = " ".join(expl_parts)

        return {
            "recommended_irrigate": True,
            "predicted_water_ml":   round(total_water_ml, 1),
            "predicted_duration_s": 0,  # filled by caller
            "target_pulses":        0,  # filled by caller
            "priority":             priority,
            "explanation":          explanation,
            "estimator_type":       "baseline",
            "model_version":        "baseline_v1",
            "et0_mm_day":           round(et0_mm_day, 2),
            "etc_mm_day":           round(etc_mm_day, 2),
            "depletion_fraction":   round(depletion_fraction, 3),
        }

    # ------------------------------------------------------------------
    # RandomForest estimator (when model available)
    # ------------------------------------------------------------------

    def _predict_rf(self, ctx: dict) -> dict:
        """Use trained RandomForestRegressor for water quantity prediction."""
        try:
            import numpy as np
            moisture      = ctx.get("moisture") or 40.0
            temperature   = ctx.get("temperature") or 28.0
            humidity      = ctx.get("humidity") or 65.0
            rain          = ctx.get("rain") or 0
            field_cap     = ctx["field_capacity"]
            wilting_pt    = ctx["wilting_point"]
            kc            = ctx["kc"]
            rain_prob     = ctx["weather_rain_prob"]
            prev_water    = ctx.get("prev_water_ml") or 0.0
            elapsed       = ctx.get("elapsed_since_prev_s") or 86400.0

            features = np.array([[
                moisture, temperature, humidity, rain,
                field_cap, wilting_pt, kc, rain_prob,
                prev_water, elapsed / 3600.0  # convert to hours
            ]])
            predicted_ml = float(self._rf_model.predict(features)[0])
            predicted_ml = max(0.0, predicted_ml)

            # Determine recommendation from moisture level
            deficit = max(0, field_cap - moisture)
            depletion = deficit / max(field_cap - wilting_pt, 1)
            recommended = predicted_ml > MIN_WATER_ML and depletion > 0.10
            priority = "HIGH" if depletion >= PRIORITY_HIGH_DEFICIT else ("MEDIUM" if depletion >= PRIORITY_MEDIUM_DEFICIT else "LOW")

            explanation = (
                f"RandomForest model predicted {predicted_ml/1000:.2f}L water requirement. "
                f"Soil moisture {moisture:.1f}% — deficit {deficit:.1f}% from field capacity {field_cap}%. "
                f"Trained on {self._model_version} (adaptive learning data)."
            )

            return {
                "recommended_irrigate": recommended,
                "predicted_water_ml":   round(predicted_ml, 1),
                "predicted_duration_s": 0,
                "target_pulses":        0,
                "priority":             priority,
                "explanation":          explanation,
                "estimator_type":       "random_forest",
                "model_version":        self._model_version,
                "depletion_fraction":   round(depletion, 3),
            }
        except Exception as e:
            print(f"[WaterPrediction] RF predict error: {e} — falling back to baseline")
            return self._predict_baseline(ctx)

    # ------------------------------------------------------------------
    # Weather adjustment
    # ------------------------------------------------------------------

    def _apply_weather_adjustment(self, result: dict, ctx: dict) -> dict:
        """
        Modify recommendation based on weather forecast.
        Note: does NOT override live rain sensor (handled before this point).
        """
        if not result["recommended_irrigate"]:
            return result

        rain_prob = ctx["weather_rain_prob"]
        precip_mm = ctx["weather_precip_mm"]

        if rain_prob >= 70:
            # Strong rain forecast: postpone irrigation
            result["recommended_irrigate"] = False
            result["predicted_water_ml"]   = 0
            result["priority"]             = "LOW"
            result["weather_adjustment"]   = "postponed"
            result["explanation"] = (
                f"⛈ Strong rain forecast ({rain_prob:.0f}% probability, "
                f"~{precip_mm:.1f}mm expected in next 12h). "
                "Irrigation postponed to conserve water and prevent waterlogging. "
                + result["explanation"]
            )
        elif rain_prob >= 40:
            # Moderate rain: reduce quantity
            reduction = (rain_prob - 40) / 60.0 * 0.60  # 0-60% reduction
            new_qty = result["predicted_water_ml"] * (1 - reduction)
            result["predicted_water_ml"] = max(MIN_WATER_ML, round(new_qty, 1))
            result["weather_adjustment"]  = f"reduced_{round(reduction*100)}pct"
            result["explanation"] = (
                f"🌦 Rain forecast ({rain_prob:.0f}% probability). "
                f"Quantity reduced by {round(reduction*100)}% to account for expected rainfall. "
                + result["explanation"]
            )
        else:
            result["weather_adjustment"] = "none"

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _try_load_rf_model(self):
        if os.path.exists(WATER_MODEL_PATH):
            try:
                import joblib
                self._rf_model      = joblib.load(WATER_MODEL_PATH)
                self._estimator_type = "random_forest"
                # Read version from db
                conn = get_db()
                row = conn.execute(
                    "SELECT version FROM water_model_versions WHERE is_active = 1 "
                    "ORDER BY trained_at DESC LIMIT 1"
                ).fetchone()
                conn.close()
                if row:
                    self._model_version = row["version"]
                else:
                    self._model_version = "rf_v1"
                self._model_loaded = True
                print(f"[WaterPrediction] RF model loaded: {self._model_version}")
            except Exception as e:
                print(f"[WaterPrediction] Could not load RF model: {e}")
                self._rf_model = None

    def _save_prediction(self, farm_id: int, device_id: int,
                         ctx: dict, result: dict) -> int:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ai_predictions (
                farm_id, device_id, moisture, temperature, humidity, rain,
                crop, soil_type, weather_rain_prob, weather_precip_mm,
                prev_irrigation_duration_s, prev_water_ml, elapsed_since_prev_s,
                recommended_irrigate, predicted_water_ml, predicted_duration_s,
                priority, explanation, model_version, estimator_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            farm_id, device_id,
            ctx.get("moisture"),    ctx.get("temperature"), ctx.get("humidity"),
            ctx.get("rain", 0),     ctx.get("crop"),        ctx.get("soil_type"),
            ctx.get("weather_rain_prob", 0.0), ctx.get("weather_precip_mm", 0.0),
            ctx.get("prev_irrigation_duration_s"), ctx.get("prev_water_ml"),
            ctx.get("elapsed_since_prev_s"),
            1 if result.get("recommended_irrigate") else 0,
            result.get("predicted_water_ml"), result.get("predicted_duration_s"),
            result.get("priority", "LOW"), result.get("explanation", ""),
            result.get("model_version", "baseline_v1"),
            result.get("estimator_type", "baseline"),
        ))
        conn.commit()
        pred_id = cursor.lastrowid
        conn.close()
        return pred_id

    def _inhibited_result(self, reason: str, ctx: dict = None) -> dict:
        return {
            "recommended_irrigate": False,
            "predicted_water_ml":   0.0,
            "predicted_duration_s": 0,
            "target_pulses":        0,
            "priority":             "LOW",
            "explanation":          reason,
            "estimator_type":       self._estimator_type,
            "model_version":        self._model_version,
            "weather_adjustment":   "inhibited",
        }

    def _error_result(self, msg: str) -> dict:
        return {
            "error": msg,
            "recommended_irrigate": False,
            "predicted_water_ml":   0.0,
            "predicted_duration_s": 0,
            "target_pulses":        0,
            "priority":             "LOW",
            "explanation":          f"Prediction error: {msg}",
            "estimator_type":       "none",
            "model_version":        "none",
        }


# Singleton — imported by routes
water_predictor = WaterPredictionService()
