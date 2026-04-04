"""
supporters_service.py — supporto a checkout, cifratura email e token browser.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets

from cryptography.fernet import Fernet
from fastapi import HTTPException

from config import settings
from database import Supporter, SupporterToken


EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}$", re.IGNORECASE)
DONATION_AMOUNT_CENTS = 100
DONATION_CURRENCY = "eur"
DONATION_PRODUCT_NAME = "Buy me a Coffee"
DONATION_PRODUCT_DESCRIPTION = "Supporta Le Previsioni con un caffe da 1 euro."


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if not normalized or not EMAIL_REGEX.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Inserisci un indirizzo email valido.")
    return normalized


def _require_hash_key() -> str:
    key = settings.supporter_email_hash_key
    if not key:
        raise HTTPException(status_code=503, detail="SUPPORTER_EMAIL_HASH_KEY non configurato sul server.")
    return key


def _require_encryption_key() -> str:
    key = settings.supporter_email_encryption_key
    if not key:
        raise HTTPException(status_code=503, detail="SUPPORTER_EMAIL_ENCRYPTION_KEY non configurato sul server.")
    return key


def require_stripe_secret_key() -> str:
    key = settings.stripe_secret_key
    if not key:
        raise HTTPException(status_code=503, detail="STRIPE_SECRET_KEY non configurato sul server.")
    return key


def require_stripe_webhook_secret() -> str:
    key = settings.stripe_webhook_secret
    if not key:
        raise HTTPException(status_code=503, detail="STRIPE_WEBHOOK_SECRET non configurato sul server.")
    return key


def encrypt_email(email: str) -> bytes:
    fernet = Fernet(_require_encryption_key().encode("utf-8"))
    return fernet.encrypt(email.encode("utf-8"))


def compute_lookup_hash(value: str) -> str:
    key = _require_hash_key().encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_email_lookup_hash(email: str) -> str:
    return compute_lookup_hash(normalize_email(email))


def compute_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def compute_user_agent_hash(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    return compute_lookup_hash(user_agent)


def generate_browser_token() -> str:
    return secrets.token_urlsafe(32)


def build_success_url() -> str:
    return f"{settings.frontend_origin.rstrip('/')}/?supporter_success=1&session_id={{CHECKOUT_SESSION_ID}}"


def build_cancel_url() -> str:
    return f"{settings.frontend_origin.rstrip('/')}/?supporter_canceled=1"


def _read_session_field(session, key: str, default=None):
    if session is None:
        return default
    if hasattr(session, "get"):
        return session.get(key, default)
    return getattr(session, key, default)


def extract_paid_session_details(session) -> dict:
    amount_total = _read_session_field(session, "amount_total") or DONATION_AMOUNT_CENTS
    currency = (_read_session_field(session, "currency") or DONATION_CURRENCY).lower()
    customer_email = _read_session_field(session, "customer_email")
    customer_details = _read_session_field(session, "customer_details") or {}
    payment_status = _read_session_field(session, "payment_status")
    session_id = _read_session_field(session, "id")
    payment_intent = _read_session_field(session, "payment_intent")
    stripe_customer_id = _read_session_field(session, "customer")

    email = customer_email
    if not email and isinstance(customer_details, dict):
        email = customer_details.get("email")

    if payment_status != "paid":
        raise HTTPException(status_code=409, detail="La donazione non risulta ancora completata.")
    if not email:
        raise HTTPException(status_code=502, detail="Stripe non ha restituito l'email del supporter.")

    return {
        "email": validate_email(email),
        "amount_total": amount_total,
        "currency": currency,
        "session_id": session_id,
        "payment_intent": payment_intent,
        "stripe_customer_id": stripe_customer_id,
    }


def register_paid_supporter(db, session) -> Supporter:
    details = extract_paid_session_details(session)
    email_hash = compute_email_lookup_hash(details["email"])
    now = utcnow()

    supporter = db.query(Supporter).filter_by(email_lookup_hash=email_hash).first()
    is_duplicate = False

    if supporter:
        is_duplicate = bool(
            (details["session_id"] and supporter.last_checkout_session_id == details["session_id"]) or
            (details["payment_intent"] and supporter.stripe_payment_intent_id == details["payment_intent"])
        )
    else:
        supporter = Supporter(
            email_encrypted=b"",
            email_lookup_hash=email_hash,
            created_at=now,
            updated_at=now,
            donation_count=0,
        )
        db.add(supporter)
        db.flush()

    supporter.email_encrypted = encrypt_email(details["email"])
    supporter.email_lookup_hash = email_hash
    supporter.updated_at = now

    if details["stripe_customer_id"]:
        supporter.stripe_customer_id = details["stripe_customer_id"]
    if details["payment_intent"]:
        supporter.stripe_payment_intent_id = details["payment_intent"]
    if details["session_id"]:
        supporter.last_checkout_session_id = details["session_id"]

    if not is_duplicate:
        supporter.donation_count = int(supporter.donation_count or 0) + 1
        supporter.last_donation_at = now
        supporter.last_amount_cents = int(details["amount_total"] or DONATION_AMOUNT_CENTS)
        supporter.last_currency = details["currency"]

    db.add(supporter)
    db.flush()
    return supporter


def issue_supporter_token(db, supporter: Supporter, user_agent: str | None = None) -> str:
    raw_token = generate_browser_token()
    now = utcnow()
    token = SupporterToken(
        supporter_id=supporter.id,
        token_hash=compute_token_hash(raw_token),
        user_agent_hash=compute_user_agent_hash(user_agent),
        created_at=now,
        last_seen_at=now,
    )
    db.add(token)
    db.flush()
    return raw_token


def resolve_supporter_from_token(db, token: str | None, user_agent: str | None = None) -> Supporter | None:
    if not token:
        return None

    token_hash = compute_token_hash(token)
    token_row = db.query(SupporterToken).filter_by(token_hash=token_hash).first()
    if not token_row:
        return None

    token_row.last_seen_at = utcnow()
    if user_agent and not token_row.user_agent_hash:
        token_row.user_agent_hash = compute_user_agent_hash(user_agent)
    db.add(token_row)

    supporter = db.query(Supporter).filter_by(id=token_row.supporter_id).first()
    if supporter:
        supporter.updated_at = utcnow()
        db.add(supporter)
    return supporter
