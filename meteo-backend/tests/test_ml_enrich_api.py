"""Test endpoint ML enrich per forecast frontend."""
import importlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from database import get_db


client = TestClient(app)
ml_module = importlib.import_module("routers.ml")


def test_ml_enrich_returns_current_and_daily_blocks(monkeypatch):
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

    lead_hours_calls = []

    monkeypatch.setattr(ml_module.ml_model, "predict_correction", lambda **kwargs: {
        "model_ready": True,
        "correction": 0.3,
        "corrected_temp": 15.4,
        "confidence": "media",
    })
    monkeypatch.setattr(ml_module.ml_model, "predict_rain_probability", lambda **kwargs: {
        "model_ready": True,
        "rain_probability": 0.2,
        "will_rain": False,
        "confidence": "media",
    })

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
        }

    monkeypatch.setattr(ml_module.ml_model, "build_daily_insight", fake_daily_insight)
    monkeypatch.setattr(ml_module.ml_model, "get_public_summary", lambda: {"model_ready": True})

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.post(
            "/api/ml/enrich",
            json={
                "city": {
                    "name": "Roma",
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
    assert lead_hours_calls == [14, 38]
