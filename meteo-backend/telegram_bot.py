"""
telegram_bot.py — logica bot Telegram per il linking degli account.

Gestisce:
  - Ricezione webhook da Telegram
  - Verifica codice OTP per collegare chat_id
  - Risposte automatiche agli utenti
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from config import settings
from database import TelegramSubscription, SessionLocal

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


def _bot_api_url(method: str) -> str:
    return f"{TELEGRAM_API_BASE.format(token=settings.telegram_bot_token)}/{method}"


async def send_telegram_message(chat_id: int, text: str) -> bool:
    """Invia un messaggio Telegram a una chat specifica."""
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN non configurato")
        return False

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
            resp.raise_for_status()
            data = resp.json()
            return data.get("ok", False)
    except Exception as exc:
        logger.error(f"Errore invio messaggio Telegram a {chat_id}: {exc}")
        return False


def _find_subscription_by_code(code: str) -> TelegramSubscription | None:
    """Trova una subscription tramite codice OTP."""
    with SessionLocal() as db:
        sub = (
            db.query(TelegramSubscription)
            .filter(
                TelegramSubscription.linking_code == code,
                TelegramSubscription.chat_id.is_(None),
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
            )
            .first()
        )
        if not sub:
            return False

        sub.chat_id = chat_id
        sub.user_name = user_name
        sub.linking_code = None  # invalida il codice dopo l'uso
        sub.linked_at = datetime.now(timezone.utc)
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


async def handle_webhook_update(update: dict) -> None:
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
                "❌ Codice non valido o già utilizzato.\n\n"
                "Genera un nuovo codice sul sito e riprova.",
            )
        return

    # Comando /stato
    if text.lower() in ("/stato", "/status"):
        with SessionLocal() as db:
            sub = (
                db.query(TelegramSubscription)
                .filter(TelegramSubscription.chat_id == chat_id)
                .first()
            )
            if not sub:
                await send_telegram_message(
                    chat_id,
                    "⚠️ Account non collegato.\n"
                    "Genera un codice sul sito e invia <code>/start CODICE</code>.",
                )
                return

            city = sub.city or "Non impostata"
            rain = "✅ Attive" if sub.rain_alerts_enabled else "❌ Disattive"
            daily = "✅ Attive" if sub.daily_forecast_enabled else "❌ Disattive"
            hour = sub.daily_forecast_hour

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
            sub = (
                db.query(TelegramSubscription)
                .filter(TelegramSubscription.chat_id == chat_id)
                .first()
            )
            if sub:
                sub.rain_alerts_enabled = False
                sub.daily_forecast_enabled = False
                db.commit()

            await send_telegram_message(
                chat_id,
                "🔕 Notifiche disattivate.\n"
                "Puoi riattivarle dal sito in qualsiasi momento.",
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
