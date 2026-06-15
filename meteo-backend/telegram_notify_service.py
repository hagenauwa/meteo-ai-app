"""
telegram_notify_service.py — servizio notifiche Telegram per pioggia e promemoria giornaliero.

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

from database import TelegramSubscription, SessionLocal, City
from weather_service import fetch_single_city
from telegram_bot import send_telegram_message
from ml_model import is_city_in_ml_coverage
from notification_utils import (
    resolve_city_coords,
    check_hourly_rain_adaptive,
    build_rain_message,
    build_daily_message,
    should_notify_rain,
    should_notify_daily,
)

logger = logging.getLogger(__name__)


def _lookup_city_geo(city_name: str) -> tuple[str | None, str | None]:
    """Recupera (region, province) reali dal DB per una città, best-effort.

    Serve a passare al modello la regione vista in training (invece di
    "Sconosciuta") e a decidere se la città è nell'area di copertura ML.
    """
    if not city_name:
        return None, None
    with SessionLocal() as db:
        row = (
            db.query(City.region, City.province)
            .filter(City.name_lower == city_name.strip().lower())
            .order_by(City.population.desc())
            .first()
        )
        if row:
            return row.region, row.province
    return None, None


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

    if not sub.rain_alerts_enabled or not sub.chat_id:
        return {"status": "skipped", "reason": "disabled"}

    if not should_notify_rain(sub.last_rain_alert_at, now):
        return {"status": "skipped", "reason": "cooldown"}

    lat, lon = await resolve_city_coords(city_name)
    if lat is None or lon is None:
        return {"status": "skipped", "reason": "coords_not_found"}

    data = await fetch_single_city(lat, lon)
    if not data:
        return {"status": "skipped", "reason": "fetch_failed"}

    hourly = data.get("hourly", {})

    # Regione reale (per coerenza con le feature di training) e copertura ML:
    # fuori dalle province coperte non usiamo il modello per non estrapolare.
    region, province = await asyncio.to_thread(_lookup_city_geo, city_name)
    rain_info = check_hourly_rain_adaptive(
        hourly,
        lat=lat,
        lon=lon,
        city_name=city_name,
        region=region or "Sconosciuta",
        ml_coverage=is_city_in_ml_coverage(province),
    )

    if not rain_info:
        return {"status": "no_rain"}

    message = build_rain_message(city_name, rain_info)
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

    if not sub.daily_forecast_enabled or not sub.chat_id:
        return {"status": "skipped", "reason": "disabled"}

    if not should_notify_daily(
        sub.last_daily_forecast_at, sub.daily_forecast_hour, now
    ):
        return {"status": "skipped", "reason": "not_time"}

    lat, lon = await resolve_city_coords(city_name)
    if lat is None or lon is None:
        return {"status": "skipped", "reason": "coords_not_found"}

    data = await fetch_single_city(lat, lon)
    if not data:
        return {"status": "skipped", "reason": "fetch_failed"}

    daily = data.get("daily", {})
    times = daily.get("time", [])
    if not times:
        return {"status": "skipped", "reason": "no_daily_data"}

    hourly = data.get("hourly", {})
    message = build_daily_message(city_name, daily, hourly, today_idx=0)

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

    print(
        f"[TELEGRAM-RAIN] Controllo allerte pioggia per {len(subscriptions)} subscription Telegram..."
    )

    results = []
    sent_count = 0

    for sub in subscriptions:
        try:
            result = await _fetch_and_check_rain(sub, now)
            results.append(result)
            if result.get("status") == "sent":
                sent_count += 1
        except Exception as exc:
            logger.warning(
                f"Errore controllo rain alert Telegram per {sub.city}: {exc}"
            )
            results.append({"status": "error", "city": sub.city, "error": str(exc)})

        await asyncio.sleep(0.5)

    summary = {
        "checked": len(subscriptions),
        "sent": sent_count,
        "results": results,
    }
    print(
        f"[TELEGRAM-RAIN] Allerte pioggia Telegram: {sent_count} inviate su {len(subscriptions)} controllate"
    )
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

    print(
        f"[TELEGRAM-DAILY] Controllo promemoria giornalieri per {len(subscriptions)} subscription Telegram..."
    )

    results = []
    sent_count = 0

    for sub in subscriptions:
        try:
            result = await _send_daily_forecast(sub, now)
            results.append(result)
            if result.get("status") == "sent":
                sent_count += 1
        except Exception as exc:
            logger.warning(
                f"Errore invio daily forecast Telegram per {sub.city}: {exc}"
            )
            results.append({"status": "error", "city": sub.city, "error": str(exc)})

        await asyncio.sleep(0.5)

    summary = {
        "checked": len(subscriptions),
        "sent": sent_count,
        "results": results,
    }
    print(
        f"[TELEGRAM-DAILY] Promemoria giornalieri Telegram: {sent_count} inviati su {len(subscriptions)} controllati"
    )
    return summary
