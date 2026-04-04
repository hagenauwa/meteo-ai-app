"""
rate_limit.py — rate limiting in-memory per endpoint a quota ridotta.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException


@dataclass
class _ClientWindow:
    minute_hits: deque[datetime]
    day_hits: deque[datetime]


class InMemoryRateLimiter:
    def __init__(self, per_minute: int, per_day: int):
        self.per_minute = per_minute
        self.per_day = per_day
        self._clients: dict[str, _ClientWindow] = defaultdict(
            lambda: _ClientWindow(minute_hits=deque(), day_hits=deque())
        )

    def check(self, client_id: str) -> None:
        now = datetime.now(timezone.utc)
        minute_cutoff = now - timedelta(minutes=1)
        day_cutoff = now - timedelta(days=1)

        window = self._clients[client_id]
        while window.minute_hits and window.minute_hits[0] < minute_cutoff:
            window.minute_hits.popleft()
        while window.day_hits and window.day_hits[0] < day_cutoff:
            window.day_hits.popleft()

        if len(window.minute_hits) >= self.per_minute:
            raise HTTPException(
                status_code=429,
                detail="Limite richieste/minuto superato per la chat AI",
            )
        if len(window.day_hits) >= self.per_day:
            raise HTTPException(
                status_code=429,
                detail="Quota giornaliera chat AI esaurita",
            )

        window.minute_hits.append(now)
        window.day_hits.append(now)
