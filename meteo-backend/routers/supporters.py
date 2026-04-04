"""
routers/supporters.py — checkout e riconoscimento supporter nel browser.
"""
from __future__ import annotations

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from supporters_service import (
    DONATION_AMOUNT_CENTS,
    DONATION_CURRENCY,
    DONATION_PRODUCT_DESCRIPTION,
    DONATION_PRODUCT_NAME,
    build_cancel_url,
    build_success_url,
    compute_email_lookup_hash,
    issue_supporter_token,
    register_paid_supporter,
    require_stripe_secret_key,
    require_stripe_webhook_secret,
    resolve_supporter_from_token,
    validate_email,
)


router = APIRouter()


class CheckoutSessionRequest(BaseModel):
    email: str


class ConfirmSessionRequest(BaseModel):
    session_id: str


def _set_stripe_api_key() -> None:
    stripe.api_key = require_stripe_secret_key()


@router.post("/checkout-session")
def create_checkout_session(payload: CheckoutSessionRequest):
    email = validate_email(payload.email)
    _set_stripe_api_key()

    session = stripe.checkout.Session.create(
        mode="payment",
        submit_type="donate",
        success_url=build_success_url(),
        cancel_url=build_cancel_url(),
        customer_email=email,
        metadata={"supporter_email_hash": compute_email_lookup_hash(email)},
        line_items=[
            {
                "price_data": {
                    "currency": DONATION_CURRENCY,
                    "product_data": {
                        "name": DONATION_PRODUCT_NAME,
                        "description": DONATION_PRODUCT_DESCRIPTION,
                    },
                    "unit_amount": DONATION_AMOUNT_CENTS,
                },
                "quantity": 1,
            }
        ],
    )

    checkout_url = session.get("url") if hasattr(session, "get") else getattr(session, "url", None)
    if not checkout_url:
        raise HTTPException(status_code=502, detail="Stripe non ha restituito un URL di checkout valido.")

    return {"checkout_url": checkout_url}


@router.post("/confirm-session")
def confirm_checkout_session(
    payload: ConfirmSessionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _set_stripe_api_key()
    session = stripe.checkout.Session.retrieve(payload.session_id)
    supporter = register_paid_supporter(db, session)
    token = issue_supporter_token(db, supporter, request.headers.get("user-agent"))
    db.commit()

    return {
        "recognized": True,
        "token": token,
        "donation_count": supporter.donation_count,
    }


@router.get("/status")
def get_supporter_status(
    request: Request,
    x_supporter_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    supporter = resolve_supporter_from_token(db, x_supporter_token, request.headers.get("user-agent"))
    if not supporter:
        return {"recognized": False}

    db.commit()
    return {
        "recognized": True,
        "donation_count": supporter.donation_count,
    }


@router.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    _set_stripe_api_key()
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, signature, require_stripe_webhook_secret())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Payload webhook non valido.") from exc
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail="Firma webhook non valida.") from exc

    event_type = event.get("type")
    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        session = (event.get("data") or {}).get("object") or {}
        if session.get("payment_status") == "paid":
            register_paid_supporter(db, session)
            db.commit()

    return {"received": True}
