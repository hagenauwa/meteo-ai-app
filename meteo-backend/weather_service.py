"""
weather_service.py — integrazione con Open-Meteo.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
BATCH_SIZE = 100
MAX_CONCURRENCY = 1
TIMEOUT = 30
ML_FORECAST_LEADS = (1, 2, 3, 4, 5, 6)
BATCH_DELAY_SECONDS = 0.75
BATCH_RETRY_DELAYS = (5, 15)
PUBLIC_CACHE_TTL_SECONDS = 300
ROME_TZ = ZoneInfo("Europe/Rome")
METNO_USER_AGENT = "MeteoAI/2.1 https://leprevisioni.netlify.app"
SINGLE_CITY_CURRENT_FIELDS = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,cloud_cover,"
    "wind_speed_10m,wind_direction_10m,surface_pressure,precipitation,weather_code"
)
SINGLE_CITY_DAILY_FIELDS = (
    "temperature_2m_max,temperature_2m_min,weather_code,"
    "precipitation_probability_max,wind_speed_10m_max"
)
SINGLE_CITY_HOURLY_RICH_FIELDS = (
    "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,"
    "precipitation_probability,precipitation,weather_code"
)
SINGLE_CITY_HOURLY_COMPAT_FIELDS = (
    "temperature_2m,relative_humidity_2m,wind_speed_10m,"
    "precipitation_probability,weather_code"
)

logger = logging.getLogger(__name__)
_public_weather_cache: dict[tuple[float, float], tuple[datetime, dict]] = {}


class OpenMeteoRateLimited(Exception):
    """Raised when Open-Meteo returns HTTP 429 and the caller should back off."""


def parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _warn(message: str):
    print(f"[WARN]  {message}")
    logger.warning(message)


def _cache_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 4), round(lon, 4))


def _get_cached_public_weather(lat: float, lon: float) -> Optional[dict]:
    entry = _public_weather_cache.get(_cache_key(lat, lon))
    if not entry:
        return None
    expires_at, payload = entry
    if expires_at <= datetime.now(timezone.utc):
        _public_weather_cache.pop(_cache_key(lat, lon), None)
        return None
    return payload


def _set_cached_public_weather(lat: float, lon: float, payload: dict):
    _public_weather_cache[_cache_key(lat, lon)] = (
        datetime.now(timezone.utc) + timedelta(seconds=PUBLIC_CACHE_TTL_SECONDS),
        payload,
    )


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

    for retry_index, delay in enumerate((0, *BATCH_RETRY_DELAYS), start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            response = await client.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
            break
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                _warn(
                    f"Errore Open-Meteo batch: rate limit 429 sul tentativo {retry_index} "
                    f"(batch di {len(cities)} città)"
                )
                if retry_index == len(BATCH_RETRY_DELAYS) + 1:
                    raise OpenMeteoRateLimited("Open-Meteo rate limited the batch fetch") from exc
                continue
            _warn(f"Errore Open-Meteo batch: {exc}")
            return {"observations": [], "predictions": []}
        except Exception as exc:
            _warn(f"Errore Open-Meteo batch: {exc}")
            return {"observations": [], "predictions": []}

    payload = data if isinstance(data, list) else [data]
    return _build_batch_results(cities, payload)


async def fetch_all_cities_weather(cities: list[dict]) -> dict:
    """
    Scarica meteo per tutte le città in batch con pacing prudente per evitare 429.
    """
    all_observations: list[dict] = []
    all_predictions: list[dict] = []
    batches = [cities[i:i + BATCH_SIZE] for i in range(0, len(cities), BATCH_SIZE)]

    print(f"[API] Scaricando meteo per {len(cities)} città in {len(batches)} batch...")
    async with httpx.AsyncClient() as client:
        for index, batch in enumerate(batches):
            try:
                result = await fetch_weather_batch(batch, client)
            except OpenMeteoRateLimited:
                _warn(
                    f"Scheduler batch interrotto dopo {index} batch su {len(batches)} "
                    f"per ridurre la pressione su Open-Meteo"
                )
                break

            all_observations.extend(result["observations"])
            all_predictions.extend(result["predictions"])

            if index < len(batches) - 1:
                await asyncio.sleep(BATCH_DELAY_SECONDS)

    print(f"[OK] Scaricate {len(all_observations)} osservazioni e {len(all_predictions)} previsioni target-based")
    return {"observations": all_observations, "predictions": all_predictions}


def _build_single_city_params(lat: float, lon: float, hourly_fields: str) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "current": SINGLE_CITY_CURRENT_FIELDS,
        "hourly": hourly_fields,
        "daily": SINGLE_CITY_DAILY_FIELDS,
        "wind_speed_unit": "kmh",
        "timezone": "Europe/Rome",
        "forecast_days": 6,
        "forecast_hours": 24,
    }


def _response_snippet(response: httpx.Response | None) -> str:
    if response is None:
        return ""
    try:
        text = response.text
    except Exception:
        return ""
    return " ".join(text.split())[:300]


def _response_snippet_from_text(text: str) -> str:
    return " ".join(text.split())[:300]


def _validate_single_city_payload(data: object, *, params: dict, attempt_name: str) -> Optional[dict]:
    if not isinstance(data, dict):
        logger.warning(
            "Open-Meteo single-city schema_mismatch (%s) lat=%s lon=%s: expected dict got %s",
            attempt_name,
            params.get("latitude"),
            params.get("longitude"),
            type(data).__name__,
        )
        return None

    missing_sections = [section for section in ("current", "hourly", "daily") if section not in data]
    if missing_sections:
        logger.warning(
            "Open-Meteo single-city schema_mismatch (%s) lat=%s lon=%s missing=%s keys=%s",
            attempt_name,
            params.get("latitude"),
            params.get("longitude"),
            ",".join(missing_sections),
            ",".join(sorted(data.keys())[:10]),
        )
        return None

    return data


async def _fetch_open_meteo_payload(
    client: httpx.AsyncClient,
    *,
    params: dict,
    attempt_name: str,
) -> Optional[dict]:
    response: httpx.Response | None = None
    try:
        response = await client.get(
            OPEN_METEO_URL,
            params=params,
            timeout=TIMEOUT,
            headers={"User-Agent": METNO_USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException as exc:
        _warn(
            "Open-Meteo single-city timeout "
            f"({attempt_name}) lat={params.get('latitude')} lon={params.get('longitude')}: {exc}"
        )
        return None
    except httpx.HTTPStatusError as exc:
        _warn(
            "Open-Meteo single-city http_error "
            f"({attempt_name}) lat={params.get('latitude')} lon={params.get('longitude')} "
            f"status={exc.response.status_code if exc.response else 'unknown'} "
            f"body={_response_snippet(exc.response)}"
        )
        return None
    except httpx.RequestError as exc:
        _warn(
            "Open-Meteo single-city network_error "
            f"({attempt_name}) lat={params.get('latitude')} lon={params.get('longitude')}: {exc}"
        )
        return None
    except ValueError as exc:
        _warn(
            "Open-Meteo single-city invalid_json "
            f"({attempt_name}) lat={params.get('latitude')} lon={params.get('longitude')} "
            f"body={_response_snippet(response)} error={exc}"
        )
        return None

    return _validate_single_city_payload(data, params=params, attempt_name=attempt_name)


def _fetch_open_meteo_payload_via_urllib(*, params: dict, attempt_name: str) -> Optional[dict]:
    url = f"{OPEN_METEO_URL}?{urlencode(params)}"
    try:
        request = Request(url, headers={"User-Agent": METNO_USER_AGENT})
        with urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        _warn(
            "Open-Meteo single-city http_error "
            f"({attempt_name}) lat={params.get('latitude')} lon={params.get('longitude')} "
            f"status={exc.code} body={_response_snippet_from_text(body)}"
        )
        return None
    except URLError as exc:
        _warn(
            "Open-Meteo single-city network_error "
            f"({attempt_name}) lat={params.get('latitude')} lon={params.get('longitude')}: {exc.reason}"
        )
        return None
    except TimeoutError as exc:
        _warn(
            "Open-Meteo single-city timeout "
            f"({attempt_name}) lat={params.get('latitude')} lon={params.get('longitude')}: {exc}"
        )
        return None

    try:
        data = json.loads(body)
    except ValueError as exc:
        _warn(
            "Open-Meteo single-city invalid_json "
            f"({attempt_name}) lat={params.get('latitude')} lon={params.get('longitude')} "
            f"body={_response_snippet_from_text(body)} error={exc}"
        )
        return None

    return _validate_single_city_payload(data, params=params, attempt_name=attempt_name)


def _metno_symbol_to_wmo(symbol_code: str | None) -> int:
    if not symbol_code:
        return 2
    base = symbol_code
    for suffix in ("_day", "_night", "_polartwilight"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break

    if "thunder" in base:
        return 95
    if "snow" in base:
        if "heavy" in base:
            return 75
        if "light" in base:
            return 71
        return 73
    if "sleet" in base:
        return 61
    if "showers" in base:
        if "heavy" in base:
            return 82
        if "light" in base:
            return 80
        return 81
    if "rain" in base:
        if "heavy" in base:
            return 65
        if "light" in base:
            return 61
        return 63
    if "fog" in base:
        return 45
    if base == "clearsky":
        return 0
    if base == "fair":
        return 1
    if base == "partlycloudy":
        return 2
    if base == "cloudy":
        return 3
    return 2


def _format_local_hour(dt: datetime) -> str:
    return dt.astimezone(ROME_TZ).strftime("%Y-%m-%dT%H:%M")


def _format_local_day(dt: datetime) -> str:
    return dt.astimezone(ROME_TZ).strftime("%Y-%m-%d")


def _convert_metno_to_open_meteo_payload(payload: dict, *, lat: float, lon: float) -> Optional[dict]:
    try:
        timeseries = payload["properties"]["timeseries"]
    except (KeyError, TypeError):
        return None

    if not timeseries:
        return None

    hourly_items = []
    daily_groups: dict[str, list[dict]] = {}
    for item in timeseries:
        timestamp = parse_utc_timestamp(item["time"])
        details = item["data"]["instant"]["details"]
        next_1 = item["data"].get("next_1_hours", {})
        summary = next_1.get("summary") or item["data"].get("next_6_hours", {}).get("summary") or {}
        precipitation = (next_1.get("details") or {}).get("precipitation_amount", 0.0)
        weather_code = _metno_symbol_to_wmo(summary.get("symbol_code"))

        hourly_entry = {
            "timestamp": timestamp,
            "local_hour": _format_local_hour(timestamp),
            "local_day": _format_local_day(timestamp),
            "temp": details.get("air_temperature", 0.0),
            "humidity": details.get("relative_humidity", 0),
            "cloud_cover": details.get("cloud_area_fraction", 0),
            "wind_speed": (details.get("wind_speed", 0.0) or 0.0) * 3.6,
            "wind_direction": details.get("wind_from_direction", 0),
            "pressure": details.get("air_pressure_at_sea_level", 1013),
            "precipitation": precipitation or 0.0,
            "precipitation_probability": 100 if (precipitation or 0.0) > 0 else 0,
            "weather_code": weather_code,
        }
        hourly_items.append(hourly_entry)
        daily_groups.setdefault(hourly_entry["local_day"], []).append(hourly_entry)

    current_hour = hourly_items[0]
    daily_keys = sorted(daily_groups.keys())[:6]
    daily = {
        "time": daily_keys,
        "temperature_2m_min": [],
        "temperature_2m_max": [],
        "weather_code": [],
        "precipitation_probability_max": [],
        "wind_speed_10m_max": [],
    }

    for day in daily_keys:
        items = daily_groups[day]
        temps = [entry["temp"] for entry in items]
        winds = [entry["wind_speed"] for entry in items]
        pops = [entry["precipitation_probability"] for entry in items]
        preferred = next((entry for entry in items if entry["local_hour"].endswith("12:00")), items[len(items) // 2])
        common_code = Counter(entry["weather_code"] for entry in items).most_common(1)[0][0]
        daily["temperature_2m_min"].append(min(temps))
        daily["temperature_2m_max"].append(max(temps))
        daily["weather_code"].append(preferred["weather_code"] or common_code)
        daily["precipitation_probability_max"].append(max(pops))
        daily["wind_speed_10m_max"].append(max(winds))

    return {
        "latitude": lat,
        "longitude": lon,
        "timezone": "Europe/Rome",
        "current": {
            "time": current_hour["local_hour"],
            "temperature_2m": current_hour["temp"],
            "relative_humidity_2m": current_hour["humidity"],
            "apparent_temperature": current_hour["temp"],
            "cloud_cover": current_hour["cloud_cover"],
            "wind_speed_10m": current_hour["wind_speed"],
            "wind_direction_10m": current_hour["wind_direction"],
            "surface_pressure": current_hour["pressure"],
            "precipitation": current_hour["precipitation"],
            "weather_code": current_hour["weather_code"],
        },
        "hourly": {
            "time": [entry["local_hour"] for entry in hourly_items[:24]],
            "temperature_2m": [entry["temp"] for entry in hourly_items[:24]],
            "relative_humidity_2m": [entry["humidity"] for entry in hourly_items[:24]],
            "cloud_cover": [entry["cloud_cover"] for entry in hourly_items[:24]],
            "wind_speed_10m": [entry["wind_speed"] for entry in hourly_items[:24]],
            "precipitation_probability": [entry["precipitation_probability"] for entry in hourly_items[:24]],
            "precipitation": [entry["precipitation"] for entry in hourly_items[:24]],
            "weather_code": [entry["weather_code"] for entry in hourly_items[:24]],
        },
        "daily": daily,
    }


async def _fetch_metno_payload(lat: float, lon: float) -> Optional[dict]:
    headers = {"User-Agent": METNO_USER_AGENT}
    params = {"lat": lat, "lon": lon}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(METNO_URL, params=params, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        _warn(f"Fallback met.no fallito lat={lat} lon={lon}: {exc}")
        return None

    converted = _convert_metno_to_open_meteo_payload(data, lat=lat, lon=lon)
    if not converted:
        _warn(f"Fallback met.no ha restituito payload non convertibile lat={lat} lon={lon}")
    return converted


async def fetch_single_city(lat: float, lon: float) -> Optional[dict]:
    """
    Scarica meteo per una singola città per il frontend pubblico.
    """
    cached = _get_cached_public_weather(lat, lon)
    if cached is not None:
        return cached

    async with httpx.AsyncClient() as client:
        attempts = (
            ("rich", SINGLE_CITY_HOURLY_RICH_FIELDS),
            ("compat", SINGLE_CITY_HOURLY_COMPAT_FIELDS),
        )

        for attempt_name, hourly_fields in attempts:
            params = _build_single_city_params(lat, lon, hourly_fields)
            data = await _fetch_open_meteo_payload(client, params=params, attempt_name=attempt_name)
            if data is not None:
                if attempt_name == "compat":
                    logger.warning(
                        "Open-Meteo single-city fallback_succeeded lat=%s lon=%s attempt=%s",
                        lat,
                        lon,
                        attempt_name,
                    )
                _set_cached_public_weather(lat, lon, data)
                return data

    compat_params = _build_single_city_params(lat, lon, SINGLE_CITY_HOURLY_COMPAT_FIELDS)
    data = await asyncio.to_thread(
        _fetch_open_meteo_payload_via_urllib,
        params=compat_params,
        attempt_name="compat-urllib",
    )
    if data is not None:
        logger.warning("Open-Meteo single-city fallback_succeeded lat=%s lon=%s attempt=%s", lat, lon, "compat-urllib")
        _set_cached_public_weather(lat, lon, data)
        return data

    data = await _fetch_metno_payload(lat, lon)
    if data is not None:
        _warn(f"Single-city weather served via met.no fallback lat={lat} lon={lon}")
        _set_cached_public_weather(lat, lon, data)
        return data

    logger.warning("Open-Meteo single-city fetch failed after fallback lat=%s lon=%s", lat, lon)
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
