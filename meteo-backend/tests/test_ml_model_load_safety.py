"""TDD coverage for safe degradation when persisted ML models fail to load."""

import importlib
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from database import Base, MlModelStore, get_db


ml_model = importlib.import_module("ml_model")

client = TestClient(app)


class _PickleableTemperaturePipeline:
    n_features_in_ = 6

    def predict(self, features):
        return np.array([0.8])


class _PickleableRainPipeline:
    n_features_in_ = 6

    def predict_proba(self, features):
        return np.array([[0.3, 0.7]])


class _PickleableConditionPipeline:
    n_features_in_ = 11

    def predict_proba(self, features):
        return np.array([[0.1, 0.7, 0.1, 0.1]])

    def predict(self, features):
        return np.array([1])


class _PickleableLabelEncoder:
    def transform(self, values):
        return np.array([0 for _ in values])


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return SimpleNamespace(
            id=1,
            name="Roma",
            region="Lazio",
            province="RM",
            lat=41.9,
            lon=12.5,
            locality_type="comune",
            name_lower="roma",
        )


class _FakeCityDb:
    def query(self, *args, **kwargs):
        return _FakeQuery()


@contextmanager
def _override_city_db():
    def override_get_db():
        yield _FakeCityDb()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def isolated_model_store(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionTesting = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(ml_model, "SessionLocal", SessionTesting)
    return SessionTesting


@pytest.fixture(autouse=True)
def reset_ml_runtime(monkeypatch):
    ml_model._reset_loaded_model_state()
    monkeypatch.setattr(ml_model, "_latest_summary", ml_model._empty_model_summary())
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", None)
    monkeypatch.setattr(ml_model, "_loaded_model_trained_at", None)
    monkeypatch.setattr(ml_model, "_last_model_version_check_at", None)
    monkeypatch.setattr(ml_model, "_stats_cache", None)
    monkeypatch.setattr(ml_model, "_shadow_state", {
        "consecutive_positive_windows": 0,
        "last_check_at": None,
        "last_pass": None,
        "last_details": None,
    })


def _valid_payload(*, sklearn_version: str | None = None, model_format_version: int | None = None):
    return {
        "model_format_version": model_format_version or ml_model.MODEL_FORMAT_VERSION,
        "sklearn_version": sklearn_version or ml_model.sklearn.__version__,
        "pipeline": _PickleableTemperaturePipeline(),
        "rain_pipeline": _PickleableRainPipeline(),
        "condition_pipeline": _PickleableConditionPipeline(),
        "rain_pipeline_v2": None,
        "condition_pipeline_v2": None,
        "rain_platt_v2": None,
        "condition_platt_v2": None,
        "temperature_feature_variant": "v1",
        "blend_profiles": {"v1": {}, "v2": {}},
        "le": _PickleableLabelEncoder(),
        "regions": ["Lazio"],
    }


def _insert_model_record(session_factory, model_bytes: bytes):
    session = session_factory()
    try:
        session.add(
            MlModelStore(
                trained_at=datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc),
                model_bytes=model_bytes,
                mae=0.8,
                n_samples=321,
            )
        )
        session.commit()
    finally:
        session.close()


def _tamper_blob(blob: bytes) -> bytes:
    return blob[:-1] + bytes([blob[-1] ^ 1])


def _exercise_public_helpers():
    correction = ml_model.predict_correction(
        temp=20.0,
        humidity=60.0,
        hour=12,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=40.0,
        lead_hours=0,
    )
    rain = ml_model.predict_rain_probability(
        forecast_temp=20.0,
        humidity=60.0,
        hour=12,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=40.0,
        lead_hours=0,
        city_name="Roma",
    )
    condition = ml_model.predict_condition_outlook(
        forecast_temp=20.0,
        humidity=60.0,
        hour=12,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=40.0,
        lead_hours=0,
        forecast_precipitation=0.0,
        forecast_wind_speed=10.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=1,
        city_name="Roma",
    )
    return correction, rain, condition


def _exercise_api_paths():
    with _override_city_db():
        correction_response = client.get("/api/ml/correction?city=Roma&temp=20&humidity=60&cloud_cover=40")
        rain_response = client.get("/api/ml/rain-prediction?city=Roma&temp=20&humidity=60&cloud_cover=40&lead_hours=0")
        stats_response = client.get("/api/ml/stats")
    return correction_response, rain_response, stats_response


def _missing_model_row(session_factory, monkeypatch):
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")


def _corrupt_pickle_blob(session_factory, monkeypatch):
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")
    payload = _valid_payload(sklearn_version="1.6.1")
    encoded = ml_model._encode_model_payload(payload)
    header, _, _ = encoded.partition(b"\n")
    _insert_model_record(session_factory, header + b"\nthis-is-not-a-valid-pickle")


def _signature_mismatch(session_factory, monkeypatch):
    monkeypatch.setattr(ml_model, "_signing_key", lambda: b"signing-secret-a")
    encoded = ml_model._encode_model_payload(_valid_payload(sklearn_version="1.6.1"))
    _insert_model_record(session_factory, _tamper_blob(encoded))
    monkeypatch.setattr(ml_model, "_signing_key", lambda: b"signing-secret-b")
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")


def _format_mismatch(session_factory, monkeypatch):
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")
    encoded = ml_model._encode_model_payload(_valid_payload(sklearn_version="1.6.1", model_format_version=999))
    _insert_model_record(session_factory, encoded)


def _sklearn_version_mismatch(session_factory, monkeypatch):
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")
    encoded = ml_model._encode_model_payload(_valid_payload(sklearn_version="0.0.test-mismatch"))
    _insert_model_record(session_factory, encoded)


@pytest.mark.parametrize(
    ("case_builder", "expected_status"),
    [
        (_missing_model_row, "missing_model_row"),
        (_corrupt_pickle_blob, "corrupt_model_blob"),
        (_signature_mismatch, "invalid_model_signature"),
        (_format_mismatch, "incompatible_model_format"),
        (_sklearn_version_mismatch, "incompatible_model_sklearn"),
    ],
    ids=["missing-row", "corrupt-pickle", "signature-mismatch", "format-mismatch", "sklearn-mismatch"],
)
def test_model_load_failures_disable_public_ml_and_should_expose_stable_status(
    isolated_model_store,
    monkeypatch,
    case_builder,
    expected_status,
):
    case_builder(isolated_model_store, monkeypatch)

    loaded = ml_model.load_latest_model()
    correction, rain, condition = _exercise_public_helpers()
    correction_response, rain_response, stats_response = _exercise_api_paths()
    stats_payload = stats_response.json()

    assert loaded is False
    assert correction["model_ready"] is False
    assert correction["model_variant"] == "provider"
    assert rain["model_ready"] is False
    assert rain["model_variant"] == "provider"
    assert condition["model_ready"] is False
    assert condition["model_variant"] == "provider"
    assert correction_response.status_code == 200
    assert correction_response.json()["model_ready"] is False
    assert rain_response.status_code == 200
    assert rain_response.json()["model_ready"] is False
    assert stats_response.status_code == 200
    assert stats_payload["model_ready"] is False

    # TDD expectation: every degraded public surface should expose a stable load-failure status.
    assert correction["warning_status"] == expected_status
    assert rain["warning_status"] == expected_status
    assert condition["warning_status"] == expected_status
    assert correction_response.json()["warning_status"] == expected_status
    assert rain_response.json()["warning_status"] == expected_status
    assert stats_payload["model_status"] == "disabled"
    assert stats_payload["model_load_warning"] == expected_status


def test_valid_model_fixture_keeps_public_ml_ready_without_disabled_status(isolated_model_store, monkeypatch):
    monkeypatch.setattr(ml_model, "_signing_key", lambda: b"signing-secret-ok")
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")
    _insert_model_record(
        isolated_model_store,
        ml_model._encode_model_payload(_valid_payload(sklearn_version="1.6.1")),
    )

    loaded = ml_model.load_latest_model()
    correction, rain, condition = _exercise_public_helpers()
    _, _, stats_response = _exercise_api_paths()
    stats_payload = stats_response.json()

    assert loaded is True
    assert correction["model_ready"] is True
    assert rain["model_ready"] is True
    assert condition["model_ready"] is True

    # TDD expectation: callers should have an explicit positive status too.
    assert correction["warning_status"] is None
    assert rain["warning_status"] is None
    assert condition["warning_status"] is None
    assert stats_payload["model_status"] == "loaded"
