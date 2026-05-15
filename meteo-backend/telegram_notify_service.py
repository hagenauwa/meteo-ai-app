"""
telegram_notify_service.py — servizio notifiche Telegram per pioggia e promemoria giornaliero.

Logica:
  - Allerte pioggia: stessa logica di rain_alert_service.py ma invia via Telegram
  - Promemoria giornaliero: invia previsione sintetica all'ora preferita
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from config import settings
from database import TelegramSubscription, SessionLocal
from weather_service import fetch_single_city, wmo_to_description
from ml_model import RAIN_WEATHER_CODES
from telegram_bot import send_telegram_message

logger = logging.getLogger(__name__)

RAIN_ALERT_COOLDOWN_HOURS = 6
RAIN_POP_THRESHOLD = 0.60
RAIN_ML_THRESHOLD = 0.50
MAX_LEAD_HOURS = 6


def _is_rain_weather_code(code: int | None) -> bool:
    if code is None:
        return False
    return code in RAIN_WEATHER_CODES


def _wmo_rain_description(code: int) -> str:
    desc, _ = wmo_to_description(code)
    return desc


def _find_rain_time_slots(hourly: dict, threshold: float = 0.40) -> list[str]:
    """
    Scansiona TUTTE le ore disponibili e raggruppa quelle piovose in range consecutivi.

    Un'ora è piovosa se:
      - precipitation_probability >= threshold * 100  OPPURE
      - weather_code in RAIN_WEATHER_CODES           OPPURE
      - precipitation > 0.1

    Ritorna max 3 periodi formattati come "14:00-16:00" o "14:00" per singola ora.
    Se nessuna ora piovosa ritorna [].
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
        start_hm = start_time[11:16]  # "14:00" da "2024-01-01T14:00"
        end_hm = end_time[11:16]
        if start_idx == end_idx:
            result.append(start_hm)
        else:
            result.append(f"{start_hm}-{end_hm}")

    return result


def _check_hourly_rain(hourly: dict, max_lead_hours: int = MAX_LEAD_HOURS) -> dict | None:
    """Scansiona le previsioni orarie per trovare pioggia nelle prossime N ore."""
    times = hourly.get("time", [])
    if not times:
        return None

    pops = hourly.get("precipitation_probability", [])
    weather_codes = hourly.get("weather_code", [])
    precipitations = hourly.get("precipitation", [])

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

        if meets_pop and (meets_wmo or meets_precip):
            return {
                "hour_index": i,
                "time": time_str,
                "pop": pop_fraction,
                "weather_code": weather_code,
                "precipitation": precipitation,
                "description": _wmo_rain_description(weather_code) if weather_code else "Pioggia prevista",
            }

    return None


def _build_rain_message_telegram(city_name: str, rain_info: dict) -> str:
    """Costruisce il messaggio Telegram per l'allerta pioggia."""
    pop_pct = round(rain_info["pop"] * 100)
    description = rain_info.get("description", "Pioggia prevista")
    precip_mm = rain_info.get("precipitation", 0)

    if precip_mm and precip_mm > 0:
        return (
            f"🌧️ <b>Sta per piovere a {city_name}!</b>\n\n"
            f"{description}\n"
            f"Probabilità: {pop_pct}%\n"
            f"Previsione: {precip_mm:.1f}mm di pioggia"
        )
    return (
        f"🌧️ <b>Sta per piovere a {city_name}!</b>\n\n"
        f"{description}\n"
        f"Probabilità: {pop_pct}% nelle prossime ore"
    )


async def _resolve_city_coords(city_name: str) -> tuple[float | None, float | None]:
    """Risolve il nome della città in coordinate via Open-Meteo geocoding."""
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
                return results[0]["latitude"], results[0]["longitude"]
    except Exception as exc:
        logger.warning(f"Geocoding fallito per {city_name}: {exc}")

    return None, None


def _should_notify_rain(sub: TelegramSubscription, now: datetime) -> bool:
    """Verifica se la subscription può ricevere un'allerta pioggia (cooldown)."""
    if not sub.rain_alerts_enabled or not sub.chat_id:
        return False
    if sub.last_rain_alert_at is None:
        return True
    cooldown_cutoff = now - timedelta(hours=RAIN_ALERT_COOLDOWN_HOURS)
    return sub.last_rain_alert_at < cooldown_cutoff


def _should_notify_daily(sub: TelegramSubscription, now: datetime) -> bool:
    """Verifica se è il momento di inviare il promemoria giornaliero."""
    if not sub.daily_forecast_enabled or not sub.chat_id:
        return False

    current_hour = now.astimezone(ZoneInfo("Europe/Rome")).hour
    if current_hour != sub.daily_forecast_hour:
        return False

    if sub.last_daily_forecast_at is None:
        return True

    # Evita duplicati nella stessa ora
    last = sub.last_daily_forecast_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last).total_seconds() > 3500  # ~58 minuti


def _mark_rain_notified(sub_id: int, now: datetime):
    """Aggiorna il timestamp dell'ultima notifica pioggia."""
    with SessionLocal() as db:
        sub = db.get(TelegramSubscription, sub_id)
        if sub:
            sub.last_rain_alert_at = now
            db.commit()


def _mark_daily_notified(sub_id: int, now: datetime):
    """Aggiorna il timestamp dell'ultimo promemoria giornaliero."""
    with SessionLocal() as db:
        sub = db.get(TelegramSubscription, sub_id)
        if sub:
            sub.last_daily_forecast_at = now
            db.commit()


async def _fetch_and_check_rain(sub: TelegramSubscription, now: datetime) -> dict:
    """Controlla se pioverà per la città della subscription Telegram."""
    city_name = sub.city
    if not city_name:
        return {"status": "skipped", "reason": "no_city"}

    if not _should_notify_rain(sub, now):
        return {"status": "skipped", "reason": "cooldown"}

    lat, lon = await _resolve_city_coords(city_name)
    if lat is None or lon is None:
        return {"status": "skipped", "reason": "coords_not_found"}

    data = await fetch_single_city(lat, lon)
    if not data:
        return {"status": "skipped", "reason": "fetch_failed"}

    hourly = data.get("hourly", {})
    rain_info = _check_hourly_rain(hourly, max_lead_hours=MAX_LEAD_HOURS)

    if not rain_info:
        return {"status": "no_rain"}

    message = _build_rain_message_telegram(city_name, rain_info)
    sent = await send_telegram_message(sub.chat_id, message)

    if sent:
        _mark_rain_notified(sub.id, now)
        return {"status": "sent", "city": city_name, "rain_info": rain_info}

    return {"status": "send_failed"}


async def _send_daily_forecast(sub: TelegramSubscription, now: datetime) -> dict:
    """Invia il promemoria giornaliero con le previsioni sintetiche."""
    city_name = sub.city
    if not city_name:
        return {"status": "skipped", "reason": "no_city"}

    if not _should_notify_daily(sub, now):
        return {"status": "skipped", "reason": "not_time"}

    lat, lon = await _resolve_city_coords(city_name)
    if lat is None or lon is None:
        return {"status": "skipped", "reason": "coords_not_found"}

    data = await fetch_single_city(lat, lon)
    if not data:
        return {"status": "skipped", "reason": "fetch_failed"}

    daily = data.get("daily", {})
    times = daily.get("time", [])
    if not times:
        return {"status": "skipped", "reason": "no_daily_data"}

    # Prendi oggi (indice 0)
    today_idx = 0
    max_temp = daily.get("temperature_2m_max", [None])[today_idx]
    min_temp = daily.get("temperature_2m_min", [None])[today_idx]
    weather_code = daily.get("weather_code", [None])[today_idx]
    precip_prob = daily.get("precipitation_probability_max", [None])[today_idx]
    precip_sum = daily.get("precipitation_sum", [None])[today_idx]

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

    message = f"{emoji} <b>Previsioni per {city_name}</b>\n\n"

    if max_temp is not None and min_temp is not None:
        message += f"🌡️ Temperatura: {min_temp:.0f}° - {max_temp:.0f}°\n"
    message += f"📋 Condizioni: {description}\n"

    if precip_prob is not None:
        message += f"💧 Probabilità pioggia: {precip_prob}%\n"
    if precip_sum is not None and precip_sum > 0:
        message += f"🌧️ Precipitazioni: {precip_sum:.1f}mm\n"

    hourly = data.get("hourly", {})
    wind_speeds = hourly.get("wind_speed_10m", [])
    if wind_speeds:
        avg_wind = sum(wind_speeds[:12]) / min(12, len(wind_speeds))
        message += f"💨 Vento medio: {avg_wind:.0f} km/h\n"

    # Sezione pioggia prevista
    rain_slots = _find_rain_time_slots(hourly)
    if rain_slots:
        if len(rain_slots) > 3:
            message += f"🌧️ Pioggia prevista: {', '.join(rain_slots[:3])}, e altri orari\n"
        else:
            message += f"🌧️ Pioggia prevista: {', '.join(rain_slots)}\n"
    else:
        message += "☀️ Nessuna pioggia prevista\n"

    message += "\nBuona giornata! ☕"

    sent = await send_telegram_message(sub.chat_id, message)

    if sent:
        _mark_daily_notified(sub.id, now)
        return {"status": "sent", "city": city_name}

    return {"status": "send_failed"}


async def check_telegram_rain_alerts() -> dict:
    """Entry point: controlla allerte pioggia per tutte le subscription Telegram attive."""
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        subscriptions = (
            db.query(TelegramSubscription)
            .filter(TelegramSubscription.rain_alerts_enabled.is_(True))
            .filter(TelegramSubscription.chat_id.isnot(None))
            .filter(TelegramSubscription.is_active.is_(True))
            .all()
        )

    if not subscriptions:
        return {"checked": 0, "sent": 0, "results": []}

    print(f"[TELEGRAM-RAIN] Controllo allerte pioggia per {len(subscriptions)} subscription Telegram...")

    results = []
    sent_count = 0

    for sub in subscriptions:
        try:
            result = await _fetch_and_check_rain(sub, now)
            results.append(result)
            if result.get("status") == "sent":
                sent_count += 1
        except Exception as exc:
            logger.warning(f"Errore controllo rain alert Telegram per {sub.city}: {exc}")
            results.append({"status": "error", "city": sub.city, "error": str(exc)})

        await asyncio.sleep(0.5)

    summary = {
        "checked": len(subscriptions),
        "sent": sent_count,
        "results": results,
    }
    print(f"[TELEGRAM-RAIN] Allerte pioggia Telegram: {sent_count} inviate su {len(subscriptions)} controllate")
    return summary


async def check_telegram_daily_forecasts() -> dict:
    """Entry point: invia promemoria giornalieri a chi li ha attivati."""
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        subscriptions = (
            db.query(TelegramSubscription)
            .filter(TelegramSubscription.daily_forecast_enabled.is_(True))
            .filter(TelegramSubscription.chat_id.isnot(None))
            .filter(TelegramSubscription.is_active.is_(True))
            .all()
        )

    if not subscriptions:
        return {"checked": 0, "sent": 0, "results": []}

    print(f"[TELEGRAM-DAILY] Controllo promemoria giornalieri per {len(subscriptions)} subscription Telegram...")

    results = []
    sent_count = 0

    for sub in subscriptions:
        try:
            result = await _send_daily_forecast(sub, now)
            results.append(result)
            if result.get("status") == "sent":
                sent_count += 1
        except Exception as exc:
            logger.warning(f"Errore invio daily forecast Telegram per {sub.city}: {exc}")
            results.append({"status": "error", "city": sub.city, "error": str(exc)})

        await asyncio.sleep(0.5)

    summary = {
        "checked": len(subscriptions),
        "sent": sent_count,
        "results": results,
    }
    print(f"[TELEGRAM-DAILY] Promemoria giornalieri Telegram: {sent_count} inviati su {len(subscriptions)} controllati")
    return summary
