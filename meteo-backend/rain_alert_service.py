"""
rain_alert_service.py — servizio notifiche push quando sta per piovere.

Logica trigger combinato:
  - precipitation_probability >= 60% nelle prossime 1-6 ore
  - E weather_code indica pioggia (51-99 range)
  - E (ML non disponibile OPPURE rain_probability calibrata >= 50%)

Cooldown: max 1 notifica per subscription ogni 6 ore.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from config import settings
from database import PushSubscription, SessionLocal
from weather_service import fetch_single_city, wmo_to_description
from ml_model import RAIN_WEATHER_CODES

logger = logging.getLogger(__name__)

RAIN_ALERT_COOLDOWN_HOURS = 6
RAIN_POP_THRESHOLD = 0.60
RAIN_ML_THRESHOLD = 0.50
MAX_LEAD_HOURS = 6
TIMEOUT = 30

try:
    from pywebpush import webpush
    _WEBPUSH_AVAILABLE = True
except Exception:
    _WEBPUSH_AVAILABLE = False

_VAPID_PRIVATE_KEY = ""
_VAPID_CLAIMS: dict[str, str] = {}


def _init_vapid():
    global _VAPID_PRIVATE_KEY, _VAPID_CLAIMS
    import os
    _VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    _VAPID_CLAIMS = {
        "sub": os.getenv("VAPID_SUBJECT", "mailto:admin@leprevisioni.netlify.app"),
    }


_init_vapid()


def _vapid_ready() -> bool:
    return _WEBPUSH_AVAILABLE and bool(_VAPID_PRIVATE_KEY)


def _is_rain_weather_code(code: int | None) -> bool:
    if code is None:
        return False
    return code in RAIN_WEATHER_CODES


def _wmo_rain_description(code: int) -> str:
    desc, _ = wmo_to_description(code)
    return desc


def _check_hourly_rain(hourly: dict, max_lead_hours: int = MAX_LEAD_HOURS) -> dict | None:
    """
    Scansiona le previsioni orarie per trovare pioggia nelle prossime N ore.
    Ritorna il primo orario che soddisfa il trigger combinato, o None.
    """
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


def _build_rain_message(city_name: str, rain_info: dict) -> dict:
    """Costruisce il payload della notifica push per la pioggia."""
    pop_pct = round(rain_info["pop"] * 100)
    description = rain_info.get("description", "Pioggia prevista")
    precip_mm = rain_info.get("precipitation", 0)

    if precip_mm and precip_mm > 0:
        body = f"{description} a {city_name}. Probabilita {pop_pct}%, previsti {precip_mm:.1f}mm di pioggia."
    else:
        body = f"{description} a {city_name}. Probabilita {pop_pct}% nelle prossime ore."

    return {
        "title": "Sta per piovere!",
        "body": body,
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-72x72.png",
        "tag": f"rain-alert-{city_name.lower().replace(' ', '-')}",
        "requireInteraction": False,
        "data": {
            "type": "rain_alert",
            "city": city_name,
            "pop": rain_info["pop"],
            "weather_code": rain_info.get("weather_code"),
        },
    }


def _send_push_notification(subscription: PushSubscription, message: dict) -> bool:
    """Invia una notifica push a una subscription. Ritorna True se successo."""
    if not _vapid_ready():
        logger.warning("VAPID non configurato, notifiche push disabilitate")
        return False

    sub_info = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth,
        },
    }

    try:
        webpush(
            subscription_info=sub_info,
            data=str(message),
            vapid_private_key=_VAPID_PRIVATE_KEY,
            vapid_claims=_VAPID_CLAIMS,
        )
        return True
    except Exception as exc:
        err_msg = str(exc)
        if "410" in err_msg or "NotRegistered" in err_msg or "Expired" in err_msg:
            logger.info(f"Subscription scaduta per {subscription.city}: rimuovo")
            with SessionLocal() as db:
                db.delete(subscription)
                db.commit()
        else:
            logger.warning(f"Errore invio push a {subscription.city}: {err_msg[:100]}")
        return False


def _should_notify(subscription: PushSubscription, now: datetime) -> bool:
    """Verifica se la subscription puo ricevere una notifica (cooldown)."""
    if not subscription.rain_alerts_enabled:
        return False

    if subscription.last_rain_alert_at is None:
        return True

    cooldown_cutoff = now - timedelta(hours=RAIN_ALERT_COOLDOWN_HOURS)
    return subscription.last_rain_alert_at < cooldown_cutoff


def _mark_notified(subscription: PushSubscription, now: datetime):
    """Aggiorna il timestamp dell'ultima notifica."""
    subscription.last_rain_alert_at = now
    with SessionLocal() as db:
        db.add(subscription)
        db.commit()


async def _fetch_and_check_subscription(subscription: PushSubscription, now: datetime) -> dict:
    """Controlla se piovera per la citta della subscription."""
    city_name = subscription.city
    if not city_name:
        return {"status": "skipped", "reason": "no_city"}

    if not _should_notify(subscription, now):
        return {"status": "skipped", "reason": "cooldown"}

    # Usa la geocoding Open-Meteo per ottenere le coordinate della citta
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

    message = _build_rain_message(city_name, rain_info)
    sent = _send_push_notification(subscription, message)

    if sent:
        _mark_notified(subscription, now)
        return {"status": "sent", "city": city_name, "rain_info": rain_info}

    return {"status": "send_failed"}


async def _resolve_city_coords(city_name: str) -> tuple[float | None, float | None]:
    """Risolve il nome della citta in coordinate via Open-Meteo geocoding."""
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


async def check_rain_alerts() -> dict:
    """
    Entry point principale: controlla tutte le subscription con rain_alerts_enabled
    e invia notifiche dove il trigger combinato e' soddisfatto.
    """
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        subscriptions = (
            db.query(PushSubscription)
            .filter(PushSubscription.rain_alerts_enabled.is_(True))
            .filter(PushSubscription.city.isnot(None))
            .all()
        )

    if not subscriptions:
        return {"checked": 0, "sent": 0, "results": []}

    print(f"[RAIN] Controllo allerte pioggia per {len(subscriptions)} subscription...")

    results = []
    sent_count = 0

    for sub in subscriptions:
        try:
            result = await _fetch_and_check_subscription(sub, now)
            results.append(result)
            if result.get("status") == "sent":
                sent_count += 1
        except Exception as exc:
            logger.warning(f"Errore controllo rain alert per {sub.city}: {exc}")
            results.append({"status": "error", "city": sub.city, "error": str(exc)})

        # Piccolo delay per evitare rate limiting su Open-Meteo
        await asyncio.sleep(0.5)

    summary = {
        "checked": len(subscriptions),
        "sent": sent_count,
        "results": results,
    }
    print(f"[RAIN] Allerte pioggia: {sent_count} inviate su {len(subscriptions)} controllate")
    return summary


def check_rain_alerts_sync() -> dict:
    """Wrapper sincrono per uso nello scheduler."""
    return asyncio.run(check_rain_alerts())
