"""
weather_service.py — integrazione con Open-Meteo.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
BATCH_SIZE = 100
MAX_CONCURRENCY = 6
TIMEOUT = 30
ML_FORECAST_LEADS = (1, 2, 3, 4, 5, 6)


def parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_batch_results(cities: list[dict], payload: list[dict]) -> dict:
    observations: list[dict] = []
    predictions: list[dict] = []

    for i, city_data in enumerate(payload):
        if i >= len(cities):
            break

        city = cities[i]
        current = city_data.get("current", {})
        current_time_raw = current.get("time")
        if current_time_raw and current.get("temperature_2m") is not None:
            current_time = parse_utc_timestamp(current_time_raw)
            observations.append({
                "city_id": city["id"],
                "observed_at": current_time,
                "temp": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
                "cloud_cover": current.get("cloud_cover"),
                "wind_speed": current.get("wind_speed_10m"),
                "precipitation": current.get("precipitation", 0.0),
                "weather_code": current.get("weather_code"),
            })

        hourly = city_data.get("hourly", {})
        hourly_times = hourly.get("time", [])
        if not hourly_times:
            continue

        hourly_map = {}
        for idx, raw_time in enumerate(hourly_times):
            hourly_map[parse_utc_timestamp(raw_time)] = idx

        forecast_anchor = parse_utc_timestamp(current_time_raw).replace(minute=0, second=0, microsecond=0)
        for lead_hours in ML_FORECAST_LEADS:
            target_time = forecast_anchor + timedelta(hours=lead_hours)
            idx = hourly_map.get(target_time)
            if idx is None:
                continue

            temperatures = hourly.get("temperature_2m", [])
            forecast_temp = temperatures[idx] if idx < len(temperatures) else None
            if forecast_temp is None:
                continue

            humidities = hourly.get("relative_humidity_2m", [])
            precipitations = hourly.get("precipitation", [])
            weather_codes = hourly.get("weather_code", [])
            cloud_covers = hourly.get("cloud_cover", [])

            predictions.append({
                "city_id": city["id"],
                "predicted_at": forecast_anchor,
                "target_time": target_time,
                "lead_hours": lead_hours,
                "forecast_source": "open-meteo",
                "forecast_temp": forecast_temp,
                "humidity": humidities[idx] if idx < len(humidities) else None,
                "forecast_precipitation": precipitations[idx] if idx < len(precipitations) else None,
                "forecast_weather_code": weather_codes[idx] if idx < len(weather_codes) else None,
                "forecast_cloud_cover": cloud_covers[idx] if idx < len(cloud_covers) else None,
            })

    return {"observations": observations, "predictions": predictions}


async def fetch_weather_batch(cities: list[dict], client: httpx.AsyncClient) -> dict:
    """
    Scarica osservazioni correnti e previsioni orarie per un batch di città.
    """
    if not cities:
        return {"observations": [], "predictions": []}

    params = {
        "latitude": ",".join(str(c["lat"]) for c in cities),
        "longitude": ",".join(str(c["lon"]) for c in cities),
        "current": "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,precipitation,weather_code",
        "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,precipitation,weather_code",
        "wind_speed_unit": "kmh",
        "timezone": "UTC",
        "forecast_hours": max(ML_FORECAST_LEADS) + 1,
    }

    try:
        response = await client.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[WARN]  Errore Open-Meteo batch: {e}")
        return {"observations": [], "predictions": []}

    payload = data if isinstance(data, list) else [data]
    return _build_batch_results(cities, payload)


async def fetch_all_cities_weather(cities: list[dict]) -> dict:
    """
    Scarica meteo per tutte le città in batch paralleli a concorrenza limitata.
    """
    all_observations: list[dict] = []
    all_predictions: list[dict] = []
    batches = [cities[i:i + BATCH_SIZE] for i in range(0, len(cities), BATCH_SIZE)]

    print(f"[API] Scaricando meteo per {len(cities)} città in {len(batches)} batch...")
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def run_batch(batch: list[dict], client: httpx.AsyncClient) -> dict:
        async with semaphore:
            return await fetch_weather_batch(batch, client)

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(run_batch(batch, client) for batch in batches))

    for result in results:
        all_observations.extend(result["observations"])
        all_predictions.extend(result["predictions"])

    print(f"[OK] Scaricate {len(all_observations)} osservazioni e {len(all_predictions)} previsioni target-based")
    return {"observations": all_observations, "predictions": all_predictions}


async def fetch_single_city(lat: float, lon: float) -> Optional[dict]:
    """
    Scarica meteo per una singola città per il frontend pubblico.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,cloud_cover,wind_speed_10m,wind_direction_10m,surface_pressure,precipitation,weather_code",
        "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,precipitation_probability,precipitation,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max,wind_speed_10m_max",
        "wind_speed_unit": "kmh",
        "timezone": "Europe/Rome",
        "forecast_days": 6,
        "forecast_hours": 24,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[WARN]  Errore fetch singola città: {e}")
            return None


WMO_CODES = {
    0: ("Cielo sereno", "01d"),
    1: ("Prevalentemente sereno", "02d"),
    2: ("Parzialmente nuvoloso", "03d"),
    3: ("Nuvoloso", "04d"),
    45: ("Nebbia", "50d"),
    48: ("Nebbia con brina", "50d"),
    51: ("Pioggerella leggera", "09d"),
    53: ("Pioggerella moderata", "09d"),
    55: ("Pioggerella intensa", "09d"),
    61: ("Pioggia leggera", "10d"),
    63: ("Pioggia moderata", "10d"),
    65: ("Pioggia intensa", "10d"),
    71: ("Neve leggera", "13d"),
    73: ("Neve moderata", "13d"),
    75: ("Neve intensa", "13d"),
    80: ("Rovesci leggeri", "09d"),
    81: ("Rovesci moderati", "09d"),
    82: ("Rovesci violenti", "09d"),
    95: ("Temporale", "11d"),
    96: ("Temporale con grandine", "11d"),
    99: ("Temporale con grandine intensa", "11d"),
}


def wmo_to_description(code: int, is_night: bool = False) -> tuple[str, str]:
    desc, icon = WMO_CODES.get(code, ("Condizioni variabili", "02d"))
    if is_night and icon.endswith("d"):
        icon = icon[:-1] + "n"
    return desc, icon


def format_weather_for_frontend(raw_data: dict, city_name: str) -> dict:
    if not raw_data:
        return None

    current = raw_data.get("current", {})
    hourly = raw_data.get("hourly", {})
    daily = raw_data.get("daily", {})

    wmo_code = current.get("weather_code", 0)
    description, icon = wmo_to_description(wmo_code)

    current_formatted = {
        "temp": round(current.get("temperature_2m", 0), 1),
        "feels_like": round(current.get("apparent_temperature", 0), 1),
        "humidity": current.get("relative_humidity_2m", 0),
        "pressure": round(current.get("surface_pressure", 1013), 0),
        "wind_speed": round(current.get("wind_speed_10m", 0), 1),
        "wind_deg": current.get("wind_direction_10m", 0),
        "visibility": 10000,
        "clouds": current.get("cloud_cover", 0),
        "precipitation": current.get("precipitation", 0.0),
        "weather": [{"description": description, "icon": icon}],
    }

    hourly_times = hourly.get("time", [])
    hourly_formatted = []
    for i, t in enumerate(hourly_times[:24]):
        wmo = hourly.get("weather_code", [0] * 24)
        desc_h, icon_h = wmo_to_description(wmo[i] if i < len(wmo) else 0)
        hourly_formatted.append({
            "dt": t,
            "lead_hours": i,
            "temp": round(hourly["temperature_2m"][i], 1) if i < len(hourly.get("temperature_2m", [])) else 0,
            "humidity": hourly["relative_humidity_2m"][i] if i < len(hourly.get("relative_humidity_2m", [])) else 0,
            "cloud_cover": hourly["cloud_cover"][i] if i < len(hourly.get("cloud_cover", [])) else 0,
            "wind_speed": round(hourly["wind_speed_10m"][i], 1) if i < len(hourly.get("wind_speed_10m", [])) else 0,
            "precipitation": hourly["precipitation"][i] if i < len(hourly.get("precipitation", [])) else 0,
            "pop": (hourly["precipitation_probability"][i] or 0) / 100 if i < len(hourly.get("precipitation_probability", [])) else 0,
            "weather": [{"description": desc_h, "icon": icon_h}],
            "weather_code": wmo[i] if i < len(wmo) else 0,
        })

    daily_times = daily.get("time", [])
    daily_formatted = []
    for i, t in enumerate(daily_times[:6]):
        wmo_d = daily.get("weather_code", [0] * 6)
        desc_d, icon_d = wmo_to_description(wmo_d[i] if i < len(wmo_d) else 0)
        daily_formatted.append({
            "dt": t,
            "temp": {
                "min": round(daily["temperature_2m_min"][i], 1) if i < len(daily.get("temperature_2m_min", [])) else 0,
                "max": round(daily["temperature_2m_max"][i], 1) if i < len(daily.get("temperature_2m_max", [])) else 0,
                "day": round((daily["temperature_2m_min"][i] + daily["temperature_2m_max"][i]) / 2, 1) if i < len(daily.get("temperature_2m_min", [])) else 0,
            },
            "humidity": 50,
            "wind_speed": round(daily["wind_speed_10m_max"][i], 1) if i < len(daily.get("wind_speed_10m_max", [])) else 0,
            "pop": (daily["precipitation_probability_max"][i] or 0) / 100 if i < len(daily.get("precipitation_probability_max", [])) else 0,
            "weather": [{"description": desc_d, "icon": icon_d}],
            "weather_code": wmo_d[i] if i < len(wmo_d) else 0,
        })

    return {
        "current": current_formatted,
        "hourly": hourly_formatted,
        "daily": daily_formatted,
        "lat": raw_data.get("latitude"),
        "lon": raw_data.get("longitude"),
        "name": city_name,
        "timezone": "Europe/Rome",
    }
