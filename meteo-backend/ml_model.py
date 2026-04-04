"""
ml_model.py — modelli ML per correzione temperatura, probabilità pioggia e condizione del cielo.
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

CONDITION_LABELS = ("sereno", "parzialmente nuvoloso", "nuvoloso", "pioggia")
CONDITION_TO_CODE = {label: index for index, label in enumerate(CONDITION_LABELS)}
RAIN_WEATHER_CODES = {
    51, 53, 55, 56, 57,
    61, 63, 65, 66, 67,
    80, 81, 82,
    95, 96, 99,
}

# Pipeline globali caricate in memoria all'avvio
_pipeline: Optional[Pipeline] = None
_rain_pipeline: Optional[Pipeline] = None
_condition_pipeline: Optional[Pipeline] = None
_label_encoder: Optional[LabelEncoder] = None
_known_regions: list[str] = []
_latest_summary: dict = {
    "model_ready": False,
    "rain_model_ready": False,
    "condition_model_ready": False,
    "model_mae": None,
    "baseline_mae": None,
    "rain_accuracy": None,
    "rain_baseline_accuracy": None,
    "condition_accuracy": None,
    "condition_baseline_accuracy": None,
    "model_samples": None,
    "model_trained_at": None,
}


def _safe_float(value: float | int | None, fallback: float = 0.0) -> float:
    return float(value if value is not None else fallback)


def _normalize_wind_direction(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value) % 360.0


def _region_code(region: str) -> int:
    if _label_encoder and region in _known_regions:
        return int(_label_encoder.transform([region])[0])
    return 0


def _condition_from_inputs(
    *,
    weather_code: int | None,
    cloud_cover: float | None,
    precipitation: float | None,
) -> str:
    if (precipitation or 0.0) > 0.15 or weather_code in RAIN_WEATHER_CODES:
        return "pioggia"

    if cloud_cover is not None:
        if cloud_cover <= 25:
            return "sereno"
        if cloud_cover <= 60:
            return "parzialmente nuvoloso"
        return "nuvoloso"

    if weather_code in {0, 1}:
        return "sereno"
    if weather_code == 2:
        return "parzialmente nuvoloso"
    return "nuvoloso"


def _condition_display(label: str) -> str:
    mapping = {
        "sereno": "Cielo sereno",
        "parzialmente nuvoloso": "Parzialmente nuvoloso",
        "nuvoloso": "Nuvoloso",
        "pioggia": "Pioggia probabile",
    }
    return mapping.get(label, "Condizioni variabili")


def _confidence_from_score(score: float) -> str:
    if score < 0.45:
        return "bassa"
    if score < 0.7:
        return "media"
    return "alta"


def _daily_badge(condition_label: str, rain_probability: float, wind_speed: float) -> str:
    if rain_probability >= 0.55:
        return "Possibili piogge"
    if wind_speed >= 30:
        return "Vento in rinforzo"
    if condition_label == "nuvoloso":
        return "Cielo coperto"
    if condition_label == "parzialmente nuvoloso":
        return "Cielo variabile"
    return "Scenario stabile"


def _daily_summary(condition_label: str, rain_probability: float, wind_speed: float, confidence: str) -> str:
    condition_text = _condition_display(condition_label)
    rain_pct = round(rain_probability * 100)

    if rain_probability >= 0.55:
        return f"{condition_text}. Possibilita di pioggia intorno al {rain_pct}% con confidenza {confidence}."
    if wind_speed >= 30:
        return f"{condition_text}. Giornata ventilata, con raffiche fino a {round(wind_speed)} km/h."
    if condition_label == "parzialmente nuvoloso":
        return f"{condition_text}. Schiarite alternate a passaggi nuvolosi per gran parte della giornata."
    if condition_label == "nuvoloso":
        return f"{condition_text}. Previsione piu coperta del normale, ma senza segnali di instabilita marcata."
    return f"{condition_text}. Scenario asciutto e piuttosto regolare durante la giornata."


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
    """Feature vector legacy per temperatura/pioggia, mantenuto compatibile coi modelli esistenti."""
    return np.array([[
        forecast_temp,
        humidity or 50.0,
        hour,
        month,
        lat,
        cloud_cover or 50.0,
        max(0, lead_hours or 0),
        _region_code(region),
    ]])


def _build_condition_features(
    *,
    forecast_temp: float,
    humidity: float,
    hour: int,
    month: int,
    lat: float,
    region: str,
    cloud_cover: float,
    lead_hours: int,
    forecast_precipitation: float,
    forecast_wind_speed: float,
    forecast_wind_direction: float,
    forecast_weather_code: int | None,
) -> np.ndarray:
    provider_condition = _condition_from_inputs(
        weather_code=forecast_weather_code,
        cloud_cover=cloud_cover,
        precipitation=forecast_precipitation,
    )

    return np.array([[
        forecast_temp,
        humidity or 50.0,
        hour,
        month,
        lat,
        cloud_cover or 50.0,
        max(0, lead_hours or 0),
        forecast_precipitation or 0.0,
        forecast_wind_speed or 0.0,
        _normalize_wind_direction(forecast_wind_direction),
        _region_code(region),
        CONDITION_TO_CODE[provider_condition],
        forecast_weather_code or 0,
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
            MlPrediction.forecast_precipitation,
            MlPrediction.forecast_weather_code,
            MlPrediction.forecast_wind_speed,
            MlPrediction.forecast_wind_direction,
            MlPrediction.actual_precipitation,
            MlPrediction.actual_weather_code,
            MlPrediction.actual_cloud_cover,
            MlPrediction.actual_wind_speed,
            MlPrediction.actual_wind_direction,
            MlPrediction.lead_hours,
            MlPrediction.error,
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
            "forecast_precipitation": row.forecast_precipitation or 0.0,
            "forecast_weather_code": row.forecast_weather_code,
            "forecast_wind_speed": row.forecast_wind_speed or 0.0,
            "forecast_wind_direction": _normalize_wind_direction(row.forecast_wind_direction),
            "actual_precipitation": row.actual_precipitation,
            "actual_weather_code": row.actual_weather_code,
            "actual_cloud_cover": row.actual_cloud_cover,
            "actual_wind_speed": row.actual_wind_speed,
            "actual_wind_direction": row.actual_wind_direction,
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


def _build_condition_matrices(rows: list[dict], encoder: LabelEncoder) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for row in rows:
        if row["actual_weather_code"] is None and row["actual_cloud_cover"] is None and row["actual_precipitation"] is None:
            continue

        region_code = int(encoder.transform([row["region"]])[0])
        provider_condition = _condition_from_inputs(
            weather_code=row["forecast_weather_code"],
            cloud_cover=row["cloud_cover"],
            precipitation=row["forecast_precipitation"],
        )
        actual_condition = _condition_from_inputs(
            weather_code=row["actual_weather_code"],
            cloud_cover=row["actual_cloud_cover"],
            precipitation=row["actual_precipitation"],
        )
        X.append([
            row["forecast_temp"],
            row["humidity"],
            row["hour"],
            row["month"],
            row["lat"],
            row["cloud_cover"],
            row["lead_hours"],
            row["forecast_precipitation"],
            row["forecast_wind_speed"],
            row["forecast_wind_direction"],
            region_code,
            CONDITION_TO_CODE[provider_condition],
            row["forecast_weather_code"] or 0,
        ])
        y.append(CONDITION_TO_CODE[actual_condition])
    return np.array(X), np.array(y)


def _split_train_validation(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    if len(X) < 10:
        return None

    split_idx = max(int(len(X) * 0.8), 1)
    if split_idx >= len(X):
        split_idx = len(X) - 1

    return X[:split_idx], X[split_idx:], y[:split_idx], y[split_idx:]


def _train_temperature_pipeline(rows: list[dict]) -> dict:
    encoder = _encode_regions(rows)
    X, y = _build_temperature_matrices(rows, encoder)
    split = _split_train_validation(X, y)
    if split is None:
        return {"success": False, "message": "Campioni insufficienti per split temporale"}

    X_train, X_val, y_train, y_val = split
    baseline_mae = float(np.mean(np.abs(y_val)))

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=1.0)),
    ])
    pipeline.fit(X_train, y_train)

    mae = float(mean_absolute_error(y_val, pipeline.predict(X_val)))
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
    split = _split_train_validation(X, y)
    if split is None:
        return {"success": False, "message": "Campioni insufficienti per il modello pioggia"}

    X_train, X_val, y_train, y_val = split
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


def _train_condition_pipeline(rows: list[dict], encoder: LabelEncoder) -> dict:
    X, y = _build_condition_matrices(rows, encoder)
    if len(X) < 40:
        return {"success": False, "message": "Dati insufficienti per il modello condizioni"}
    if len(set(y.tolist())) < 2:
        return {"success": False, "message": "Solo una classe disponibile per il modello condizioni"}

    split = _split_train_validation(X, y)
    if split is None:
        return {"success": False, "message": "Campioni insufficienti per il modello condizioni"}

    X_train, X_val, y_train, y_val = split
    baseline_acc = float(np.max(np.bincount(y_val)) / len(y_val))

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=2000)),
    ])
    pipeline.fit(X_train, y_train)

    acc = float(accuracy_score(y_val, pipeline.predict(X_val)))
    if acc < baseline_acc:
        return {
            "success": False,
            "message": f"Il modello condizioni non supera il baseline ({acc:.3f} vs {baseline_acc:.3f})",
            "accuracy": acc,
            "baseline_accuracy": baseline_acc,
        }

    return {
        "success": True,
        "pipeline": pipeline,
        "accuracy": acc,
        "baseline_accuracy": baseline_acc,
        "n_samples": len(X),
    }


def train(min_samples: int = 100) -> dict:
    """
    Addestra i modelli sulle previsioni verificate con target_time futuro.
    Promuove ogni modello solo se batte un baseline semplice.
    """
    global _pipeline, _rain_pipeline, _condition_pipeline, _latest_summary

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
        condition_result = _train_condition_pipeline(rows, encoder)

        rain_pipeline = rain_result["pipeline"] if rain_result.get("success") else None
        condition_pipeline = condition_result["pipeline"] if condition_result.get("success") else None

        model_data = pickle.dumps({
            "pipeline": pipeline,
            "rain_pipeline": rain_pipeline,
            "condition_pipeline": condition_pipeline,
            "le": encoder,
            "regions": _known_regions,
            "baseline_mae": temp_result["baseline_mae"],
            "rain_accuracy": rain_result.get("accuracy"),
            "rain_baseline_accuracy": rain_result.get("baseline_accuracy"),
            "condition_accuracy": condition_result.get("accuracy"),
            "condition_baseline_accuracy": condition_result.get("baseline_accuracy"),
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
        _condition_pipeline = condition_pipeline
        _latest_summary = {
            "model_ready": True,
            "rain_model_ready": rain_pipeline is not None,
            "condition_model_ready": condition_pipeline is not None,
            "model_mae": temp_result["mae"],
            "baseline_mae": temp_result["baseline_mae"],
            "rain_accuracy": rain_result.get("accuracy"),
            "rain_baseline_accuracy": rain_result.get("baseline_accuracy"),
            "condition_accuracy": condition_result.get("accuracy"),
            "condition_baseline_accuracy": condition_result.get("baseline_accuracy"),
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
            "condition_accuracy": condition_result.get("accuracy"),
            "condition_baseline_accuracy": condition_result.get("baseline_accuracy"),
            "condition_model_ready": condition_pipeline is not None,
            "condition_message": None if condition_pipeline is not None else condition_result.get("message"),
        }
    except Exception as e:
        print(f"[ERROR] Errore training ML: {e}")
        return {"success": False, "message": str(e)}
    finally:
        db.close()


def load_latest_model() -> bool:
    """Carica in memoria l'ultimo modello promosso."""
    global _pipeline, _rain_pipeline, _condition_pipeline, _label_encoder, _known_regions, _latest_summary

    db: Session = SessionLocal()
    try:
        record = db.query(MlModelStore).order_by(MlModelStore.trained_at.desc()).first()
        if not record or not record.model_bytes:
            print("[INFO]  Nessun modello ML salvato nel DB")
            _pipeline = None
            _rain_pipeline = None
            _condition_pipeline = None
            _latest_summary = {
                **_latest_summary,
                "model_ready": False,
                "rain_model_ready": False,
                "condition_model_ready": False,
                "model_trained_at": None,
                "model_mae": None,
                "condition_accuracy": None,
                "condition_baseline_accuracy": None,
                "model_samples": None,
            }
            return False

        data = pickle.loads(record.model_bytes)
        _pipeline = data["pipeline"]
        _rain_pipeline = data.get("rain_pipeline")
        _condition_pipeline = data.get("condition_pipeline")
        _label_encoder = data["le"]
        _known_regions = data.get("regions", [])
        _latest_summary = {
            "model_ready": _pipeline is not None,
            "rain_model_ready": _rain_pipeline is not None,
            "condition_model_ready": _condition_pipeline is not None,
            "model_mae": record.mae,
            "baseline_mae": data.get("baseline_mae"),
            "rain_accuracy": data.get("rain_accuracy"),
            "rain_baseline_accuracy": data.get("rain_baseline_accuracy"),
            "condition_accuracy": data.get("condition_accuracy"),
            "condition_baseline_accuracy": data.get("condition_baseline_accuracy"),
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
    """Predice la correzione da applicare alla temperatura prevista."""
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
        confidence = _confidence_from_score(abs(correction) / 1.5)

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
    """Predice la probabilità di pioggia per una previsione futura."""
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

        return {
            "rain_probability": round(rain_prob, 3),
            "will_rain": rain_prob >= 0.5,
            "model_ready": True,
            "confidence": _confidence_from_score(abs(rain_prob - 0.5) * 2),
        }
    except Exception as e:
        return {"model_ready": False, "error": str(e)}


def predict_condition_outlook(
    *,
    forecast_temp: float,
    humidity: float,
    hour: int,
    month: int,
    lat: float,
    region: str,
    cloud_cover: float = 50.0,
    lead_hours: int = 0,
    forecast_precipitation: float = 0.0,
    forecast_wind_speed: float = 0.0,
    forecast_wind_direction: float = 0.0,
    forecast_weather_code: int | None = None,
) -> dict:
    provider_condition = _condition_from_inputs(
        weather_code=forecast_weather_code,
        cloud_cover=cloud_cover,
        precipitation=forecast_precipitation,
    )

    if _condition_pipeline is None:
        return {
            "model_ready": False,
            "expected_condition": provider_condition,
            "display_condition": _condition_display(provider_condition),
            "confidence": "media",
            "source": "provider",
        }

    try:
        features = _build_condition_features(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            forecast_precipitation=forecast_precipitation,
            forecast_wind_speed=forecast_wind_speed,
            forecast_wind_direction=forecast_wind_direction,
            forecast_weather_code=forecast_weather_code,
        )
        probabilities = _condition_pipeline.predict_proba(features)[0]
        predicted_code = int(_condition_pipeline.predict(features)[0])
        top_probability = float(np.max(probabilities))
        predicted_label = CONDITION_LABELS[predicted_code]

        return {
            "model_ready": True,
            "expected_condition": predicted_label,
            "display_condition": _condition_display(predicted_label),
            "confidence": _confidence_from_score(top_probability),
            "source": "ml",
            "probability": round(top_probability, 3),
            "provider_condition": provider_condition,
        }
    except Exception as e:
        return {
            "model_ready": False,
            "expected_condition": provider_condition,
            "display_condition": _condition_display(provider_condition),
            "confidence": "media",
            "source": "provider",
            "error": str(e),
        }


def build_daily_insight(
    *,
    day: dict,
    lat: float,
    region: str,
    lead_hours: int,
) -> dict:
    day_date = datetime.fromisoformat(day["dt"])
    hour = 14
    forecast_temp = day.get("temp", {}).get("day", 0.0)
    forecast_pop = _safe_float(day.get("pop"), 0.0)
    forecast_precipitation = round(forecast_pop * 2.0, 2)
    cloud_cover = _safe_float(day.get("cloud_cover"), 55.0)
    wind_speed = _safe_float(day.get("wind_speed"), 0.0)
    wind_direction = _safe_float(day.get("wind_deg"), 0.0)
    weather_code = day.get("weather_code")

    correction = predict_correction(
        temp=forecast_temp,
        humidity=_safe_float(day.get("humidity"), 55.0),
        hour=hour,
        month=day_date.month,
        lat=lat,
        region=region,
        cloud_cover=cloud_cover,
        lead_hours=min(lead_hours, 6),
    )
    rain = predict_rain_probability(
        forecast_temp=forecast_temp,
        humidity=_safe_float(day.get("humidity"), 55.0),
        hour=hour,
        month=day_date.month,
        lat=lat,
        region=region,
        cloud_cover=cloud_cover,
        lead_hours=min(lead_hours, 6),
    )
    condition = predict_condition_outlook(
        forecast_temp=forecast_temp,
        humidity=_safe_float(day.get("humidity"), 55.0),
        hour=hour,
        month=day_date.month,
        lat=lat,
        region=region,
        cloud_cover=cloud_cover,
        lead_hours=min(lead_hours, 6),
        forecast_precipitation=forecast_precipitation,
        forecast_wind_speed=wind_speed,
        forecast_wind_direction=wind_direction,
        forecast_weather_code=weather_code,
    )

    blended_rain = forecast_pop
    if rain.get("model_ready"):
        blended_rain = round((forecast_pop * 0.6) + (rain["rain_probability"] * 0.4), 3)

    delta = correction["correction"] if correction.get("model_ready") else 0.0
    adjusted_min = round(day["temp"]["min"] + delta, 1)
    adjusted_max = round(day["temp"]["max"] + delta, 1)
    expected_condition = condition["expected_condition"]
    confidence = condition["confidence"]

    return {
        "expected_condition": expected_condition,
        "display_condition": condition["display_condition"],
        "condition_confidence": confidence,
        "condition_source": condition["source"],
        "rain_probability": blended_rain,
        "rain_confidence": rain.get("confidence", "media") if rain.get("model_ready") else "provider",
        "temperature_delta": round(delta, 2),
        "adjusted_temp_range": {
            "min": adjusted_min,
            "max": adjusted_max,
        },
        "summary": _daily_summary(expected_condition, blended_rain, wind_speed, confidence),
        "badge": _daily_badge(expected_condition, blended_rain, wind_speed),
    }


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
