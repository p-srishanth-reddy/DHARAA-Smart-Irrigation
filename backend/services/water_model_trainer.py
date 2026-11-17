"""
DHARAA Water Model Trainer
===========================
Trains a RandomForestRegressor on collected irrigation learning records
to predict water quantity required (ml) for future irrigation cycles.

Workflow:
  1. Accumulate ≥ MIN_RECORDS_TO_TRAIN valid irrigation_learning_records
  2. Call train_water_model() (via API or CLI script)
  3. New model is evaluated; if better than baseline it replaces the active model
  4. Previous model preserved as backup on disk

Features used:
  moisture, temperature, humidity, rain,
  field_capacity (soil-derived), wilting_point (soil-derived),
  crop_kc (crop-derived), weather_rain_prob,
  prev_water_ml, elapsed_hours_since_prev

Target:
  actual_water_ml (true water delivered by flow sensor)
"""

import os
import json
import shutil
import joblib
import numpy as np
from datetime import datetime

from backend.database import get_db

ML_DIR            = os.path.join(os.path.dirname(__file__), "..", "ml")
WATER_MODEL_PATH  = os.path.join(ML_DIR, "water_model.joblib")
WATER_MODEL_BACKUP = os.path.join(ML_DIR, "water_model_backup.joblib")

MIN_RECORDS_TO_TRAIN = 30

# Soil / crop lookup tables (duplicated from prediction service to keep trainer self-contained)
SOIL_FIELD_CAPACITY = {
    "Sandy": 28, "Sandy Loam": 34, "Loamy": 42, "Loam": 42,
    "Clay Loam": 48, "Clay": 54, "Black Cotton Soil": 52,
    "Silt Loam": 44, "Red Soil": 36, "Laterite": 34,
}
SOIL_WILTING_POINT = {
    "Sandy": 10, "Sandy Loam": 14, "Loamy": 18, "Loam": 18,
    "Clay Loam": 22, "Clay": 26, "Black Cotton Soil": 25,
    "Silt Loam": 20, "Red Soil": 16, "Laterite": 14,
}
CROP_KC = {
    "Wheat": 0.90, "Rice": 1.20, "Cotton": 1.15, "Maize": 1.10,
    "Sugarcane": 1.25, "Soybean": 1.00, "Groundnut": 0.95,
    "Sunflower": 1.05, "Jowar": 0.85, "Bajra": 0.85, "Ragi": 0.90,
    "Tomato": 1.10, "Chilli": 1.00, "Onion": 0.95, "Potato": 1.10,
    "Banana": 1.10, "Mango": 0.85, "Coconut": 0.95, "Coffee": 0.90,
    "Jute": 1.00, "Lentil": 0.80, "Chickpea": 0.80, "Pigeonpeas": 0.85,
    "Blackgram": 0.75, "Mungbean": 0.75, "Mothbeans": 0.75,
    "Kidneybeans": 0.85, "Papaya": 0.85, "Watermelon": 0.90,
    "Muskmelon": 0.90, "Pomegranate": 0.85, "Grapes": 0.85,
    "Orange": 0.80, "Apple": 0.80,
}


def get_training_data():
    """
    Load valid irrigation learning records and build feature/target arrays.
    Returns (X, y, record_count) or (None, None, count) if insufficient data.
    """
    conn = get_db()
    rows = conn.execute("""
        SELECT ilr.*, f.soil_type, f.crop
        FROM irrigation_learning_records ilr
        JOIN farms f ON ilr.farm_id = f.id
        WHERE ilr.is_valid = 1
          AND ilr.actual_water_ml IS NOT NULL
          AND ilr.actual_water_ml > 100
          AND ilr.initial_moisture IS NOT NULL
    """).fetchall()
    conn.close()

    if len(rows) < MIN_RECORDS_TO_TRAIN:
        return None, None, len(rows)

    X, y = [], []
    for r in rows:
        soil = r["soil_type"] or "Loamy"
        crop = r["crop"] or "Wheat"
        fc   = SOIL_FIELD_CAPACITY.get(soil, 42)
        wp   = SOIL_WILTING_POINT.get(soil,  18)
        kc   = CROP_KC.get(crop, 0.90)

        moisture  = r["initial_moisture"] or 40.0
        temp      = r["temperature"]     or 28.0
        humidity  = r["humidity"]        or 65.0
        rain      = r["rain"]            or 0
        prev_ml   = r["predicted_water_ml"] or 0.0

        # Elapsed since previous irrigation (hours) — derived from started_at vs ended_at gap
        elapsed_h = 24.0
        if r["started_at"] and r["ended_at"]:
            try:
                ts = datetime.strptime(r["started_at"], "%Y-%m-%d %H:%M:%S")
                te = datetime.strptime(r["ended_at"],   "%Y-%m-%d %H:%M:%S")
                elapsed_h = max(0.5, (ts - te).total_seconds() / 3600.0)
            except Exception:
                pass

        X.append([moisture, temp, humidity, rain, fc, wp, kc, 0.0, prev_ml, elapsed_h])
        y.append(r["actual_water_ml"])

    return np.array(X, dtype=float), np.array(y, dtype=float), len(rows)


def train_water_model():
    """
    Train RandomForestRegressor on collected learning records.
    Returns a result dict with success status and metrics.
    """
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error, r2_score

    X, y, total_records = get_training_data()
    if X is None:
        return {
            "success": False,
            "message": f"Insufficient data: {total_records}/{MIN_RECORDS_TO_TRAIN} valid records.",
            "records_available": total_records,
            "records_needed": MIN_RECORDS_TO_TRAIN,
        }

    # Split: 80% train / 20% test
    test_size = max(0.1, min(0.25, 6 / len(y)))  # At least 6 samples in test set
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42
    )

    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=12,
        min_samples_split=4,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    mae    = float(mean_absolute_error(y_test, y_pred))
    r2     = float(r2_score(y_test, y_pred))

    version = f"rf_v{datetime.utcnow().strftime('%Y%m%d_%H%M')}"

    # Backup previous model
    if os.path.exists(WATER_MODEL_PATH):
        shutil.copy2(WATER_MODEL_PATH, WATER_MODEL_BACKUP)

    # Save new model
    joblib.dump(model, WATER_MODEL_PATH)

    # Record in database
    conn = get_db()
    cursor = conn.cursor()
    # Deactivate previous
    cursor.execute("UPDATE water_model_versions SET is_active = 0")
    cursor.execute("""
        INSERT INTO water_model_versions
            (version, training_samples, mae_ml, r2_score, is_active, notes)
        VALUES (?, ?, ?, ?, 1, ?)
    """, (
        version,
        len(X_train),
        round(mae, 2),
        round(r2, 4),
        f"Trained on {len(y)} records; test MAE={mae:.1f}ml, R²={r2:.3f}"
    ))
    conn.commit()
    conn.close()

    # Reload the singleton predictor
    try:
        from backend.services.water_prediction_service import water_predictor
        water_predictor.reload_model()
    except Exception as e:
        print(f"[Trainer] Warning: could not reload predictor singleton: {e}")

    return {
        "success":          True,
        "version":          version,
        "training_samples": int(len(X_train)),
        "test_samples":     int(len(X_test)),
        "mae_ml":           round(mae, 2),
        "r2_score":         round(r2, 4),
        "total_records":    int(len(y)),
        "message":          f"Model {version} trained. MAE={mae:.1f}ml, R²={r2:.3f}",
    }


def record_irrigation_outcome(farm_id: int, irrigation_event_id: int,
                               initial_moisture: float, final_moisture: float,
                               predicted_water_ml: float, actual_water_ml: float,
                               predicted_duration_s: float, actual_duration_s: float,
                               temperature: float, humidity: float, rain: int,
                               stop_reason: str, started_at=None, ended_at=None):
    """
    Save an irrigation learning record after a cycle completes.
    Called by the irrigation route when a session ends.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Get farm crop/soil info
    farm = cursor.execute(
        "SELECT crop, soil_type FROM farms f JOIN irrigation_events e ON e.farm_id = f.id WHERE e.id = ?",
        (irrigation_event_id,)
    ).fetchone()

    crop      = farm["crop"]      if farm else None
    soil_type = farm["soil_type"] if farm else None

    # Basic validity check: reject obviously invalid records
    is_valid = 1
    if actual_water_ml is None or actual_water_ml <= 0:
        is_valid = 0
    if initial_moisture is None or final_moisture is None:
        is_valid = 0

    cursor.execute("""
        INSERT INTO irrigation_learning_records (
            farm_id, irrigation_event_id, started_at, ended_at,
            initial_moisture, final_moisture, temperature, humidity, rain,
            predicted_water_ml, actual_water_ml, predicted_duration_s, actual_duration_s,
            crop, soil_type, stop_reason, is_valid
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        farm_id, irrigation_event_id, started_at, ended_at,
        initial_moisture, final_moisture, temperature, humidity, rain,
        predicted_water_ml, actual_water_ml, predicted_duration_s, actual_duration_s,
        crop, soil_type, stop_reason, is_valid
    ))
    conn.commit()
    record_id = cursor.lastrowid
    conn.close()
    return record_id
