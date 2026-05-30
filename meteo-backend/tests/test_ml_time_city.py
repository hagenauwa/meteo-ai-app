"""TDD contract tests for ML city warnings and daily representative time."""
import importlib
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import get_db
from main import app
from tests.ml_test_utils import (
    WARNING_CITY_AMBIGUOUS,
    WARNING_CITY_UNRESOLVED,
    assert_warning_contract,
    fake_city,
    override_get_db,
)


client = TestClient(app)
ml_module = importlib.import_module("routers.ml")

ROME_TZ = ZoneInfo("Europe/Rome")


def _base_payload(*, name: str = "Roma", lat: float = 41.9, lon: float = 12.5, dt: str = "2026-04-10"):
    return {
        "city": {
            "name": name,
            "lat": lat,
            "lon": lon,
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
                "dt": dt,
                "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
                "humidity": 60,
                "cloud_cover": 40,
                "wind_speed": 12,
                "wind_deg": 180,
                "pop": 0.2,
                "weather_code": 1,
            }
        ],
    }


def _stub_ml(monkeypatch):
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
    monkeypatch.setattr(ml_module.ml_model, "build_daily_insight", lambda **kwargs: {
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
    })
    monkeypatch.setattr(ml_module.ml_model, "get_public_summary", lambda: {"model_ready": True})


def _expected_representative_lead_hours(now_utc: datetime, day_iso: str) -> int:
    representative_local = datetime.fromisoformat(f"{day_iso}T14:00:00").replace(tzinfo=ROME_TZ)
    representative_utc = representative_local.astimezone(timezone.utc)
    delta = representative_utc - now_utc.astimezone(timezone.utc)
    return int(delta.total_seconds() // 3600)


def test_ml_enrich_unknown_city_returns_warning_contract(monkeypatch):
    _stub_ml(monkeypatch)
    app.dependency_overrides[get_db] = override_get_db([])

    try:
        response = client.post(
            "/api/ml/enrich",
            json=_base_payload(name="Atlantide", lat=44.0, lon=9.0),
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert_warning_contract(
        response.json(),
        code=WARNING_CITY_UNRESOLVED,
        reason_substring="unknown city",
    )


def test_ml_enrich_ambiguous_city_returns_warning_contract(monkeypatch):
    _stub_ml(monkeypatch)
    app.dependency_overrides[get_db] = override_get_db([
        fake_city(id=1, name="Castro", region="Puglia", province="LE", lat=40.0, lon=18.4),
        fake_city(id=2, name="Castro", region="Lombardia", province="BG", lat=45.8, lon=9.9),
    ])

    try:
        response = client.post(
            "/api/ml/enrich",
            json=_base_payload(name="Castro", lat=40.0, lon=18.4, dt="2026-05-10"),
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert_warning_contract(
        response.json(),
        code=WARNING_CITY_AMBIGUOUS,
        reason_substring="multiple city matches",
    )


def test_ml_enrich_coordinate_mismatch_returns_warning_contract(monkeypatch):
    _stub_ml(monkeypatch)
    app.dependency_overrides[get_db] = override_get_db([
        fake_city(name="Roma", region="Lazio", province="RM", lat=41.9, lon=12.5),
    ])

    try:
        response = client.post(
            "/api/ml/enrich",
            json=_base_payload(name="Roma", lat=41.98, lon=12.62),
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert_warning_contract(
        response.json(),
        code=WARNING_CITY_UNRESOLVED,
        reason_substring="coordinates differ by more than 0.05",
    )


def test_ml_enrich_uses_europe_rome_14_local_for_daily_representative_time(monkeypatch):
    _stub_ml(monkeypatch)
    lead_hours_calls = []

    fixed_now = datetime(2026, 3, 29, 13, 0, tzinfo=timezone.utc)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return fixed_now.astimezone(tz)
            return fixed_now

    def _capture_daily_insight(**kwargs):
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

    monkeypatch.setattr(ml_module, "datetime", _FixedDateTime)
    monkeypatch.setattr(ml_module.ml_model, "build_daily_insight", _capture_daily_insight)

    # Città in copertura ML (Massa-Carrara) così l'enrich non viene disabilitato
    # dal gate out-of-area e build_daily_insight viene effettivamente chiamato.
    app.dependency_overrides[get_db] = override_get_db([
        fake_city(name="Massa", region="Toscana", province="Massa-Carrara", lat=41.9, lon=12.5),
    ])

    try:
        response = client.post(
            "/api/ml/enrich",
            json=_base_payload(name="Massa", lat=41.9, lon=12.5, dt="2026-03-30"),
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert lead_hours_calls == [_expected_representative_lead_hours(fixed_now, "2026-03-30")]
