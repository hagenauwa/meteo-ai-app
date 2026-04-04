"""Test endpoint supporter donations."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
import stripe

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import Settings
from database import Supporter, SupporterToken, get_db
from main import app
import supporters_service


client = TestClient(app)


class FakeQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model
        self._filters = {}

    def filter_by(self, **kwargs):
        self._filters.update(kwargs)
        return self

    def first(self):
        for item in self.db.store.get(self.model, []):
            if all(getattr(item, key, None) == value for key, value in self._filters.items()):
                return item
        return None


class FakeDb:
    def __init__(self):
        self.store = {
            Supporter: [],
            SupporterToken: [],
        }
        self._ids = {
            Supporter: 1,
            SupporterToken: 1,
        }

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, item):
        model = type(item)
        if getattr(item, "id", None) is None:
            item.id = self._ids[model]
            self._ids[model] += 1
        if item not in self.store[model]:
            self.store[model].append(item)

    def flush(self):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def override_db(fake_db):
    def _override():
        yield fake_db

    return _override


def fake_settings():
    return Settings(
        app_env="development",
        frontend_origin="https://leprevisioni.netlify.app",
        cors_origins=("https://leprevisioni.netlify.app",),
        admin_api_token="",
        cities_index_cache_seconds=3600,
        max_model_store_records=5,
        stripe_secret_key="sk_test_123",
        stripe_webhook_secret="whsec_123",
        supporter_email_encryption_key="uQ0OQ8B3miEC1Rk2JKvxhX8R9EAgb6g3QwpTVYV2P9A=",
        supporter_email_hash_key="supporter-hash-secret",
    )


def test_checkout_session_requires_valid_email(monkeypatch):
    monkeypatch.setattr(supporters_service, "settings", fake_settings())

    response = client.post("/api/supporters/checkout-session", json={"email": "not-an-email"})
    assert response.status_code == 422


def test_checkout_session_returns_stripe_url(monkeypatch):
    monkeypatch.setattr(supporters_service, "settings", fake_settings())
    create_calls = []

    def fake_create(**kwargs):
        create_calls.append(kwargs)
        return {"url": "https://checkout.stripe.test/session_123"}

    monkeypatch.setattr(stripe.checkout.Session, "create", fake_create)

    response = client.post("/api/supporters/checkout-session", json={"email": "Supporter@Example.com"})

    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.stripe.test/session_123"
    assert create_calls[0]["customer_email"] == "supporter@example.com"
    assert create_calls[0]["line_items"][0]["price_data"]["unit_amount"] == 100


def test_confirm_session_creates_supporter_token(monkeypatch):
    fake_db = FakeDb()
    monkeypatch.setattr(supporters_service, "settings", fake_settings())
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", lambda session_id: {
        "id": session_id,
        "payment_status": "paid",
        "customer_email": "supporter@example.com",
        "amount_total": 100,
        "currency": "eur",
        "payment_intent": "pi_123",
        "customer": "cus_123",
    })
    app.dependency_overrides[get_db] = override_db(fake_db)

    try:
        response = client.post(
            "/api/supporters/confirm-session",
            json={"session_id": "cs_test_123"},
            headers={"user-agent": "pytest-browser"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["recognized"] is True
    assert body["token"]
    assert body["donation_count"] == 1
    assert len(fake_db.store[Supporter]) == 1
    assert len(fake_db.store[SupporterToken]) == 1


def test_status_recognizes_existing_supporter(monkeypatch):
    fake_db = FakeDb()
    monkeypatch.setattr(supporters_service, "settings", fake_settings())

    supporter = Supporter(
        id=None,
        email_encrypted=b"encrypted",
        email_lookup_hash="lookup",
        created_at=supporters_service.utcnow(),
        updated_at=supporters_service.utcnow(),
        donation_count=2,
    )
    fake_db.add(supporter)

    token_value = "plain-token"
    token = SupporterToken(
        id=None,
        supporter_id=supporter.id,
        token_hash=supporters_service.compute_token_hash(token_value),
        user_agent_hash=None,
        created_at=supporters_service.utcnow(),
        last_seen_at=supporters_service.utcnow(),
    )
    fake_db.add(token)
    app.dependency_overrides[get_db] = override_db(fake_db)

    try:
        response = client.get("/api/supporters/status", headers={"x-supporter-token": token_value, "user-agent": "pytest-browser"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json() == {"recognized": True, "donation_count": 2}


def test_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(supporters_service, "settings", fake_settings())

    def fake_construct_event(payload, signature, secret):
        raise stripe.error.SignatureVerificationError("invalid", payload, signature)

    monkeypatch.setattr(stripe.Webhook, "construct_event", fake_construct_event)

    response = client.post(
        "/api/supporters/stripe-webhook",
        data="{}",
        headers={"stripe-signature": "bad-signature"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Firma webhook non valida."
