"""Unit test mirati per ML v2 (feature engineering, calibrazione, horizon blending)."""
import importlib

import numpy as np

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ml_model = importlib.import_module("ml_model")


def test_rain_feature_vector_v2_shape_and_missing_flags():
    features = ml_model._build_rain_features_v2(
        forecast_temp=18.0,
        humidity=None,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=None,
        lead_hours=3,
        forecast_precipitation=None,
        forecast_wind_speed=None,
        forecast_wind_direction=180.0,
        forecast_weather_code=None,
    )

    assert features.shape == (1, 20)
    assert features[0, -5:].tolist() == [1.0, 1.0, 1.0, 1.0, 1.0]


def test_platt_scaler_produces_bounded_probabilities():
    raw_probs = np.array([0.1, 0.2, 0.4, 0.55, 0.6, 0.8, 0.9, 0.3, 0.7, 0.85] * 6)
    y = np.array([0, 0, 0, 1, 1, 1, 1, 0, 1, 1] * 6)

    params = ml_model._fit_platt_scaler(raw_probs, y)
    assert params is not None

    calibrated = [ml_model._apply_platt(float(prob), params) for prob in raw_probs]
    assert all(0.0 < prob < 1.0 for prob in calibrated)


def test_daily_insight_applies_horizon_support_rules(monkeypatch):
    monkeypatch.setattr(
        ml_model,
        "predict_correction",
        lambda **kwargs: {"model_ready": True, "correction": 0.0, "corrected_temp": kwargs["temp"], "confidence": "alta"},
    )
    monkeypatch.setattr(
        ml_model,
        "predict_rain_probability",
        lambda **kwargs: {
            "model_ready": True,
            "rain_probability": 0.8,
            "will_rain": True,
            "confidence": "alta",
            "model_variant": "v2",
        },
    )
    monkeypatch.setattr(
        ml_model,
        "predict_condition_outlook",
        lambda **kwargs: {
            "model_ready": True,
            "expected_condition": "pioggia",
            "display_condition": "Pioggia probabile",
            "confidence": "alta",
            "source": "ml",
            "probability": 0.8,
            "model_variant": "v2",
        },
    )
    monkeypatch.setattr(ml_model, "_resolve_live_model_variant", lambda city_name=None: "v2")

    day = {
        "dt": "2026-04-11",
        "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
        "humidity": 70,
        "cloud_cover": 50,
        "wind_speed": 8,
        "wind_deg": 180,
        "pop": 0.2,
        "weather_code": 1,
    }

    full = ml_model.build_daily_insight(day=day, lat=41.9, lon=12.5, region="Lazio", lead_hours=24, city_name="Roma")
    limited = ml_model.build_daily_insight(day=day, lat=41.9, lon=12.5, region="Lazio", lead_hours=72, city_name="Roma")
    provider_only = ml_model.build_daily_insight(
        day=day,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        lead_hours=120,
        city_name="Roma",
    )

    assert full["horizon_support"] == "full"
    assert full["model_variant"] == "v2"
    assert full["rain_probability"] == 0.5  # 50% provider + 50% ML

    assert limited["horizon_support"] == "limited"
    assert limited["model_variant"] == "v2"
    assert limited["rain_probability"] == 0.35  # 75% provider + 25% ML

    assert provider_only["horizon_support"] == "provider_only"
    assert provider_only["model_variant"] == "provider"
    assert provider_only["rain_probability"] == 0.2

