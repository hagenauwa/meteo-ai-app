"""
ml_model.py — modelli ML per correzione temperatura e probabilità pioggia.
"""
from __future__ import annotations

import pickle
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import City, MlModelStore, MlPrediction, SessionLocal

# Pipeline globali caricate in memoria all'avvio
_pipeline: Optional[Pipeline] = None
_rain_pipeline: Optional[Pipeline] = None
_label_encoder: Optional[LabelEncoder] = None
_known_regions: list[str] = []
_latest_summary: dict = {
    "model_ready": False,
    "rain_model_ready": False,
    "model_mae": None,
    "baseline_mae": None,
    "rain_accuracy": None,
    "rain_baseline_accuracy": None,
    "model_samples": None,
    "model_trained_at": None,
}


def _build_features(
    *,
    forecast_temp: float,
    humidity: float,
    hour: int,
    month: int,
    lat: float,
    region: str,
    cloud_cover: float,
    lead_hours: int,
) -> np.ndarray:
    """Costruisce il vettore features per una singola previsione."""
    region_code = 0
    if _label_encoder and region in _known_regions:
        region_code = int(_label_encoder.transform([region])[0])

    return np.array([[
        forecast_temp,
        humidity or 50.0,
        hour,
        month,
        lat,
        cloud_cover or 50.0,
        max(0, lead_hours or 0),
        region_code,
    ]])


def _prepare_training_rows(db: Session) -> list[dict]:
    rows = (
        db.query(
            MlPrediction.predicted_at,
            MlPrediction.target_time,
            MlPrediction.predicted_temp,
            MlPrediction.forecast_temp,
            MlPrediction.humidity,
            MlPrediction.forecast_cloud_cover,
            MlPrediction.lead_hours,
            MlPrediction.error,
            MlPrediction.actual_precipitation,
            City.lat,
            City.region,
        )
        .join(City, MlPrediction.city_id == City.id)
        .filter(MlPrediction.verified.is_(True))
        .filter(MlPrediction.actual_temp.isnot(None))
        .filter(MlPrediction.error.isnot(None))
        .all()
    )

    prepared: list[dict] = []
    for row in rows:
        target_time = row.target_time or row.predicted_at
        if not target_time:
            continue
        forecast_temp = row.forecast_temp if row.forecast_temp is not None else row.predicted_temp
        prepared.append({
            "target_time": target_time,
            "forecast_temp": forecast_temp,
            "humidity": row.humidity or 50.0,
            "hour": target_time.hour,
            "month": target_time.month,
            "lat": row.lat or 43.0,
            "cloud_cover": row.forecast_cloud_cover or 50.0,
            "lead_hours": row.lead_hours or 0,
            "region": row.region or "Sconosciuta",
            "error": row.error,
            "actual_precipitation": row.actual_precipitation,
        })
    prepared.sort(key=lambda item: item["target_time"])
    return prepared


def _encode_regions(rows: list[dict]) -> LabelEncoder:
    global _known_regions, _label_encoder

    regions = sorted({row["region"] for row in rows} or {"Sconosciuta"})
    encoder = LabelEncoder()
    encoder.fit(regions)
    _known_regions = regions
    _label_encoder = encoder
    return encoder


def _build_temperature_matrices(rows: list[dict], encoder: LabelEncoder) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for row in rows:
        region_code = int(encoder.transform([row["region"]])[0])
        X.append([
            row["forecast_temp"],
            row["humidity"],
            row["hour"],
            row["month"],
            row["lat"],
            row["cloud_cover"],
            row["lead_hours"],
            region_code,
        ])
        y.append(row["error"])
    return np.array(X), np.array(y)


def _build_rain_matrices(rows: list[dict], encoder: LabelEncoder) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for row in rows:
        region_code = int(encoder.transform([row["region"]])[0])
        X.append([
            row["forecast_temp"],
            row["humidity"],
            row["hour"],
            row["month"],
            row["lat"],
            row["cloud_cover"],
            row["lead_hours"],
            region_code,
        ])
        y.append(1 if (row["actual_precipitation"] or 0.0) > 0.1 else 0)
    return np.array(X), np.array(y)


def _train_temperature_pipeline(rows: list[dict]) -> dict:
    encoder = _encode_regions(rows)
    X, y = _build_temperature_matrices(rows, encoder)

    if len(X) < 10:
        return {"success": False, "message": "Campioni insufficienti per split temporale"}

    split_idx = max(int(len(X) * 0.8), 1)
    if split_idx >= len(X):
        split_idx = len(X) - 1

    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    baseline_mae = float(np.mean(np.abs(y_val)))

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=1.0)),
    ])
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_val)
    mae = float(mean_absolute_error(y_val, y_pred))

    if mae >= baseline_mae:
        return {
            "success": False,
            "message": f"Il modello non supera il baseline (MAE {mae:.3f} vs {baseline_mae:.3f})",
            "baseline_mae": baseline_mae,
            "mae": mae,
            "pipeline": None,
            "encoder": encoder,
        }

    return {
        "success": True,
        "pipeline": pipeline,
        "encoder": encoder,
        "mae": mae,
        "baseline_mae": baseline_mae,
        "n_samples": len(rows),
    }


def _train_rain_pipeline(rows: list[dict], encoder: LabelEncoder) -> dict:
    rain_rows = [row for row in rows if row["actual_precipitation"] is not None]
    if len(rain_rows) < 20:
        return {"success": False, "message": "Dati insufficienti per il modello pioggia"}

    X, y = _build_rain_matrices(rain_rows, encoder)
    if len(set(y.tolist())) < 2:
        return {"success": False, "message": "Solo una classe disponibile per la pioggia"}

    split_idx = max(int(len(X) * 0.8), 1)
    if split_idx >= len(X):
        split_idx = len(X) - 1

    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    baseline_acc = max(float(np.mean(y_val)), 1.0 - float(np.mean(y_val)))

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=1000)),
    ])
    pipeline.fit(X_train, y_train)

    acc = float(accuracy_score(y_val, pipeline.predict(X_val)))
    if acc < baseline_acc:
        return {
            "success": False,
            "message": f"Il modello pioggia non supera il baseline ({acc:.3f} vs {baseline_acc:.3f})",
            "accuracy": acc,
            "baseline_accuracy": baseline_acc,
        }

    return {
        "success": True,
        "pipeline": pipeline,
        "accuracy": acc,
        "baseline_accuracy": baseline_acc,
        "n_samples": len(rain_rows),
        "rain_share": round(float(np.mean(y)), 3),
    }


def train(min_samples: int = 100) -> dict:
    """
    Addestra i modelli sulle previsioni verificate con target_time futuro.
    Promuove il modello solo se batte un baseline semplice.
    """
    global _pipeline, _rain_pipeline, _latest_summary

    db: Session = SessionLocal()
    try:
        rows = _prepare_training_rows(db)
        if len(rows) < min_samples:
            return {
                "success": False,
                "message": f"Dati insufficienti: {len(rows)} campioni (minimo {min_samples})",
            }

        temp_result = _train_temperature_pipeline(rows)
        if not temp_result["success"]:
            return {
                "success": False,
                "message": temp_result["message"],
                "baseline_mae": temp_result.get("baseline_mae"),
                "mae": temp_result.get("mae"),
            }

        pipeline = temp_result["pipeline"]
        encoder = temp_result["encoder"]
        rain_result = _train_rain_pipeline(rows, encoder)
        rain_pipeline = rain_result["pipeline"] if rain_result.get("success") else None

        model_data = pickle.dumps({
            "pipeline": pipeline,
            "rain_pipeline": rain_pipeline,
            "le": encoder,
            "regions": _known_regions,
            "baseline_mae": temp_result["baseline_mae"],
            "rain_accuracy": rain_result.get("accuracy"),
            "rain_baseline_accuracy": rain_result.get("baseline_accuracy"),
        })

        record = MlModelStore(
            trained_at=datetime.now(timezone.utc),
            model_bytes=model_data,
            mae=temp_result["mae"],
            n_samples=temp_result["n_samples"],
        )
        db.add(record)
        db.commit()

        _pipeline = pipeline
        _rain_pipeline = rain_pipeline
        _latest_summary = {
            "model_ready": True,
            "rain_model_ready": rain_pipeline is not None,
            "model_mae": temp_result["mae"],
            "baseline_mae": temp_result["baseline_mae"],
            "rain_accuracy": rain_result.get("accuracy"),
            "rain_baseline_accuracy": rain_result.get("baseline_accuracy"),
            "model_samples": temp_result["n_samples"],
            "model_trained_at": record.trained_at.isoformat(),
        }

        return {
            "success": True,
            "mae": temp_result["mae"],
            "baseline_mae": temp_result["baseline_mae"],
            "n_samples": temp_result["n_samples"],
            "trained_at": record.trained_at.isoformat(),
            "rain_accuracy": rain_result.get("accuracy"),
            "rain_baseline_accuracy": rain_result.get("baseline_accuracy"),
            "rain_model_ready": rain_pipeline is not None,
            "rain_message": None if rain_pipeline is not None else rain_result.get("message"),
        }
    except Exception as e:
        print(f"[ERROR] Errore training ML: {e}")
        return {"success": False, "message": str(e)}
    finally:
        db.close()


def load_latest_model() -> bool:
    """Carica in memoria l'ultimo modello promosso."""
    global _pipeline, _rain_pipeline, _label_encoder, _known_regions, _latest_summary

    db: Session = SessionLocal()
    try:
        record = db.query(MlModelStore).order_by(MlModelStore.trained_at.desc()).first()
        if not record or not record.model_bytes:
            print("[INFO]  Nessun modello ML salvato nel DB")
            _latest_summary = {
                **_latest_summary,
                "model_ready": False,
                "rain_model_ready": False,
                "model_trained_at": None,
                "model_mae": None,
                "model_samples": None,
            }
            return False

        data = pickle.loads(record.model_bytes)
        _pipeline = data["pipeline"]
        _rain_pipeline = data.get("rain_pipeline")
        _label_encoder = data["le"]
        _known_regions = data.get("regions", [])
        _latest_summary = {
            "model_ready": _pipeline is not None,
            "rain_model_ready": _rain_pipeline is not None,
            "model_mae": record.mae,
            "baseline_mae": data.get("baseline_mae"),
            "rain_accuracy": data.get("rain_accuracy"),
            "rain_baseline_accuracy": data.get("rain_baseline_accuracy"),
            "model_samples": record.n_samples,
            "model_trained_at": record.trained_at.isoformat(),
        }
        print(f"[OK] Modello ML caricato (addestrato: {record.trained_at}, MAE: {record.mae})")
        return True
    except Exception as e:
        print(f"[WARN]  Errore caricamento modello: {e}")
        return False
    finally:
        db.close()


def predict_correction(
    *,
    temp: float,
    humidity: float,
    hour: int,
    month: int,
    lat: float,
    region: str,
    cloud_cover: float = 50.0,
    lead_hours: int = 0,
) -> dict:
    """
    Predice la correzione da applicare alla temperatura prevista.
    """
    if _pipeline is None:
        return {"correction": 0.0, "corrected_temp": temp, "model_ready": False}

    try:
        features = _build_features(
            forecast_temp=temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
        )
        correction = float(_pipeline.predict(features)[0])
        correction = max(-5.0, min(5.0, correction))

        if abs(correction) < 0.3:
            confidence = "bassa"
        elif abs(correction) < 1.0:
            confidence = "media"
        else:
            confidence = "alta"

        return {
            "correction": round(correction, 2),
            "corrected_temp": round(temp + correction, 1),
            "model_ready": True,
            "confidence": confidence,
        }
    except Exception as e:
        return {"correction": 0.0, "corrected_temp": temp, "model_ready": False, "error": str(e)}


def predict_rain_probability(
    *,
    forecast_temp: float,
    humidity: float,
    hour: int,
    month: int,
    lat: float,
    region: str,
    cloud_cover: float = 50.0,
    lead_hours: int = 0,
) -> dict:
    """
    Predice la probabilità di pioggia per una previsione futura.
    """
    if _rain_pipeline is None:
        return {
            "model_ready": False,
            "message": "Modello pioggia non ancora disponibile",
        }

    try:
        features = _build_features(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
        )
        proba = _rain_pipeline.predict_proba(features)[0]
        rain_prob = float(proba[1])

        if rain_prob < 0.35:
            confidence = "bassa"
        elif rain_prob < 0.65:
            confidence = "media"
        else:
            confidence = "alta"

        return {
            "rain_probability": round(rain_prob, 3),
            "will_rain": rain_prob >= 0.5,
            "model_ready": True,
            "confidence": confidence,
        }
    except Exception as e:
        return {"model_ready": False, "error": str(e)}


def get_public_summary() -> dict:
    return dict(_latest_summary)


def get_stats() -> dict:
    """Statistiche aggregate sul modello e sul dataset."""
    db: Session = SessionLocal()
    try:
        total = db.query(func.count(MlPrediction.id)).scalar() or 0
        verified = db.query(func.count(MlPrediction.id)).filter(MlPrediction.verified.is_(True)).scalar() or 0
        avg_error = db.query(func.avg(func.abs(MlPrediction.error))).filter(
            MlPrediction.verified.is_(True),
            MlPrediction.error.isnot(None),
        ).scalar()

        lead_error_rows = (
            db.query(MlPrediction.lead_hours, func.avg(func.abs(MlPrediction.error)))
            .filter(MlPrediction.verified.is_(True), MlPrediction.error.isnot(None))
            .group_by(MlPrediction.lead_hours)
            .order_by(MlPrediction.lead_hours)
            .all()
        )

        return {
            "total_predictions": int(total),
            "verified_predictions": int(verified),
            "avg_error_celsius": round(float(avg_error), 3) if avg_error is not None else None,
            "lead_time_error": [
                {"lead_hours": lead_hours or 0, "avg_abs_error": round(float(value), 3)}
                for lead_hours, value in lead_error_rows
            ],
            **get_public_summary(),
        }
    finally:
        db.close()
