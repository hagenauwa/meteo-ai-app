"""Test endpoint ML pubblici reali."""

import importlib

import pytest

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
    install_fake_db_override,
)


client = TestClient(app)
ml_router = importlib.import_module("routers.ml")
ml_model = importlib.import_module("ml_model")
auth_module = importlib.import_module("auth")


def test_rain_prediction_endpoint_supports_legacy_models(monkeypatch):
    class FakeRainPipeline:
        n_features_in_ = 6

        def predict_proba(self, features):
            return [[0.7, 0.3]]

    monkeypatch.setattr(ml_model, "_rain_pipeline", FakeRainPipeline())
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", None)
    monkeypatch.setattr(ml_model, "_rain_pipeline_v2", None)
    monkeypatch.setattr(ml_model, "_ensure_latest_model_loaded", lambda **kwargs: None)

    install_fake_db_override(app, get_db)
    try:
        response = client.get("/api/ml/rain-prediction?city=Roma&temp=20&humidity=60&cloud_cover=40&lead_hours=0")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_ready"] is True
    assert payload["model_variant"] == "legacy"
    assert payload["rain_probability"] == 0.3


def test_correction_endpoint_known_city_returns_ml_payload(monkeypatch):
    captured = {}

    def fake_predict_correction(**kwargs):
        captured.update(kwargs)
        return {
            "model_ready": True,
            "correction": 0.8,
            "corrected_temp": 21.3,
            "confidence": "alta",
            "model_variant": "legacy",
        }

    monkeypatch.setattr(ml_router.ml_model, "predict_correction", fake_predict_correction)

    install_fake_db_override(app, get_db)
    try:
        response = client.get(
            "/api/ml/correction?city=Roma&temp=20.5&humidity=61&hour=14&cloud_cover=35"
            "&lead_hours=8&forecast_precipitation=0.4&forecast_wind_speed=12"
            "&forecast_wind_direction=190&forecast_weather_code=2"
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_ready"] is True
    assert payload["correction"] == 0.8
    assert payload["corrected_temp"] == 21.3
    assert payload["confidence"] == "alta"
    assert payload["model_variant"] == "legacy"
    assert captured["lat"] == 41.9
    assert captured["lon"] == 12.5
    assert captured["region"] == "Lazio"
    assert captured["lead_hours"] == 8
    assert captured["forecast_weather_code"] == 2


def test_correction_endpoint_keeps_200_when_model_not_ready(monkeypatch):
    monkeypatch.setattr(
        ml_router.ml_model,
        "predict_correction",
        lambda **kwargs: {
            "model_ready": False,
            "message": "Modello temperatura non ancora disponibile",
            "model_variant": "provider",
        },
    )

    install_fake_db_override(app, get_db)
    try:
        response = client.get("/api/ml/correction?city=Roma&temp=20&humidity=60&hour=14")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_ready"] is False
    assert payload["message"] == "Modello temperatura non ancora disponibile"
    assert payload["model_variant"] == "provider"


def test_correction_endpoint_unknown_city_returns_warning_contract():
    install_fake_db_override(app, get_db, [])
    try:
        response = client.get("/api/ml/correction?city=Atlantide&temp=20&humidity=60&hour=14")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert_warning_contract(
        payload,
        code=WARNING_CITY_UNRESOLVED,
        reason_substring="unknown city: Atlantide",
        warning_parent="self",
    )
    assert payload["model_ready"] is False
    assert payload["corrected_temp"] == 20.0


@pytest.mark.parametrize(
    ("query", "reason_substring"),
    [
        ("temp=ciao&humidity=60&hour=14", "invalid temp: ciao"),
        ("temp=20&humidity=troppa&hour=14", "invalid humidity: troppa"),
        ("temp=20&humidity=60&hour=sera", "invalid hour: sera"),
    ],
)
def test_correction_endpoint_invalid_input_returns_warning_contract(query, reason_substring):
    install_fake_db_override(app, get_db)
    try:
        response = client.get(f"/api/ml/correction?city=Roma&{query}")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert_warning_contract(
        payload,
        code="ML_INVALID_INPUT",
        reason_substring=reason_substring,
        warning_parent="self",
    )
    assert payload["model_ready"] is False


def test_correction_endpoint_model_unavailable_returns_warning_contract(monkeypatch):
    monkeypatch.setattr(
        ml_router.ml_model,
        "predict_correction",
        lambda **kwargs: {
            "model_ready": False,
            "message": "Modello temperatura non ancora disponibile",
            "model_variant": "provider",
            "warning_status": MODEL_STATUS_MISSING_ROW,
        },
    )

    install_fake_db_override(app, get_db)
    try:
        response = client.get("/api/ml/correction?city=Roma&temp=20&humidity=60&hour=14")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert_warning_contract(
        payload,
        code="ML_MODEL_DISABLED",
        reason_substring=f"model unavailable: {MODEL_STATUS_MISSING_ROW}",
        warning_parent="self",
    )
    assert payload["message"] == "Modello temperatura non ancora disponibile"
    assert payload["model_ready"] is False
    assert payload["warning_status"] == MODEL_STATUS_MISSING_ROW


def test_stats_endpoint_returns_current_model_stats(monkeypatch):
    monkeypatch.setattr(
        ml_router.ml_model,
        "get_stats",
        lambda: {
            "model_ready": True,
            "verified_predictions": 12,
            "avg_error": 1.4,
            "lead_time_error": [{"lead_hours": 24, "mae": 1.1}],
        },
    )

    response = client.get("/api/ml/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_ready"] is True
    assert payload["verified_predictions"] == 12
    assert payload["avg_error"] == 1.4
    assert payload["lead_time_error"][0]["lead_hours"] == 24


def test_stats_endpoint_exposes_disabled_model_status_when_summary_is_disabled(monkeypatch):
    monkeypatch.setattr(
        ml_router.ml_model,
        "get_stats",
        lambda: {
            "verified_predictions": 0,
            "lead_time_error": [],
        },
    )
    monkeypatch.setattr(
        ml_router.ml_model,
        "get_public_summary",
        lambda: {
            "model_ready": False,
            "model_status": "disabled",
            "model_load_warning": MODEL_STATUS_MISSING_ROW,
        },
    )

    response = client.get("/api/ml/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_ready"] is False
    assert payload["model_status"] == "disabled"
    assert payload["model_load_warning"] == MODEL_STATUS_MISSING_ROW


def test_train_endpoint_with_admin_token_runs_training_and_reload(monkeypatch):
    calls = []
    original_token = auth_module.settings.admin_api_token

    monkeypatch.setattr(
        ml_router.ml_model,
        "train",
        lambda min_samples: (
            calls.append(("train", min_samples)) or {"success": True, "trained_samples": 640, "model_ready": True}
        ),
    )
    monkeypatch.setattr(
        ml_router.ml_model,
        "load_latest_model",
        lambda: calls.append(("load_latest_model", None)) or None,
    )
    object.__setattr__(auth_module.settings, "admin_api_token", "test-admin-token")

    try:
        response = client.post(
            "/api/ml/train?min_samples=250",
            headers={"x-admin-token": "test-admin-token"},
        )
    finally:
        object.__setattr__(auth_module.settings, "admin_api_token", original_token)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["trained_samples"] == 640
    assert payload["model_ready"] is True
    assert calls == [("train", 250), ("load_latest_model", None)]


def test_train_endpoint_requires_valid_admin_token(monkeypatch):
    calls = []
    original_token = auth_module.settings.admin_api_token

    monkeypatch.setattr(
        ml_router.ml_model,
        "train",
        lambda min_samples: calls.append(("train", min_samples)) or {"success": True},
    )
    object.__setattr__(auth_module.settings, "admin_api_token", "test-admin-token")

    try:
        response = client.post(
            "/api/ml/train?min_samples=250",
            headers={"x-admin-token": "wrong-token"},
        )
    finally:
        object.__setattr__(auth_module.settings, "admin_api_token", original_token)

    assert response.status_code == 403
    assert response.json()["detail"] == "Token amministratore non valido"
    assert calls == []
