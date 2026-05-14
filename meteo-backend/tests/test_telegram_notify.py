"""Test unitari per _find_rain_time_slots() in telegram_notify_service.py."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telegram_notify_service import _find_rain_time_slots


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