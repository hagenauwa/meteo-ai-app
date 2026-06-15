"""Test unitari per find_rain_time_slots() in notification_utils.py."""

import sys
import os
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import notification_utils
from notification_utils import (
    build_daily_message,
    check_hourly_rain_adaptive,
    find_rain_time_slots as _find_rain_time_slots,
)
from scripts import run_telegram_checks


def _rainy_hourly():
    """Ore con POP alta ma codice meteo NON di pioggia e niente precipitazione:
    senza il modello ML non scatta alcun trigger."""
    return {
        "time": ["2026-05-22T10:00", "2026-05-22T11:00"],
        "precipitation_probability": [70, 70],
        "weather_code": [3, 3],
        "precipitation": [0.0, 0.0],
        "temperature_2m": [18.0, 18.0],
        "relative_humidity_2m": [80.0, 80.0],
        "cloud_cover": [80.0, 80.0],
        "wind_speed_10m": [10.0, 10.0],
        "wind_direction_10m": [180.0, 180.0],
    }


def test_rain_adaptive_skips_ml_when_out_of_coverage(monkeypatch):
    calls = []

    def fake_ml(**kwargs):
        calls.append(kwargs)
        return {"rain_probability": 0.9, "model_ready": True, "will_rain": True, "confidence": "alta"}

    monkeypatch.setattr(notification_utils, "get_ml_rain_probability", fake_ml)

    result = check_hourly_rain_adaptive(
        _rainy_hourly(),
        lat=45.4,
        lon=9.2,
        city_name="Milano",
        region="Lombardia",
        ml_coverage=False,
    )

    assert calls == []  # ML non interrogato fuori area
    assert result is None  # nessun trigger (solo POP, niente wmo/precip/ML)


def test_rain_adaptive_uses_ml_when_in_coverage(monkeypatch):
    calls = []

    def fake_ml(**kwargs):
        calls.append(kwargs)
        return {"rain_probability": 0.8, "model_ready": True, "will_rain": True, "confidence": "alta"}

    monkeypatch.setattr(notification_utils, "get_ml_rain_probability", fake_ml)

    result = check_hourly_rain_adaptive(
        _rainy_hourly(),
        lat=44.0,
        lon=10.1,
        city_name="Massa",
        region="Toscana",
        ml_coverage=True,
    )

    assert len(calls) >= 1
    assert result is not None
    assert result["trigger_reason"] == "ml_confirmed"


def test_no_rain():
    """Nessuna pioggia: tutte le ore hanno POP=0, weather_code sereno → []."""
    hourly = {
        "time": [
            "2024-01-01T08:00",
            "2024-01-01T09:00",
            "2024-01-01T10:00",
        ],
        "precipitation_probability": [0, 0, 0],
        "weather_code": [0, 1, 0],  # sereno
        "precipitation": [0.0, 0.0, 0.0],
    }
    result = _find_rain_time_slots(hourly)
    assert result == []


def test_single_hour():
    """Singola ora piovosa: POP=70 → ["14:00"]."""
    hourly = {
        "time": [
            "2024-01-01T12:00",
            "2024-01-01T13:00",
            "2024-01-01T14:00",
            "2024-01-01T15:00",
        ],
        "precipitation_probability": [10, 20, 70, 15],
        "weather_code": [0, 0, 51, 0],
        "precipitation": [0.0, 0.0, 1.2, 0.0],
    }
    result = _find_rain_time_slots(hourly)
    assert result == ["14:00"]


def test_consecutive_range():
    """3 ore consecutive piovose → ["14:00-16:00"]."""
    hourly = {
        "time": [
            "2024-01-01T12:00",
            "2024-01-01T13:00",
            "2024-01-01T14:00",
            "2024-01-01T15:00",
            "2024-01-01T16:00",
            "2024-01-01T17:00",
        ],
        "precipitation_probability": [10, 20, 80, 85, 75, 10],
        "weather_code": [0, 0, 51, 51, 51, 0],
        "precipitation": [0.0, 0.0, 1.2, 2.0, 0.8, 0.0],
    }
    result = _find_rain_time_slots(hourly)
    assert result == ["14:00-16:00"]


def test_multiple_disjoint_periods():
    """Due periodi separati: 10:00-11:00 e 14:00-16:00 piovose → ["10:00-11:00", "14:00-16:00"]."""
    hourly = {
        "time": [
            "2024-01-01T08:00",
            "2024-01-01T09:00",
            "2024-01-01T10:00",
            "2024-01-01T11:00",
            "2024-01-01T12:00",
            "2024-01-01T13:00",
            "2024-01-01T14:00",
            "2024-01-01T15:00",
            "2024-01-01T16:00",
        ],
        "precipitation_probability": [10, 35, 70, 75, 10, 10, 80, 85, 75],
        "weather_code": [0, 0, 51, 51, 0, 0, 51, 51, 51],
        "precipitation": [0.0, 0.0, 0.5, 0.8, 0.0, 0.0, 1.5, 2.0, 1.0],
    }
    result = _find_rain_time_slots(hourly)
    assert result == ["10:00-11:00", "14:00-16:00"]


def test_cap_multiple_periods():
    """5 periodi separati → solo i primi 3 (il cap è gestito dal chiamante, non dalla helper)."""
    hourly = {
        "time": [
            "2024-01-01T06:00",
            "2024-01-01T07:00",
            "2024-01-01T08:00",
            "2024-01-01T09:00",
            "2024-01-01T10:00",
            "2024-01-01T11:00",
            "2024-01-01T14:00",
            "2024-01-01T15:00",
            "2024-01-01T16:00",
            "2024-01-01T19:00",
            "2024-01-01T20:00",
        ],
        "precipitation_probability": [
            60,  # 06:00 - rain
            10,  # 07:00
            70,  # 08:00 - rain
            10,  # 09:00
            65,  # 10:00 - rain
            10,  # 11:00
            80,  # 14:00 - rain
            85,  # 15:00 - rain
            75,  # 16:00 - rain
            10,  # 19:00
            60,  # 20:00 - rain
        ],
        "weather_code": [61, 0, 61, 0, 61, 0, 51, 51, 51, 0, 61],
        "precipitation": [0.1, 0.0, 0.2, 0.0, 0.3, 0.0, 1.0, 1.5, 0.8, 0.0, 0.2],
    }
    result = _find_rain_time_slots(hourly)
    # Helper returns max 3 periods: 06:00, 08:00, 10:00, 14:00-16:00, 20:00
    # Consecutive: [06], [08], [10], [14-16], [20]
    # Only first 3 by helper: 06:00, 08:00, 10:00
    assert len(result) == 3
    assert result == ["06:00", "08:00", "10:00"]


def test_missing_data():
    """hourly dict vuoto o senza time → [] senza crash."""
    # Empty dict
    result = _find_rain_time_slots({})
    assert result == []

    # No time key
    result = _find_rain_time_slots({"precipitation_probability": [50]})
    assert result == []

    # Empty time list
    result = _find_rain_time_slots({"time": [], "precipitation_probability": []})
    assert result == []


def test_daily_message_prefers_clear_hourly_picture_over_cloudy_daily_code():
    daily = {
        "time": ["2026-05-22"],
        "temperature_2m_max": [24.0],
        "temperature_2m_min": [17.0],
        "weather_code": [3],  # Open-Meteo daily può essere pessimista
        "precipitation_probability_max": [0],
        "precipitation_sum": [0.0],
    }
    hourly = {
        "time": [f"2026-05-22T{hour:02d}:00" for hour in range(9, 21)],
        "weather_code": [0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
        "cloud_cover": [5, 9, 0, 0, 1, 6, 0, 3, 0, 0, 0, 0],
        "precipitation_probability": [0] * 12,
        "precipitation": [0.0] * 12,
        "wind_speed_10m": [5.0] * 12,
    }

    message = build_daily_message("Avenza", daily, hourly)

    assert "Condizioni: Cielo sereno" in message
    assert "Condizioni: Nuvoloso" not in message
    assert "Nessuna pioggia prevista" in message


def test_daily_message_keeps_rainy_daily_code_when_hourly_has_rain_risk():
    daily = {
        "time": ["2026-05-22"],
        "temperature_2m_max": [20.0],
        "temperature_2m_min": [15.0],
        "weather_code": [61],
        "precipitation_probability_max": [70],
        "precipitation_sum": [2.0],
    }
    hourly = {
        "time": ["2026-05-22T10:00", "2026-05-22T11:00"],
        "weather_code": [0, 61],
        "cloud_cover": [5, 80],
        "precipitation_probability": [10, 70],
        "precipitation": [0.0, 1.2],
        "wind_speed_10m": [5.0, 5.0],
    }

    message = build_daily_message("Avenza", daily, hourly)

    assert "Condizioni: Pioggia leggera" in message
    assert "Pioggia prevista: 11:00" in message


def test_telegram_cron_requires_secrets_in_production(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        run_telegram_checks,
        "settings",
        SimpleNamespace(is_production=True, telegram_bot_token=""),
    )

    with pytest.raises(RuntimeError, match="DATABASE_URL, TELEGRAM_BOT_TOKEN"):
        run_telegram_checks._validate_runtime_config()


def test_telegram_cron_allows_development_without_production_secrets(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        run_telegram_checks,
        "settings",
        SimpleNamespace(is_production=False, telegram_bot_token=""),
    )

    run_telegram_checks._validate_runtime_config()
