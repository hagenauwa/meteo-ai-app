"""
weather_service.py — Chiamate Open-Meteo bulk API (gratuita, nessuna chiave)

Open-Meteo supporta fino a 100 location per chiamata.
Con 8.000 comuni → 80 chiamate per coprire tutta Italia.
Limiti gratuiti: 10.000 chiamate/giorno → abbondante.
"""
import asyncio
from typing import List, Optional
import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
BATCH_SIZE = 100    # Max location per singola chiamata Open-Meteo
TIMEOUT = 30        # secondi


async def fetch_weather_batch(
    cities: List[dict],
    client: httpx.AsyncClient
) -> List[dict]:
    """
    Chiama Open-Meteo per un batch di città (max 100).

    cities: lista di dict con {id, name, lat, lon}
    Ritorna lista di dict con {city_id, temp, humidity, cloud_cover, wind_speed, precipitation}
    """
    if not cities:
        return []

    lats = ",".join(str(c["lat"]) for c in cities)
    lons = ",".join(str(c["lon"]) for c in cities)

    params = {
        "latitude": lats,
        "longitude": lons,
        "current": "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,precipitation",
        "wind_speed_unit": "kmh",
        "timezone": "Europe/Rome"
    }

    try:
        response = await client.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[WARN]  Errore Open-Meteo batch: {e}")
        return []

    # Open-Meteo restituisce una lista quando ci sono più location
    if isinstance(data, dict):
        data = [data]

    results = []
    for i, city_data in enumerate(data):
        if i >= len(cities):
            break
        current = city_data.get("current", {})
        results.append({
            "city_id":     cities[i]["id"],
            "temp":        current.get("temperature_2m"),
            "humidity":    current.get("relative_humidity_2m"),
            "cloud_cover": current.get("cloud_cover"),
            "wind_speed":  current.get("wind_speed_10m"),
            "precipitation": current.get("precipitation", 0.0)
        })

    return results


async def fetch_all_cities_weather(cities: List[dict]) -> List[dict]:
    """
    Scarica meteo per tutte le città in batch da BATCH_SIZE.
    Gestisce automaticamente rate-limiting con piccoli ritardi tra batch.
    """
    all_results = []
    batches = [cities[i:i+BATCH_SIZE] for i in range(0, len(cities), BATCH_SIZE)]

    print(f"[API] Scaricando meteo per {len(cities)} città in {len(batches)} batch...")

    async with httpx.AsyncClient() as client:
        for idx, batch in enumerate(batches):
            results = await fetch_weather_batch(batch, client)
            all_results.extend(results)

            # Piccolo ritardo tra batch per non sovraccaricare l'API
            if idx < len(batches) - 1:
                await asyncio.sleep(0.1)

    print(f"[OK] Scaricate {len(all_results)} osservazioni meteo")
    return all_results


async def fetch_single_city(lat: float, lon: float) -> Optional[dict]:
    """
    Scarica meteo per una singola città (usato dalle API del frontend).
    Restituisce anche previsioni orarie e giornaliere per compatibilità.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,cloud_cover,wind_speed_10m,wind_direction_10m,surface_pressure,precipitation,weather_code",
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation_probability,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max,wind_speed_10m_max",
        "wind_speed_unit": "kmh",
        "timezone": "Europe/Rome",
        "forecast_days": 6,
        "forecast_hours": 24
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[WARN]  Errore fetch singola città: {e}")
            return None


# Mappatura codici meteo WMO → descrizione + icona (compatibile con frontend esistente)
WMO_CODES = {
    0:  ("Cielo sereno", "01d"),
    1:  ("Prevalentemente sereno", "02d"),
    2:  ("Parzialmente nuvoloso", "03d"),
    3:  ("Nuvoloso", "04d"),
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


def wmo_to_description(code: int, is_night: bool = False) -> tuple:
    """Converte codice WMO in (descrizione, icona_id)."""
    desc, icon = WMO_CODES.get(code, ("Condizioni variabili", "02d"))
    if is_night and icon.endswith("d"):
        icon = icon[:-1] + "n"
    return desc, icon


def format_weather_for_frontend(raw_data: dict, city_name: str) -> dict:
    """
    Converte risposta Open-Meteo nel formato usato dal frontend existente.
    Mantiene compatibilità con app.js.
    """
    if not raw_data:
        return None

    current = raw_data.get("current", {})
    hourly  = raw_data.get("hourly", {})
    daily   = raw_data.get("daily", {})

    wmo_code = current.get("weather_code", 0)
    description, icon = wmo_to_description(wmo_code)

    # Formato current compatibile con il frontend
    current_formatted = {
        "temp":        round(current.get("temperature_2m", 0), 1),
        "feels_like":  round(current.get("apparent_temperature", 0), 1),
        "humidity":    current.get("relative_humidity_2m", 0),
        "pressure":    round(current.get("surface_pressure", 1013), 0),
        "wind_speed":  round(current.get("wind_speed_10m", 0), 1),
        "wind_deg":    current.get("wind_direction_10m", 0),
        "visibility":  10000,   # Open-Meteo free non fornisce visibilità, default 10km
        "clouds":      current.get("cloud_cover", 0),
        "weather": [{"description": description, "icon": icon}]
    }

    # Previsioni orarie (prossime 24h)
    hourly_times = hourly.get("time", [])
    hourly_formatted = []
    for i, t in enumerate(hourly_times[:24]):
        wmo = hourly.get("weather_code", [0] * 24)
        desc_h, icon_h = wmo_to_description(wmo[i] if i < len(wmo) else 0)
        hourly_formatted.append({
            "dt":         t,
            "temp":       round(hourly["temperature_2m"][i], 1) if i < len(hourly.get("temperature_2m", [])) else 0,
            "humidity":   hourly["relative_humidity_2m"][i] if i < len(hourly.get("relative_humidity_2m", [])) else 0,
            "wind_speed": round(hourly["wind_speed_10m"][i], 1) if i < len(hourly.get("wind_speed_10m", [])) else 0,
            "pop":        (hourly["precipitation_probability"][i] or 0) / 100 if i < len(hourly.get("precipitation_probability", [])) else 0,
            "weather":    [{"description": desc_h, "icon": icon_h}]
        })

    # Previsioni giornaliere (prossimi 5 giorni)
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
            "humidity":   50,
            "wind_speed": round(daily["wind_speed_10m_max"][i], 1) if i < len(daily.get("wind_speed_10m_max", [])) else 0,
            "pop":        (daily["precipitation_probability_max"][i] or 0) / 100 if i < len(daily.get("precipitation_probability_max", [])) else 0,
            "weather":    [{"description": desc_d, "icon": icon_d}]
        })

    return {
        "current": current_formatted,
        "hourly":  hourly_formatted,
        "daily":   daily_formatted,
        "lat":     raw_data.get("latitude"),
        "lon":     raw_data.get("longitude"),
        "name":    city_name,
        "timezone": "Europe/Rome"
    }
