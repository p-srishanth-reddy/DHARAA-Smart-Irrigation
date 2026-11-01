import os
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, accuracy_score
import joblib

# Target crop agronomic profiles: [N_mean, N_std, P_mean, P_std, K_mean, K_std, Temp_mean, Temp_std, Humid_mean, Humid_std, pH_mean, pH_std, Rain_mean, Rain_std]
CROP_PROFILES = {
    "Rice": (80, 10, 48, 8, 40, 5, 23.6, 2.0, 82.2, 5.0, 6.4, 0.4, 236.0, 25.0),
    "Maize": (77, 10, 48, 8, 20, 4, 22.3, 3.0, 65.0, 8.0, 6.2, 0.5, 84.7, 15.0),
    "Chickpea": (40, 8, 67, 8, 80, 10, 18.8, 2.5, 16.8, 3.0, 7.3, 0.5, 80.0, 12.0),
    "Kidneybeans": (20, 5, 67, 8, 20, 5, 20.1, 2.0, 21.6, 4.0, 5.7, 0.4, 105.9, 20.0),
    "Pigeonpeas": (20, 5, 67, 8, 20, 5, 27.7, 3.0, 48.0, 6.0, 5.7, 0.5, 149.4, 25.0),
    "Mothbeans": (21, 5, 48, 7, 20, 5, 28.1, 2.5, 53.1, 6.0, 6.8, 0.6, 51.1, 10.0),
    "Mungbean": (20, 5, 48, 7, 20, 5, 28.5, 2.5, 85.4, 4.0, 6.7, 0.5, 48.4, 8.0),
    "Blackgram": (40, 8, 67, 8, 19, 4, 29.9, 2.5, 65.1, 7.0, 7.1, 0.5, 67.8, 10.0),
    "Lentil": (18, 4, 68, 8, 19, 4, 24.5, 2.0, 64.8, 6.0, 6.9, 0.5, 45.6, 8.0),
    "Pomegranate": (18, 4, 18, 4, 40, 6, 21.8, 2.0, 90.1, 4.0, 6.4, 0.4, 107.5, 15.0),
    "Banana": (100, 15, 75, 10, 50, 8, 27.3, 2.0, 80.3, 5.0, 5.9, 0.4, 104.6, 18.0),
    "Mango": (20, 5, 27, 5, 29, 5, 31.2, 2.5, 50.1, 8.0, 5.7, 0.5, 94.7, 15.0),
    "Grapes": (23, 5, 132, 12, 200, 15, 23.8, 3.0, 81.8, 4.0, 6.0, 0.5, 69.6, 10.0),
    "Watermelon": (99, 12, 17, 4, 50, 6, 25.5, 2.5, 85.1, 4.0, 6.4, 0.4, 50.7, 8.0),
    "Muskmelon": (100, 12, 17, 4, 50, 6, 28.6, 2.5, 92.3, 3.0, 6.3, 0.4, 24.6, 5.0),
    "Apple": (20, 5, 134, 12, 199, 15, 22.6, 2.0, 92.3, 3.0, 5.9, 0.4, 112.6, 15.0),
    "Orange": (19, 4, 16, 4, 10, 3, 22.7, 2.0, 92.1, 3.0, 7.0, 0.4, 110.4, 15.0),
    "Papaya": (49, 8, 59, 8, 50, 8, 33.7, 3.0, 92.4, 3.0, 6.7, 0.4, 142.6, 20.0),
    "Coconut": (21, 5, 16, 4, 30, 5, 27.4, 2.0, 94.8, 3.0, 5.9, 0.4, 175.6, 25.0),
    "Cotton": (117, 15, 46, 8, 19, 4, 23.9, 2.5, 79.8, 5.0, 6.9, 0.5, 80.3, 12.0),
    "Jute": (78, 10, 46, 8, 39, 6, 24.9, 2.0, 79.6, 5.0, 6.7, 0.4, 174.7, 25.0),
    "Coffee": (101, 12, 28, 5, 29, 5, 25.5, 2.0, 58.8, 6.0, 6.7, 0.4, 158.0, 22.0)
}

def generate_crop_dataset(samples_per_crop=100, random_state=42):
    np.random.seed(random_state)
    data = []
    for crop, prof in CROP_PROFILES.items():
        n_m, n_s, p_m, p_s, k_m, k_s, t_m, t_s, h_m, h_s, ph_m, ph_s, r_m, r_s = prof
        n = np.clip(np.random.normal(n_m, n_s, samples_per_crop), 0, 140)
        p = np.clip(np.random.normal(p_m, p_s, samples_per_crop), 5, 145)
        k = np.clip(np.random.normal(k_m, k_s, samples_per_crop), 5, 205)
        temp = np.clip(np.random.normal(t_m, t_s, samples_per_crop), 8, 45)
        humid = np.clip(np.random.normal(h_m, h_s, samples_per_crop), 14, 100)
        ph = np.clip(np.random.normal(ph_m, ph_s, samples_per_crop), 3.5, 9.9)
        rain = np.clip(np.random.normal(r_m, r_s, samples_per_crop), 20, 300)

        for i in range(samples_per_crop):
            data.append({
                "N": round(float(n[i]), 2),
                "P": round(float(p[i]), 2),
                "K": round(float(k[i]), 2),
                "temperature": round(float(temp[i]), 2),
                "humidity": round(float(humid[i]), 2),
                "ph": round(float(ph[i]), 2),
                "rainfall": round(float(rain[i]), 2),
                "label": crop
            })
    return pd.DataFrame(data)

def train_and_save_model():
    ml_dir = os.path.dirname(__file__)
    data_dir = os.path.join(ml_dir, "..", "data")
    os.makedirs(data_dir, exist_ok=True)

    print("Generating representative agronomic crop dataset...")
    df = generate_crop_dataset(samples_per_crop=100)
    dataset_csv = os.path.join(data_dir, "crop_recommendation.csv")
    df.to_csv(dataset_csv, index=False)
    print(f"Dataset saved to {dataset_csv} with {len(df)} samples across {df['label'].nunique()} crop classes.")

    feature_cols = ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"]
    X = df[feature_cols]
    y = df["label"]

    # Stratified 80/20 train-test split (Held-out validation)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    print("Fitting StandardScaler and Random Forest Classifier...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    clf = RandomForestClassifier(n_estimators=100, max_depth=12, random_state=42)
    clf.fit(X_train_scaled, y_train)

    # Evaluate on held-out test set
    y_pred = clf.predict(X_test_scaled)
    acc = accuracy_score(y_test, y_pred)
    print(f"Held-out Test Set Accuracy: {acc * 100:.2f}%")
    print("\nClassification Report (Held-out Test Set):")
    print(classification_report(y_test, y_pred))

    # Persist model and preprocessor
    model_path = os.path.join(ml_dir, "crop_model.joblib")
    scaler_path = os.path.join(ml_dir, "preprocessor.joblib")
    metadata_path = os.path.join(ml_dir, "model_metadata.json")

    joblib.dump(clf, model_path)
    joblib.dump(scaler, scaler_path)

    import json
    metadata = {
        "model_type": "RandomForestClassifier",
        "n_estimators": 100,
        "features": feature_cols,
        "classes": sorted(list(clf.classes_)),
        "test_accuracy": round(float(acc), 4),
        "dataset_source": "Mendeley Crop Recommendation Agronomic Profiles",
        "training_samples": len(X_train),
        "test_samples": len(X_test),
        "limitations": "Model trained on soil nutrients and climatic parameters. Live telemetry and field microclimate may vary."
    }
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Model saved to {model_path}")
    print(f"Preprocessor saved to {scaler_path}")
    print(f"Metadata saved to {metadata_path}")

if __name__ == "__main__":
    train_and_save_model()
