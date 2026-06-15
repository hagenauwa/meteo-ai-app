"""
telegram_bot.py — logica bot Telegram per il linking degli account.

Gestisce:
  - Ricezione webhook da Telegram
  - Verifica codice OTP per collegare chat_id
  - Risposte automatiche agli utenti
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any, cast

import httpx

from config import settings
from database import TelegramSubscription, SessionLocal

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


def _bot_api_url(method: str) -> str:
    return f"{TELEGRAM_API_BASE.format(token=settings.telegram_bot_token)}/{method}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_default_city(value: str | None) -> bool:
    return value is None or not value.strip()


def _copy_preferences_if_default(source: TelegramSubscription, target: TelegramSubscription) -> None:
    source_row = cast(Any, source)
    target_row = cast(Any, target)

    if _is_default_city(target_row.city) and source_row.city:
        target_row.city = source_row.city
    if target_row.rain_alerts_enabled is not True and source_row.rain_alerts_enabled is True:
        target_row.rain_alerts_enabled = source_row.rain_alerts_enabled
    if target_row.daily_forecast_enabled is not True and source_row.daily_forecast_enabled is True:
        target_row.daily_forecast_enabled = source_row.daily_forecast_enabled
    if target_row.daily_forecast_hour in (None, 8) and source_row.daily_forecast_hour is not None:
        target_row.daily_forecast_hour = source_row.daily_forecast_hour


async def send_telegram_message(
    chat_id: int,
    text: str,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> bool:
    """
    Invia un messaggio Telegram a una chat specifica.
    Retry con backoff esponenziale per errori recuperabili.
    """
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN non configurato")
        return False

    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    _bot_api_url("sendMessage"),
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                    timeout=10,
                )

                # Gestione rate limit Telegram (429)
                if resp.status_code == 429:
                    try:
                        retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                    except Exception:
                        retry_after = 5
                    logger.warning(
                        f"Telegram rate limit 429 per {chat_id}, "
                        f"retry dopo {retry_after}s (tentativo {attempt + 1}/{max_retries})"
                    )
                    if attempt < max_retries - 1:
                        import asyncio

                        await asyncio.sleep(retry_after)
                        continue
                    return False

                # Chat bloccata o non trovata (403) — non riprovare
                if resp.status_code == 403:
                    logger.warning(f"Telegram 403 per {chat_id}: chat bloccata o bot rimosso")
                    return False

                resp.raise_for_status()
                data = resp.json()
                return data.get("ok", False)

        except httpx.TimeoutException as exc:
            last_exc = exc
            logger.warning(f"Timeout invio Telegram a {chat_id} (tentativo {attempt + 1}/{max_retries}): {exc}")
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            # Errori server Telegram (5xx) — retry
            if exc.response is not None and exc.response.status_code >= 500:
                logger.warning(
                    f"Errore server Telegram {exc.response.status_code} per {chat_id} "
                    f"(tentativo {attempt + 1}/{max_retries})"
                )
            else:
                # Altri errori HTTP — non retry
                logger.error(f"Errore HTTP Telegram per {chat_id}: {exc}")
                return False
        except Exception as exc:
            last_exc = exc
            logger.error(f"Errore invio messaggio Telegram a {chat_id}: {exc}")
            return False

        # Backoff esponenziale: 1s, 2s, 4s...
        if attempt < max_retries - 1:
            import asyncio

            delay = base_delay * (2**attempt)
            await asyncio.sleep(delay)

    if last_exc:
        logger.error(f"Invio Telegram fallito dopo {max_retries} tentativi a {chat_id}: {last_exc}")
    return False


def _find_subscription_by_code(code: str) -> TelegramSubscription | None:
    """Trova una subscription tramite codice OTP."""
    with SessionLocal() as db:
        sub = (
            db.query(TelegramSubscription)
            .filter(
                TelegramSubscription.linking_code == code,
                TelegramSubscription.chat_id.is_(None),
                TelegramSubscription.is_active.is_(True),
                TelegramSubscription.linking_code_expires_at.is_not(None),
                TelegramSubscription.linking_code_expires_at > _utcnow(),
            )
            .first()
        )
        if sub:
            db.expunge(sub)
        return sub


def _link_chat_id(code: str, chat_id: int, user_name: str | None) -> bool:
    """Collega un chat_id Telegram a una subscription esistente."""
    with SessionLocal() as db:
        sub = (
            db.query(TelegramSubscription)
            .filter(
                TelegramSubscription.linking_code == code,
                TelegramSubscription.chat_id.is_(None),
                TelegramSubscription.is_active.is_(True),
                TelegramSubscription.linking_code_expires_at.is_not(None),
                TelegramSubscription.linking_code_expires_at > _utcnow(),
            )
            .first()
        )
        if not sub:
            return False

        sub_row = cast(Any, sub)

        previous_sub = (
            db.query(TelegramSubscription)
            .filter(
                TelegramSubscription.chat_id == chat_id,
                TelegramSubscription.is_active.is_(True),
                TelegramSubscription.id != sub.id,
            )
            .first()
        )

        if previous_sub:
            previous_sub_row = cast(Any, previous_sub)
            _copy_preferences_if_default(previous_sub, sub)
            previous_sub_row.is_active = False
            previous_sub_row.chat_id = None
            db.flush()

        sub_row.chat_id = chat_id
        sub_row.user_name = user_name
        sub_row.linking_code = None  # invalida il codice dopo l'uso
        sub_row.linking_code_expires_at = None
        sub_row.linked_at = datetime.now(timezone.utc)
        db.commit()
        return True


async def register_webhook() -> bool:
    """Registra il webhook con l'API di Telegram all'avvio del backend."""
    if not settings.telegram_bot_token:
        logger.info("TELEGRAM_BOT_TOKEN non configurato, salto registrazione webhook")
        return False

    url = _bot_api_url("setWebhook")
    payload = {
        "url": settings.telegram_webhook_url,
        "allowed_updates": ["message"],
    }
    if settings.telegram_webhook_secret:
        payload["secret_token"] = settings.telegram_webhook_secret

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                logger.info(f"Webhook Telegram registrato: {settings.telegram_webhook_url}")
                return True
            else:
                logger.warning(f"Registrazione webhook Telegram fallita: {data}")
                return False
    except Exception as exc:
        logger.error(f"Errore registrazione webhook Telegram: {exc}")
        return False


async def handle_webhook_update(update: dict[str, Any]) -> None:
    """Processa un aggiornamento ricevuto dal webhook Telegram."""
    message = update.get("message")
    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "").strip()
    user = message.get("from", {})
    user_name = user.get("username")

    if not chat_id or not text:
        return

    # Gestione comando /start con codice OTP
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_telegram_message(
                chat_id,
                "👋 Benvenuto su Le Previsioni!\n\n"
                "Per collegare il tuo account, genera un codice sul sito "
                "e invialo qui con il comando:\n"
                "<code>/start CODICE</code>",
            )
            return

        code = parts[1].strip().upper()
        if _link_chat_id(code, chat_id, user_name):
            await send_telegram_message(
                chat_id,
                "✅ <b>Account collegato con successo!</b>\n\n"
                "Ora puoi gestire le tue preferenze di notifica direttamente dal sito.\n\n"
                "Comandi disponibili:\n"
                "/stato — Mostra le tue impostazioni\n"
                "/disattiva — Disattiva tutte le notifiche",
            )
        else:
            await send_telegram_message(
                chat_id,
                "❌ Codice non valido, scaduto o già utilizzato.\n\nGenera un nuovo codice sul sito e riprova.",
            )
        return

    # Comando /stato
    if text.lower() in ("/stato", "/status"):
        with SessionLocal() as db:
            sub = db.query(TelegramSubscription).filter(TelegramSubscription.chat_id == chat_id).first()
            if not sub:
                await send_telegram_message(
                    chat_id,
                    "⚠️ Account non collegato.\nGenera un codice sul sito e invia <code>/start CODICE</code>.",
                )
                return

            sub_row = cast(Any, sub)
            city = html.escape(sub_row.city) if sub_row.city else "Non impostata"
            rain = "✅ Attive" if sub_row.rain_alerts_enabled is True else "❌ Disattive"
            daily = "✅ Attive" if sub_row.daily_forecast_enabled is True else "❌ Disattive"
            hour = sub_row.daily_forecast_hour if sub_row.daily_forecast_hour is not None else 8

            await send_telegram_message(
                chat_id,
                f"📊 <b>Le tue impostazioni</b>\n\n"
                f"🏙️ Città: <b>{city}</b>\n"
                f"🌧️ Allerte pioggia: {rain}\n"
                f"📅 Promemoria giornaliero: {daily} (ore {hour:02d}:00)\n\n"
                f"Puoi modificare le preferenze dal sito.",
            )
            return

    # Comando /disattiva
    if text.lower() in ("/disattiva", "/stop"):
        with SessionLocal() as db:
            sub = db.query(TelegramSubscription).filter(TelegramSubscription.chat_id == chat_id).first()
            if sub:
                sub_row = cast(Any, sub)
                sub_row.rain_alerts_enabled = False
                sub_row.daily_forecast_enabled = False
                db.commit()

            await send_telegram_message(
                chat_id,
                "🔕 Notifiche disattivate.\nPuoi riattivarle dal sito in qualsiasi momento.",
            )
            return

    # Messaggio sconosciuto — suggerisci i comandi
    await send_telegram_message(
        chat_id,
        "Comandi disponibili:\n"
        "/start CODICE — Collega il tuo account\n"
        "/stato — Mostra le impostazioni\n"
        "/disattiva — Disattiva le notifiche",
    )
