"""
rain_alert_service.py — servizio notifiche push quando sta per piovere.

Refactored:
  - Usa notification_utils.py per logica condivisa
  - Integrazione modello ML per trigger pioggia
  - Cache geocoding con TTL
  - Cooldown ridotto a 2 ore
  - Trigger adattivo (POP + ML + weather_code)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from config import settings
from database import PushSubscription, SessionLocal
from weather_service import fetch_single_city
from notification_utils import (
    resolve_city_coords,
    check_hourly_rain_adaptive,
    build_rain_message,
    should_notify_rain,
)

logger = logging.getLogger(__name__)

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


def _build_rain_message_push(city_name: str, rain_info: dict) -> dict:
    """Costruisce il payload della notifica push per la pioggia."""
    pop_pct = round(rain_info["pop"] * 100)
    description = rain_info.get("description", "Pioggia prevista")
    precip_mm = rain_info.get("precipitation", 0)
    ml_prob = rain_info.get("ml_probability")
    ml_ready = rain_info.get("model_ready", False)

    # Costruisci body del messaggio
    if precip_mm and precip_mm > 0:
        body = f"{description} a {city_name}. Probabilità {pop_pct}%, previsti {precip_mm:.1f}mm di pioggia."
    else:
        body = (
            f"{description} a {city_name}. Probabilità {pop_pct}% nelle prossime ore."
        )

    # Aggiungi info ML se disponibili
    if ml_ready and ml_prob is not None:
        ml_pct = round(ml_prob * 100)
        body += f" Modello ML: {ml_pct}%."

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
            "ml_probability": ml_prob,
            "trigger_reason": rain_info.get("trigger_reason"),
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


def _mark_notified(subscription: PushSubscription, now: datetime):
    """Aggiorna il timestamp dell'ultima notifica."""
    subscription.last_rain_alert_at = now
    with SessionLocal() as db:
        db.add(subscription)
        db.commit()


async def _fetch_and_check_subscription(
    subscription: PushSubscription, now: datetime
) -> dict:
    """Controlla se pioverà per la città della subscription."""
    city_name = subscription.city
    if not city_name:
        return {"status": "skipped", "reason": "no_city"}

    if not subscription.rain_alerts_enabled:
        return {"status": "skipped", "reason": "disabled"}

    if not should_notify_rain(subscription.last_rain_alert_at, now):
        return {"status": "skipped", "reason": "cooldown"}

    lat, lon = await resolve_city_coords(city_name)
    if lat is None or lon is None:
        return {"status": "skipped", "reason": "coords_not_found"}

    data = await fetch_single_city(lat, lon)
    if not data:
        return {"status": "skipped", "reason": "fetch_failed"}

    hourly = data.get("hourly", {})

    # Trigger adattivo con ML
    rain_info = check_hourly_rain_adaptive(
        hourly,
        lat=lat,
        lon=lon,
        city_name=city_name,
        region="Sconosciuta",
    )

    if not rain_info:
        return {"status": "no_rain"}

    message = _build_rain_message_push(city_name, rain_info)
    sent = _send_push_notification(subscription, message)

    if sent:
        _mark_notified(subscription, now)
        return {"status": "sent", "city": city_name, "rain_info": rain_info}

    return {"status": "send_failed"}


async def check_rain_alerts() -> dict:
    """
    Entry point principale: controlla tutte le subscription con rain_alerts_enabled
    e invia notifiche dove il trigger adattivo è soddisfatto.
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
    print(
        f"[RAIN] Allerte pioggia: {sent_count} inviate su {len(subscriptions)} controllate"
    )
    return summary


def check_rain_alerts_sync() -> dict:
    """Wrapper sincrono per uso nello scheduler."""
    return asyncio.run(check_rain_alerts())
