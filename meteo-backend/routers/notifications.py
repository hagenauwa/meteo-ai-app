"""
routers/notifications.py — gestione iscrizioni push Web (Web Push API) e allerte pioggia.

Endpoint:
  • POST /api/subscriptions/register        — registra/aggiorna una subscription
  • POST /api/subscriptions/rain-alerts     — abilita/disabilita allerte pioggia
  • GET  /api/subscriptions/rain-alerts     — stato allerte pioggia per una subscription
  • GET  /api/subscriptions/count           — conteggio iscritti (admin)
  • POST /api/admin/push-test               — invia notifica di test (admin)
  • POST /api/admin/rain-alert-check        — forza controllo allerte pioggia (admin)
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import require_admin_access
from database import get_db, PushSubscription

# ---------------------------------------------------------------------------
# Graceful degradation: se py-vapid non è disponibile o le chiavi mancano,
# il backend restituisce 501 invece di crashare.
# ---------------------------------------------------------------------------

try:
    from py_vapid import Vapid
    _VAPID_AVAILABLE = True
except Exception:  # pragma: no cover
    _VAPID_AVAILABLE = False

_VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
_VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
_VAPID_CLAIMS = {
    "sub": os.getenv("VAPID_SUBJECT", "mailto:admin@leprevisioni.netlify.app"),
}


def _vapid_ready() -> bool:
    """True solo se la libreria e le chiavi sono entrambe presenti."""
    return _VAPID_AVAILABLE and bool(_VAPID_PRIVATE_KEY) and bool(_VAPID_PUBLIC_KEY)


# ---------------------------------------------------------------------------
# Schemi Pydantic
# ---------------------------------------------------------------------------

class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    subscription: dict[str, Any]
    city: str | None = None


class PushTestIn(BaseModel):
    title: str = "Test Meteo AI"
    body: str = "Messaggio di prova"


class RainAlertToggle(BaseModel):
    endpoint: str
    enabled: bool = True
    city: str | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["notifications"])


# ---------------------------------------------------------------------------
# VAPID public key endpoint (pubblico)
# ---------------------------------------------------------------------------

@router.get("/subscriptions/vapid-public-key")
def vapid_public_key():
    """Restituisce la chiave pubblica VAPID per le subscription push."""
    if not _vapid_ready():
        raise HTTPException(
            status_code=501,
            detail="Notifiche push non configurate",
        )
    return {"publicKey": _VAPID_PUBLIC_KEY}


# ---------------------------------------------------------------------------
# Endpoint pubblici
# ---------------------------------------------------------------------------

@router.post("/subscriptions/register")
def register_subscription(
    payload: PushSubscriptionIn,
    db: Session = Depends(get_db),
):
    """
    Registra o aggiorna una sottoscrizione push Web.
    L'upsert avviene per `endpoint` (identificativo univoco del client).
    """
    sub = payload.subscription
    endpoint = sub.get("endpoint", "").strip()
    keys = sub.get("keys", {})
    p256dh = keys.get("p256dh", "").strip()
    auth = keys.get("auth", "").strip()

    if not endpoint or not p256dh or not auth:
        raise HTTPException(
            status_code=400,
            detail="Parametri subscription incompleti (endpoint, p256dh, auth)",
        )

    existing = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == endpoint)
        .first()
    )

    if existing:
        existing.p256dh = p256dh
        existing.auth = auth
        existing.city = payload.city
    else:
        existing = PushSubscription(
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            city=payload.city,
        )
        db.add(existing)

    db.commit()
    return {"success": True, "message": "Iscrizione registrata"}


# ---------------------------------------------------------------------------
# Endpoint amministrativi
# ---------------------------------------------------------------------------

@router.get("/subscriptions/count", dependencies=[Depends(require_admin_access)])
def count_subscriptions(db: Session = Depends(get_db)):
    """Restituisce il numero totale di sottoscrizioni push."""
    count = db.query(PushSubscription).count()
    return {"count": count}


@router.post("/admin/push-test", dependencies=[Depends(require_admin_access)])
async def push_test(
    payload: PushTestIn | None = None,
    db: Session = Depends(get_db),
):
    """
    Invia una notifica push di test alla prima subscription trovata (o a tutte).
    Richiede le chiavi VAPID configurate; altrimenti restituisce 501.
    """
    if not _vapid_ready():
        raise HTTPException(
            status_code=501,
            detail="Notifiche push non configurate",
        )

    subs = db.query(PushSubscription).all()
    if not subs:
        raise HTTPException(
            status_code=404,
            detail="Nessuna subscription trovata nel database",
        )

    # Costruisce payload JSON di test
    if payload is None:
        payload = PushTestIn()

    message = {
        "title": payload.title,
        "body": payload.body,
        "icon": "/icon-192x192.png",
        "badge": "/icon-72x72.png",
    }

    # Preferiamo pywebpush se disponibile (criptazione payload ECE inclusa)
    try:
        from pywebpush import webpush  # type: ignore[import-untyped]
        _webpush_available = True
    except Exception:
        _webpush_available = False

    vapid = Vapid.from_string(_VAPID_PRIVATE_KEY)
    sent = 0
    errors: list[str] = []

    for sub in subs:
        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        }

        try:
            if _webpush_available:
                webpush(
                    subscription_info=subscription_info,
                    data=str(message),
                    vapid_private_key=_VAPID_PRIVATE_KEY,
                    vapid_claims=_VAPID_CLAIMS,
                )
            else:
                # Fallback senza pywebpush: inviamo un "ping" (TTL, nessun body).
                # Il service worker riceverà un evento push vuoto e potrà
                # mostrare una notifica predefinita.
                import httpx

                vapid = Vapid.from_string(_VAPID_PRIVATE_KEY)
                headers = vapid.sign(sub.endpoint, _VAPID_CLAIMS)
                headers["TTL"] = "0"

                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        sub.endpoint,
                        headers=headers,
                        timeout=15.0,
                    )
                    resp.raise_for_status()

            sent += 1
        except Exception as exc:
            err_msg = str(exc)
            errors.append(f"{sub.endpoint[:60]}... -> {err_msg[:100]}")
            # Se l'endpoint non è più valido (410 Gone), rimuoviamo la subscription
            if "410" in err_msg or "NotRegistered" in err_msg or "Expired" in err_msg:
                db.delete(sub)
                db.commit()

    return {"success": True, "sent": sent, "errors": errors if errors else None}


# ---------------------------------------------------------------------------
# Endpoint allerte pioggia
# ---------------------------------------------------------------------------

@router.post("/subscriptions/rain-alerts")
def toggle_rain_alerts(
    payload: RainAlertToggle,
    db: Session = Depends(get_db),
):
    """
    Abilita o disabilita le allerte pioggia per una subscription.
    """
    subscription = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == payload.endpoint)
        .first()
    )

    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="Subscription non trovata. Registra prima la subscription push.",
        )

    subscription.rain_alerts_enabled = payload.enabled
    if payload.city:
        subscription.city = payload.city

    db.commit()

    return {
        "success": True,
        "rain_alerts_enabled": subscription.rain_alerts_enabled,
        "city": subscription.city,
    }


@router.get("/subscriptions/rain-alerts")
def get_rain_alerts_status(
    endpoint: str,
    db: Session = Depends(get_db),
):
    """
    Restituisce lo stato delle allerte pioggia per una subscription.
    """
    subscription = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == endpoint)
        .first()
    )

    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="Subscription non trovata",
        )

    return {
        "rain_alerts_enabled": subscription.rain_alerts_enabled,
        "city": subscription.city,
        "last_rain_alert_at": subscription.last_rain_alert_at.isoformat() if subscription.last_rain_alert_at else None,
    }


@router.post("/admin/rain-alert-check", dependencies=[Depends(require_admin_access)])
async def admin_rain_alert_check(
    db: Session = Depends(get_db),
):
    """
    Forza un controllo immediato delle allerte pioggia per tutte le subscription.
    Richiede token admin.
    """
    from rain_alert_service import check_rain_alerts

    result = await check_rain_alerts()
    return result
