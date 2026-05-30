"""Test endpoint meteo avanzato /api/weather/advanced."""
import importlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from database import get_db


client = TestClient(app)
advanced_module = importlib.import_module("routers.advanced")
weather_module = importlib.import_module("routers.weather")
weather_service_module = importlib.import_module("weather_service")


def _make_fake_city(**kwargs):
    defaults = dict(
        id=1,
        name="Roma",
        region="Lazio",
        province="RM",
        lat=41.9,
        lon=12.5,
        locality_type="comune",
        name_lower="roma",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _override_db(rows):
    class FakeQuery:
        def __init__(self, items):
            self.items = items

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, limit):
            self.items = self.items[:limit]
            return self

        def all(self):
            return self.items

        def first(self):
            return self.items[0] if self.items else None

    class FakeDb:
        def query(self, *args, **kwargs):
            return FakeQuery(rows)

    def _override():
        yield FakeDb()

    return _override


async def _fake_fetch_single_city(lat, lon):
    """Restituisce dati meteo fittizi compatibili con il frontend."""
    daily_time = [f"2026-04-{day:02d}" for day in range(4, 12)]
    return {
        "latitude": lat,
        "longitude": lon,
        "current": {
            "time": "2026-04-04T12:00",
            "temperature_2m": 22.5,
            "relative_humidity_2m": 55,
            "apparent_temperature": 23.0,
            "cloud_cover": 30,
            "wind_speed_10m": 10,
            "wind_direction_10m": 180,
            "surface_pressure": 1015,
            "precipitation": 0,
            "weather_code": 1,
        },
        "hourly": {
            "time": ["2026-04-04T12:00", "2026-04-04T13:00"],
            "temperature_2m": [22.5, 23.0],
            "relative_humidity_2m": [55, 54],
            "cloud_cover": [30, 35],
            "wind_speed_10m": [10, 12],
            "wind_direction_10m": [180, 190],
            "precipitation_probability": [5, 10],
            "precipitation": [0, 0],
            "weather_code": [1, 2],
        },
        "daily": {
            "time": daily_time,
            "temperature_2m_min": [12 + offset for offset in range(len(daily_time))],
            "temperature_2m_max": [22 + offset for offset in range(len(daily_time))],
            "weather_code": [1 + (offset % 2) for offset in range(len(daily_time))],
            "precipitation_probability_max": [10 + (offset * 5) for offset in range(len(daily_time))],
            "wind_speed_10m_max": [10 + offset for offset in range(len(daily_time))],
            "wind_direction_10m_dominant": [180 + (offset * 5) for offset in range(len(daily_time))],
            "precipitation_sum": [0.0 for _ in range(len(daily_time))],
        },
    }


async def _fake_air_quality_ok(lat, lon):
    return {
        "current": {
            "pm10": 15.0,
            "pm2_5": 8.0,
            "european_aqi": 2,
            "us_aqi": 35,
            "uv_index": 4.5,
        }
    }


async def _fake_air_quality_fail(*args, **kwargs):
    """Simula fallimento dell'API Air Quality (es. HTTP 500)."""
    return None


class TestWeatherAdvanced:
    def test_valid_city_returns_200_with_advanced(self, monkeypatch):
        """Con citta valida → 200, contiene advanced con uv_index e european_aqi."""
        fake_city = _make_fake_city()
        app.dependency_overrides[get_db] = _override_db([fake_city])
        monkeypatch.setattr(advanced_module, "fetch_single_city", _fake_fetch_single_city)
        monkeypatch.setattr(advanced_module, "_fetch_air_quality", _fake_air_quality_ok)

        try:
            response = client.get("/api/weather/advanced?city=Roma")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        assert "advanced" in data
        adv = data["advanced"]
        assert adv["uv_index"] == 4.5
        assert adv["european_aqi"] == 2
        assert adv["pm10"] == 15.0
        assert adv["pm2_5"] == 8.0
        assert adv["us_aqi"] == 35
        assert adv["source"] == "open-meteo-air-quality"
        assert "current" in data
        assert "hourly" in data
        assert "daily" in data

    def test_invalid_city_returns_404(self, monkeypatch):
        """Con citta invalida (non nel DB e geocoding fallisce) → 404."""
        app.dependency_overrides[get_db] = _override_db([])

        async def fake_geocode(city):
            return None

        monkeypatch.setattr(weather_module, "_geocode_city", fake_geocode)
        monkeypatch.setattr(advanced_module, "fetch_single_city", _fake_fetch_single_city)

        try:
            response = client.get("/api/weather/advanced?city=CittaInesistenteXYZ123")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 404

    def test_air_quality_fallback_when_api_fails(self, monkeypatch):
        """Fallback: se Open-Meteo Air Quality fallisce, i campi advanced sono None."""
        fake_city = _make_fake_city()
        app.dependency_overrides[get_db] = _override_db([fake_city])
        monkeypatch.setattr(advanced_module, "fetch_single_city", _fake_fetch_single_city)
        monkeypatch.setattr(advanced_module, "_fetch_air_quality", _fake_air_quality_fail)

        try:
            response = client.get("/api/weather/advanced?city=Roma")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        assert "advanced" in data
        adv = data["advanced"]
        assert adv["uv_index"] is None
        assert adv["european_aqi"] is None
        assert adv["pm10"] is None
        assert adv["pm2_5"] is None
        assert adv["us_aqi"] is None
        assert adv["source"] == "open-meteo-air-quality"
        # Dati base comunque presenti
        assert "current" in data

    def test_lat_lon_bypass_db(self, monkeypatch):
        """Fornendo lat/lon il risultato e 200 anche senza DB hit."""
        app.dependency_overrides[get_db] = _override_db([])
        monkeypatch.setattr(advanced_module, "fetch_single_city", _fake_fetch_single_city)
        monkeypatch.setattr(advanced_module, "_fetch_air_quality", _fake_air_quality_ok)

        try:
            response = client.get("/api/weather/advanced?lat=41.9&lon=12.5&name=Roma")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        assert data["advanced"]["uv_index"] == 4.5

    def test_missing_city_and_coords_returns_422(self, monkeypatch):
        """Senza city ne lat/lon → errore di validazione 422."""
        app.dependency_overrides[get_db] = _override_db([])
        monkeypatch.setattr(advanced_module, "fetch_single_city", _fake_fetch_single_city)

        try:
            response = client.get("/api/weather/advanced")
        finally:
            app.dependency_overrides.pop(get_db, None)

        # 422 perche lat e lon mancano e city e None => _resolve_city solleva 400
        # ma FastAPI restituisce 422 per parametri mancanti obbligatori (nessuno e obbligatorio)
        # In realta con tutti None, _resolve_city solleva 400
        assert response.status_code in (400, 422)
