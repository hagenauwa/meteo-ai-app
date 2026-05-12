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

import secrets
import string
from datetime import datetime, timezone

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
    expires_in_minutes: int = 30


class PreferencesUpdate(BaseModel):
    city: str | None = None
    rain_alerts_enabled: bool | None = None
    daily_forecast_enabled: bool | None = None
    daily_forecast_hour: int | None = None


class TelegramStatusResponse(BaseModel):
    linked: bool
    chat_id: int | None = None
    user_name: str | None = None
    city: str | None = None
    rain_alerts_enabled: bool = False
    daily_forecast_enabled: bool = False
    daily_forecast_hour: int = 7
    linked_at: str | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["telegram"])


def _generate_linking_code(length: int = 6) -> str:
    """Genera un codice OTP alfanumerico maiuscolo."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


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

    # Crea una nuova subscription in attesa di linking
    sub = TelegramSubscription(
        linking_code=code,
        is_active=True,
    )
    db.add(sub)
    db.commit()

    return LinkCodeResponse(linking_code=code)


@router.get("/telegram/status")
def get_telegram_status(
    linking_code: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Restituisce lo stato del collegamento Telegram.
    Se fornito linking_code, controlla se è stato collegato.
    """
    if linking_code:
        sub = (
            db.query(TelegramSubscription)
            .filter(TelegramSubscription.linking_code == linking_code)
            .first()
        )
        if sub and sub.chat_id:
            return TelegramStatusResponse(
                linked=True,
                chat_id=sub.chat_id,
                user_name=sub.user_name,
                city=sub.city,
                rain_alerts_enabled=sub.rain_alerts_enabled,
                daily_forecast_enabled=sub.daily_forecast_enabled,
                daily_forecast_hour=sub.daily_forecast_hour,
                linked_at=sub.linked_at.isoformat() if sub.linked_at else None,
            )
        return TelegramStatusResponse(linked=False)

    # Se non fornito code, cerca per sessione (supporter token o simile)
    # Per ora restituiamo non collegato
    return TelegramStatusResponse(linked=False)


@router.post("/telegram/preferences")
def update_preferences(
    payload: PreferencesUpdate,
    linking_code: str = "",
    db: Session = Depends(get_db),
):
    """
    Aggiorna le preferenze di notifica Telegram.
    Richiede il linking_code per identificare la subscription.
    """
    if not linking_code:
        raise HTTPException(status_code=400, detail="linking_code richiesto")

    sub = (
        db.query(TelegramSubscription)
        .filter(TelegramSubscription.linking_code == linking_code)
        .first()
    )

    # Se non trovato per linking_code, potrebbe essere già stato collegato
    # In quel caso cerca per chat_id (ma non abbiamo il chat_id dal frontend)
    # Per semplicità, restituiamo errore se non trovato
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription non trovata")

    if payload.city is not None:
        sub.city = payload.city
    if payload.rain_alerts_enabled is not None:
        sub.rain_alerts_enabled = payload.rain_alerts_enabled
    if payload.daily_forecast_enabled is not None:
        sub.daily_forecast_enabled = payload.daily_forecast_enabled
    if payload.daily_forecast_hour is not None:
        hour = max(0, min(23, payload.daily_forecast_hour))
        sub.daily_forecast_hour = hour

    db.commit()

    return {
        "success": True,
        "city": sub.city,
        "rain_alerts_enabled": sub.rain_alerts_enabled,
        "daily_forecast_enabled": sub.daily_forecast_enabled,
        "daily_forecast_hour": sub.daily_forecast_hour,
    }


@router.post("/telegram/unlink")
def unlink_telegram(
    linking_code: str = "",
    db: Session = Depends(get_db),
):
    """
    Scollega un account Telegram disattivando la subscription.
    """
    if not linking_code:
        raise HTTPException(status_code=400, detail="linking_code richiesto")

    sub = (
        db.query(TelegramSubscription)
        .filter(TelegramSubscription.linking_code == linking_code)
        .first()
    )

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription non trovata")

    sub.is_active = False
    sub.chat_id = None
    sub.linking_code = None
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
    # Verifica secret se configurato
    if settings.telegram_webhook_secret:
        # Telegram invia il secret nell'header X-Telegram-Bot-Api-Secret-Token
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret_header != settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail="Secret non valido")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON non valido")

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
