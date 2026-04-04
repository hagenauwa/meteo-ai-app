"""Test endpoint weather composito."""
import importlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from database import get_db


client = TestClient(app)
weather_module = importlib.import_module("routers.weather")


def test_weather_includes_ml_block(monkeypatch):
    fake_city = SimpleNamespace(
        id=1,
        name="Roma",
        region="Lazio",
        province="RM",
        lat=41.9,
        lon=12.5,
        locality_type="comune",
        name_lower="roma",
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return fake_city

    class FakeDb:
        def query(self, *args, **kwargs):
            return FakeQuery()

    def override_get_db():
        yield FakeDb()

    async def fake_fetch_single_city(lat, lon):
        return {
        "latitude": lat,
        "longitude": lon,
        "current": {
            "temperature_2m": 20,
            "relative_humidity_2m": 60,
            "apparent_temperature": 20,
            "cloud_cover": 40,
            "wind_speed_10m": 12,
            "wind_direction_10m": 180,
            "surface_pressure": 1012,
            "precipitation": 0,
            "weather_code": 1,
        },
        "hourly": {
            "time": ["2026-04-04T12:00", "2026-04-04T13:00"],
            "temperature_2m": [20, 21],
            "relative_humidity_2m": [60, 61],
            "cloud_cover": [40, 45],
            "wind_speed_10m": [12, 13],
            "wind_direction_10m": [180, 190],
            "precipitation_probability": [10, 20],
            "precipitation": [0, 0.1],
            "weather_code": [1, 2],
        },
        "daily": {
            "time": ["2026-04-04", "2026-04-05"],
            "temperature_2m_min": [12, 11],
            "temperature_2m_max": [22, 21],
            "weather_code": [1, 2],
            "precipitation_probability_max": [10, 30],
            "wind_speed_10m_max": [12, 14],
            "wind_direction_10m_dominant": [180, 210],
        },
    }

    monkeypatch.setattr(weather_module, "fetch_single_city", fake_fetch_single_city)
    monkeypatch.setattr(weather_module.ml_model, "predict_correction", lambda **kwargs: {
        "model_ready": True,
        "correction": 0.4,
        "corrected_temp": 20.4,
        "confidence": "media",
    })
    monkeypatch.setattr(weather_module.ml_model, "predict_rain_probability", lambda **kwargs: {
        "model_ready": True,
        "rain_probability": 0.25,
        "will_rain": False,
        "confidence": "media",
    })
    monkeypatch.setattr(weather_module.ml_model, "build_daily_insight", lambda **kwargs: {
        "expected_condition": "sereno",
        "display_condition": "Cielo sereno",
        "condition_confidence": "alta",
        "condition_source": "ml",
        "rain_probability": 0.22,
        "rain_confidence": "media",
        "temperature_delta": 0.4,
        "adjusted_temp_range": {"min": 11.4, "max": 21.4},
        "summary": "Cielo sereno con basso rischio di pioggia.",
        "badge": "Scenario stabile",
    })
    monkeypatch.setattr(weather_module.ml_model, "get_public_summary", lambda: {"model_ready": True})
    monkeypatch.setattr(weather_module.ml_model, "get_stats", lambda: {"verified_predictions": 12, "lead_time_error": []})

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/api/weather?city=Roma")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert "ml" in data
    assert data["ml"]["correction"]["model_ready"] is True
    assert data["ml"]["stats"]["verified_predictions"] == 12
    assert data["daily"][0]["ml"]["expected_condition"] == "sereno"
    assert data["daily"][0]["ml"]["adjusted_temp_range"]["max"] == 21.4
