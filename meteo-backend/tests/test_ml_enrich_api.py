"""Test endpoint ML enrich per forecast frontend."""

import importlib

from fastapi.testclient import TestClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from database import get_db
from tests.ml_test_utils import (
    MODEL_STATUS_MISSING_ROW,
    WARNING_CITY_UNRESOLVED,
    assert_warning_contract,
    fake_city,
    install_fake_db_override,
)

# Provincia in copertura ML (vedi config.ml_training_allowed_provinces).
_COVERED = {"province": "Massa-Carrara", "region": "Toscana"}


client = TestClient(app)
ml_module = importlib.import_module("routers.ml")


def test_ml_enrich_returns_current_and_daily_blocks(monkeypatch):
    lead_hours_calls = []

    monkeypatch.setattr(
        ml_module.ml_model,
        "predict_correction",
        lambda **kwargs: {
            "model_ready": True,
            "correction": 0.3,
            "corrected_temp": 15.4,
            "confidence": "media",
        },
    )
    monkeypatch.setattr(
        ml_module.ml_model,
        "predict_rain_probability",
        lambda **kwargs: {
            "model_ready": True,
            "rain_probability": 0.2,
            "will_rain": False,
            "confidence": "media",
        },
    )

    def fake_daily_insight(**kwargs):
        lead_hours_calls.append(kwargs["lead_hours"])
        return {
            "expected_condition": "sereno",
            "display_condition": "Cielo sereno",
            "condition_confidence": "alta",
            "condition_source": "ml",
            "rain_probability": 0.2,
            "rain_confidence": "media",
            "temperature_delta": 0.3,
            "adjusted_temp_range": {"min": 10.3, "max": 20.3},
            "summary": "Scenario stabile",
            "badge": "Scenario stabile",
            "horizon_support": "full",
            "model_variant": "v1",
        }

    monkeypatch.setattr(ml_module.ml_model, "build_daily_insight", fake_daily_insight)
    monkeypatch.setattr(ml_module.ml_model, "get_public_summary", lambda: {"model_ready": True})

    install_fake_db_override(app, get_db, [fake_city(name="Massa", **_COVERED)])
    try:
        response = client.post(
            "/api/ml/enrich",
            json={
                "city": {
                    "name": "Massa",
                    "lat": 41.9,
                    "lon": 12.5,
                    "region": "Toscana",
                    "province": "Massa-Carrara",
                },
                "current": {
                    "temp": 15.1,
                    "humidity": 86,
                    "clouds": 42,
                },
                "daily": [
                    {
                        "dt": "2026-04-10",
                        "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
                        "humidity": 60,
                        "cloud_cover": 40,
                        "wind_speed": 12,
                        "wind_deg": 180,
                        "pop": 0.2,
                        "weather_code": 1,
                    },
                    {
                        "dt": "2026-04-11",
                        "temp": {"min": 11.0, "max": 21.0, "day": 16.0},
                        "humidity": 58,
                        "cloud_cover": 35,
                        "wind_speed": 10,
                        "wind_deg": 170,
                        "pop": 0.1,
                        "weather_code": 2,
                    },
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ml"]["correction"]["model_ready"] is True
    assert payload["ml"]["summary"]["model_ready"] is True
    assert len(payload["daily_ml"]) == 2
    assert payload["daily_ml"][0]["badge"] == "Scenario stabile"
    assert payload["daily_ml"][0]["horizon_support"] == "full"
    assert payload["daily_ml"][0]["model_variant"] == "v1"
    assert len(lead_hours_calls) == 2
    assert all(isinstance(h, int) and h >= 0 for h in lead_hours_calls)


def test_ml_enrich_keeps_200_for_known_city_when_models_are_not_ready(monkeypatch):
    monkeypatch.setattr(
        ml_module.ml_model,
        "predict_correction",
        lambda **kwargs: {
            "model_ready": False,
            "message": "Modello temperatura non ancora disponibile",
            "model_variant": "provider",
        },
    )
    monkeypatch.setattr(
        ml_module.ml_model,
        "predict_rain_probability",
        lambda **kwargs: {
            "model_ready": False,
            "message": "Modello pioggia non ancora disponibile",
            "model_variant": "provider",
        },
    )
    monkeypatch.setattr(
        ml_module.ml_model,
        "build_daily_insight",
        lambda **kwargs: {
            "expected_condition": "sereno",
            "display_condition": "Cielo sereno",
            "condition_confidence": "media",
            "condition_source": "provider",
            "rain_probability": 0.1,
            "rain_confidence": "media",
            "temperature_delta": 0.0,
            "adjusted_temp_range": {"min": 10.0, "max": 20.0},
            "summary": "Fallback provider disponibile",
            "badge": "Fallback provider",
            "horizon_support": "full",
            "model_variant": "provider",
        },
    )
    monkeypatch.setattr(ml_module.ml_model, "get_public_summary", lambda: {"model_ready": False})

    install_fake_db_override(app, get_db, [fake_city(name="Massa", **_COVERED)])
    try:
        response = client.post(
            "/api/ml/enrich",
            json={
                "city": {
                    "name": "Massa",
                    "lat": 41.9,
                    "lon": 12.5,
                    "region": "Toscana",
                    "province": "Massa-Carrara",
                },
                "current": {
                    "temp": 15.1,
                    "humidity": 86,
                    "clouds": 42,
                },
                "daily": [
                    {
                        "dt": "2026-04-10",
                        "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
                        "humidity": 60,
                        "cloud_cover": 40,
                        "wind_speed": 12,
                        "wind_deg": 180,
                        "pop": 0.2,
                        "weather_code": 1,
                    }
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ml"]["correction"]["model_ready"] is False
    assert payload["ml"]["correction"]["model_variant"] == "provider"
    assert payload["ml"]["rain_prediction"]["model_ready"] is False
    assert payload["ml"]["summary"]["model_ready"] is False
    assert len(payload["daily_ml"]) == 1
    assert payload["daily_ml"][0]["badge"] == "Fallback provider"
    assert payload["daily_ml"][0]["model_variant"] == "provider"


def test_ml_enrich_unknown_city_returns_warning_contract(monkeypatch):
    monkeypatch.setattr(
        ml_module.ml_model,
        "get_public_summary",
        lambda: {
            "model_ready": False,
            "model_status": "disabled",
            "model_load_warning": MODEL_STATUS_MISSING_ROW,
        },
    )

    install_fake_db_override(app, get_db, [])
    try:
        response = client.post(
            "/api/ml/enrich",
            json={
                "city": {
                    "name": "Atlantide",
                    "lat": 41.9,
                    "lon": 12.5,
                    "region": "",
                    "province": "RM",
                },
                "current": {
                    "temp": 15.1,
                    "humidity": 86,
                    "clouds": 42,
                },
                "daily": [
                    {
                        "dt": "2026-04-10",
                        "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
                        "humidity": 60,
                        "cloud_cover": 40,
                        "wind_speed": 12,
                        "wind_deg": 180,
                        "pop": 0.2,
                        "weather_code": 1,
                    }
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert_warning_contract(
        payload,
        code=WARNING_CITY_UNRESOLVED,
        reason_substring="unknown city: Atlantide",
    )
    assert payload["ml"]["summary"]["model_status"] == "disabled"
    assert payload["ml"]["summary"]["model_load_warning"] == MODEL_STATUS_MISSING_ROW
    assert payload["daily_ml"] == []


def test_ml_enrich_out_of_area_city_disables_ml(monkeypatch):
    # Serving onesto: una città fuori dalle province coperte (es. Milano) NON deve
    # ricevere predizioni ML estrapolate.
    monkeypatch.setattr(ml_module.ml_model, "get_public_summary", lambda: {"model_ready": True})

    install_fake_db_override(
        app,
        get_db,
        [fake_city(name="Milano", region="Lombardia", province="MI", lat=45.46, lon=9.19)],
    )
    try:
        response = client.post(
            "/api/ml/enrich",
            json={
                "city": {"name": "Milano", "lat": 45.46, "lon": 9.19, "region": "Lombardia", "province": "MI"},
                "current": {"temp": 15.1, "humidity": 86, "clouds": 42},
                "daily": [
                    {
                        "dt": "2026-04-10",
                        "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
                        "humidity": 60,
                        "cloud_cover": 40,
                        "wind_speed": 12,
                        "wind_deg": 180,
                        "pop": 0.2,
                        "weather_code": 1,
                    }
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ml"]["enabled"] is False
    assert payload["ml"]["warning"]["code"] == "ML_OUT_OF_AREA"
    assert payload["daily_ml"] == []
