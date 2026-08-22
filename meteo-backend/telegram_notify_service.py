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
from datetime import datetime, timedelta, timezone

from config import settings
from database import City, SessionLocal, TelegramRainAlert, TelegramSubscription, WeatherObservation
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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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


def _persist_city_coords(
    sub_id: int,
    *,
    lat: float,
    lon: float,
    region: str | None = None,
    province: str | None = None,
):
    with SessionLocal() as db:
        sub = db.get(TelegramSubscription, sub_id)
        if not sub:
            return
        sub.city_lat = lat
        sub.city_lon = lon
        if region:
            sub.city_region = region
        if province:
            sub.city_province = province
        db.commit()


def _is_same_rain_event(sub_id: int, rain_info: dict, now: datetime) -> bool:
    interval_start = rain_info.get("interval_start")
    interval_end = rain_info.get("interval_end")
    if not isinstance(interval_start, datetime) or not isinstance(interval_end, datetime):
        return False

    with SessionLocal() as db:
        latest = (
            db.query(TelegramRainAlert)
            .filter(TelegramRainAlert.subscription_id == sub_id)
            .filter(TelegramRainAlert.sent_at >= now - timedelta(hours=3))
            .order_by(TelegramRainAlert.sent_at.desc())
            .first()
        )
        if latest is None:
            return False

        last_start = _as_utc(latest.forecast_interval_start)
        last_end = _as_utc(latest.forecast_interval_end)
        next_start = _as_utc(interval_start)
        next_end = _as_utc(interval_end)
        return next_start <= last_end and next_end >= last_start


def _has_recorded_rain_alert(sub_id: int) -> bool:
    with SessionLocal() as db:
        return db.query(TelegramRainAlert.id).filter(TelegramRainAlert.subscription_id == sub_id).first() is not None


def _record_rain_alert(
    sub: TelegramSubscription,
    *,
    lat: float,
    lon: float,
    rain_info: dict,
    now: datetime,
):
    interval_start = rain_info.get("interval_start")
    interval_end = rain_info.get("interval_end")
    if not isinstance(interval_start, datetime) or not isinstance(interval_end, datetime):
        return

    with SessionLocal() as db:
        db.add(
            TelegramRainAlert(
                subscription_id=sub.id,
                city=sub.city,
                city_lat=lat,
                city_lon=lon,
                forecast_interval_start=_as_utc(interval_start),
                forecast_interval_end=_as_utc(interval_end),
                precipitation_probability=rain_info.get("pop"),
                precipitation_mm=rain_info.get("precipitation"),
                weather_code=rain_info.get("weather_code"),
                ml_probability=rain_info.get("ml_probability") if rain_info.get("ml_ready") else None,
                trigger_reason=rain_info.get("trigger_reason"),
                sent_at=now,
            )
        )
        db.commit()


def _verify_pending_alerts(now: datetime) -> dict:
    trusted_sources = tuple(getattr(settings, "ml_trusted_observation_sources", ()))
    if not trusted_sources:
        return {"checked": 0, "verified": 0}

    with SessionLocal() as db:
        alerts = (
            db.query(TelegramRainAlert)
            .filter(TelegramRainAlert.verification_status == "pending")
            .filter(TelegramRainAlert.forecast_interval_end <= now)
            .limit(200)
            .all()
        )
        verified = 0
        for alert in alerts:
            city = (
                db.query(City)
                .filter(City.name_lower == alert.city.strip().lower())
                .filter(City.lat.between(alert.city_lat - 0.05, alert.city_lat + 0.05))
                .filter(City.lon.between(alert.city_lon - 0.05, alert.city_lon + 0.05))
                .order_by(City.population.desc())
                .first()
            )
            if city is None:
                continue

            observations = (
                db.query(WeatherObservation)
                .filter(WeatherObservation.city_id == city.id)
                .filter(WeatherObservation.observation_source.in_(trusted_sources))
                .filter(WeatherObservation.observed_at > alert.forecast_interval_start)
                .filter(WeatherObservation.observed_at <= alert.forecast_interval_end)
                .all()
            )
            covered_minutes = sum(max(1, item.observation_interval_minutes or 0) for item in observations)
            if covered_minutes < 45:
                continue

            observed_mm = max((item.precipitation or 0.0) for item in observations)
            alert.observed_precipitation_mm = observed_mm
            alert.verification_status = "hit" if observed_mm > 0.1 else "false_alarm"
            alert.verified_at = now
            verified += 1

        if verified:
            db.commit()
        return {"checked": len(alerts), "verified": verified}


async def _fetch_and_check_rain(sub: TelegramSubscription, now: datetime) -> dict:
    """Controlla se pioverà per la città della subscription Telegram."""
    city_name = sub.city
    if not city_name:
        return {"status": "skipped", "reason": "no_city"}

    if not sub.rain_alerts_enabled or not sub.chat_id:
        return {"status": "skipped", "reason": "disabled"}

    lat = sub.city_lat
    lon = sub.city_lon
    if lat is None or lon is None:
        lat, lon = await resolve_city_coords(city_name)
    if lat is None or lon is None:
        return {"status": "skipped", "reason": "coords_not_found"}

    data = await fetch_single_city(lat, lon)
    if not data:
        return {"status": "skipped", "reason": "fetch_failed"}

    hourly = data.get("hourly", {})

    # Regione reale (per coerenza con le feature di training) e copertura ML:
    # fuori dalle province coperte non usiamo il modello per non estrapolare.
    region = sub.city_region
    province = sub.city_province
    if not region or not province:
        lookup_region, lookup_province = await asyncio.to_thread(_lookup_city_geo, city_name)
        region = region or lookup_region
        province = province or lookup_province
    if sub.city_lat is None or sub.city_lon is None:
        await asyncio.to_thread(
            _persist_city_coords,
            sub.id,
            lat=lat,
            lon=lon,
            region=region,
            province=province,
        )
    rain_info = check_hourly_rain_adaptive(
        hourly,
        lat=lat,
        lon=lon,
        city_name=city_name,
        region=region or "Sconosciuta",
        ml_coverage=is_city_in_ml_coverage(province),
        now=now,
    )

    if not rain_info:
        return {"status": "no_rain"}

    same_event = await asyncio.to_thread(_is_same_rain_event, sub.id, rain_info, now)
    if same_event:
        return {"status": "skipped", "reason": "same_rain_event"}

    # Compatibilità per sottoscrizioni esistenti che hanno un timestamp ma non
    # ancora righe nel nuovo registro degli eventi.
    has_recorded_alert = await asyncio.to_thread(_has_recorded_rain_alert, sub.id)
    if not has_recorded_alert and not should_notify_rain(sub.last_rain_alert_at, now):
        return {"status": "skipped", "reason": "legacy_cooldown"}

    message = build_rain_message(city_name, rain_info)
    sent = await send_telegram_message(sub.chat_id, message)

    if sent:
        _mark_rain_notified(sub.id, now)
        try:
            await asyncio.to_thread(_record_rain_alert, sub, lat=lat, lon=lon, rain_info=rain_info, now=now)
        except Exception as exc:
            logger.warning("Avviso Telegram inviato ma non registrato per %s: %s", city_name, exc)
        return {"status": "sent", "city": city_name, "rain_info": rain_info}

    return {"status": "send_failed"}


async def _send_daily_forecast(sub: TelegramSubscription, now: datetime) -> dict:
    """Invia il promemoria giornaliero con le previsioni sintetiche."""
    city_name = sub.city
    if not city_name:
        return {"status": "skipped", "reason": "no_city"}

    if not sub.daily_forecast_enabled or not sub.chat_id:
        return {"status": "skipped", "reason": "disabled"}

    if not should_notify_daily(sub.last_daily_forecast_at, sub.daily_forecast_hour, now):
        return {"status": "skipped", "reason": "not_time"}

    lat = sub.city_lat
    lon = sub.city_lon
    if lat is None or lon is None:
        lat, lon = await resolve_city_coords(city_name)
    if lat is None or lon is None:
        return {"status": "skipped", "reason": "coords_not_found"}

    if sub.city_lat is None or sub.city_lon is None:
        region, province = await asyncio.to_thread(_lookup_city_geo, city_name)
        await asyncio.to_thread(
            _persist_city_coords,
            sub.id,
            lat=lat,
            lon=lon,
            region=region,
            province=province,
        )

    data = await fetch_single_city(lat, lon)
    if not data:
        return {"status": "skipped", "reason": "fetch_failed"}

    daily = data.get("daily", {})
    times = daily.get("time", [])
    if not times:
        return {"status": "skipped", "reason": "no_daily_data"}

    hourly = data.get("hourly", {})
    message = build_daily_message(city_name, daily, hourly, today_idx=0, now=now)

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

    verification = await asyncio.to_thread(_verify_pending_alerts, now)
    summary = {
        "checked": len(subscriptions),
        "sent": sent_count,
        "results": results,
        "verification": verification,
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
