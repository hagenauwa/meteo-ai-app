"""Test costruzione dataset forecast target-based."""
import asyncio
from datetime import datetime, timedelta, timezone

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx

import weather_service
from weather_service import _build_batch_results, _fetch_open_meteo_payload


def test_build_batch_results_creates_future_predictions():
    cities = [{"id": 1, "name": "Roma", "lat": 41.9, "lon": 12.5}]
    payload = [{
        "current": {
            "time": "2026-04-04T10:00",
            "temperature_2m": 18.0,
            "relative_humidity_2m": 60,
            "cloud_cover": 20,
            "wind_speed_10m": 10,
            "wind_direction_10m": 180,
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
            "wind_speed_10m": [10, 11, 12, 13, 14, 15, 16],
            "wind_direction_10m": [180, 181, 182, 183, 184, 185, 186],
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
    assert first_prediction["forecast_wind_speed"] == 11
    assert first_prediction["forecast_wind_direction"] == 181


def test_fetch_single_city_returns_first_attempt_payload(monkeypatch):
    weather_service._public_weather_cache.clear()
    calls = []
    expected = {"current": {}, "hourly": {}, "daily": {}}

    async def fake_fetch(client, *, params, attempt_name):
        calls.append((attempt_name, params["hourly"]))
        assert params["forecast_days"] == weather_service.PUBLIC_FORECAST_DAYS
        assert params["forecast_hours"] == weather_service.PUBLIC_HOURLY_FORECAST_HOURS
        return expected

    monkeypatch.setattr(weather_service, "_fetch_open_meteo_payload", fake_fetch)

    result = asyncio.run(weather_service.fetch_single_city(41.9, 12.5))

    assert result == expected
    assert calls == [("rich", weather_service.SINGLE_CITY_HOURLY_RICH_FIELDS)]


def test_fetch_single_city_falls_back_to_compat(monkeypatch):
    weather_service._public_weather_cache.clear()
    calls = []
    warnings = []
    expected = {"current": {}, "hourly": {}, "daily": {}}

    async def fake_fetch(client, *, params, attempt_name):
        calls.append((attempt_name, params["hourly"]))
        if attempt_name == "rich":
            return None
        return expected

    monkeypatch.setattr(weather_service, "_fetch_open_meteo_payload", fake_fetch)
    monkeypatch.setattr(weather_service.logger, "warning", lambda message, *args: warnings.append(message % args))

    result = asyncio.run(weather_service.fetch_single_city(41.9, 12.5))

    assert result == expected
    assert calls == [
        ("rich", weather_service.SINGLE_CITY_HOURLY_RICH_FIELDS),
        ("compat", weather_service.SINGLE_CITY_HOURLY_COMPAT_FIELDS),
    ]
    assert any("fallback_succeeded" in warning for warning in warnings)


def test_fetch_single_city_logs_failure_after_both_attempts(monkeypatch):
    weather_service._public_weather_cache.clear()
    warnings = []

    async def fake_fetch(client, *, params, attempt_name):
        return None

    def fake_urllib_fetch(*, params, attempt_name):
        return None

    async def fake_metno_fetch(lat, lon):
        return None

    monkeypatch.setattr(weather_service, "_fetch_open_meteo_payload", fake_fetch)
    monkeypatch.setattr(weather_service, "_fetch_open_meteo_payload_via_urllib", fake_urllib_fetch)
    monkeypatch.setattr(weather_service, "_fetch_metno_payload", fake_metno_fetch)
    monkeypatch.setattr(weather_service.logger, "warning", lambda message, *args: warnings.append(message % args))

    result = asyncio.run(weather_service.fetch_single_city(41.9, 12.5))

    assert result is None
    assert any("fetch failed after fallback" in warning for warning in warnings)


def test_fetch_single_city_uses_urllib_fallback(monkeypatch):
    weather_service._public_weather_cache.clear()
    calls = []
    warnings = []
    expected = {"current": {}, "hourly": {}, "daily": {}}

    async def fake_fetch(client, *, params, attempt_name):
        calls.append(("httpx", attempt_name, params["hourly"]))
        return None

    def fake_urllib_fetch(*, params, attempt_name):
        calls.append(("urllib", attempt_name, params["hourly"]))
        return expected

    monkeypatch.setattr(weather_service, "_fetch_open_meteo_payload", fake_fetch)
    monkeypatch.setattr(weather_service, "_fetch_open_meteo_payload_via_urllib", fake_urllib_fetch)
    monkeypatch.setattr(weather_service.logger, "warning", lambda message, *args: warnings.append(message % args))

    result = asyncio.run(weather_service.fetch_single_city(41.9, 12.5))

    assert result == expected
    assert calls == [
        ("httpx", "rich", weather_service.SINGLE_CITY_HOURLY_RICH_FIELDS),
        ("httpx", "compat", weather_service.SINGLE_CITY_HOURLY_COMPAT_FIELDS),
        ("urllib", "compat-urllib", weather_service.SINGLE_CITY_HOURLY_COMPAT_FIELDS),
    ]
    assert any("compat-urllib" in warning for warning in warnings)


def test_fetch_single_city_uses_metno_fallback(monkeypatch):
    weather_service._public_weather_cache.clear()
    calls = []
    expected = {"current": {}, "hourly": {}, "daily": {}}

    async def fake_fetch(client, *, params, attempt_name):
        calls.append(("httpx", attempt_name))
        return None

    def fake_urllib_fetch(*, params, attempt_name):
        calls.append(("urllib", attempt_name))
        return None

    async def fake_metno_fetch(lat, lon):
        calls.append(("metno", "fallback"))
        return expected

    monkeypatch.setattr(weather_service, "_fetch_open_meteo_payload", fake_fetch)
    monkeypatch.setattr(weather_service, "_fetch_open_meteo_payload_via_urllib", fake_urllib_fetch)
    monkeypatch.setattr(weather_service, "_fetch_metno_payload", fake_metno_fetch)

    result = asyncio.run(weather_service.fetch_single_city(41.9, 12.5))

    assert result == expected
    assert calls == [
        ("httpx", "rich"),
        ("httpx", "compat"),
        ("urllib", "compat-urllib"),
        ("metno", "fallback"),
    ]


def test_fetch_open_meteo_payload_logs_http_error(monkeypatch):
    warnings = []

    class FakeResponse:
        status_code = 503
        text = "upstream temporarily unavailable"

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "bad gateway",
                request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
                response=self,
            )

    class FakeClient:
        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(weather_service.logger, "warning", lambda message, *args: warnings.append(message % args))

    result = asyncio.run(
        _fetch_open_meteo_payload(
            FakeClient(),
            params={"latitude": 41.9, "longitude": 12.5},
            attempt_name="rich",
        )
    )

    assert result is None
    assert any("http_error" in warning for warning in warnings)
    assert any("status=503" in warning for warning in warnings)


def test_convert_metno_payload_to_open_meteo_shape():
    payload = {
        "properties": {
            "timeseries": [
                {
                    "time": "2026-04-04T10:00:00Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_pressure_at_sea_level": 1018,
                                "air_temperature": 20.5,
                                "cloud_area_fraction": 35,
                                "relative_humidity": 60,
                                "wind_from_direction": 180,
                                "wind_speed": 5.0,
                            }
                        },
                        "next_1_hours": {
                            "summary": {"symbol_code": "partlycloudy_day"},
                            "details": {"precipitation_amount": 0.0},
                        },
                    },
                },
                {
                    "time": "2026-04-04T11:00:00Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_pressure_at_sea_level": 1017,
                                "air_temperature": 21.5,
                                "cloud_area_fraction": 40,
                                "relative_humidity": 58,
                                "wind_from_direction": 190,
                                "wind_speed": 6.0,
                            }
                        },
                        "next_1_hours": {
                            "summary": {"symbol_code": "lightrain_day"},
                            "details": {"precipitation_amount": 0.2},
                        },
                    },
                },
            ]
        }
    }

    result = weather_service._convert_metno_to_open_meteo_payload(payload, lat=41.9, lon=12.5)

    assert result is not None
    assert result["current"]["temperature_2m"] == 20.5
    assert result["current"]["weather_code"] == 2
    assert result["hourly"]["weather_code"][1] == 61
    assert result["daily"]["time"]
    assert result["daily"]["wind_direction_10m_dominant"][0] == 180


def test_convert_metno_payload_limits_daily_horizon_to_nine_days():
    start = datetime(2026, 4, 4, 10, 0, tzinfo=timezone.utc)
    payload = {
        "properties": {
            "timeseries": [
                {
                    "time": (start + timedelta(days=offset)).isoformat().replace("+00:00", "Z"),
                    "data": {
                        "instant": {
                            "details": {
                                "air_pressure_at_sea_level": 1015,
                                "air_temperature": 15 + offset,
                                "cloud_area_fraction": 20 + offset,
                                "relative_humidity": 60,
                                "wind_from_direction": 180,
                                "wind_speed": 4.0,
                            }
                        },
                        "next_1_hours": {
                            "summary": {"symbol_code": "partlycloudy_day"},
                            "details": {"precipitation_amount": 0.0},
                        },
                    },
                }
                for offset in range(11)
            ]
        }
    }

    result = weather_service._convert_metno_to_open_meteo_payload(payload, lat=41.9, lon=12.5)

    assert result is not None
    assert len(result["daily"]["time"]) == weather_service.PUBLIC_FALLBACK_FORECAST_DAYS
    assert result["daily"]["time"][-1] == "2026-04-12"


def test_format_weather_for_frontend_preserves_sixteen_daily_entries():
    raw_data = {
        "latitude": 41.9,
        "longitude": 12.5,
        "current": {
            "temperature_2m": 20,
            "relative_humidity_2m": 60,
            "apparent_temperature": 20,
            "cloud_cover": 35,
            "wind_speed_10m": 12,
            "wind_direction_10m": 180,
            "surface_pressure": 1014,
            "precipitation": 0,
            "weather_code": 1,
        },
        "hourly": {
            "time": [f"2026-04-04T{hour:02d}:00" for hour in range(weather_service.PUBLIC_HOURLY_FORECAST_HOURS)],
            "temperature_2m": [18 + (hour * 0.1) for hour in range(weather_service.PUBLIC_HOURLY_FORECAST_HOURS)],
            "relative_humidity_2m": [60] * weather_service.PUBLIC_HOURLY_FORECAST_HOURS,
            "cloud_cover": [35] * weather_service.PUBLIC_HOURLY_FORECAST_HOURS,
            "wind_speed_10m": [10] * weather_service.PUBLIC_HOURLY_FORECAST_HOURS,
            "wind_direction_10m": [180] * weather_service.PUBLIC_HOURLY_FORECAST_HOURS,
            "precipitation_probability": [10] * weather_service.PUBLIC_HOURLY_FORECAST_HOURS,
            "precipitation": [0.0] * weather_service.PUBLIC_HOURLY_FORECAST_HOURS,
            "weather_code": [1] * weather_service.PUBLIC_HOURLY_FORECAST_HOURS,
        },
        "daily": {
            "time": [f"2026-04-{day:02d}" for day in range(4, 4 + weather_service.PUBLIC_FORECAST_DAYS)],
            "temperature_2m_min": [10 + day for day in range(weather_service.PUBLIC_FORECAST_DAYS)],
            "temperature_2m_max": [20 + day for day in range(weather_service.PUBLIC_FORECAST_DAYS)],
            "weather_code": [1] * weather_service.PUBLIC_FORECAST_DAYS,
            "precipitation_probability_max": [10] * weather_service.PUBLIC_FORECAST_DAYS,
            "wind_speed_10m_max": [12] * weather_service.PUBLIC_FORECAST_DAYS,
            "wind_direction_10m_dominant": [180] * weather_service.PUBLIC_FORECAST_DAYS,
        },
    }

    result = weather_service.format_weather_for_frontend(raw_data, "Roma")

    assert result is not None
    assert len(result["daily"]) == weather_service.PUBLIC_FORECAST_DAYS
    assert result["daily"][-1]["dt"] == "2026-04-19"
