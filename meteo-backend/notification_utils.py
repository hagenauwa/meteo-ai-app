"""
notification_utils.py — logica condivisa per notifiche meteo.

Modulo fondazione per Telegram e push Web:
  - Cache geocoding con TTL
  - Integrazione modello ML per pioggia
  - Logica trigger adattiva (POP + ML + weather_code)
  - Utilità comuni per messaggi e formattazione
"""

from __future__ import annotations

import html
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ml_model import RAIN_WEATHER_CODES, predict_rain_probability
from weather_service import wmo_to_description

logger = logging.getLogger(__name__)

# ─── Costanti ────────────────────────────────────────────────────────────────

RAIN_POP_THRESHOLD = 0.50  # Soglia POP ridotta da 60% a 50%
RAIN_ML_THRESHOLD = 0.40  # Soglia ML per trigger combinato
MAX_LEAD_HOURS = 6  # Finestra previsione ore
RAIN_ALERT_COOLDOWN_HOURS = 2  # Cooldown ridotto da 6 a 2 ore

# Cache geocoding: {city_name: (lat, lon, timestamp)}
_geocoding_cache: dict[str, tuple[float, float, float]] = {}
GEOCODING_CACHE_TTL_SECONDS = 86400  # 24 ore


# ─── Geocoding con cache ─────────────────────────────────────────────────────


def _is_rain_weather_code(code: int | None) -> bool:
    """Verifica se il codice WMO indica pioggia."""
    if code is None:
        return False
    return code in RAIN_WEATHER_CODES


def _wmo_rain_description(code: int) -> str:
    """Restituisce la descrizione testuale di un codice WMO di pioggia."""
    desc, _ = wmo_to_description(code)
    return desc


def get_cached_coords(city_name: str) -> tuple[float | None, float | None]:
    """Restituisce coordinate dalla cache se disponibili e non scadute."""
    if not city_name:
        return None, None

    entry = _geocoding_cache.get(city_name)
    if not entry:
        return None, None

    lat, lon, timestamp = entry
    if time.time() - timestamp > GEOCODING_CACHE_TTL_SECONDS:
        _geocoding_cache.pop(city_name, None)
        return None, None

    return lat, lon


def set_cached_coords(city_name: str, lat: float, lon: float) -> None:
    """Memorizza coordinate in cache."""
    if city_name and lat is not None and lon is not None:
        _geocoding_cache[city_name] = (lat, lon, time.time())


async def resolve_city_coords(city_name: str) -> tuple[float | None, float | None]:
    """
    Risolve il nome della città in coordinate.
    Prima controlla la cache, poi chiama Open-Meteo geocoding.
    """
    if not city_name:
        return None, None

    # Check cache
    cached_lat, cached_lon = get_cached_coords(city_name)
    if cached_lat is not None and cached_lon is not None:
        return cached_lat, cached_lon

    # Fetch da Open-Meteo
    try:
        async with httpx.AsyncClient() as client:
            params = {
                "name": city_name,
                "count": 1,
                "language": "it",
                "format": "json",
                "countryCode": "IT",
            }
            resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                lat = results[0]["latitude"]
                lon = results[0]["longitude"]
                set_cached_coords(city_name, lat, lon)
                return lat, lon
    except Exception as exc:
        logger.warning(f"Geocoding fallito per {city_name}: {exc}")

    return None, None


# ─── Integrazione ML ─────────────────────────────────────────────────────────


def get_ml_rain_probability(
    *,
    lat: float,
    lon: float,
    city_name: str | None = None,
    forecast_temp: float,
    humidity: float,
    hour: int,
    month: int,
    cloud_cover: float = 50.0,
    lead_hours: int = 0,
    forecast_precipitation: float | None = None,
    forecast_wind_speed: float | None = None,
    forecast_wind_direction: float | None = None,
    forecast_weather_code: int | None = None,
    region: str = "Sconosciuta",
) -> dict:
    """
    Ottiene la probabilità di pioggia dal modello ML.
    Restituisce dict con rain_probability, model_ready, confidence.
    """
    try:
        result = predict_rain_probability(
            forecast_temp=forecast_temp,
            humidity=humidity,
            hour=hour,
            month=month,
            lat=lat,
            region=region,
            cloud_cover=cloud_cover,
            lead_hours=lead_hours,
            lon=lon,
            forecast_precipitation=forecast_precipitation,
            forecast_wind_speed=forecast_wind_speed,
            forecast_wind_direction=forecast_wind_direction,
            forecast_weather_code=forecast_weather_code,
            city_name=city_name,
        )
        return result
    except Exception as exc:
        logger.warning(f"Errore predizione ML pioggia: {exc}")
        return {
            "rain_probability": 0.0,
            "model_ready": False,
            "confidence": "bassa",
            "error": str(exc),
        }


# ─── Logica trigger pioggia ──────────────────────────────────────────────────


def check_hourly_rain_adaptive(
    hourly: dict,
    *,
    lat: float,
    lon: float,
    city_name: str | None = None,
    region: str = "Sconosciuta",
    max_lead_hours: int = MAX_LEAD_HOURS,
    ml_coverage: bool = True,
) -> dict | None:
    """
    Scansiona le previsioni orarie con logica adattiva:
    - POP >= 50% AND (weather_code pioggia OR ML >= 40% OR precipitazione > 0.1mm)

    Restituisce il primo orario che soddisfa il trigger, o None.
    """
    times = hourly.get("time", [])
    if not times:
        return None

    pops = hourly.get("precipitation_probability", [])
    weather_codes = hourly.get("weather_code", [])
    precipitations = hourly.get("precipitation", [])
    temperatures = hourly.get("temperature_2m", [])
    humidities = hourly.get("relative_humidity_2m", [])
    cloud_covers = hourly.get("cloud_cover", [])
    wind_speeds = hourly.get("wind_speed_10m", [])
    wind_directions = hourly.get("wind_direction_10m", [])

    now = datetime.now(ZoneInfo("Europe/Rome"))

    for i, time_str in enumerate(times):
        if i >= max_lead_hours:
            break

        pop = (pops[i] if i < len(pops) else 0) or 0
        weather_code = weather_codes[i] if i < len(weather_codes) else None
        precipitation = precipitations[i] if i < len(precipitations) else 0

        pop_fraction = pop / 100.0
        meets_pop = pop_fraction >= RAIN_POP_THRESHOLD
        meets_wmo = _is_rain_weather_code(weather_code)
        meets_precip = (precipitation or 0) > 0.1

        # Se POP basso e non piove secondo WMO, salta
        if not meets_pop and not meets_wmo and not meets_precip:
            continue

        # Calcola lead_hours dall'orario previsto
        forecast_hour = now.hour
        try:
            forecast_time = datetime.fromisoformat(time_str)
            if forecast_time.tzinfo is None:
                forecast_time = forecast_time.replace(tzinfo=timezone.utc)
            forecast_hour = forecast_time.hour
            lead_hours = max(
                0,
                int(
                    (forecast_time - now.replace(tzinfo=timezone.utc)).total_seconds()
                    / 3600
                ),
            )
        except (ValueError, TypeError):
            lead_hours = i

        # Ottieni ML probability solo se la città è nell'area coperta dal modello:
        # fuori area sarebbe un'estrapolazione fuorviante (serving onesto).
        if ml_coverage:
            ml_result = get_ml_rain_probability(
                lat=lat,
                lon=lon,
                city_name=city_name,
                forecast_temp=temperatures[i] if i < len(temperatures) else 20.0,
                humidity=humidities[i] if i < len(humidities) else 50.0,
                hour=forecast_hour,
                month=now.month,
                cloud_cover=cloud_covers[i] if i < len(cloud_covers) else 50.0,
                lead_hours=lead_hours,
                forecast_precipitation=precipitation,
                forecast_wind_speed=wind_speeds[i] if i < len(wind_speeds) else None,
                forecast_wind_direction=wind_directions[i]
                if i < len(wind_directions)
                else None,
                forecast_weather_code=weather_code,
                region=region,
            )
        else:
            ml_result = {
                "rain_probability": 0.0,
                "model_ready": False,
                "will_rain": False,
                "confidence": "bassa",
            }

        ml_prob = ml_result.get("rain_probability", 0.0)
        ml_ready = ml_result.get("model_ready", False)
        # will_rain usa la probabilità CALIBRATA e la soglia ottimizzata su F1 del
        # modello (fallback alla soglia fissa solo per modelli senza will_rain).
        ml_will_rain = bool(ml_result.get("will_rain", ml_prob >= RAIN_ML_THRESHOLD))

        # Trigger adattivo:
        # 1. POP >= 50% AND weather_code pioggia → sempre trigger
        # 2. POP >= 50% AND il modello ML prevede pioggia → trigger (ML conferma)
        # 3. POP >= 50% AND precipitazione > 0.1mm → trigger (dati reali)
        trigger = False
        trigger_reason = ""

        if meets_pop and meets_wmo:
            trigger = True
            trigger_reason = "wmo_rain"
        elif meets_pop and ml_ready and ml_will_rain:
            trigger = True
            trigger_reason = "ml_confirmed"
        elif meets_pop and meets_precip:
            trigger = True
            trigger_reason = "precipitation"
        elif meets_wmo and ml_ready and ml_will_rain:
            trigger = True
            trigger_reason = "wmo_with_ml_support"

        if trigger:
            return {
                "hour_index": i,
                "time": time_str,
                "pop": pop_fraction,
                "weather_code": weather_code,
                "precipitation": precipitation,
                "description": _wmo_rain_description(weather_code)
                if weather_code
                else "Pioggia prevista",
                "ml_probability": ml_prob,
                "ml_ready": ml_ready,
                "trigger_reason": trigger_reason,
                "confidence": ml_result.get("confidence", "bassa"),
            }

    return None


def find_rain_time_slots(hourly: dict, threshold: float = 0.40) -> list[str]:
    """
    Scansiona TUTTE le ore disponibili e raggruppa quelle piovose in range consecutivi.
    Restituisce max 3 periodi formattati come "14:00-16:00" o "14:00" per singola ora.
    """
    times = hourly.get("time", [])
    pops = hourly.get("precipitation_probability", [])
    weather_codes = hourly.get("weather_code", [])
    precipitations = hourly.get("precipitation", [])

    if not times:
        return []

    rainy_indices: list[int] = []
    for i, time_str in enumerate(times):
        pop = (pops[i] if i < len(pops) else 0) or 0
        weather_code = weather_codes[i] if i < len(weather_codes) else None
        precipitation = precipitations[i] if i < len(precipitations) else 0

        meets_pop = pop >= threshold * 100
        meets_wmo = _is_rain_weather_code(weather_code)
        meets_precip = (precipitation or 0) > 0.1

        if meets_pop or meets_wmo or meets_precip:
            rainy_indices.append(i)

    if not rainy_indices:
        return []

    # Raggruppa indici consecutivi in range
    ranges: list[tuple[int, int]] = []
    start = rainy_indices[0]
    end = rainy_indices[0]
    for idx in rainy_indices[1:]:
        if idx == end + 1:
            end = idx
        else:
            ranges.append((start, end))
            start = idx
            end = idx
    ranges.append((start, end))

    # Formatta: "HH:MM-HH:MM" per range, "HH:MM" per singola ora; max 3
    result: list[str] = []
    for start_idx, end_idx in ranges[:3]:
        start_time = times[start_idx]
        end_time = times[end_idx]
        start_hm = start_time[11:16]
        end_hm = end_time[11:16]
        if start_idx == end_idx:
            result.append(start_hm)
        else:
            result.append(f"{start_hm}-{end_hm}")

    return result


# ─── Cooldown management ─────────────────────────────────────────────────────


def should_notify_rain(last_alert_at: datetime | None, now: datetime) -> bool:
    """Verifica se è passato abbastanza tempo dall'ultima notifica pioggia."""
    if last_alert_at is None:
        return True

    # Normalizza timezone
    if last_alert_at.tzinfo is None:
        last_alert_at = last_alert_at.replace(tzinfo=timezone.utc)

    cooldown_cutoff = now - timedelta(hours=RAIN_ALERT_COOLDOWN_HOURS)
    return last_alert_at < cooldown_cutoff


def should_notify_daily(
    last_daily_at: datetime | None,
    daily_forecast_hour: int | None,
    now: datetime,
) -> bool:
    """Verifica se è il momento di inviare il promemoria giornaliero.

    Invia una sola volta per giorno (data locale Europe/Rome), all'ora scelta o
    subito dopo: così un cron in ritardo a cavallo dell'ora non salta del tutto il
    promemoria di quel giorno (catch-up). daily_forecast_hour None usa default 8.
    """
    target_hour = daily_forecast_hour if daily_forecast_hour is not None else 8
    now_rome = now.astimezone(ZoneInfo("Europe/Rome"))
    if now_rome.hour < target_hour:
        return False

    if last_daily_at is None:
        return True

    if last_daily_at.tzinfo is None:
        last_daily_at = last_daily_at.replace(tzinfo=timezone.utc)
    # Già inviato oggi (confronto sulla data locale Roma)?
    return last_daily_at.astimezone(ZoneInfo("Europe/Rome")).date() < now_rome.date()


# ─── Formattazione messaggi ──────────────────────────────────────────────────


def build_rain_message(city_name: str, rain_info: dict) -> str:
    """
    Costruisce il messaggio HTML per l'allerta pioggia.
    Include informazioni ML se disponibili.
    """
    pop_pct = round(rain_info["pop"] * 100)
    description = rain_info.get("description", "Pioggia prevista")
    precip_mm = rain_info.get("precipitation", 0)
    ml_prob = rain_info.get("ml_probability")
    ml_ready = rain_info.get("ml_ready", False)
    confidence = rain_info.get("confidence", "")
    trigger_reason = rain_info.get("trigger_reason", "")

    # Header
    message = f"🌧️ <b>Sta per piovere a {html.escape(city_name)}!</b>\n\n"

    # Descrizione condizioni
    message += f"{description}\n"

    # Probabilità POP
    message += f"💧 Probabilità: {pop_pct}%\n"

    # Precipitazione prevista
    if precip_mm and precip_mm > 0:
        message += f"🌧️ Previsione: {precip_mm:.1f}mm di pioggia\n"

    # Informazioni ML (se disponibili)
    if ml_ready and ml_prob is not None:
        ml_pct = round(ml_prob * 100)
        message += f"🤖 Modello ML: {ml_pct}%"
        if confidence:
            message += f" (confidenza {confidence})"
        message += "\n"

    # Motivo del trigger (debug, utile per capire)
    if trigger_reason:
        reason_labels = {
            "wmo_rain": "Codice meteo pioggia",
            "ml_confirmed": "Confermato dal modello ML",
            "precipitation": "Precipitazione rilevata",
            "wmo_with_ml_support": "Codice meteo + supporto ML",
        }
        reason_text = reason_labels.get(trigger_reason, trigger_reason)
        message += f"📊 Trigger: {reason_text}\n"

    return message


def _derive_daily_weather_code_from_hourly(
    daily: dict,
    hourly: dict,
    today_idx: int,
    fallback_code: int | None,
) -> int | None:
    """
    Preferisce il quadro orario quando il codice giornaliero Open-Meteo è troppo
    pessimista per una giornata quasi tutta serena.

    Il daily `weather_code` di Open-Meteo sintetizza l'intera giornata e può
    diventare "Nuvoloso" anche con molte ore soleggiate. Per il promemoria
    giornaliero è più utile descrivere le ore disponibili della data, mantenendo
    comunque priorità assoluta a pioggia/nebbia quando sono presenti.
    """
    daily_times = daily.get("time", [])
    if today_idx >= len(daily_times):
        return fallback_code

    day_prefix = str(daily_times[today_idx])
    hourly_times = hourly.get("time", [])
    if not hourly_times:
        return fallback_code

    codes = hourly.get("weather_code", [])
    clouds = hourly.get("cloud_cover", [])
    pops = hourly.get("precipitation_probability", [])
    precipitations = hourly.get("precipitation", [])

    relevant: list[tuple[int | None, float | None, float, float]] = []
    for idx, time_str in enumerate(hourly_times):
        if not str(time_str).startswith(day_prefix):
            continue
        code = codes[idx] if idx < len(codes) else None
        cloud = clouds[idx] if idx < len(clouds) else None
        pop = (pops[idx] if idx < len(pops) else 0) or 0
        precipitation = (precipitations[idx] if idx < len(precipitations) else 0) or 0
        relevant.append((code, cloud, pop, precipitation))

    if not relevant:
        return fallback_code

    if any(
        _is_rain_weather_code(code) or precipitation > 0.1
        for code, _, _, precipitation in relevant
    ):
        return fallback_code
    if any((pop or 0) >= 40 for _, _, pop, _ in relevant):
        return fallback_code

    non_null_clouds = [cloud for _, cloud, _, _ in relevant if cloud is not None]
    avg_cloud = sum(non_null_clouds) / len(non_null_clouds) if non_null_clouds else None
    max_cloud = max(non_null_clouds) if non_null_clouds else None
    codes_present = [code for code, _, _, _ in relevant if code is not None]

    if 45 in codes_present or 48 in codes_present:
        return fallback_code

    cloudy_fraction = (
        sum(1 for code in codes_present if code == 3) / len(codes_present)
        if codes_present
        else 0
    )
    partly_fraction = (
        sum(1 for code in codes_present if code == 2) / len(codes_present)
        if codes_present
        else 0
    )

    if avg_cloud is not None:
        if avg_cloud <= 20 and (max_cloud or 0) <= 35:
            return 0
        if avg_cloud <= 35 and cloudy_fraction < 0.25:
            return 1
        if avg_cloud <= 65 or partly_fraction >= 0.35:
            return 2
        return 3

    if cloudy_fraction >= 0.5:
        return 3
    if partly_fraction >= 0.35:
        return 2
    if codes_present:
        return 1 if 1 in codes_present else 0
    return fallback_code


def _series_value(seq: Any, idx: int) -> Any:
    """Accesso sicuro a una serie giornaliera: None se assente o fuori range."""
    if isinstance(seq, list) and 0 <= idx < len(seq):
        return seq[idx]
    return None


def build_daily_message(
    city_name: str,
    daily: dict,
    hourly: dict,
    today_idx: int = 0,
) -> str:
    """
    Costruisce il messaggio HTML per il promemoria giornaliero.
    Include previsioni sintetiche con emoji e dettagli pioggia.
    """
    max_temp = _series_value(daily.get("temperature_2m_max"), today_idx)
    min_temp = _series_value(daily.get("temperature_2m_min"), today_idx)
    daily_weather_code = _series_value(daily.get("weather_code"), today_idx)
    weather_code = _derive_daily_weather_code_from_hourly(
        daily, hourly, today_idx, daily_weather_code
    )
    precip_prob = _series_value(daily.get("precipitation_probability_max"), today_idx)
    precip_sum = _series_value(daily.get("precipitation_sum"), today_idx)

    # Descrizione meteo
    if weather_code is not None:
        description, _ = wmo_to_description(weather_code)
    else:
        description = "Condizioni non disponibili"

    # Emoji in base al meteo
    if weather_code is not None and _is_rain_weather_code(weather_code):
        emoji = "🌧️"
    elif weather_code is not None and weather_code in (0, 1):
        emoji = "☀️"
    elif weather_code is not None and weather_code in (2, 3):
        emoji = "⛅"
    else:
        emoji = "🌤️"

    # Costruzione messaggio
    message = f"{emoji} <b>Previsioni per {html.escape(city_name)}</b>\n\n"

    if max_temp is not None and min_temp is not None:
        message += f"🌡️ Temperatura: {min_temp:.0f}° - {max_temp:.0f}°\n"
    message += f"📋 Condizioni: {description}\n"

    if precip_prob is not None:
        message += f"💧 Probabilità pioggia: {precip_prob}%\n"
    if precip_sum is not None and precip_sum > 0:
        message += f"🌧️ Precipitazioni: {precip_sum:.1f}mm\n"

    # Vento medio prime 12 ore
    wind_speeds = hourly.get("wind_speed_10m", [])
    if wind_speeds:
        avg_wind = sum(wind_speeds[:12]) / min(12, len(wind_speeds))
        message += f"💨 Vento medio: {avg_wind:.0f} km/h\n"

    # Fascie orarie pioggia (find_rain_time_slots limita già a max 3 periodi)
    rain_slots = find_rain_time_slots(hourly)
    if rain_slots:
        message += f"🌧️ Pioggia prevista: {', '.join(rain_slots)}\n"
    else:
        message += "☀️ Nessuna pioggia prevista\n"

    message += "\nBuona giornata! ☕"

    return message
