"""Esegue un singolo ciclo ML per il cron job di produzione."""
from __future__ import annotations

import asyncio

from database import init_db
import ml_model
from scheduler import hourly_cycle


def main() -> None:
    print("[ML-CRON] Avvio ciclo ML schedulato")
    init_db()
    ml_model.load_latest_model()
    asyncio.run(hourly_cycle())
    print("[ML-CRON] Ciclo ML completato")


if __name__ == "__main__":
    main()
