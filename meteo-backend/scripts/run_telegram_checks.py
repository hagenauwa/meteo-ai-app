"""Esegue check notifiche Telegram (rain alerts + daily forecast) per il cron job."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import init_db
from telegram_notify_service import check_telegram_rain_alerts, check_telegram_daily_forecasts


async def main() -> None:
    print("[TELEGRAM-CRON] Avvio check notifiche Telegram")
    init_db()

    rain_result = await check_telegram_rain_alerts()
    daily_result = await check_telegram_daily_forecasts()

    print(f"[TELEGRAM-CRON] Rain alerts: {rain_result.get('sent', 0)}/{rain_result.get('checked', 0)}")
    print(f"[TELEGRAM-CRON] Daily forecasts: {daily_result.get('sent', 0)}/{daily_result.get('checked', 0)}")
    print("[TELEGRAM-CRON] Completato")


if __name__ == "__main__":
    asyncio.run(main())
