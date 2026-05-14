"""Regression tests for Telegram browser-token linking flow."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import os
import re
import sys
from pathlib import Path

from types import SimpleNamespace
from typing import TypedDict, cast

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    for module_name in (
        "main",
        "config",
        "database",
        "telegram_bot",
        "routers",
        "routers.telegram",
    ):
        sys.modules.pop(module_name, None)


class LinkCodePayload(TypedDict):
    linking_code: str
    client_token: str
    expires_in_minutes: int


@pytest.fixture(scope="module")
def telegram_app(tmp_path_factory: pytest.TempPathFactory):
    temp_dir = tmp_path_factory.mktemp("telegram-linking")
    db_path = temp_dir / "telegram-linking.sqlite"

    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["APP_ENV"] = "development"
    os.environ["ENABLE_SCHEDULER"] = "false"
    os.environ["AUTO_LOAD_CITIES"] = "false"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
    os.environ["TELEGRAM_WEBHOOK_URL"] = "https://example.com/webhook"

    _clear_backend_modules()

    database = importlib.import_module("database")
    database.Base.metadata.create_all(bind=database.engine)
    telegram_router = importlib.import_module("routers.telegram")
    telegram_bot = importlib.import_module("telegram_bot")
    main = importlib.import_module("main")

    client = TestClient(main.app)

    yield SimpleNamespace(
        client=client,
        database=database,
        telegram_router=telegram_router,
        telegram_bot=telegram_bot,
    )

    client.close()
    database.engine.dispose()


@pytest.fixture(autouse=True)
def reset_telegram_subscriptions(telegram_app):
    with telegram_app.database.SessionLocal() as db:
        db.query(telegram_app.database.TelegramSubscription).delete()
        db.commit()

    yield

    with telegram_app.database.SessionLocal() as db:
        db.query(telegram_app.database.TelegramSubscription).delete()
        db.commit()


def _create_link_code(telegram_app) -> LinkCodePayload:
    response = telegram_app.client.post("/api/telegram/link-code")
    assert response.status_code == 200
    payload = cast(LinkCodePayload, response.json())
    assert payload["expires_in_minutes"] == 30
    return payload


def test_link_code_generation_and_status_by_client_token(telegram_app):
    payload = _create_link_code(telegram_app)
    linking_code = payload["linking_code"]
    client_token = payload["client_token"]

    assert re.fullmatch(r"[A-Z0-9]{6}", linking_code)

    token_hash = telegram_app.telegram_router.hash_client_token(client_token)

    with telegram_app.database.SessionLocal() as db:
        sub = (
            db.query(telegram_app.database.TelegramSubscription)
            .filter(telegram_app.database.TelegramSubscription.client_token_hash == token_hash)
            .one()
        )
        assert sub.linking_code == linking_code
        assert sub.chat_id is None
        assert sub.is_active is True
        assert sub.client_token_hash != client_token
        assert re.fullmatch(r"[0-9a-f]{64}", sub.client_token_hash or "")
        assert sub.linking_code_expires_at is not None

    assert telegram_app.telegram_bot._link_chat_id(linking_code, 123456789, "meteo_user") is True

    with telegram_app.database.SessionLocal() as db:
        linked_sub = (
            db.query(telegram_app.database.TelegramSubscription)
            .filter(telegram_app.database.TelegramSubscription.client_token_hash == token_hash)
            .one()
        )
        assert linked_sub.chat_id == 123456789
        assert linked_sub.user_name == "meteo_user"
        assert linked_sub.linking_code is None
        assert linked_sub.linking_code_expires_at is None
        assert linked_sub.client_token_hash == token_hash

    status_response = telegram_app.client.get(
        "/api/telegram/status",
        headers={"X-Telegram-Client-Token": client_token},
    )
    assert status_response.status_code == 200
    assert status_response.json()["linked"] is True
    assert status_response.json()["state"] == "linked"
    assert status_response.json()["chat_id"] == 123456789
    assert status_response.json()["linked_at"] is not None

    legacy_status = telegram_app.client.get(
        "/api/telegram/status",
        params={"linking_code": linking_code},
    )
    assert legacy_status.status_code == 200
    assert legacy_status.json()["linked"] is False
    assert legacy_status.json()["state"] == "not_found"


def test_preferences_update_and_unlink_with_client_token(telegram_app):
    payload = _create_link_code(telegram_app)
    linking_code = payload["linking_code"]
    client_token = payload["client_token"]
    token_hash = telegram_app.telegram_router.hash_client_token(client_token)

    with telegram_app.database.SessionLocal() as db:
        sub_id = (
            db.query(telegram_app.database.TelegramSubscription.id)
            .filter(telegram_app.database.TelegramSubscription.client_token_hash == token_hash)
            .scalar()
        )

    assert telegram_app.telegram_bot._link_chat_id(linking_code, 222333444, "prefs_user") is True

    preferences_response = telegram_app.client.post(
        "/api/telegram/preferences",
        headers={"X-Telegram-Client-Token": client_token},
        json={
            "city": "Roma",
            "rain_alerts_enabled": True,
            "daily_forecast_enabled": True,
            "daily_forecast_hour": 7,
        },
    )
    assert preferences_response.status_code == 200
    assert preferences_response.json() == {
        "success": True,
        "city": "Roma",
        "rain_alerts_enabled": True,
        "daily_forecast_enabled": True,
        "daily_forecast_hour": 7,
    }

    with telegram_app.database.SessionLocal() as db:
        sub = db.get(telegram_app.database.TelegramSubscription, sub_id)
        assert sub is not None
        assert sub.city == "Roma"
        assert sub.rain_alerts_enabled is True
        assert sub.daily_forecast_enabled is True
        assert sub.daily_forecast_hour == 7

    unlink_response = telegram_app.client.post(
        "/api/telegram/unlink",
        headers={"X-Telegram-Client-Token": client_token},
    )
    assert unlink_response.status_code == 200
    assert unlink_response.json() == {"success": True, "message": "Telegram scollegato"}

    with telegram_app.database.SessionLocal() as db:
        sub = db.get(telegram_app.database.TelegramSubscription, sub_id)
        assert sub is not None
        assert sub.is_active is False
        assert sub.chat_id is None
        assert sub.linking_code is None
        assert sub.linking_code_expires_at is None
        assert sub.client_token_hash is None


def test_expired_code_cannot_link_and_status_is_expired(telegram_app):
    client_token = "expired-browser-token"
    linking_code = "EXPIRE"

    with telegram_app.database.SessionLocal() as db:
        expired_sub = telegram_app.database.TelegramSubscription(
            linking_code=linking_code,
            client_token_hash=telegram_app.telegram_router.hash_client_token(client_token),
            linking_code_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            is_active=True,
        )
        db.add(expired_sub)
        db.commit()

    assert telegram_app.telegram_bot._link_chat_id(linking_code, 999888777, "too_late") is False

    status_response = telegram_app.client.get(
        "/api/telegram/status",
        headers={"X-Telegram-Client-Token": client_token},
    )
    assert status_response.status_code == 200
    assert status_response.json()["linked"] is False
    assert status_response.json()["state"] == "expired"


def test_relink_same_chat_id_deactivates_old_row_and_activates_new_one(telegram_app):
    first_payload = _create_link_code(telegram_app)
    first_token = first_payload["client_token"]
    first_code = first_payload["linking_code"]

    assert telegram_app.telegram_bot._link_chat_id(first_code, 555444333, "first_user") is True

    first_preferences = telegram_app.client.post(
        "/api/telegram/preferences",
        headers={"X-Telegram-Client-Token": first_token},
        json={
            "city": "Milano",
            "rain_alerts_enabled": True,
            "daily_forecast_enabled": True,
            "daily_forecast_hour": 6,
        },
    )
    assert first_preferences.status_code == 200

    second_payload = _create_link_code(telegram_app)
    second_token = second_payload["client_token"]
    second_code = second_payload["linking_code"]
    second_hash = telegram_app.telegram_router.hash_client_token(second_token)

    assert telegram_app.telegram_bot._link_chat_id(second_code, 555444333, "second_user") is True

    with telegram_app.database.SessionLocal() as db:
        rows = (
            db.query(telegram_app.database.TelegramSubscription)
            .order_by(telegram_app.database.TelegramSubscription.id.asc())
            .all()
        )
        assert len(rows) == 2

        old_row, new_row = rows
        assert old_row.is_active is False
        assert old_row.chat_id is None
        assert new_row.is_active is True
        assert new_row.chat_id == 555444333
        assert new_row.user_name == "second_user"
        assert new_row.client_token_hash == second_hash
        assert new_row.city == "Milano"
        assert new_row.rain_alerts_enabled is True
        assert new_row.daily_forecast_enabled is True
        assert new_row.daily_forecast_hour == 6


def test_duplicate_start_code_returns_false_after_successful_link(telegram_app):
    payload = _create_link_code(telegram_app)

    assert telegram_app.telegram_bot._link_chat_id(payload["linking_code"], 101010101, "first_pass") is True
    assert telegram_app.telegram_bot._link_chat_id(payload["linking_code"], 101010101, "second_pass") is False
