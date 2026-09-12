"""Esegue un singolo ciclo ML per il cron job di produzione."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import init_db  # noqa: E402
import ml_model  # noqa: E402
from scheduler import hourly_cycle  # noqa: E402


def main() -> None:
    print("[ML-CRON] Avvio ciclo ML schedulato")
    init_db()
    ml_model.load_latest_model()
    result = asyncio.run(hourly_cycle())
    if not result or result.get("last_cycle_status") == "failed":
        raise RuntimeError(f"Ciclo ML fallito: {(result or {}).get('last_cycle_message', 'missing_result')}")
    print("[ML-CRON] Ciclo ML completato")


if __name__ == "__main__":
    main()
