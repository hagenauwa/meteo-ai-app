"""Smoke test minimale per il deploy pubblico del backend Meteo AI."""
from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=30) as response:
            payload = response.read().decode("utf-8")
            return response.status, json.loads(payload)
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} -> HTTP {exc.code}: {payload[:300]}") from exc
    except URLError as exc:
        raise RuntimeError(f"{url} -> network error: {exc.reason}") from exc


def _assert(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "https://meteo-ai-backend.onrender.com"
    base_url = base_url.rstrip("/")

    checks = [
        ("health", f"{base_url}/health"),
        ("ready", f"{base_url}/ready"),
        ("weather", f"{base_url}/api/weather?{urlencode({'city': 'Roma'})}"),
    ]

    for label, url in checks:
        status, payload = _get_json(url)
        print(f"[{label}] HTTP {status}")
        _assert(status == 200, f"{label}: expected HTTP 200, got {status}")

        if label == "health":
            _assert(payload.get("status") == "ok", f"{label}: unexpected payload {payload}")
        elif label == "ready":
            _assert(payload.get("status") in {"ready", "degraded"}, f"{label}: unexpected payload {payload}")
        elif label == "weather":
            _assert("current" in payload, f"{label}: missing 'current'")
            _assert("hourly" in payload and isinstance(payload["hourly"], list), f"{label}: missing 'hourly'")
            _assert("daily" in payload and isinstance(payload["daily"], list), f"{label}: missing 'daily'")
            _assert("ml" in payload, f"{label}: missing 'ml'")

    print("[ok] Smoke deploy completato")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
