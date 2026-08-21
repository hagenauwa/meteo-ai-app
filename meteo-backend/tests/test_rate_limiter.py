"""Test per il RateLimitMiddleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rate_limiter import RateLimitMiddleware


def _make_request(path: str, forwarded_for: str | None = None, client_host: str = "testclient"):
    """Crea una mock request compatibile con il middleware."""
    req = MagicMock()
    req.url.path = path

    client_mock = MagicMock()
    client_mock.host = client_host
    req.client = client_mock

    headers_data = {"x-forwarded-for": forwarded_for} if forwarded_for else {}
    headers_mock = MagicMock()
    headers_mock.get = lambda key, default=None: headers_data.get(key, default)
    req.headers = headers_mock

    return req


@pytest.fixture
def fresh_middleware():
    """Restituisce un RateLimitMiddleware fresco, isolato per test."""
    app = AsyncMock(return_value=MagicMock(status_code=200))
    middleware = RateLimitMiddleware(app)
    # Ferma il timer di cleanup per evitare thread zombie nei test
    if middleware._cleanup_timer:
        middleware._cleanup_timer.cancel()
    return middleware


class TestRateLimiter:
    async def _dispatch(self, middleware, path="/api/weather", forwarded_for=None, client_host="testclient"):
        req = _make_request(path, forwarded_for=forwarded_for, client_host=client_host)
        return await middleware.dispatch(req, middleware.app)

    @pytest.mark.asyncio
    async def test_sixty_requests_accepted(self, fresh_middleware):
        """60 richieste in un minuto devono essere accettate."""
        m = fresh_middleware
        for _ in range(60):
            resp = await self._dispatch(m, "/api/weather")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sixty_first_returns_429(self, fresh_middleware):
        """La 61a richiesta restituisce 429 Too Many Requests."""
        m = fresh_middleware
        for _ in range(60):
            await self._dispatch(m, "/api/weather")

        resp = await self._dispatch(m, "/api/weather")
        assert resp.status_code == 429

    @pytest.mark.asyncio
    async def test_retry_after_header_on_429(self, fresh_middleware):
        """Header Retry-After presente sulla risposta 429."""
        m = fresh_middleware
        for _ in range(60):
            await self._dispatch(m, "/api/weather")

        resp = await self._dispatch(m, "/api/weather")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        retry_after = int(resp.headers["Retry-After"])
        assert 1 <= retry_after <= 60

    @pytest.mark.asyncio
    async def test_health_excluded(self, fresh_middleware):
        """/health e escluso dal rate limit."""
        m = fresh_middleware
        for _ in range(100):
            resp = await self._dispatch(m, "/health")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_ready_excluded(self, fresh_middleware):
        """/ready e escluso dal rate limit."""
        m = fresh_middleware
        for _ in range(100):
            resp = await self._dispatch(m, "/ready")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_root_excluded(self, fresh_middleware):
        """La root / e esclusa dal rate limit."""
        m = fresh_middleware
        for _ in range(100):
            resp = await self._dispatch(m, "/")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_ip_isolation(self, fresh_middleware):
        """Rate limit e per-IP: due IP diversi hanno contatori separati."""
        m = fresh_middleware
        for _ in range(60):
            await self._dispatch(m, "/api/weather", client_host="1.1.1.1")
        # stesso IP => 429
        resp = await self._dispatch(m, "/api/weather", client_host="1.1.1.1")
        assert resp.status_code == 429

        # altro IP => ancora 200
        resp = await self._dispatch(m, "/api/weather", client_host="2.2.2.2")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_x_forwarded_for_uses_proxy_appended_rightmost_ip(self, fresh_middleware):
        """Il valore spoofabile a sinistra non deve scegliere il bucket."""
        m = fresh_middleware
        for _ in range(60):
            await self._dispatch(m, "/api/weather", forwarded_for="9.9.9.9, 3.3.3.3", client_host="1.1.1.1")

        # Cambiare il valore client-controlled a sinistra non aggira il limite.
        resp = await self._dispatch(m, "/api/weather", forwarded_for="8.8.8.8, 3.3.3.3", client_host="1.1.1.1")
        assert resp.status_code == 429

        # Il client_host originale non e toccato
        resp = await self._dispatch(m, "/api/weather", client_host="1.1.1.1")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_forwarded_for_falls_back_to_client(self, fresh_middleware):
        m = fresh_middleware
        for _ in range(60):
            await self._dispatch(m, "/api/weather", forwarded_for="not-an-ip", client_host="1.1.1.1")

        resp = await self._dispatch(m, "/api/weather", forwarded_for="also-invalid", client_host="1.1.1.1")
        assert resp.status_code == 429

    @pytest.mark.asyncio
    async def test_sensitive_endpoint_has_separate_stricter_bucket(self, fresh_middleware):
        m = fresh_middleware
        for _ in range(10):
            resp = await self._dispatch(m, "/api/telegram/link-code", client_host="1.1.1.1")
            assert resp.status_code == 200

        resp = await self._dispatch(m, "/api/telegram/link-code", client_host="1.1.1.1")
        assert resp.status_code == 429

        # Il bucket sensibile non consuma il limite generale.
        resp = await self._dispatch(m, "/api/weather", client_host="1.1.1.1")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sliding_window(self, fresh_middleware, monkeypatch):
        """La finestra scorrevente: dopo il WINDOW secondi il contatore si resetta."""
        m = fresh_middleware
        fake_time = [0.0]
        monkeypatch.setattr("rate_limiter.time.time", lambda: fake_time[0])

        # 60 richieste al tempo 0
        for _ in range(60):
            await self._dispatch(m, "/api/weather")

        # 61a => 429
        resp = await self._dispatch(m, "/api/weather")
        assert resp.status_code == 429

        # Dopo 61 secondi la finestra e scaduta
        fake_time[0] = 61.0
        resp = await self._dispatch(m, "/api/weather")
        assert resp.status_code == 200
