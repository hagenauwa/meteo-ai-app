"""
routers/telegram.py — gestione sottoscrizioni Telegram e webhook bot.

Endpoint:
  • POST /api/telegram/link-code          — genera codice OTP per collegamento
  • GET  /api/telegram/status             — stato collegamento + preferenze
  • POST /api/telegram/preferences        — aggiorna preferenze notifiche
  • POST /api/telegram/unlink             — scollega Telegram
  • POST /api/telegram/webhook            — riceve aggiornamenti dal bot (Telegram)
  • POST /api/admin/telegram/check        — forza controllo notifiche Telegram (admin)
"""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import require_admin_access
from config import settings
from database import get_db, TelegramSubscription

# ---------------------------------------------------------------------------
# Schemi Pydantic
# ---------------------------------------------------------------------------


class LinkCodeResponse(BaseModel):
    linking_code: str
    client_token: str
    expires_in_minutes: int = 30


class PreferencesUpdate(BaseModel):
    city: str | None = None
    city_lat: float | None = None
    city_lon: float | None = None
    city_region: str | None = None
    city_province: str | None = None
    rain_alerts_enabled: bool | None = None
    daily_forecast_enabled: bool | None = None
    daily_forecast_hour: int | None = None


class TelegramStatusResponse(BaseModel):
    linked: bool
    state: str
    chat_id: int | None = None
    user_name: str | None = None
    city: str | None = None
    city_lat: float | None = None
    city_lon: float | None = None
    city_region: str | None = None
    city_province: str | None = None
    rain_alerts_enabled: bool = False
    daily_forecast_enabled: bool = False
    daily_forecast_hour: int = 8
    linked_at: str | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["telegram"])


def _generate_linking_code(length: int = 6) -> str:
    """Genera un codice OTP alfanumerico maiuscolo."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_client_token() -> str:
    """Genera un token browser stabile e imprevedibile."""
    return secrets.token_urlsafe(32)


def hash_client_token(token: str) -> str:
    """Restituisce l'hash SHA-256 del token browser."""
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_unique_client_token(db: Session, max_attempts: int = 5) -> tuple[str, str]:
    """Genera un token browser con hash unico nel database."""
    for _ in range(max_attempts):
        token = generate_client_token()
        token_hash = hash_client_token(token)
        existing = (
            db.query(TelegramSubscription.id).filter(TelegramSubscription.client_token_hash == token_hash).first()
        )
        if not existing:
            return token, token_hash

    raise HTTPException(status_code=500, detail="Impossibile generare un token client univoco")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_linking_expired(sub: TelegramSubscription) -> bool:
    sub_row = cast(Any, sub)
    expires_at = _normalize_utc(sub_row.linking_code_expires_at)
    return expires_at is not None and expires_at <= _utcnow()


def _get_subscription_by_client_token(
    db: Session,
    client_token: str | None,
) -> TelegramSubscription | None:
    if not client_token:
        return None

    return (
        db.query(TelegramSubscription)
        .filter(TelegramSubscription.client_token_hash == hash_client_token(client_token))
        .first()
    )


def _build_status_response(sub: TelegramSubscription | None) -> TelegramStatusResponse:
    if not sub:
        return TelegramStatusResponse(linked=False, state="not_found")

    sub_row = cast(Any, sub)

    if sub_row.is_active is not True:
        return TelegramStatusResponse(linked=False, state="unlinked")

    if sub_row.chat_id is not None:
        linked_at = _normalize_utc(sub_row.linked_at)
        return TelegramStatusResponse(
            linked=True,
            state="linked",
            chat_id=sub_row.chat_id,
            user_name=sub_row.user_name,
            city=sub_row.city,
            city_lat=sub_row.city_lat,
            city_lon=sub_row.city_lon,
            city_region=sub_row.city_region,
            city_province=sub_row.city_province,
            rain_alerts_enabled=sub_row.rain_alerts_enabled,
            daily_forecast_enabled=sub_row.daily_forecast_enabled,
            daily_forecast_hour=sub_row.daily_forecast_hour,
            linked_at=linked_at.isoformat() if linked_at is not None else None,
        )

    if _is_linking_expired(sub):
        return TelegramStatusResponse(linked=False, state="expired")

    return TelegramStatusResponse(
        linked=False,
        state="pending",
        city=sub_row.city,
        city_lat=sub_row.city_lat,
        city_lon=sub_row.city_lon,
        city_region=sub_row.city_region,
        city_province=sub_row.city_province,
        rain_alerts_enabled=sub_row.rain_alerts_enabled,
        daily_forecast_enabled=sub_row.daily_forecast_enabled,
        daily_forecast_hour=sub_row.daily_forecast_hour,
    )


# ---------------------------------------------------------------------------
# Endpoint pubblici
# ---------------------------------------------------------------------------


@router.post("/telegram/link-code")
def generate_link_code(db: Session = Depends(get_db)):
    """
    Genera un nuovo codice OTP per collegare un account Telegram.
    Il codice ha validità 30 minuti.
    """
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=501,
            detail="Bot Telegram non configurato",
        )

    code = _generate_linking_code()
    client_token, client_token_hash = _generate_unique_client_token(db)

    # Crea una nuova subscription in attesa di linking
    sub = TelegramSubscription(
        linking_code=code,
        client_token_hash=client_token_hash,
        linking_code_expires_at=_utcnow() + timedelta(minutes=30),
        is_active=True,
    )
    db.add(sub)
    db.commit()

    return LinkCodeResponse(linking_code=code, client_token=client_token)


@router.get("/telegram/status")
def get_telegram_status(
    linking_code: str | None = None,
    x_telegram_client_token: str | None = Header(default=None, alias="X-Telegram-Client-Token"),
    db: Session = Depends(get_db),
):
    """
    Restituisce lo stato del collegamento Telegram.
    Se fornito linking_code, controlla se è stato collegato.
    """
    try:
        if x_telegram_client_token:
            sub = _get_subscription_by_client_token(db, x_telegram_client_token)
            return _build_status_response(sub)

        if linking_code:
            sub = db.query(TelegramSubscription).filter(TelegramSubscription.linking_code == linking_code).first()
            return _build_status_response(sub)

        return TelegramStatusResponse(linked=False, state="not_found")
    except HTTPException:
        raise
    except Exception:
        return TelegramStatusResponse(linked=False, state="error")


@router.post("/telegram/preferences")
def update_preferences(
    payload: PreferencesUpdate,
    x_telegram_client_token: str | None = Header(default=None, alias="X-Telegram-Client-Token"),
    db: Session = Depends(get_db),
):
    """
    Aggiorna le preferenze di notifica Telegram.
    Richiede il client_token del browser per identificare la subscription.
    """
    if not x_telegram_client_token:
        raise HTTPException(status_code=400, detail="X-Telegram-Client-Token richiesto")

    sub = _get_subscription_by_client_token(db, x_telegram_client_token)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription non trovata")

    sub_row = cast(Any, sub)

    if payload.city is not None:
        city_changed = payload.city.strip().lower() != (sub_row.city or "").strip().lower()
        sub_row.city = payload.city
        if city_changed and (payload.city_lat is None or payload.city_lon is None):
            sub_row.city_lat = None
            sub_row.city_lon = None
            sub_row.city_region = None
            sub_row.city_province = None
    if payload.city_lat is not None and payload.city_lon is not None:
        if not (-90 <= payload.city_lat <= 90 and -180 <= payload.city_lon <= 180):
            raise HTTPException(status_code=422, detail="Coordinate città non valide")
        sub_row.city_lat = payload.city_lat
        sub_row.city_lon = payload.city_lon
        sub_row.city_region = payload.city_region
        sub_row.city_province = payload.city_province
    if payload.rain_alerts_enabled is not None:
        sub_row.rain_alerts_enabled = payload.rain_alerts_enabled
    if payload.daily_forecast_enabled is not None:
        sub_row.daily_forecast_enabled = payload.daily_forecast_enabled
    if payload.daily_forecast_hour is not None:
        hour = max(0, min(23, payload.daily_forecast_hour))
        sub_row.daily_forecast_hour = hour

    db.commit()

    return {
        "success": True,
        "city": sub_row.city,
        "city_lat": sub_row.city_lat,
        "city_lon": sub_row.city_lon,
        "city_region": sub_row.city_region,
        "city_province": sub_row.city_province,
        "rain_alerts_enabled": sub_row.rain_alerts_enabled,
        "daily_forecast_enabled": sub_row.daily_forecast_enabled,
        "daily_forecast_hour": sub_row.daily_forecast_hour,
    }


@router.post("/telegram/unlink")
def unlink_telegram(
    x_telegram_client_token: str | None = Header(default=None, alias="X-Telegram-Client-Token"),
    db: Session = Depends(get_db),
):
    """
    Scollega un account Telegram disattivando la subscription.
    """
    if not x_telegram_client_token:
        raise HTTPException(status_code=400, detail="X-Telegram-Client-Token richiesto")

    sub = _get_subscription_by_client_token(db, x_telegram_client_token)

    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription non trovata")

    sub_row = cast(Any, sub)

    sub_row.is_active = False
    sub_row.chat_id = None
    sub_row.linking_code = None
    sub_row.linking_code_expires_at = None
    sub_row.client_token_hash = None
    db.commit()

    return {"success": True, "message": "Telegram scollegato"}


# ---------------------------------------------------------------------------
# Webhook Telegram
# ---------------------------------------------------------------------------


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Riceve gli aggiornamenti dal bot Telegram.
    Telegram invia POST JSON a questo endpoint.
    """
    # Verifica secret. In produzione è OBBLIGATORIO: senza, l'endpoint sarebbe
    # aperto e chiunque potrebbe iniettare update falsi (linking/unlinking).
    if settings.telegram_webhook_secret:
        # Telegram invia il secret nell'header X-Telegram-Bot-Api-Secret-Token
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secrets.compare_digest(secret_header, settings.telegram_webhook_secret):
            raise HTTPException(status_code=403, detail="Secret non valido")
    elif settings.is_production:
        import logging

        logging.getLogger(__name__).error("TELEGRAM_WEBHOOK_SECRET non configurato in produzione: webhook rifiutato")
        raise HTTPException(status_code=403, detail="Webhook secret non configurato")

    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON non valido") from exc

    from telegram_bot import handle_webhook_update

    try:
        await handle_webhook_update(update)
    except Exception as exc:
        # Non propagare errori a Telegram per evitare retry infiniti
        import logging

        logging.getLogger(__name__).error(f"Errore gestione webhook Telegram: {exc}")

    return {"ok": True}


# ---------------------------------------------------------------------------
# Endpoint amministrativi
# ---------------------------------------------------------------------------


@router.post("/admin/telegram/check", dependencies=[Depends(require_admin_access)])
async def admin_telegram_check():
    """
    Forza un controllo immediato delle notifiche Telegram (pioggia + daily).
    """
    from telegram_notify_service import check_telegram_rain_alerts, check_telegram_daily_forecasts

    rain_result = await check_telegram_rain_alerts()
    daily_result = await check_telegram_daily_forecasts()

    return {
        "rain_alerts": rain_result,
        "daily_forecasts": daily_result,
    }


@router.get("/admin/telegram/subscriptions", dependencies=[Depends(require_admin_access)])
def count_telegram_subscriptions(db: Session = Depends(get_db)):
    """Restituisce il numero totale di sottoscrizioni Telegram."""
    total = db.query(TelegramSubscription).count()
    linked = db.query(TelegramSubscription).filter(TelegramSubscription.chat_id.isnot(None)).count()
    active = db.query(TelegramSubscription).filter(TelegramSubscription.is_active.is_(True)).count()
    return {
        "total": total,
        "linked": linked,
        "active": active,
    }
