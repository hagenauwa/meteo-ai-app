"""Shared pytest test-suite setup for backend tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest


PYTEST_TEMP_ROOT = Path("C:/Users/Andrea/AppData/Local/Temp/opencode/pytest").resolve()
PYTEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(PYTEST_TEMP_ROOT))


def _find_rate_limit_middleware():
    from main import app
    from rate_limiter import RateLimitMiddleware

    if app.middleware_stack is None:
        app.middleware_stack = app.build_middleware_stack()

    current = app.middleware_stack
    while current is not None:
        if isinstance(current, RateLimitMiddleware):
            return current
        current = getattr(current, "app", None)
    return None


@pytest.fixture(autouse=True)
def reset_rate_limiter_state() -> Iterator[None]:
    middleware = _find_rate_limit_middleware()
    if middleware is not None:
        with middleware._lock:
            middleware._requests.clear()

    yield

    if middleware is not None:
        with middleware._lock:
            middleware._requests.clear()
