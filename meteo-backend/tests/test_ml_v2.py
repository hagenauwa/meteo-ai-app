"""Unit test mirati per ML v2 (feature engineering, calibrazione, horizon blending)."""
import importlib
from types import SimpleNamespace

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

    assert features.shape == (1, 26)
    assert features[0, -5:].tolist() == [1.0, 1.0, 1.0, 1.0, 1.0]


def test_temperature_feature_vector_v2_includes_lead_bucket_flags():
    features = ml_model._build_temperature_features_v2(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert features.shape == (1, 26)
    assert features[0, 15:21].tolist() == [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def test_predict_correction_supports_legacy_temperature_models(monkeypatch):
    class FakePipeline:
        def __init__(self):
            self.last_shape = None
            self.n_features_in_ = 6

        def predict(self, features):
            self.last_shape = features.shape
            return np.array([1.2])

    fake_pipeline = FakePipeline()
    monkeypatch.setattr(ml_model, "_pipeline", fake_pipeline)
    monkeypatch.setattr(ml_model, "_temperature_feature_variant", "v1")

    result = ml_model.predict_correction(
        temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert fake_pipeline.last_shape == (1, 6)
    assert result["model_ready"] is True
    assert result["model_variant"] == "legacy"
    assert result["corrected_temp"] == 19.2


def test_predict_correction_disables_saturated_legacy_models(monkeypatch):
    class FakePipeline:
        n_features_in_ = 6

        def predict(self, features):
            return np.array([9.0])

    monkeypatch.setattr(ml_model, "_pipeline", FakePipeline())
    monkeypatch.setattr(ml_model, "_temperature_feature_variant", "v1")
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", None)

    result = ml_model.predict_correction(
        temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert result["model_ready"] is False
    assert result["model_variant"] == "provider"


def test_predict_rain_probability_supports_legacy_models(monkeypatch):
    class FakePipeline:
        def __init__(self):
            self.last_shape = None
            self.n_features_in_ = 6

        def predict_proba(self, features):
            self.last_shape = features.shape
            return np.array([[0.8, 0.2]])

    fake_pipeline = FakePipeline()
    monkeypatch.setattr(ml_model, "_rain_pipeline", fake_pipeline)
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", None)

    result = ml_model.predict_rain_probability(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert fake_pipeline.last_shape == (1, 6)
    assert result["model_ready"] is True
    assert result["model_variant"] == "legacy"
    assert result["rain_probability"] == 0.2


def test_predict_condition_outlook_supports_legacy_models(monkeypatch):
    class FakePipeline:
        def __init__(self):
            self.last_shape = None
            self.n_features_in_ = 11

        def predict_proba(self, features):
            self.last_shape = features.shape
            return np.array([[0.1, 0.7, 0.1, 0.1]])

        def predict(self, features):
            return np.array([1])

    fake_pipeline = FakePipeline()
    monkeypatch.setattr(ml_model, "_condition_pipeline", fake_pipeline)
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", None)

    result = ml_model.predict_condition_outlook(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert fake_pipeline.last_shape == (1, 11)
    assert result["model_ready"] is True
    assert result["model_variant"] == "legacy"
    assert result["expected_condition"] == "parzialmente nuvoloso"


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
    monkeypatch.setattr(
        ml_model,
        "_blend_profiles",
        {
            "v1": {},
            "v2": {
                "intraday": {"ml_weight": 0.5},
                "day2_3": {"ml_weight": 0.25},
                "day8_plus": {"ml_weight": 0.0},
            },
        },
    )

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
        lead_hours=192,
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


def test_train_uses_bounded_training_rows(monkeypatch):
    calls = []

    class FakeSession:
        def close(self):
            return None

    monkeypatch.setattr(ml_model, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        ml_model,
        "settings",
        SimpleNamespace(
            ml_training_window_days=7,
            ml_training_max_rows=1234,
        ),
    )

    def fake_prepare_training_rows(db, *, window_start=None, limit=None):
        calls.append((window_start, limit))
        return []

    monkeypatch.setattr(ml_model, "_prepare_training_rows", fake_prepare_training_rows)

    result = ml_model.train(min_samples=10)

    assert result["success"] is False
    assert "Dati insufficienti" in result["message"]
    assert len(calls) == 1
    window_start, limit = calls[0]
    assert limit == 1234
    assert window_start is not None
    assert window_start.tzinfo is not None
