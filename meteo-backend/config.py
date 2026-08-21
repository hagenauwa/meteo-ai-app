"""
config.py — configurazione centralizzata backend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int_csv(value: str | None, default: tuple[int, ...]) -> tuple[int, ...]:
    if not value:
        return default

    parsed: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            parsed.append(int(item))
        except ValueError:
            continue

    return tuple(parsed) or default


@dataclass(frozen=False)
class Settings:
    app_env: str = "development"
    frontend_origin: str = "https://leprevisioni.netlify.app"
    cors_origins: tuple[str, ...] = ("https://leprevisioni.netlify.app",)
    cors_origin_regex: str | None = None
    enable_scheduler: bool = True
    auto_load_cities: bool = True
    admin_api_token: str = ""
    model_signing_key: str = ""
    cities_index_cache_seconds: int = 3600
    max_model_store_records: int = 5
    ml_v2_enabled: bool = True
    ml_v2_shadow_only: bool = True
    ml_v2_rollout_percent: int = 0
    ml_require_trusted_observations: bool = False
    ml_trusted_observation_sources: tuple[str, ...] = ("station", "arpa", "meteostat")
    ml_kpi_window_days: int = 14
    ml_training_window_days: int = 30
    ml_training_max_rows: int = 60000
    ml_min_new_verified_for_retrain: int = 500
    ml_city_sample_size: int = 300
    ml_city_core_size: int = 80
    # Area di copertura ML (training, raccolta dati e serving "onesto"). Espansione
    # graduale da Massa-Carrara a tutta la Toscana + La Spezia (climi affini).
    # Nel DB le province sono nomi completi (es. "Massa-Carrara", non "MS").
    ml_training_allowed_provinces: tuple[str, ...] = (
        "Massa-Carrara",
        "Lucca",
        "Pisa",
        "Livorno",
        "Pistoia",
        "Prato",
        "Firenze",
        "Arezzo",
        "Siena",
        "Grosseto",
        "La Spezia",
    )
    ml_forecast_leads: tuple[int, ...] = (1, 3, 6, 14, 38, 86, 158)
    ml_cycle_every_hours: int = 1
    ml_observation_retention_days: int = 7
    ml_prediction_retention_days: int = 8
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    supporter_email_encryption_key: str = ""
    supporter_email_hash_key: str = ""
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_webhook_url: str = "https://meteo-ai-backend.onrender.com/api/telegram/webhook"

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
        cors_origins.extend(
            [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8888",
                "http://127.0.0.1:8888",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
            ]
        )

    seen: set[str] = set()
    ordered_origins = []
    for origin in cors_origins:
        if origin and origin not in seen:
            seen.add(origin)
            ordered_origins.append(origin)

    cors_origin_regex = None
    if app_env != "production":
        # In sviluppo locale possono servire origin LAN o tunnel pubblici temporanei.
        cors_origin_regex = r"^https?://.+$"

    return Settings(
        app_env=app_env,
        frontend_origin=frontend_origin,
        cors_origins=tuple(ordered_origins),
        cors_origin_regex=cors_origin_regex,
        enable_scheduler=_as_bool(os.getenv("ENABLE_SCHEDULER"), default=app_env == "production"),
        auto_load_cities=_as_bool(os.getenv("AUTO_LOAD_CITIES"), default=app_env == "production"),
        admin_api_token=os.getenv("ADMIN_API_TOKEN", "").strip(),
        model_signing_key=os.getenv("MODEL_SIGNING_KEY", "").strip(),
        cities_index_cache_seconds=int(os.getenv("CITIES_INDEX_CACHE_SECONDS", "3600")),
        max_model_store_records=int(os.getenv("MAX_MODEL_STORE_RECORDS", "5")),
        ml_v2_enabled=_as_bool(os.getenv("ML_V2_ENABLED"), default=True),
        ml_v2_shadow_only=_as_bool(os.getenv("ML_V2_SHADOW_ONLY"), default=True),
        ml_v2_rollout_percent=max(0, min(100, int(os.getenv("ML_V2_ROLLOUT_PERCENT", "0")))),
        ml_require_trusted_observations=_as_bool(
            os.getenv("ML_REQUIRE_TRUSTED_OBSERVATIONS"), default=app_env == "production"
        ),
        ml_trusted_observation_sources=tuple(
            source.lower()
            for source in _split_csv(os.getenv("ML_TRUSTED_OBSERVATION_SOURCES", "station,arpa,meteostat"))
        ),
        ml_kpi_window_days=max(3, int(os.getenv("ML_KPI_WINDOW_DAYS", "14"))),
        ml_training_window_days=max(3, int(os.getenv("ML_TRAINING_WINDOW_DAYS", "30"))),
        ml_training_max_rows=max(1000, int(os.getenv("ML_TRAINING_MAX_ROWS", "60000"))),
        ml_min_new_verified_for_retrain=max(50, int(os.getenv("ML_MIN_NEW_VERIFIED_FOR_RETRAIN", "500"))),
        ml_city_sample_size=max(1, int(os.getenv("ML_CITY_SAMPLE_SIZE", "300"))),
        ml_city_core_size=max(0, int(os.getenv("ML_CITY_CORE_SIZE", "80"))),
        ml_training_allowed_provinces=tuple(
            _split_csv(
                os.getenv(
                    "ML_TRAINING_ALLOWED_PROVINCES",
                    "Massa-Carrara,Lucca,Pisa,Livorno,Pistoia,Prato,Firenze,Arezzo,Siena,Grosseto,La Spezia",
                )
            )
        ),
        ml_forecast_leads=tuple(
            sorted(
                {
                    max(1, min(240, lead))
                    for lead in _as_int_csv(os.getenv("ML_FORECAST_LEADS"), (1, 3, 6, 14, 38, 86, 158))
                }
            )
        ),
        ml_cycle_every_hours=max(1, int(os.getenv("ML_CYCLE_EVERY_HOURS", "1"))),
        ml_observation_retention_days=max(1, int(os.getenv("ML_OBSERVATION_RETENTION_DAYS", "7"))),
        ml_prediction_retention_days=max(1, int(os.getenv("ML_PREDICTION_RETENTION_DAYS", "8"))),
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", "").strip(),
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", "").strip(),
        supporter_email_encryption_key=os.getenv("SUPPORTER_EMAIL_ENCRYPTION_KEY", "").strip(),
        supporter_email_hash_key=os.getenv("SUPPORTER_EMAIL_HASH_KEY", "").strip(),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip(),
        telegram_webhook_url=os.getenv(
            "TELEGRAM_WEBHOOK_URL", "https://meteo-ai-backend.onrender.com/api/telegram/webhook"
        ).strip(),
    )


settings = load_settings()
