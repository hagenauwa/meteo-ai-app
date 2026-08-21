"""
rate_limiter.py — Middleware in-memory per rate limiting per IP.

Regole:
- 60 richieste/minuto per IP (sliding window).
- Esclude percorsi esatti: /health, /ready, /, /docs, /openapi.json.
- Usa l'ultimo IP valido di x-forwarded-for, quello aggiunto dal reverse proxy.
- Applica limiti più stretti agli endpoint che generano OTP o costi esterni.
- Se superato il limite: HTTP 429 con header Retry-After.
- Cleanup automatico degli IP inattivi ogni 60 secondi via threading.Timer.
"""

import ipaddress
import threading
import time
import weakref

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware che limita a 60 req/min per IP con sliding window in-memory."""

    EXCLUDED_PATHS = {"/health", "/ready", "/", "/docs", "/openapi.json"}
    LIMIT = 60
    SENSITIVE_LIMITS = {
        "/api/telegram/link-code": 10,
        "/api/supporters/checkout-session": 10,
        "/api/supporters/confirm-session": 20,
    }
    WINDOW = 60.0
    CLEANUP_INTERVAL = 60.0
    _INSTANCES = weakref.WeakSet()

    def __init__(self, app):
        super().__init__(app)
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._cleanup_timer: threading.Timer | None = None
        self._INSTANCES.add(self)
        self._start_cleanup()

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()

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
    @staticmethod
    def _valid_ip(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return str(ipaddress.ip_address(value.strip()))
        except ValueError:
            return None

    def _client_ip(self, request) -> str:
        # I reverse proxy aggiungono l'IP verificato a destra. Il primo valore
        # della catena può invece essere fornito arbitrariamente dal client.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            for candidate in reversed(forwarded.split(",")):
                valid = self._valid_ip(candidate)
                if valid is not None:
                    return valid

        client_host = request.client.host if request.client else None
        return self._valid_ip(client_host) or "unknown"

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in self.EXCLUDED_PATHS:
            return await call_next(request)

        ip = self._client_ip(request)
        limit = self.SENSITIVE_LIMITS.get(path, self.LIMIT)
        bucket = path if path in self.SENSITIVE_LIMITS else "default"
        request_key = f"{ip}:{bucket}"

        now = time.time()

        with self._lock:
            timestamps = self._requests.get(request_key, [])
            # Sliding window: mantieni solo richieste negli ultimi WINDOW secondi
            timestamps = [t for t in timestamps if now - t < self.WINDOW]

            if len(timestamps) >= limit:
                # Calcola quanti secondi mancano alla prima richiesta che uscirà dalla finestra
                retry_after = int(self.WINDOW - (now - timestamps[0]))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Try again later."},
                    headers={"Retry-After": str(max(1, retry_after))},
                )

            timestamps.append(now)
            self._requests[request_key] = timestamps

        return await call_next(request)


def reset_rate_limits() -> None:
    for instance in list(RateLimitMiddleware._INSTANCES):
        instance.reset()
