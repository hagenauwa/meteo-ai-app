"""
config.py — configurazione centralizzata backend.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_env: str
    frontend_origin: str
    cors_origins: tuple[str, ...]
    admin_api_token: str
    cities_index_cache_seconds: int
    max_model_store_records: int
    stripe_secret_key: str
    stripe_webhook_secret: str
    supporter_email_encryption_key: str
    supporter_email_hash_key: str

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


def load_settings() -> Settings:
    app_env = os.getenv("APP_ENV")
    if not app_env:
        app_env = "production" if os.getenv("RENDER_EXTERNAL_URL") else "development"

    frontend_origin = os.getenv("FRONTEND_ORIGIN", "https://leprevisioni.netlify.app").strip()
    extra_origins = _split_csv(os.getenv("CORS_ORIGINS", ""))

    cors_origins = [frontend_origin, *extra_origins]
    if app_env != "production":
        cors_origins.extend([
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ])

    seen: set[str] = set()
    ordered_origins = []
    for origin in cors_origins:
        if origin and origin not in seen:
            seen.add(origin)
            ordered_origins.append(origin)

    return Settings(
        app_env=app_env,
        frontend_origin=frontend_origin,
        cors_origins=tuple(ordered_origins),
        admin_api_token=os.getenv("ADMIN_API_TOKEN", "").strip(),
        cities_index_cache_seconds=int(os.getenv("CITIES_INDEX_CACHE_SECONDS", "3600")),
        max_model_store_records=int(os.getenv("MAX_MODEL_STORE_RECORDS", "5")),
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", "").strip(),
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", "").strip(),
        supporter_email_encryption_key=os.getenv("SUPPORTER_EMAIL_ENCRYPTION_KEY", "").strip(),
        supporter_email_hash_key=os.getenv("SUPPORTER_EMAIL_HASH_KEY", "").strip(),
    )


settings = load_settings()
