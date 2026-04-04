"""Test costruzione dataset forecast target-based."""
from datetime import datetime, timezone

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from weather_service import _build_batch_results


def test_build_batch_results_creates_future_predictions():
    cities = [{"id": 1, "name": "Roma", "lat": 41.9, "lon": 12.5}]
    payload = [{
        "current": {
            "time": "2026-04-04T10:00",
            "temperature_2m": 18.0,
            "relative_humidity_2m": 60,
            "cloud_cover": 20,
            "wind_speed_10m": 10,
            "precipitation": 0.0,
            "weather_code": 1,
        },
        "hourly": {
            "time": [
                "2026-04-04T10:00",
                "2026-04-04T11:00",
                "2026-04-04T12:00",
                "2026-04-04T13:00",
                "2026-04-04T14:00",
                "2026-04-04T15:00",
                "2026-04-04T16:00",
            ],
            "temperature_2m": [18, 19, 20, 21, 22, 23, 24],
            "relative_humidity_2m": [60, 61, 62, 63, 64, 65, 66],
            "cloud_cover": [20, 21, 22, 23, 24, 25, 26],
            "precipitation": [0, 0, 0, 0, 0.2, 0.3, 0.4],
            "weather_code": [1, 1, 2, 2, 3, 61, 61],
        },
    }]

    result = _build_batch_results(cities, payload)

    assert len(result["observations"]) == 1
    assert len(result["predictions"]) == 6
    first_prediction = result["predictions"][0]
    assert first_prediction["lead_hours"] == 1
    assert first_prediction["target_time"] == datetime(2026, 4, 4, 11, 0, tzinfo=timezone.utc)
    assert first_prediction["forecast_temp"] == 19
