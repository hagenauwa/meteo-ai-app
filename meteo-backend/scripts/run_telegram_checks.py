"""Esegue check notifiche Telegram (rain alerts + daily forecast) per il cron job."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import settings  # noqa: E402
from database import init_db  # noqa: E402
from telegram_notify_service import check_telegram_rain_alerts, check_telegram_daily_forecasts  # noqa: E402


def _validate_runtime_config() -> None:
    if not settings.is_production:
        return

    missing = []
    if not os.getenv("DATABASE_URL", "").strip():
        missing.append("DATABASE_URL")
    if not settings.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")

    if missing:
        raise RuntimeError("Configurazione cron Telegram incompleta: " + ", ".join(missing))


async def main() -> None:
    print("[TELEGRAM-CRON] Avvio check notifiche Telegram")
    _validate_runtime_config()
    init_db()

    rain_result = await check_telegram_rain_alerts()
    daily_result = await check_telegram_daily_forecasts()

    print(f"[TELEGRAM-CRON] Rain alerts: {rain_result.get('sent', 0)}/{rain_result.get('checked', 0)}")
    print(f"[TELEGRAM-CRON] Daily forecasts: {daily_result.get('sent', 0)}/{daily_result.get('checked', 0)}")
    print("[TELEGRAM-CRON] Completato")


if __name__ == "__main__":
    asyncio.run(main())
