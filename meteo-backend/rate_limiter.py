"""
rate_limiter.py — Middleware in-memory per rate limiting per IP.

Regole:
- 60 richieste/minuto per IP (sliding window).
- Esclude percorsi esatti: /health, /ready, /, /docs, /openapi.json.
- Header x-forwarded-for ha priorità su request.client.host.
- Se superato il limite: HTTP 429 con header Retry-After.
- Cleanup automatico degli IP inattivi ogni 60 secondi via threading.Timer.
"""

import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware che limita a 60 req/min per IP con sliding window in-memory."""

    EXCLUDED_PATHS = {"/health", "/ready", "/", "/docs", "/openapi.json"}
    LIMIT = 60
    WINDOW = 60.0
    CLEANUP_INTERVAL = 60.0

    def __init__(self, app):
        super().__init__(app)
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._cleanup_timer: threading.Timer | None = None
        self._start_cleanup()

    # ------------------------------------------------------------------
    # Cleanup automatico ogni minuto
    # ------------------------------------------------------------------
    def _start_cleanup(self) -> None:
        self._cleanup_timer = threading.Timer(self.CLEANUP_INTERVAL, self._cleanup)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def _cleanup(self) -> None:
        now = time.time()
        with self._lock:
            to_remove = [
                ip
                for ip, timestamps in self._requests.items()
                if not timestamps or all(now - t >= self.WINDOW for t in timestamps)
            ]
            for ip in to_remove:
                del self._requests[ip]
        self._start_cleanup()

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Estrai IP: x-forwarded-for > client.host
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"

        now = time.time()

        with self._lock:
            timestamps = self._requests.get(ip, [])
            # Sliding window: mantieni solo richieste negli ultimi WINDOW secondi
            timestamps = [t for t in timestamps if now - t < self.WINDOW]

            if len(timestamps) >= self.LIMIT:
                # Calcola quanti secondi mancano alla prima richiesta che uscirà dalla finestra
                retry_after = int(self.WINDOW - (now - timestamps[0]))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Try again later."},
                    headers={"Retry-After": str(max(1, retry_after))},
                )

            timestamps.append(now)
            self._requests[ip] = timestamps

        return await call_next(request)
