"""Test endpoint ML pubblici reali."""
import importlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from database import get_db


client = TestClient(app)
ml_router = importlib.import_module("routers.ml")
ml_model = importlib.import_module("ml_model")


def test_rain_prediction_endpoint_supports_legacy_models(monkeypatch):
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

    class FakeRainPipeline:
        n_features_in_ = 6

        def predict_proba(self, features):
            return [[0.7, 0.3]]

    def override_get_db():
        yield FakeDb()

    monkeypatch.setattr(ml_model, "_rain_pipeline", FakeRainPipeline())
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", None)
    monkeypatch.setattr(ml_model, "_rain_pipeline_v2", None)
    monkeypatch.setattr(ml_model, "_ensure_latest_model_loaded", lambda **kwargs: None)

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get(
            "/api/ml/rain-prediction?city=Roma&temp=20&humidity=60&cloud_cover=40&lead_hours=0"
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_ready"] is True
    assert payload["model_variant"] == "legacy"
    assert payload["rain_probability"] == 0.3
