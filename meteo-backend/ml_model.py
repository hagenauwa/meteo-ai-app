"""
ml_model.py — modelli ML per correzione temperatura, probabilità pioggia e condizione del cielo.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import pickle
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database import City, MlModelStore, MlPrediction, SessionLocal

logger = logging.getLogger(__name__)

CONDITION_LABELS = ("sereno", "parzialmente nuvoloso", "nuvoloso", "pioggia")
CONDITION_TO_CODE = {label: index for index, label in enumerate(CONDITION_LABELS)}
RAIN_WEATHER_CODES = {
    51, 53, 55, 56, 57,
    61, 63, 65, 66, 67,
    80, 81, 82,
    95, 96, 99,
}
STATS_CACHE_TTL_SECONDS = 45
MODEL_VERSION_CHECK_TTL_SECONDS = 90
MAX_KPI_EVAL_ROWS = 2500
SHADOW_REQUIRED_STREAK = 3
RECENCY_HALF_LIFE_DAYS = 21
LEAD_BUCKETS = (
    "short",
    "intraday",
    "day1",
    "day2_3",
    "day4_7",
    "day8_plus",
)
BLEND_BUCKET_ML_WEIGHT_LIMITS = {
    "short": (0.2, 0.7),
    "intraday": (0.15, 0.65),
    "day1": (0.15, 0.55),
    "day2_3": (0.1, 0.45),
    "day4_7": (0.05, 0.35),
    "day8_plus": (0.0, 0.2),
}
MODEL_FORMAT_VERSION = 2
MODEL_METADATA_PREFIX = b"MLMETA "

# Pipeline globali caricate in memoria all'avvio
_pipeline: Optional[Pipeline] = None
_rain_pipeline: Optional[Pipeline] = None
_condition_pipeline: Optional[Pipeline] = None
_rain_pipeline_v2: Optional[Pipeline] = None
_condition_pipeline_v2: Optional[Pipeline] = None
_rain_platt_v2: dict | None = None
_condition_platt_v2: dict | None = None
_label_encoder: Optional[LabelEncoder] = None
_known_regions: list[str] = []
_temperature_feature_variant = "v1"
_blend_profiles: dict[str, dict[str, dict[str, float | int]]] = {"v1": {}, "v2": {}}

_latest_summary: dict = {
    "model_ready": False,
    "rain_model_ready": False,
    "condition_model_ready": False,
    "rain_model_v2_ready": False,
    "condition_model_v2_ready": False,
    "model_mae": None,
    "baseline_mae": None,
    "rain_accuracy": None,
    "rain_baseline_accuracy": None,
    "condition_accuracy": None,
    "condition_baseline_accuracy": None,
    "rain_brier_v2": None,
    "condition_macro_f1_v2": None,
    "temperature_model_variant": None,
    "model_format_version": None,
    "model_sklearn_version": None,
    "model_load_warning": None,
    "model_samples": None,
    "model_trained_at": None,
}


def _empty_model_summary() -> dict:
    return {
        "model_ready": False,
        "rain_model_ready": False,
        "condition_model_ready": False,
        "rain_model_v2_ready": False,
        "condition_model_v2_ready": False,
        "model_mae": None,
        "baseline_mae": None,
        "rain_accuracy": None,
        "rain_baseline_accuracy": None,
        "condition_accuracy": None,
        "condition_baseline_accuracy": None,
        "rain_brier_v2": None,
        "condition_macro_f1_v2": None,
        "temperature_model_variant": None,
        "model_format_version": None,
        "model_sklearn_version": None,
        "model_load_warning": None,
        "model_samples": None,
        "model_trained_at": None,
    }
_stats_cache: dict[str, object] | None = None
_shadow_state: dict[str, object] = {
    "consecutive_positive_windows": 0,
    "last_check_at": None,
    "last_pass": None,
    "last_details": None,
}
_runtime_force_v1 = False
_loaded_model_store_id: int | None = None
_loaded_model_trained_at: datetime | None = None
_last_model_version_check_at: datetime | None = None


def _safe_float(value: float | int | None, fallback: float = 0.0) -> float:
    return float(value if value is not None else fallback)


def _clip_prob(value: float) -> float:
    return float(max(1e-6, min(1.0 - 1e-6, value)))


def _invalidate_stats_cache():
    global _stats_cache
    _stats_cache = None


def _get_cached_stats_value(*, allow_stale: bool) -> dict | None:
    if not _stats_cache:
        return None

    expires_at = _stats_cache.get("expires_at")
    cached_value = _stats_cache.get("value")
    if not isinstance(cached_value, dict):
        return None

    if not allow_stale:
        now = datetime.now(timezone.utc)
        if not isinstance(expires_at, datetime) or expires_at <= now:
            return None

    return copy.deepcopy(cached_value)


def get_cached_stats(*, allow_stale: bool = False) -> dict | None:
    return _get_cached_stats_value(allow_stale=allow_stale)


def _latest_model_record_summary() -> dict | None:
    db: Session = SessionLocal()
    try:
        record = db.query(MlModelStore.id, MlModelStore.trained_at).order_by(MlModelStore.trained_at.desc()).first()
        if not record:
            return None
        return {
            "id": int(record.id),
            "trained_at": record.trained_at,
        }
    except Exception:
        return None
    finally:
        db.close()


def _reset_loaded_model_state() -> None:
    global _pipeline, _rain_pipeline, _condition_pipeline
    global _rain_pipeline_v2, _condition_pipeline_v2, _rain_platt_v2, _condition_platt_v2
    global _label_encoder, _known_regions, _temperature_feature_variant, _blend_profiles

    _pipeline = None
    _rain_pipeline = None
    _condition_pipeline = None
    _rain_pipeline_v2 = None
    _condition_pipeline_v2 = None
    _rain_platt_v2 = None
    _condition_platt_v2 = None
    _label_encoder = None
    _known_regions = []
    _temperature_feature_variant = "v1"
    _blend_profiles = {"v1": {}, "v2": {}}


def _encode_model_payload(payload: dict) -> bytes:
    metadata = {
        "model_format_version": int(payload.get("model_format_version", MODEL_FORMAT_VERSION)),
        "sklearn_version": payload.get("sklearn_version"),
    }
    header = MODEL_METADATA_PREFIX + json.dumps(metadata, separators=(",", ":")).encode("ascii") + b"\n"
    return header + pickle.dumps(payload)


def _decode_model_payload(blob: bytes) -> tuple[dict | None, bytes | None]:
    if not blob.startswith(MODEL_METADATA_PREFIX):
        return None, None

    header, separator, payload = blob.partition(b"\n")
    if not separator:
        raise ValueError("missing_model_metadata_separator")

    metadata = json.loads(header[len(MODEL_METADATA_PREFIX):].decode("ascii"))
    return metadata, payload


def _ensure_latest_model_loaded(*, force: bool = False) -> None:
    global _last_model_version_check_at

    now = datetime.now(timezone.utc)
    if not force and _last_model_version_check_at and (now - _last_model_version_check_at).total_seconds() < MODEL_VERSION_CHECK_TTL_SECONDS:
        return

    _last_model_version_check_at = now
    latest = _latest_model_record_summary()
    if latest is None:
        if _loaded_model_store_id is not None:
            load_latest_model()
        return

    if latest["id"] != _loaded_model_store_id or latest["trained_at"] != _loaded_model_trained_at:
        load_latest_model()


def _normalize_wind_direction(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value) % 360.0


def _region_code(region: str) -> int:
    if _label_encoder and region in _known_regions:
        return int(_label_encoder.transform([region])[0])
    return 0


def _hour_sin(hour: int) -> float:
    return float(np.sin((2.0 * np.pi * (hour % 24)) / 24.0))


def _hour_cos(hour: int) -> float:
    return float(np.cos((2.0 * np.pi * (hour % 24)) / 24.0))


def _month_sin(month: int) -> float:
    month_zero = max(1, min(12, month)) - 1
    return float(np.sin((2.0 * np.pi * month_zero) / 12.0))


def _month_cos(month: int) -> float:
    month_zero = max(1, min(12, month)) - 1
    return float(np.cos((2.0 * np.pi * month_zero) / 12.0))


def _lead_bucket_name(lead_hours: int | None) -> str:
    lead = max(0, int(lead_hours or 0))
    if lead <= 6:
        return "short"
    if lead <= 24:
        return "intraday"
    if lead <= 48:
        return "day1"
    if lead <= 96:
        return "day2_3"
    if lead <= 168:
        return "day4_7"
    return "day8_plus"


def _lead_bucket_flags(lead_hours: int | None) -> list[float]:
    bucket = _lead_bucket_name(lead_hours)
    return [1.0 if bucket == label else 0.0 for label in LEAD_BUCKETS]


def _lead_bucket_code(lead_hours: int | None) -> int:
    return LEAD_BUCKETS.index(_lead_bucket_name(lead_hours))


def _lead_hours_feature(lead_hours: int | None) -> int:
    return max(0, min(int(lead_hours or 0), 240))


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


def _downgrade_confidence(label: str) -> str:
    if label == "alta":
        return "media"
    if label == "media":
        return "bassa"
    return "bassa"


def _lead_support_count(lead_hours: int) -> int:
    if not _stats_cache:
        return 0

    value = _stats_cache.get("value")
    if not isinstance(value, dict):
        return 0

    rows = value.get("temp_mae_14d_by_lead")
    if isinstance(rows, list):
        lookup = {
            int(item.get("lead_hours", 0)): int(item.get("samples", 0))
            for item in rows
            if isinstance(item, dict)
        }
        if int(lead_hours) in lookup:
            return lookup[int(lead_hours)]

    bucket_rows = value.get("temp_mae_14d_by_bucket")
    if not isinstance(bucket_rows, list):
        return 0

    bucket = _lead_bucket_name(lead_hours)
    lookup = {
        str(item.get("bucket", "")): int(item.get("samples", 0))
        for item in bucket_rows
        if isinstance(item, dict)
    }
    return lookup.get(bucket, 0)


def _empirical_confidence(label: str, lead_hours: int) -> str:
    support = _lead_support_count(lead_hours)
    if support >= 200:
        return label
    if support >= 50:
        return _downgrade_confidence(label)
    return _downgrade_confidence(_downgrade_confidence(label))


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


def _horizon_support(lead_hours: int) -> str:
    if lead_hours < 48:
        return "full"
    if lead_hours <= 168:
        return "limited"
    return "provider_only"


def _recency_sample_weights(rows: list[dict]) -> np.ndarray:
    if not rows:
        return np.array([], dtype=float)

    reference_time = max(row.get("verified_at") or row["target_time"] for row in rows)
    weights = []
    for row in rows:
        sample_time = row.get("verified_at") or row["target_time"]
        age_days = max(0.0, (reference_time - sample_time).total_seconds() / 86400.0)
        weights.append(max(0.2, 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)))
    return np.array(weights, dtype=float)


def _city_rollout_bucket(city_name: str | None) -> int:
    key = (city_name or "global").strip().lower().encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    return int(digest[:8], 16) % 100


def _can_use_v2_live() -> bool:
    if not settings.ml_v2_enabled:
        return False
    if settings.ml_v2_shadow_only:
        return False
    if _runtime_force_v1:
        return False
    if _shadow_state.get("consecutive_positive_windows", 0) < SHADOW_REQUIRED_STREAK:
        return False
    return True


def _resolve_live_model_variant(city_name: str | None = None) -> str:
    if not _can_use_v2_live():
        return "v1"

    rollout = max(0, min(100, settings.ml_v2_rollout_percent))
    if rollout <= 0:
        return "v1"

    return "v2" if _city_rollout_bucket(city_name) < rollout else "v1"


def _global_model_variant_for_stats() -> str:
    if settings.ml_v2_shadow_only and settings.ml_v2_enabled:
        return "v1"
    return _resolve_live_model_variant(None)


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
        _lead_hours_feature(lead_hours),
        _region_code(region),
    ]])


def _build_temperature_features_legacy_v0(
    *,
    forecast_temp: float,
    humidity: float | None,
    hour: int,
    month: int,
    lat: float,
    region: str,
) -> np.ndarray:
    """Compat con i primi modelli temperatura salvati prima di cloud_cover/lead_hours."""
    return np.array([[
        forecast_temp,
        _safe_float(humidity, 50.0),
        hour,
        month,
        lat,
        _region_code(region),
    ]])


def _build_rain_features_legacy_v0(
    *,
    forecast_temp: float,
    humidity: float | None,
    hour: int,
    month: int,
    lat: float,
    region: str,
) -> np.ndarray:
    return np.array([[
        forecast_temp,
        _safe_float(humidity, 50.0),
        hour,
        month,
        lat,
        _region_code(region),
    ]])


def _build_temperature_features_v2(
    *,
    forecast_temp: float,
    humidity: float | None,
    hour: int,
    month: int,
    lat: float,
    lon: float | None,
    region: str,
    cloud_cover: float | None,
    lead_hours: int,
    forecast_precipitation: float | None,
    forecast_wind_speed: float | None,
    forecast_wind_direction: float | None,
    forecast_weather_code: int | None,
) -> np.ndarray:
    return np.array([[
        forecast_temp,
        _safe_float(humidity, 50.0),
        _safe_float(cloud_cover, 50.0),
        _safe_float(forecast_precipitation, 0.0),
        _safe_float(forecast_wind_speed, 0.0),
        _normalize_wind_direction(forecast_wind_direction),
        int(forecast_weather_code or 0),
        _lead_hours_feature(lead_hours),
        _hour_sin(hour),
        _hour_cos(hour),
        _month_sin(month),
        _month_cos(month),
        _safe_float(lat, 43.0),
        _safe_float(lon, 12.0),
        _region_code(region),
        *_lead_bucket_flags(lead_hours),
        1.0 if humidity is None else 0.0,
        1.0 if cloud_cover is None else 0.0,
        1.0 if forecast_precipitation is None else 0.0,
        1.0 if forecast_wind_speed is None else 0.0,
        1.0 if forecast_weather_code is None else 0.0,
    ]])


def _pipeline_feature_count(pipeline: Pipeline | None) -> int | None:
    if pipeline is None:
        return None

    try:
        count = getattr(pipeline, "n_features_in_", None)
        if count is not None:
            return int(count)

        scaler = getattr(pipeline, "named_steps", {}).get("scaler") if hasattr(pipeline, "named_steps") else None
        if scaler is not None and getattr(scaler, "n_features_in_", None) is not None:
            return int(scaler.n_features_in_)
    except Exception:
        return None

    return None


def _temperature_pipeline_feature_count() -> int | None:
    return _pipeline_feature_count(_pipeline)


def _rain_pipeline_feature_count() -> int | None:
    return _pipeline_feature_count(_rain_pipeline)


def _condition_pipeline_feature_count() -> int | None:
    return _pipeline_feature_count(_condition_pipeline)


def _infer_temperature_feature_variant_from_pipeline(default_variant: str | None = None) -> str:
    feature_count = _temperature_pipeline_feature_count()
    if feature_count == 6:
        return "legacy"
    if feature_count == 8:
        return "v1"
    if feature_count == 21:
        return "v2"
    return default_variant or _temperature_feature_variant or "v1"


def _infer_rain_feature_variant_from_pipeline(default_variant: str | None = None) -> str:
    feature_count = _rain_pipeline_feature_count()
    if feature_count == 6:
        return "legacy"
    if feature_count == 8:
        return "v1"
    if feature_count == 26:
        return "v2"
    return default_variant or "v1"


def _infer_condition_feature_variant_from_pipeline(default_variant: str | None = None) -> str:
    feature_count = _condition_pipeline_feature_count()
    if feature_count == 11:
        return "legacy"
    if feature_count == 13:
        return "v1"
    if feature_count == 26:
        return "v2"
    return default_variant or "v1"


def _build_temperature_features_for_inference(
    *,
    forecast_temp: float,
    humidity: float | None,
    hour: int,
    month: int,
    lat: float,
    lon: float | None,
    region: str,
    cloud_cover: float | None,
    lead_hours: int,
    forecast_precipitation: float | None,
    forecast_wind_speed: float | None,
    forecast_wind_direction: float | None,
    forecast_weather_code: int | None,
) -> tuple[np.ndarray, str]:
    variant = _infer_temperature_feature_variant_from_pipeline(_temperature_feature_variant)
    if variant == "legacy":
        return _build_temperature_features_legacy_v0(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            region=region,
        ), variant
    if variant == "v2":
        return _build_temperature_features_v2(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            lon=lon,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            forecast_precipitation=forecast_precipitation,
            forecast_wind_speed=forecast_wind_speed,
            forecast_wind_direction=forecast_wind_direction,
            forecast_weather_code=forecast_weather_code,
        ), variant
    return _build_features(
        forecast_temp=forecast_temp,
        humidity=_safe_float(humidity, 50.0),
        hour=hour,
        month=month,
        lat=lat,
        region=region,
        cloud_cover=_safe_float(cloud_cover, 50.0),
        lead_hours=lead_hours,
    ), "v1"


def _build_rain_features_v2(
    *,
    forecast_temp: float,
    humidity: float | None,
    hour: int,
    month: int,
    lat: float,
    lon: float | None,
    region: str,
    cloud_cover: float | None,
    lead_hours: int,
    forecast_precipitation: float | None,
    forecast_wind_speed: float | None,
    forecast_wind_direction: float | None,
    forecast_weather_code: int | None,
) -> np.ndarray:
    return np.array([[
        forecast_temp,
        _safe_float(humidity, 50.0),
        _safe_float(cloud_cover, 50.0),
        _safe_float(forecast_precipitation, 0.0),
        _safe_float(forecast_wind_speed, 0.0),
        _normalize_wind_direction(forecast_wind_direction),
        int(forecast_weather_code or 0),
        _lead_hours_feature(lead_hours),
        _hour_sin(hour),
        _hour_cos(hour),
        _month_sin(month),
        _month_cos(month),
        _safe_float(lat, 43.0),
        _safe_float(lon, 12.0),
        _region_code(region),
        *_lead_bucket_flags(lead_hours),
        1.0 if humidity is None else 0.0,
        1.0 if cloud_cover is None else 0.0,
        1.0 if forecast_precipitation is None else 0.0,
        1.0 if forecast_wind_speed is None else 0.0,
        1.0 if forecast_weather_code is None else 0.0,
    ]])


def _build_rain_features_for_inference(
    *,
    forecast_temp: float,
    humidity: float | None,
    hour: int,
    month: int,
    lat: float,
    lon: float | None,
    region: str,
    cloud_cover: float | None,
    lead_hours: int,
    forecast_precipitation: float | None,
    forecast_wind_speed: float | None,
    forecast_wind_direction: float | None,
    forecast_weather_code: int | None,
) -> tuple[np.ndarray, str]:
    variant = _infer_rain_feature_variant_from_pipeline()
    if variant == "legacy":
        return _build_rain_features_legacy_v0(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            region=region,
        ), variant
    if variant == "v2":
        return _build_rain_features_v2(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            lon=lon,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            forecast_precipitation=forecast_precipitation,
            forecast_wind_speed=forecast_wind_speed,
            forecast_wind_direction=forecast_wind_direction,
            forecast_weather_code=forecast_weather_code,
        ), variant
    return _build_features(
        forecast_temp=forecast_temp,
        humidity=_safe_float(humidity, 50.0),
        hour=hour,
        month=month,
        lat=lat,
        region=region,
        cloud_cover=_safe_float(cloud_cover, 50.0),
        lead_hours=lead_hours,
    ), "v1"


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


def _build_condition_features_legacy_v0(
    *,
    forecast_temp: float,
    humidity: float | None,
    hour: int,
    month: int,
    lat: float,
    region: str,
    cloud_cover: float | None,
    lead_hours: int,
    forecast_precipitation: float | None,
    forecast_weather_code: int | None,
) -> np.ndarray:
    provider_condition = _condition_from_inputs(
        weather_code=forecast_weather_code,
        cloud_cover=cloud_cover,
        precipitation=forecast_precipitation,
    )

    return np.array([[
        forecast_temp,
        _safe_float(humidity, 50.0),
        hour,
        month,
        lat,
        _safe_float(cloud_cover, 50.0),
        max(0, lead_hours or 0),
        _safe_float(forecast_precipitation, 0.0),
        _region_code(region),
        CONDITION_TO_CODE[provider_condition],
        forecast_weather_code or 0,
    ]])


def _build_condition_features_v2(
    *,
    forecast_temp: float,
    humidity: float | None,
    hour: int,
    month: int,
    lat: float,
    lon: float | None,
    region: str,
    cloud_cover: float | None,
    lead_hours: int,
    forecast_precipitation: float | None,
    forecast_wind_speed: float | None,
    forecast_wind_direction: float | None,
    forecast_weather_code: int | None,
) -> np.ndarray:
    provider_condition = _condition_from_inputs(
        weather_code=forecast_weather_code,
        cloud_cover=cloud_cover,
        precipitation=forecast_precipitation,
    )

    return np.array([[
        forecast_temp,
        _safe_float(humidity, 50.0),
        _safe_float(cloud_cover, 50.0),
        _safe_float(forecast_precipitation, 0.0),
        _safe_float(forecast_wind_speed, 0.0),
        _normalize_wind_direction(forecast_wind_direction),
        int(forecast_weather_code or 0),
        CONDITION_TO_CODE[provider_condition],
        _lead_hours_feature(lead_hours),
        _hour_sin(hour),
        _hour_cos(hour),
        _month_sin(month),
        _month_cos(month),
        _safe_float(lat, 43.0),
        _safe_float(lon, 12.0),
        _region_code(region),
        *_lead_bucket_flags(lead_hours),
        1.0 if humidity is None else 0.0,
        1.0 if cloud_cover is None else 0.0,
        1.0 if forecast_precipitation is None else 0.0,
        1.0 if forecast_wind_speed is None else 0.0,
        1.0 if forecast_weather_code is None else 0.0,
    ]])


def _build_condition_features_for_inference(
    *,
    forecast_temp: float,
    humidity: float | None,
    hour: int,
    month: int,
    lat: float,
    lon: float | None,
    region: str,
    cloud_cover: float | None,
    lead_hours: int,
    forecast_precipitation: float | None,
    forecast_wind_speed: float | None,
    forecast_wind_direction: float | None,
    forecast_weather_code: int | None,
) -> tuple[np.ndarray, str]:
    variant = _infer_condition_feature_variant_from_pipeline()
    if variant == "legacy":
        return _build_condition_features_legacy_v0(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            forecast_precipitation=forecast_precipitation,
            forecast_weather_code=forecast_weather_code,
        ), variant
    if variant == "v2":
        return _build_condition_features_v2(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            lon=lon,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            forecast_precipitation=forecast_precipitation,
            forecast_wind_speed=forecast_wind_speed,
            forecast_wind_direction=forecast_wind_direction,
            forecast_weather_code=forecast_weather_code,
        ), variant
    return _build_condition_features(
        forecast_temp=forecast_temp,
        humidity=_safe_float(humidity, 50.0),
        hour=hour,
        month=month,
        lat=lat,
        region=region,
        cloud_cover=_safe_float(cloud_cover, 50.0),
        lead_hours=lead_hours,
        forecast_precipitation=_safe_float(forecast_precipitation, 0.0),
        forecast_wind_speed=_safe_float(forecast_wind_speed, 0.0),
        forecast_wind_direction=_safe_float(forecast_wind_direction, 0.0),
        forecast_weather_code=forecast_weather_code,
    ), "v1"


def _prepare_training_rows(
    db: Session,
    *,
    window_start: datetime | None = None,
    limit: int | None = None,
) -> list[dict]:
    query = (
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
            MlPrediction.verified_at,
            City.lat,
            City.lon,
            City.region,
        )
        .join(City, MlPrediction.city_id == City.id)
        .filter(MlPrediction.verified.is_(True))
        .filter(MlPrediction.actual_temp.isnot(None))
        .filter(MlPrediction.error.isnot(None))
    )

    if window_start is not None:
        query = query.filter(
            MlPrediction.verified_at.isnot(None),
            MlPrediction.verified_at >= window_start,
        )

    if limit is not None and limit > 0:
        query = query.order_by(MlPrediction.verified_at.desc(), MlPrediction.id.desc()).limit(int(limit))

    rows = query.all()

    prepared: list[dict] = []
    for row in rows:
        target_time = row.target_time or row.predicted_at
        if not target_time:
            continue

        forecast_temp = row.forecast_temp if row.forecast_temp is not None else row.predicted_temp
        prepared.append({
            "target_time": target_time,
            "verified_at": row.verified_at,
            "forecast_temp": forecast_temp,
            "humidity": row.humidity,
            "hour": target_time.hour,
            "month": target_time.month,
            "lat": row.lat or 43.0,
            "lon": row.lon or 12.0,
            "cloud_cover": row.forecast_cloud_cover,
            "lead_hours": row.lead_hours or 0,
            "region": row.region or "Sconosciuta",
            "error": row.error,
            "forecast_precipitation": row.forecast_precipitation,
            "forecast_weather_code": row.forecast_weather_code,
            "forecast_wind_speed": row.forecast_wind_speed,
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
            _safe_float(row["humidity"], 50.0),
            row["hour"],
            row["month"],
            row["lat"],
            _safe_float(row["cloud_cover"], 50.0),
            row["lead_hours"],
            region_code,
        ])
        y.append(row["error"])
    return np.array(X), np.array(y)


def _build_temperature_matrices_v2(rows: list[dict], encoder: LabelEncoder) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for row in rows:
        _ = encoder
        features = _build_temperature_features_v2(
            forecast_temp=row["forecast_temp"],
            humidity=row["humidity"],
            hour=row["hour"],
            month=row["month"],
            lat=row["lat"],
            lon=row["lon"],
            region=row["region"],
            cloud_cover=row["cloud_cover"],
            lead_hours=row["lead_hours"],
            forecast_precipitation=row["forecast_precipitation"],
            forecast_wind_speed=row["forecast_wind_speed"],
            forecast_wind_direction=row["forecast_wind_direction"],
            forecast_weather_code=row["forecast_weather_code"],
        )
        X.append(features[0].tolist())
        y.append(row["error"])
    return np.array(X), np.array(y)


def _build_rain_matrices(rows: list[dict], encoder: LabelEncoder) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for row in rows:
        if row["actual_precipitation"] is None:
            continue

        region_code = int(encoder.transform([row["region"]])[0])
        X.append([
            row["forecast_temp"],
            _safe_float(row["humidity"], 50.0),
            row["hour"],
            row["month"],
            row["lat"],
            _safe_float(row["cloud_cover"], 50.0),
            row["lead_hours"],
            region_code,
        ])
        y.append(1 if (row["actual_precipitation"] or 0.0) > 0.1 else 0)
    return np.array(X), np.array(y)


def _build_rain_matrices_v2(rows: list[dict], encoder: LabelEncoder) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for row in rows:
        if row["actual_precipitation"] is None:
            continue

        _ = encoder
        features = _build_rain_features_v2(
            forecast_temp=row["forecast_temp"],
            humidity=row["humidity"],
            hour=row["hour"],
            month=row["month"],
            lat=row["lat"],
            lon=row["lon"],
            region=row["region"],
            cloud_cover=row["cloud_cover"],
            lead_hours=row["lead_hours"],
            forecast_precipitation=row["forecast_precipitation"],
            forecast_wind_speed=row["forecast_wind_speed"],
            forecast_wind_direction=row["forecast_wind_direction"],
            forecast_weather_code=row["forecast_weather_code"],
        )
        X.append(features[0].tolist())
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
            _safe_float(row["humidity"], 50.0),
            row["hour"],
            row["month"],
            row["lat"],
            _safe_float(row["cloud_cover"], 50.0),
            row["lead_hours"],
            _safe_float(row["forecast_precipitation"], 0.0),
            _safe_float(row["forecast_wind_speed"], 0.0),
            row["forecast_wind_direction"],
            region_code,
            CONDITION_TO_CODE[provider_condition],
            row["forecast_weather_code"] or 0,
        ])
        y.append(CONDITION_TO_CODE[actual_condition])
    return np.array(X), np.array(y)


def _build_condition_matrices_v2(rows: list[dict], encoder: LabelEncoder) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for row in rows:
        if row["actual_weather_code"] is None and row["actual_cloud_cover"] is None and row["actual_precipitation"] is None:
            continue

        _ = encoder
        features = _build_condition_features_v2(
            forecast_temp=row["forecast_temp"],
            humidity=row["humidity"],
            hour=row["hour"],
            month=row["month"],
            lat=row["lat"],
            lon=row["lon"],
            region=row["region"],
            cloud_cover=row["cloud_cover"],
            lead_hours=row["lead_hours"],
            forecast_precipitation=row["forecast_precipitation"],
            forecast_wind_speed=row["forecast_wind_speed"],
            forecast_wind_direction=row["forecast_wind_direction"],
            forecast_weather_code=row["forecast_weather_code"],
        )
        actual_condition = _condition_from_inputs(
            weather_code=row["actual_weather_code"],
            cloud_cover=row["actual_cloud_cover"],
            precipitation=row["actual_precipitation"],
        )
        X.append(features[0].tolist())
        y.append(CONDITION_TO_CODE[actual_condition])
    return np.array(X), np.array(y)


def _split_train_validation(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    if len(X) < 10:
        return None

    split_idx = max(int(len(X) * 0.8), 1)
    if split_idx >= len(X):
        split_idx = len(X) - 1

    return X[:split_idx], X[split_idx:], y[:split_idx], y[split_idx:]


def _fit_platt_scaler(probabilities: np.ndarray, y: np.ndarray) -> dict | None:
    if len(probabilities) < 30:
        return None
    if len(set(y.tolist())) < 2:
        return None

    probs = np.clip(probabilities.astype(float), 1e-6, 1.0 - 1e-6)
    logits = np.log(probs / (1.0 - probs)).reshape(-1, 1)
    calibrator = LogisticRegression(max_iter=1000)
    calibrator.fit(logits, y)

    return {
        "coef": float(calibrator.coef_[0][0]),
        "intercept": float(calibrator.intercept_[0]),
    }


def _apply_platt(probability: float, params: dict | None) -> float:
    if not params:
        return _clip_prob(probability)

    p = _clip_prob(probability)
    logit = np.log(p / (1.0 - p))
    score = (params.get("coef", 1.0) * logit) + params.get("intercept", 0.0)
    return _clip_prob(1.0 / (1.0 + np.exp(-score)))


def _fit_multiclass_platt(probabilities: np.ndarray, y: np.ndarray) -> dict | None:
    if len(probabilities) < 60:
        return None

    n_classes = probabilities.shape[1]
    calibrators: list[dict | None] = []
    for class_idx in range(n_classes):
        y_bin = (y == class_idx).astype(int)
        calibrators.append(_fit_platt_scaler(probabilities[:, class_idx], y_bin))

    if not any(calibrators):
        return None
    return {"calibrators": calibrators}


def _apply_multiclass_platt(probabilities: np.ndarray, params: dict | None) -> np.ndarray:
    if not params:
        return probabilities

    calibrators = params.get("calibrators") or []
    if len(calibrators) != len(probabilities):
        return probabilities

    calibrated = np.array([
        _apply_platt(float(probabilities[idx]), calibrators[idx])
        for idx in range(len(probabilities))
    ], dtype=float)

    total = float(np.sum(calibrated))
    if total <= 0:
        return probabilities
    return calibrated / total


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
        "feature_variant": "v1",
    }


def _train_temperature_pipeline_v2(rows: list[dict], encoder: LabelEncoder) -> dict:
    X, y = _build_temperature_matrices_v2(rows, encoder)
    split = _split_train_validation(X, y)
    if split is None:
        return {"success": False, "message": "Campioni insufficienti per split temporale temperatura v2"}

    X_train, X_val, y_train, y_val = split
    baseline_mae = float(np.mean(np.abs(y_val)))
    train_rows = rows[:len(X_train)]
    sample_weights = _recency_sample_weights(train_rows)

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=1.0)),
    ])
    pipeline.fit(X_train, y_train, ridge__sample_weight=sample_weights)

    mae = float(mean_absolute_error(y_val, pipeline.predict(X_val)))
    if mae >= baseline_mae:
        return {
            "success": False,
            "message": f"Il modello temperatura v2 non supera il baseline (MAE {mae:.3f} vs {baseline_mae:.3f})",
            "baseline_mae": baseline_mae,
            "mae": mae,
            "pipeline": None,
            "feature_variant": "v2",
        }

    return {
        "success": True,
        "pipeline": pipeline,
        "encoder": encoder,
        "mae": mae,
        "baseline_mae": baseline_mae,
        "n_samples": len(rows),
        "feature_variant": "v2",
    }


def _train_rain_pipeline(rows: list[dict], encoder: LabelEncoder) -> dict:
    X, y = _build_rain_matrices(rows, encoder)
    if len(X) < 20:
        return {"success": False, "message": "Dati insufficienti per il modello pioggia"}

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
        "n_samples": len(X),
        "rain_share": round(float(np.mean(y)), 3),
    }


def _train_rain_pipeline_v2(rows: list[dict], encoder: LabelEncoder) -> dict:
    X, y = _build_rain_matrices_v2(rows, encoder)
    if len(X) < 80:
        return {"success": False, "message": "Dati insufficienti per il modello pioggia v2"}

    split = _split_train_validation(X, y)
    if split is None:
        return {"success": False, "message": "Campioni insufficienti per il modello pioggia v2"}

    X_train, X_val, y_train, y_val = split
    train_rows = [row for row in rows if row["actual_precipitation"] is not None][:len(X_train)]
    sample_weights = _recency_sample_weights(train_rows)
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=2000)),
    ])
    pipeline.fit(X_train, y_train, clf__sample_weight=sample_weights)

    raw_probs = pipeline.predict_proba(X_val)[:, 1]
    platt = _fit_platt_scaler(raw_probs, y_val)
    calibrated = np.array([_apply_platt(float(prob), platt) for prob in raw_probs], dtype=float)

    preds = (calibrated >= 0.5).astype(int)
    f1 = float(f1_score(y_val, preds, zero_division=0))
    brier = float(np.mean((calibrated - y_val) ** 2))

    baseline_prob = float(np.mean(y_train)) if len(y_train) else 0.5
    baseline_probs = np.full(shape=len(y_val), fill_value=baseline_prob, dtype=float)
    baseline_preds = (baseline_probs >= 0.5).astype(int)
    baseline_f1 = float(f1_score(y_val, baseline_preds, zero_division=0))
    baseline_brier = float(np.mean((baseline_probs - y_val) ** 2))

    if brier > baseline_brier and f1 <= baseline_f1:
        return {
            "success": False,
            "message": (
                "Il modello pioggia v2 non supera il baseline "
                f"(brier {brier:.3f}/{baseline_brier:.3f}, f1 {f1:.3f}/{baseline_f1:.3f})"
            ),
            "brier": brier,
            "baseline_brier": baseline_brier,
            "f1": f1,
            "baseline_f1": baseline_f1,
        }

    return {
        "success": True,
        "pipeline": pipeline,
        "platt": platt,
        "brier": brier,
        "baseline_brier": baseline_brier,
        "f1": f1,
        "baseline_f1": baseline_f1,
        "n_samples": len(X),
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


def _train_condition_pipeline_v2(rows: list[dict], encoder: LabelEncoder) -> dict:
    X, y = _build_condition_matrices_v2(rows, encoder)
    if len(X) < 120:
        return {"success": False, "message": "Dati insufficienti per il modello condizioni v2"}
    if len(set(y.tolist())) < 2:
        return {"success": False, "message": "Solo una classe disponibile per il modello condizioni v2"}

    split = _split_train_validation(X, y)
    if split is None:
        return {"success": False, "message": "Campioni insufficienti per il modello condizioni v2"}

    X_train, X_val, y_train, y_val = split
    train_rows = [
        row
        for row in rows
        if row["actual_weather_code"] is not None or row["actual_cloud_cover"] is not None or row["actual_precipitation"] is not None
    ][:len(X_train)]
    sample_weights = _recency_sample_weights(train_rows)
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000, multi_class="multinomial")),
    ])
    pipeline.fit(X_train, y_train, clf__sample_weight=sample_weights)

    raw_probs = pipeline.predict_proba(X_val)
    platt = _fit_multiclass_platt(raw_probs, y_val)
    calibrated = np.array([_apply_multiclass_platt(raw_probs[idx], platt) for idx in range(len(raw_probs))])
    preds = np.argmax(calibrated, axis=1)

    macro_f1 = float(f1_score(y_val, preds, average="macro", zero_division=0))

    baseline_class = int(np.argmax(np.bincount(y_train))) if len(y_train) else 0
    baseline_preds = np.full(shape=len(y_val), fill_value=baseline_class, dtype=int)
    baseline_macro_f1 = float(f1_score(y_val, baseline_preds, average="macro", zero_division=0))

    if macro_f1 <= baseline_macro_f1:
        return {
            "success": False,
            "message": (
                "Il modello condizioni v2 non supera il baseline "
                f"(macro_f1 {macro_f1:.3f} vs {baseline_macro_f1:.3f})"
            ),
            "macro_f1": macro_f1,
            "baseline_macro_f1": baseline_macro_f1,
        }

    return {
        "success": True,
        "pipeline": pipeline,
        "platt": platt,
        "macro_f1": macro_f1,
        "baseline_macro_f1": baseline_macro_f1,
        "n_samples": len(X),
    }


def _condition_target_from_row(row: dict) -> int | None:
    if row.get("actual_weather_code") is None and row.get("actual_cloud_cover") is None and row.get("actual_precipitation") is None:
        return None
    label = _condition_from_inputs(
        weather_code=row.get("actual_weather_code"),
        cloud_cover=row.get("actual_cloud_cover"),
        precipitation=row.get("actual_precipitation"),
    )
    return CONDITION_TO_CODE[label]


def _rain_probability_for_row(row: dict, variant: str) -> float | None:
    if variant == "v2":
        if _rain_pipeline_v2 is None:
            return None
        features = _build_rain_features_v2(
            forecast_temp=row["forecast_temp"],
            humidity=row.get("humidity"),
            hour=row["hour"],
            month=row["month"],
            lat=row["lat"],
            lon=row.get("lon"),
            region=row["region"],
            cloud_cover=row.get("cloud_cover"),
            lead_hours=row["lead_hours"],
            forecast_precipitation=row.get("forecast_precipitation"),
            forecast_wind_speed=row.get("forecast_wind_speed"),
            forecast_wind_direction=row.get("forecast_wind_direction"),
            forecast_weather_code=row.get("forecast_weather_code"),
        )
        raw = float(_rain_pipeline_v2.predict_proba(features)[0][1])
        return float(_apply_platt(raw, _rain_platt_v2))

    if _rain_pipeline is None:
        return None

    features, _ = _build_rain_features_for_inference(
        forecast_temp=row["forecast_temp"],
        humidity=row.get("humidity"),
        hour=row["hour"],
        month=row["month"],
        lat=row["lat"],
        lon=row.get("lon"),
        region=row["region"],
        cloud_cover=row.get("cloud_cover"),
        lead_hours=row["lead_hours"],
        forecast_precipitation=row.get("forecast_precipitation"),
        forecast_wind_speed=row.get("forecast_wind_speed"),
        forecast_wind_direction=row.get("forecast_wind_direction"),
        forecast_weather_code=row.get("forecast_weather_code"),
    )
    return float(_rain_pipeline.predict_proba(features)[0][1])


def _condition_probabilities_for_row(row: dict, variant: str) -> np.ndarray | None:
    if variant == "v2":
        if _condition_pipeline_v2 is None:
            return None
        features = _build_condition_features_v2(
            forecast_temp=row["forecast_temp"],
            humidity=row.get("humidity"),
            hour=row["hour"],
            month=row["month"],
            lat=row["lat"],
            lon=row.get("lon"),
            region=row["region"],
            cloud_cover=row.get("cloud_cover"),
            lead_hours=row["lead_hours"],
            forecast_precipitation=row.get("forecast_precipitation"),
            forecast_wind_speed=row.get("forecast_wind_speed"),
            forecast_wind_direction=row.get("forecast_wind_direction"),
            forecast_weather_code=row.get("forecast_weather_code"),
        )
        raw = _condition_pipeline_v2.predict_proba(features)[0]
        return _apply_multiclass_platt(raw, _condition_platt_v2)

    if _condition_pipeline is None:
        return None

    features, _ = _build_condition_features_for_inference(
        forecast_temp=row["forecast_temp"],
        humidity=row.get("humidity"),
        hour=row["hour"],
        month=row["month"],
        lat=row["lat"],
        lon=row.get("lon"),
        region=row["region"],
        cloud_cover=row.get("cloud_cover"),
        lead_hours=row["lead_hours"],
        forecast_precipitation=row.get("forecast_precipitation"),
        forecast_wind_speed=row.get("forecast_wind_speed"),
        forecast_wind_direction=row.get("forecast_wind_direction"),
        forecast_weather_code=row.get("forecast_weather_code"),
    )
    return _condition_pipeline.predict_proba(features)[0]


def _compute_variant_kpis(rows: list[dict], variant: str) -> dict:
    rain_probs: list[float] = []
    rain_truth: list[int] = []
    condition_preds: list[int] = []
    condition_truth: list[int] = []

    for row in rows:
        if row.get("actual_precipitation") is not None:
            prob = _rain_probability_for_row(row, variant)
            if prob is not None:
                rain_probs.append(prob)
                rain_truth.append(1 if (row.get("actual_precipitation") or 0.0) > 0.1 else 0)

        target_condition = _condition_target_from_row(row)
        if target_condition is None:
            continue

        probs = _condition_probabilities_for_row(row, variant)
        if probs is None:
            continue

        condition_preds.append(int(np.argmax(probs)))
        condition_truth.append(target_condition)

    metrics: dict[str, float | int | None] = {
        "rain_brier": None,
        "rain_f1": None,
        "condition_macro_f1": None,
        "rain_samples": len(rain_truth),
        "condition_samples": len(condition_truth),
    }

    if rain_truth:
        rain_truth_np = np.array(rain_truth)
        rain_probs_np = np.array(rain_probs)
        metrics["rain_brier"] = float(np.mean((rain_probs_np - rain_truth_np) ** 2))
        metrics["rain_f1"] = float(
            f1_score(rain_truth_np, (rain_probs_np >= 0.5).astype(int), zero_division=0)
        )

    if condition_truth:
        metrics["condition_macro_f1"] = float(
            f1_score(condition_truth, condition_preds, average="macro", zero_division=0)
        )

    return metrics


def _provider_rain_probability_proxy(row: dict) -> float:
    forecast_precipitation = _safe_float(row.get("forecast_precipitation"), 0.0)
    weather_code = row.get("forecast_weather_code")
    cloud_cover = _safe_float(row.get("cloud_cover"), 50.0)

    if weather_code in RAIN_WEATHER_CODES or forecast_precipitation >= 1.0:
        return 0.85
    if forecast_precipitation >= 0.3:
        return 0.65
    if forecast_precipitation > 0.0:
        return 0.45
    if cloud_cover >= 80:
        return 0.3
    if cloud_cover >= 55:
        return 0.2
    return 0.08


def _compute_rain_kpis_by_bucket(rows: list[dict], variant: str) -> dict[str, dict[str, float | int | None]]:
    grouped: dict[str, dict[str, list[float] | list[int]]] = {}

    for row in rows:
        if row.get("actual_precipitation") is None:
            continue

        prob = _rain_probability_for_row(row, variant)
        if prob is None:
            continue

        bucket = _lead_bucket_name(row.get("lead_hours"))
        entry = grouped.setdefault(bucket, {"truth": [], "probs": [], "provider_probs": []})
        entry["truth"].append(1 if (row.get("actual_precipitation") or 0.0) > 0.1 else 0)
        entry["probs"].append(float(prob))
        entry["provider_probs"].append(_provider_rain_probability_proxy(row))

    bucket_metrics: dict[str, dict[str, float | int | None]] = {}
    for bucket in LEAD_BUCKETS:
        entry = grouped.get(bucket)
        if not entry:
            continue

        truth = np.array(entry["truth"], dtype=float)
        probs = np.array(entry["probs"], dtype=float)
        provider_probs = np.array(entry["provider_probs"], dtype=float)
        bucket_metrics[bucket] = {
            "samples": int(len(truth)),
            "rain_brier": float(np.mean((probs - truth) ** 2)),
            "provider_brier": float(np.mean((provider_probs - truth) ** 2)),
            "rain_f1": float(f1_score(truth, (probs >= 0.5).astype(int), zero_division=0)),
        }

    return bucket_metrics


def _compute_blend_profile(rows: list[dict], variant: str) -> dict[str, dict[str, float | int]]:
    bucket_kpis = _compute_rain_kpis_by_bucket(rows, variant)
    profile: dict[str, dict[str, float | int]] = {}

    for bucket in LEAD_BUCKETS:
        metrics = bucket_kpis.get(bucket)
        min_weight, max_weight = BLEND_BUCKET_ML_WEIGHT_LIMITS[bucket]
        if not metrics:
            profile[bucket] = {
                "ml_weight": round(float(min_weight), 3),
                "samples": 0,
                "rain_brier": None,
                "provider_brier": None,
            }
            continue

        samples = int(metrics.get("samples", 0) or 0)
        rain_brier_value = metrics.get("rain_brier")
        provider_brier_value = metrics.get("provider_brier")
        rain_brier = float(0.25 if rain_brier_value is None else rain_brier_value)
        provider_brier = float(0.25 if provider_brier_value is None else provider_brier_value)
        support_factor = min(1.0, samples / 200.0)
        relative_skill = max(0.0, min(1.0, (provider_brier - rain_brier + 0.25) / 0.5))
        ml_weight = min_weight + ((max_weight - min_weight) * support_factor * relative_skill)

        profile[bucket] = {
            "ml_weight": round(float(ml_weight), 3),
            "samples": samples,
            "rain_brier": round(rain_brier, 4),
            "provider_brier": round(provider_brier, 4),
        }

    return profile


def _rain_blend_weight(lead_hours: int, model_variant: str) -> float:
    bucket = _lead_bucket_name(lead_hours)
    profile = _blend_profiles.get(model_variant, {})
    bucket_profile = profile.get(bucket, {})
    if isinstance(bucket_profile, dict) and bucket_profile.get("ml_weight") is not None:
        return float(bucket_profile["ml_weight"])

    min_weight, _ = BLEND_BUCKET_ML_WEIGHT_LIMITS[bucket]
    return float(min_weight)


def _kpi_gate(v1: dict, v2: dict) -> dict:
    rain_brier_v1 = v1.get("rain_brier")
    rain_brier_v2 = v2.get("rain_brier")
    rain_f1_v1 = v1.get("rain_f1")
    rain_f1_v2 = v2.get("rain_f1")
    cond_f1_v1 = v1.get("condition_macro_f1")
    cond_f1_v2 = v2.get("condition_macro_f1")

    if any(metric is None for metric in (rain_brier_v1, rain_brier_v2, rain_f1_v1, rain_f1_v2, cond_f1_v1, cond_f1_v2)):
        return {
            "pass": False,
            "reason": "kpi_insufficient",
        }

    rain_brier_improvement = (rain_brier_v1 - rain_brier_v2) / max(rain_brier_v1, 1e-6)
    rain_f1_gain = rain_f1_v2 - rain_f1_v1
    cond_f1_gain = cond_f1_v2 - cond_f1_v1

    passed = (
        rain_brier_improvement >= 0.10
        and rain_f1_gain >= 0.05
        and cond_f1_gain >= 0.05
    )

    return {
        "pass": passed,
        "rain_brier_improvement": round(float(rain_brier_improvement), 4),
        "rain_f1_gain": round(float(rain_f1_gain), 4),
        "condition_macro_f1_gain": round(float(cond_f1_gain), 4),
        "temp_mae_delta": 0.0,  # stesso modello temperatura in v1/v2
    }


def evaluate_shadow_window() -> dict:
    global _runtime_force_v1

    now = datetime.now(timezone.utc)
    if not settings.ml_v2_enabled:
        return {
            "checked": False,
            "reason": "v2_disabled",
            "runtime_force_v1": _runtime_force_v1,
            "consecutive_positive_windows": _shadow_state.get("consecutive_positive_windows", 0),
            "rollout_allowed": _can_use_v2_live(),
        }

    if _rain_pipeline is None or _condition_pipeline is None or _rain_pipeline_v2 is None or _condition_pipeline_v2 is None:
        return {
            "checked": False,
            "reason": "models_not_ready",
            "runtime_force_v1": _runtime_force_v1,
            "consecutive_positive_windows": _shadow_state.get("consecutive_positive_windows", 0),
            "rollout_allowed": _can_use_v2_live(),
        }

    db: Session = SessionLocal()
    try:
        window_start = now - timedelta(days=settings.ml_kpi_window_days)
        rows = _prepare_training_rows(
            db,
            window_start=window_start,
            limit=MAX_KPI_EVAL_ROWS,
        )

        if len(rows) < 200:
            return {
                "checked": False,
                "reason": "not_enough_rows",
                "rows": len(rows),
                "runtime_force_v1": _runtime_force_v1,
                "consecutive_positive_windows": _shadow_state.get("consecutive_positive_windows", 0),
                "rollout_allowed": _can_use_v2_live(),
            }

        v1 = _compute_variant_kpis(rows, "v1")
        v2 = _compute_variant_kpis(rows, "v2")
        gate = _kpi_gate(v1, v2)

        if gate.get("pass"):
            _shadow_state["consecutive_positive_windows"] = int(_shadow_state.get("consecutive_positive_windows", 0)) + 1
            if _shadow_state["consecutive_positive_windows"] >= SHADOW_REQUIRED_STREAK:
                _runtime_force_v1 = False
        else:
            _shadow_state["consecutive_positive_windows"] = 0
            if settings.ml_v2_rollout_percent > 0 and not settings.ml_v2_shadow_only:
                _runtime_force_v1 = True

        _shadow_state["last_check_at"] = now.isoformat()
        _shadow_state["last_pass"] = bool(gate.get("pass"))
        _shadow_state["last_details"] = {
            "v1": v1,
            "v2": v2,
            "gate": gate,
        }

        _invalidate_stats_cache()

        return {
            "checked": True,
            "pass": bool(gate.get("pass")),
            "consecutive_positive_windows": _shadow_state["consecutive_positive_windows"],
            "runtime_force_v1": _runtime_force_v1,
            "rollout_allowed": _can_use_v2_live(),
            "gate": gate,
            "rows": len(rows),
        }
    finally:
        db.close()


def train(min_samples: int = 100) -> dict:
    """
    Addestra i modelli sulle previsioni verificate con target_time futuro.
    Promuove ogni modello solo se batte un baseline semplice.
    """
    global _pipeline, _rain_pipeline, _condition_pipeline
    global _rain_pipeline_v2, _condition_pipeline_v2, _rain_platt_v2, _condition_platt_v2
    global _latest_summary, _temperature_feature_variant, _blend_profiles
    global _loaded_model_store_id, _loaded_model_trained_at, _last_model_version_check_at

    db: Session = SessionLocal()
    try:
        window_start = datetime.now(timezone.utc) - timedelta(days=settings.ml_training_window_days)
        rows = _prepare_training_rows(
            db,
            window_start=window_start,
            limit=settings.ml_training_max_rows,
        )
        logger.info(
            "ML training loaded %s verified rows with window_start=%s window_days=%s max_rows=%s",
            len(rows),
            window_start.isoformat(),
            settings.ml_training_window_days,
            settings.ml_training_max_rows,
        )
        if len(rows) < min_samples:
            return {
                "success": False,
                "message": f"Dati insufficienti: {len(rows)} campioni (minimo {min_samples})",
            }

        encoder = _encode_regions(rows)
        temp_result_v1 = _train_temperature_pipeline(rows)
        temp_result_v2 = _train_temperature_pipeline_v2(rows, encoder)
        temp_candidates = [result for result in (temp_result_v2, temp_result_v1) if result.get("success")]
        if not temp_candidates:
            best_temp_result = temp_result_v2 if temp_result_v2.get("mae") is not None else temp_result_v1
            return {
                "success": False,
                "message": best_temp_result["message"],
                "baseline_mae": best_temp_result.get("baseline_mae"),
                "mae": best_temp_result.get("mae"),
            }

        temp_result = min(temp_candidates, key=lambda result: float(result["mae"]))
        pipeline = temp_result["pipeline"]
        temperature_feature_variant = temp_result.get("feature_variant", "v1")

        rain_result = _train_rain_pipeline(rows, encoder)
        condition_result = _train_condition_pipeline(rows, encoder)
        rain_v2_result = _train_rain_pipeline_v2(rows, encoder)
        condition_v2_result = _train_condition_pipeline_v2(rows, encoder)

        rain_pipeline = rain_result["pipeline"] if rain_result.get("success") else None
        condition_pipeline = condition_result["pipeline"] if condition_result.get("success") else None

        rain_pipeline_v2 = rain_v2_result["pipeline"] if rain_v2_result.get("success") else None
        condition_pipeline_v2 = condition_v2_result["pipeline"] if condition_v2_result.get("success") else None
        rain_platt_v2 = rain_v2_result.get("platt") if rain_pipeline_v2 is not None else None
        condition_platt_v2 = condition_v2_result.get("platt") if condition_pipeline_v2 is not None else None

        # Backtest automatico rolling sugli ultimi N giorni prima della promozione v2
        backtest = {
            "pass": False,
            "reason": "v2_not_ready",
        }
        blend_profile_v1 = {bucket: {"ml_weight": limits[0], "samples": 0} for bucket, limits in BLEND_BUCKET_ML_WEIGHT_LIMITS.items()}
        blend_profile_v2 = {bucket: {"ml_weight": limits[0], "samples": 0} for bucket, limits in BLEND_BUCKET_ML_WEIGHT_LIMITS.items()}

        if rain_pipeline is not None and condition_pipeline is not None:
            old_state = {
                "rain_pipeline": _rain_pipeline,
                "condition_pipeline": _condition_pipeline,
                "rain_pipeline_v2": _rain_pipeline_v2,
                "condition_pipeline_v2": _condition_pipeline_v2,
                "rain_platt_v2": _rain_platt_v2,
                "condition_platt_v2": _condition_platt_v2,
            }
            try:
                _rain_pipeline = rain_pipeline
                _condition_pipeline = condition_pipeline
                _rain_pipeline_v2 = rain_pipeline_v2
                _condition_pipeline_v2 = condition_pipeline_v2
                _rain_platt_v2 = rain_platt_v2
                _condition_platt_v2 = condition_platt_v2

                window_start = datetime.now(timezone.utc) - timedelta(days=settings.ml_kpi_window_days)
                backtest_rows = [row for row in rows if row["target_time"] >= window_start][-MAX_KPI_EVAL_ROWS:]
                if len(backtest_rows) >= 200:
                    blend_profile_v1 = _compute_blend_profile(backtest_rows, "v1")
                    if rain_pipeline_v2 is not None and condition_pipeline_v2 is not None:
                        v1 = _compute_variant_kpis(backtest_rows, "v1")
                        v2 = _compute_variant_kpis(backtest_rows, "v2")
                        blend_profile_v2 = _compute_blend_profile(backtest_rows, "v2")
                        backtest = {
                            "rows": len(backtest_rows),
                            "v1": v1,
                            "v2": v2,
                            "gate": _kpi_gate(v1, v2),
                        }
                        backtest["pass"] = bool(backtest["gate"].get("pass"))
                    else:
                        backtest = {
                            "pass": False,
                            "reason": "v2_not_ready",
                            "rows": len(backtest_rows),
                        }
                else:
                    backtest = {
                        "pass": False,
                        "reason": "not_enough_rows",
                        "rows": len(backtest_rows),
                    }
            finally:
                _rain_pipeline = old_state["rain_pipeline"]
                _condition_pipeline = old_state["condition_pipeline"]
                _rain_pipeline_v2 = old_state["rain_pipeline_v2"]
                _condition_pipeline_v2 = old_state["condition_pipeline_v2"]
                _rain_platt_v2 = old_state["rain_platt_v2"]
                _condition_platt_v2 = old_state["condition_platt_v2"]

        if not backtest.get("pass"):
            rain_pipeline_v2 = None
            condition_pipeline_v2 = None
            rain_platt_v2 = None
            condition_platt_v2 = None

        payload = {
            "model_format_version": MODEL_FORMAT_VERSION,
            "sklearn_version": sklearn.__version__,
            "pipeline": pipeline,
            "temperature_feature_variant": temperature_feature_variant,
            "rain_pipeline": rain_pipeline,
            "rain_feature_variant": "v1" if rain_pipeline is not None else None,
            "condition_pipeline": condition_pipeline,
            "condition_feature_variant": "v1" if condition_pipeline is not None else None,
            "rain_pipeline_v2": rain_pipeline_v2,
            "condition_pipeline_v2": condition_pipeline_v2,
            "rain_platt_v2": rain_platt_v2,
            "condition_platt_v2": condition_platt_v2,
            "blend_profiles": {
                "v1": blend_profile_v1,
                "v2": blend_profile_v2,
            },
            "le": encoder,
            "regions": _known_regions,
            "baseline_mae": temp_result["baseline_mae"],
            "rain_accuracy": rain_result.get("accuracy"),
            "rain_baseline_accuracy": rain_result.get("baseline_accuracy"),
            "condition_accuracy": condition_result.get("accuracy"),
            "condition_baseline_accuracy": condition_result.get("baseline_accuracy"),
            "rain_brier_v2": rain_v2_result.get("brier"),
            "condition_macro_f1_v2": condition_v2_result.get("macro_f1"),
        }
        model_data = _encode_model_payload(payload)

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
        _rain_pipeline_v2 = rain_pipeline_v2
        _condition_pipeline_v2 = condition_pipeline_v2
        _rain_platt_v2 = rain_platt_v2
        _condition_platt_v2 = condition_platt_v2
        _temperature_feature_variant = temperature_feature_variant
        _blend_profiles = {
            "v1": blend_profile_v1,
            "v2": blend_profile_v2,
        }
        _loaded_model_store_id = int(record.id)
        _loaded_model_trained_at = record.trained_at
        _last_model_version_check_at = datetime.now(timezone.utc)

        _latest_summary = {
            "model_ready": temperature_feature_variant in {"v1", "v2"},
            "rain_model_ready": rain_pipeline is not None,
            "condition_model_ready": condition_pipeline is not None,
            "rain_model_v2_ready": rain_pipeline_v2 is not None,
            "condition_model_v2_ready": condition_pipeline_v2 is not None,
            "model_mae": temp_result["mae"],
            "baseline_mae": temp_result["baseline_mae"],
            "rain_accuracy": rain_result.get("accuracy"),
            "rain_baseline_accuracy": rain_result.get("baseline_accuracy"),
            "condition_accuracy": condition_result.get("accuracy"),
            "condition_baseline_accuracy": condition_result.get("baseline_accuracy"),
            "rain_brier_v2": rain_v2_result.get("brier"),
            "condition_macro_f1_v2": condition_v2_result.get("macro_f1"),
            "temperature_model_variant": temperature_feature_variant,
            "model_format_version": MODEL_FORMAT_VERSION,
            "model_sklearn_version": sklearn.__version__,
            "model_load_warning": None,
            "model_samples": temp_result["n_samples"],
            "model_trained_at": record.trained_at.isoformat(),
        }
        _invalidate_stats_cache()

        return {
            "success": True,
            "mae": temp_result["mae"],
            "baseline_mae": temp_result["baseline_mae"],
            "n_samples": temp_result["n_samples"],
            "temperature_model_variant": temperature_feature_variant,
            "trained_at": record.trained_at.isoformat(),
            "rain_accuracy": rain_result.get("accuracy"),
            "rain_baseline_accuracy": rain_result.get("baseline_accuracy"),
            "rain_model_ready": rain_pipeline is not None,
            "rain_message": None if rain_pipeline is not None else rain_result.get("message"),
            "condition_accuracy": condition_result.get("accuracy"),
            "condition_baseline_accuracy": condition_result.get("baseline_accuracy"),
            "condition_model_ready": condition_pipeline is not None,
            "condition_message": None if condition_pipeline is not None else condition_result.get("message"),
            "rain_model_v2_ready": rain_pipeline_v2 is not None,
            "condition_model_v2_ready": condition_pipeline_v2 is not None,
            "model_format_version": MODEL_FORMAT_VERSION,
            "model_sklearn_version": sklearn.__version__,
            "v2_backtest": backtest,
        }
    except Exception as e:
        print(f"[ERROR] Errore training ML: {e}")
        return {"success": False, "message": str(e)}
    finally:
        db.close()


def load_latest_model() -> bool:
    """Carica in memoria l'ultimo modello promosso."""
    global _pipeline, _rain_pipeline, _condition_pipeline
    global _rain_pipeline_v2, _condition_pipeline_v2, _rain_platt_v2, _condition_platt_v2
    global _label_encoder, _known_regions, _latest_summary, _temperature_feature_variant, _blend_profiles
    global _loaded_model_store_id, _loaded_model_trained_at, _last_model_version_check_at

    db: Session = SessionLocal()
    _invalidate_stats_cache()
    try:
        record = db.query(MlModelStore).order_by(MlModelStore.trained_at.desc()).first()
        if not record or not record.model_bytes:
            print("[INFO]  Nessun modello ML salvato nel DB")
            _reset_loaded_model_state()
            _loaded_model_store_id = None
            _loaded_model_trained_at = None
            _last_model_version_check_at = datetime.now(timezone.utc)
            _latest_summary = _empty_model_summary()
            return False

        metadata, payload_bytes = _decode_model_payload(record.model_bytes)
        stored_sklearn_version = None if metadata is None else metadata.get("sklearn_version")
        stored_format_version = 1 if metadata is None else int(metadata.get("model_format_version", 1))
        if stored_format_version != MODEL_FORMAT_VERSION or stored_sklearn_version != sklearn.__version__:
            _reset_loaded_model_state()
            _loaded_model_store_id = int(record.id)
            _loaded_model_trained_at = record.trained_at
            _last_model_version_check_at = datetime.now(timezone.utc)
            warning = (
                f"incompatible_model_pickle: stored_format={stored_format_version} "
                f"runtime_format={MODEL_FORMAT_VERSION} stored_sklearn={stored_sklearn_version or 'unknown'} "
                f"runtime_sklearn={sklearn.__version__}"
            )
            _latest_summary = {
                **_empty_model_summary(),
                "model_ready": False,
                "rain_model_ready": False,
                "condition_model_ready": False,
                "rain_model_v2_ready": False,
                "condition_model_v2_ready": False,
                "model_mae": record.mae,
                "baseline_mae": None,
                "rain_accuracy": None,
                "rain_baseline_accuracy": None,
                "condition_accuracy": None,
                "condition_baseline_accuracy": None,
                "rain_brier_v2": None,
                "condition_macro_f1_v2": None,
                "temperature_model_variant": None,
                "model_format_version": stored_format_version,
                "model_sklearn_version": stored_sklearn_version,
                "model_load_warning": warning,
                "model_samples": record.n_samples,
                "model_trained_at": record.trained_at.isoformat(),
            }
            print(f"[WARN]  Modello ML incompatibile con runtime corrente: {warning}")
            return False

        data = pickle.loads(payload_bytes)
        _pipeline = data["pipeline"]
        _rain_pipeline = data.get("rain_pipeline")
        _condition_pipeline = data.get("condition_pipeline")
        _rain_pipeline_v2 = data.get("rain_pipeline_v2")
        _condition_pipeline_v2 = data.get("condition_pipeline_v2")
        _rain_platt_v2 = data.get("rain_platt_v2")
        _condition_platt_v2 = data.get("condition_platt_v2")
        _temperature_feature_variant = _infer_temperature_feature_variant_from_pipeline(
            data.get("temperature_feature_variant", "v1")
        )
        _blend_profiles = data.get("blend_profiles") or {"v1": {}, "v2": {}}
        _label_encoder = data["le"]
        _known_regions = data.get("regions", [])
        _loaded_model_store_id = int(record.id)
        _loaded_model_trained_at = record.trained_at
        _last_model_version_check_at = datetime.now(timezone.utc)
        rain_feature_variant = data.get("rain_feature_variant") or _infer_rain_feature_variant_from_pipeline()
        condition_feature_variant = data.get("condition_feature_variant") or _infer_condition_feature_variant_from_pipeline()

        _latest_summary = {
            "model_ready": _pipeline is not None and _temperature_feature_variant in {"v1", "v2"},
            "rain_model_ready": _rain_pipeline is not None and rain_feature_variant in {"legacy", "v1"},
            "condition_model_ready": _condition_pipeline is not None and condition_feature_variant in {"legacy", "v1"},
            "rain_model_v2_ready": _rain_pipeline_v2 is not None,
            "condition_model_v2_ready": _condition_pipeline_v2 is not None,
            "model_mae": record.mae,
            "baseline_mae": data.get("baseline_mae"),
            "rain_accuracy": data.get("rain_accuracy"),
            "rain_baseline_accuracy": data.get("rain_baseline_accuracy"),
            "condition_accuracy": data.get("condition_accuracy"),
            "condition_baseline_accuracy": data.get("condition_baseline_accuracy"),
            "rain_brier_v2": data.get("rain_brier_v2"),
            "condition_macro_f1_v2": data.get("condition_macro_f1_v2"),
            "temperature_model_variant": _infer_temperature_feature_variant_from_pipeline(_temperature_feature_variant),
            "model_format_version": data.get("model_format_version", 1),
            "model_sklearn_version": stored_sklearn_version,
            "model_load_warning": None,
            "model_samples": record.n_samples,
            "model_trained_at": record.trained_at.isoformat(),
        }
        print(f"[OK] Modello ML caricato (addestrato: {record.trained_at}, MAE: {record.mae})")
        return True
    except Exception as e:
        _reset_loaded_model_state()
        _loaded_model_store_id = int(record.id) if 'record' in locals() and record else None
        _loaded_model_trained_at = record.trained_at if 'record' in locals() and record else None
        _last_model_version_check_at = datetime.now(timezone.utc)
        _latest_summary = {
            **_empty_model_summary(),
            "model_load_warning": f"model_load_failed:{e}",
        }
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
    lon: float | None = None,
    cloud_cover: float = 50.0,
    lead_hours: int = 0,
    forecast_precipitation: float | None = None,
    forecast_wind_speed: float | None = None,
    forecast_wind_direction: float | None = None,
    forecast_weather_code: int | None = None,
) -> dict:
    """Predice la correzione da applicare alla temperatura prevista."""
    _ensure_latest_model_loaded()
    if _pipeline is None:
        return {"correction": 0.0, "corrected_temp": temp, "model_ready": False, "model_variant": "provider"}

    try:
        features, active_variant = _build_temperature_features_for_inference(
            forecast_temp=temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            lon=lon,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            forecast_precipitation=forecast_precipitation,
            forecast_wind_speed=forecast_wind_speed,
            forecast_wind_direction=forecast_wind_direction,
            forecast_weather_code=forecast_weather_code,
        )
        correction = float(_pipeline.predict(features)[0])
        correction = max(-5.0, min(5.0, correction))
        # I vecchi modelli legacy possono degradare su correzioni sempre saturate: meglio fallback che insight fuorviante.
        if active_variant == "legacy" and abs(correction) >= 4.95:
            return {
                "correction": 0.0,
                "corrected_temp": temp,
                "model_ready": False,
                "model_variant": "provider",
                "message": "legacy_temperature_guardrail",
            }
        confidence = _empirical_confidence(_confidence_from_score(abs(correction) / 1.5), lead_hours)

        return {
            "correction": round(correction, 2),
            "corrected_temp": round(temp + correction, 1),
            "model_ready": True,
            "confidence": confidence,
            "model_variant": active_variant,
        }
    except Exception as e:
        return {
            "correction": 0.0,
            "corrected_temp": temp,
            "model_ready": False,
            "error": str(e),
            "model_variant": "provider",
        }


def _resolve_requested_variant(force_variant: str | None, city_name: str | None) -> str:
    if force_variant in {"v1", "v2", "provider"}:
        return force_variant
    return _resolve_live_model_variant(city_name)


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
    lon: float | None = None,
    forecast_precipitation: float | None = None,
    forecast_wind_speed: float | None = None,
    forecast_wind_direction: float | None = None,
    forecast_weather_code: int | None = None,
    city_name: str | None = None,
    force_variant: str | None = None,
) -> dict:
    """Predice la probabilità di pioggia per una previsione futura."""
    _ensure_latest_model_loaded()
    requested_variant = _resolve_requested_variant(force_variant, city_name)

    if requested_variant == "v2" and _rain_pipeline_v2 is not None:
        try:
            features = _build_rain_features_v2(
                forecast_temp=forecast_temp,
                humidity=humidity,
                hour=hour,
                month=month,
                lat=lat,
                lon=lon,
                region=region,
                cloud_cover=cloud_cover,
                lead_hours=lead_hours,
                forecast_precipitation=forecast_precipitation,
                forecast_wind_speed=forecast_wind_speed,
                forecast_wind_direction=forecast_wind_direction,
                forecast_weather_code=forecast_weather_code,
            )
            raw_prob = float(_rain_pipeline_v2.predict_proba(features)[0][1])
            rain_prob = float(_apply_platt(raw_prob, _rain_platt_v2))
            confidence = _empirical_confidence(_confidence_from_score(abs(rain_prob - 0.5) * 2), lead_hours)

            return {
                "rain_probability": round(rain_prob, 3),
                "will_rain": rain_prob >= 0.5,
                "model_ready": True,
                "confidence": confidence,
                "model_variant": "v2",
            }
        except Exception as e:
            return {
                "model_ready": False,
                "error": str(e),
                "model_variant": "provider",
            }

    if _rain_pipeline is None:
        return {
            "model_ready": False,
            "message": "Modello pioggia non ancora disponibile",
            "model_variant": "provider",
        }

    try:
        features, active_variant = _build_rain_features_for_inference(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            lon=lon,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            forecast_precipitation=forecast_precipitation,
            forecast_wind_speed=forecast_wind_speed,
            forecast_wind_direction=forecast_wind_direction,
            forecast_weather_code=forecast_weather_code,
        )
        proba = _rain_pipeline.predict_proba(features)[0]
        rain_prob = float(proba[1])
        confidence = _empirical_confidence(_confidence_from_score(abs(rain_prob - 0.5) * 2), lead_hours)

        return {
            "rain_probability": round(rain_prob, 3),
            "will_rain": rain_prob >= 0.5,
            "model_ready": True,
            "confidence": confidence,
            "model_variant": active_variant,
        }
    except Exception as e:
        return {
            "model_ready": False,
            "error": str(e),
            "model_variant": "provider",
        }


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
    lon: float | None = None,
    city_name: str | None = None,
    force_variant: str | None = None,
) -> dict:
    _ensure_latest_model_loaded()
    provider_condition = _condition_from_inputs(
        weather_code=forecast_weather_code,
        cloud_cover=cloud_cover,
        precipitation=forecast_precipitation,
    )

    requested_variant = _resolve_requested_variant(force_variant, city_name)

    if requested_variant == "v2" and _condition_pipeline_v2 is not None:
        try:
            features = _build_condition_features_v2(
                forecast_temp=forecast_temp,
                humidity=humidity,
                hour=hour,
                month=month,
                lat=lat,
                lon=lon,
                region=region,
                cloud_cover=cloud_cover,
                lead_hours=lead_hours,
                forecast_precipitation=forecast_precipitation,
                forecast_wind_speed=forecast_wind_speed,
                forecast_wind_direction=forecast_wind_direction,
                forecast_weather_code=forecast_weather_code,
            )
            raw = _condition_pipeline_v2.predict_proba(features)[0]
            probabilities = _apply_multiclass_platt(raw, _condition_platt_v2)
            predicted_code = int(np.argmax(probabilities))
            top_probability = float(np.max(probabilities))
            predicted_label = CONDITION_LABELS[predicted_code]

            return {
                "model_ready": True,
                "expected_condition": predicted_label,
                "display_condition": _condition_display(predicted_label),
                "confidence": _empirical_confidence(_confidence_from_score(top_probability), lead_hours),
                "source": "ml",
                "probability": round(top_probability, 3),
                "provider_condition": provider_condition,
                "model_variant": "v2",
            }
        except Exception as e:
            return {
                "model_ready": False,
                "expected_condition": provider_condition,
                "display_condition": _condition_display(provider_condition),
                "confidence": "media",
                "source": "provider",
                "error": str(e),
                "model_variant": "provider",
            }

    if _condition_pipeline is None:
        return {
            "model_ready": False,
            "expected_condition": provider_condition,
            "display_condition": _condition_display(provider_condition),
            "confidence": "media",
            "source": "provider",
            "model_variant": "provider",
        }

    try:
        features, active_variant = _build_condition_features_for_inference(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            lon=lon,
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
            "confidence": _empirical_confidence(_confidence_from_score(top_probability), lead_hours),
            "source": "ml",
            "probability": round(top_probability, 3),
            "provider_condition": provider_condition,
            "model_variant": active_variant,
        }
    except Exception as e:
        return {
            "model_ready": False,
            "expected_condition": provider_condition,
            "display_condition": _condition_display(provider_condition),
            "confidence": "media",
            "source": "provider",
            "error": str(e),
            "model_variant": "provider",
        }


def build_daily_insight(
    *,
    day: dict,
    lat: float,
    region: str,
    lead_hours: int,
    lon: float | None = None,
    city_name: str | None = None,
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

    support = _horizon_support(lead_hours)
    requested_variant = _resolve_live_model_variant(city_name)

    correction = predict_correction(
        temp=forecast_temp,
        humidity=_safe_float(day.get("humidity"), 55.0),
        hour=hour,
        month=day_date.month,
        lat=lat,
        lon=lon,
        region=region,
        cloud_cover=cloud_cover,
        lead_hours=lead_hours,
        forecast_precipitation=forecast_precipitation,
        forecast_wind_speed=wind_speed,
        forecast_wind_direction=wind_direction,
        forecast_weather_code=weather_code,
    )

    if support == "provider_only":
        condition_label = _condition_from_inputs(
            weather_code=weather_code,
            cloud_cover=cloud_cover,
            precipitation=forecast_precipitation,
        )
        blended_rain = round(forecast_pop, 3)
        model_variant = "provider"
        condition = {
            "display_condition": _condition_display(condition_label),
            "confidence": "media",
            "source": "provider",
            "expected_condition": condition_label,
        }
        rain = {
            "model_ready": False,
            "confidence": "provider",
        }
        blend_weight = 0.0
    else:
        rain = predict_rain_probability(
            forecast_temp=forecast_temp,
            humidity=_safe_float(day.get("humidity"), 55.0),
            hour=hour,
            month=day_date.month,
            lat=lat,
            lon=lon,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            forecast_precipitation=forecast_precipitation,
            forecast_wind_speed=wind_speed,
            forecast_wind_direction=wind_direction,
            forecast_weather_code=weather_code,
            city_name=city_name,
            force_variant=requested_variant,
        )
        condition = predict_condition_outlook(
            forecast_temp=forecast_temp,
            humidity=_safe_float(day.get("humidity"), 55.0),
            hour=hour,
            month=day_date.month,
            lat=lat,
            lon=lon,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            forecast_precipitation=forecast_precipitation,
            forecast_wind_speed=wind_speed,
            forecast_wind_direction=wind_direction,
            forecast_weather_code=weather_code,
            city_name=city_name,
            force_variant=requested_variant,
        )

        blended_rain = forecast_pop
        blend_weight = 0.0
        if rain.get("model_ready"):
            blend_weight = _rain_blend_weight(lead_hours, rain.get("model_variant", requested_variant))
            provider_weight = 1.0 - blend_weight
            blended_rain = round((forecast_pop * provider_weight) + (rain["rain_probability"] * blend_weight), 3)

        model_variant = condition.get("model_variant") or rain.get("model_variant") or requested_variant
        if not (rain.get("model_ready") or condition.get("model_ready")):
            model_variant = "provider"

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
        "rain_blend_weight": round(float(blend_weight), 3),
        "rain_confidence": rain.get("confidence", "media") if rain.get("model_ready") else "provider",
        "temperature_delta": round(delta, 2),
        "adjusted_temp_range": {
            "min": adjusted_min,
            "max": adjusted_max,
        },
        "summary": _daily_summary(expected_condition, blended_rain, wind_speed, confidence),
        "badge": _daily_badge(expected_condition, blended_rain, wind_speed),
        "horizon_support": support,
        "model_variant": model_variant,
    }


def get_public_summary() -> dict:
    _ensure_latest_model_loaded()
    return {
        **dict(_latest_summary),
        "shadow": dict(_shadow_state),
        "runtime_force_v1": _runtime_force_v1,
        "blend_profiles": copy.deepcopy(_blend_profiles),
    }


def _recent_rows_for_kpis(db: Session, window_start: datetime) -> list[dict]:
    return _prepare_training_rows(
        db,
        window_start=window_start,
        limit=MAX_KPI_EVAL_ROWS,
    )


def get_stats() -> dict:
    """Statistiche aggregate sul modello e sul dataset."""
    global _stats_cache

    cached = _get_cached_stats_value(allow_stale=False)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)

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

        window_start = now - timedelta(days=settings.ml_kpi_window_days)
        temp_mae_window_rows = (
            db.query(
                MlPrediction.lead_hours,
                func.count(MlPrediction.id),
                func.avg(func.abs(MlPrediction.error)),
            )
            .filter(
                MlPrediction.verified.is_(True),
                MlPrediction.error.isnot(None),
                MlPrediction.verified_at.isnot(None),
                MlPrediction.verified_at >= window_start,
            )
            .group_by(MlPrediction.lead_hours)
            .order_by(MlPrediction.lead_hours)
            .all()
        )

        temp_mae_14d_by_lead = [
            {
                "lead_hours": int(lead_hours or 0),
                "samples": int(samples or 0),
                "mae": round(float(mae), 3) if mae is not None else None,
            }
            for lead_hours, samples, mae in temp_mae_window_rows
        ]

        recent_rows = _recent_rows_for_kpis(db, window_start)
        v1_kpis = _compute_variant_kpis(recent_rows, "v1") if recent_rows else {}
        v2_kpis = _compute_variant_kpis(recent_rows, "v2") if recent_rows else {}
        temp_bucket_metrics: dict[str, dict[str, float | int]] = {}
        for row in recent_rows:
            bucket = _lead_bucket_name(row.get("lead_hours"))
            entry = temp_bucket_metrics.setdefault(bucket, {"samples": 0, "total_abs_error": 0.0})
            entry["samples"] += 1
            entry["total_abs_error"] += abs(float(row.get("error") or 0.0))

        temp_mae_14d_by_bucket = [
            {
                "bucket": bucket,
                "samples": int(temp_bucket_metrics[bucket]["samples"]),
                "mae": round(
                    float(temp_bucket_metrics[bucket]["total_abs_error"] / max(temp_bucket_metrics[bucket]["samples"], 1)),
                    3,
                ),
            }
            for bucket in LEAD_BUCKETS
            if bucket in temp_bucket_metrics
        ]
        rain_v1_by_bucket = _compute_rain_kpis_by_bucket(recent_rows, "v1") if recent_rows else {}
        rain_v2_by_bucket = _compute_rain_kpis_by_bucket(recent_rows, "v2") if recent_rows else {}

        serving_variant = _global_model_variant_for_stats()
        serving_kpis = v2_kpis if serving_variant == "v2" else v1_kpis
        serving_rain_by_bucket = rain_v2_by_bucket if serving_variant == "v2" else rain_v1_by_bucket

        stats = {
            "total_predictions": int(total),
            "verified_predictions": int(verified),
            "avg_error_celsius": round(float(avg_error), 3) if avg_error is not None else None,
            "lead_time_error": [
                {"lead_hours": lead_hours or 0, "avg_abs_error": round(float(value), 3)}
                for lead_hours, value in lead_error_rows
            ],
            "rain_brier_14d": round(float(serving_kpis.get("rain_brier")), 4)
            if serving_kpis.get("rain_brier") is not None else None,
            "rain_f1_14d": round(float(serving_kpis.get("rain_f1")), 4)
            if serving_kpis.get("rain_f1") is not None else None,
            "condition_macro_f1_14d": round(float(serving_kpis.get("condition_macro_f1")), 4)
            if serving_kpis.get("condition_macro_f1") is not None else None,
            "temp_mae_14d_by_lead": temp_mae_14d_by_lead,
            "temp_mae_14d_by_bucket": temp_mae_14d_by_bucket,
            "rain_14d_by_bucket": serving_rain_by_bucket,
            "model_variant": serving_variant,
            "kpi_window_days": settings.ml_kpi_window_days,
            "v1_kpis": v1_kpis,
            "v2_kpis": v2_kpis,
            "rain_v1_by_bucket": rain_v1_by_bucket,
            "rain_v2_by_bucket": rain_v2_by_bucket,
            **get_public_summary(),
        }
        _stats_cache = {
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=STATS_CACHE_TTL_SECONDS),
            "value": stats,
        }
        return copy.deepcopy(stats)
    finally:
        db.close()
