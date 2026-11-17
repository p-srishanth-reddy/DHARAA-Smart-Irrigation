"""
DHARAA Water Model CLI Training Script
=======================================
Run from project root to train the water requirement prediction model:

    python -m backend.ml.train_water_model

Requires at least 30 valid irrigation learning records in the database.
"""

import sys
import os

# Allow running as a script from project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from backend.services.water_model_trainer import train_water_model, get_training_data, MIN_RECORDS_TO_TRAIN

def main():
    print("=" * 60)
    print("  DHARAA Water Requirement Model Training")
    print("=" * 60)

    _, _, record_count = get_training_data()
    print(f"  Valid irrigation learning records: {record_count}")
    print(f"  Minimum records required:         {MIN_RECORDS_TO_TRAIN}")

    if record_count < MIN_RECORDS_TO_TRAIN:
        print(f"\n  ⚠ Insufficient data. Need {MIN_RECORDS_TO_TRAIN - record_count} more records.")
        print("  The system will continue using the FAO-56 baseline estimator.")
        print("  As AI-triggered irrigation cycles complete, records accumulate automatically.")
        return

    print(f"\n  Starting training on {record_count} records...")
    result = train_water_model()

    if result["success"]:
        print(f"\n  ✓ Training complete!")
        print(f"    Model version:   {result['version']}")
        print(f"    Training samples:{result['training_samples']}")
        print(f"    Test samples:    {result['test_samples']}")
        print(f"    MAE:             {result['mae_ml']} ml")
        print(f"    R² score:        {result['r2_score']}")
        print(f"\n  Model saved to backend/ml/water_model.joblib")
        print("  The Flask app will automatically use this model on next prediction.")
    else:
        print(f"\n  ✗ Training failed: {result['message']}")

if __name__ == "__main__":
    main()
