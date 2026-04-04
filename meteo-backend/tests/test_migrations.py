"""Smoke test per migrazioni Alembic."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_alembic_upgrade_creates_expected_schema(tmp_path):
    db_path = tmp_path / "migration_smoke.db"
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    cfg.set_main_option("script_location", str(backend_root / "db_migrations"))

    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)

    assert "cities" in inspector.get_table_names()
    assert "weather_observations" in inspector.get_table_names()
    assert "ml_predictions" in inspector.get_table_names()
    assert "ml_model_store" in inspector.get_table_names()
    assert "supporters" in inspector.get_table_names()
    assert "supporter_tokens" in inspector.get_table_names()

    prediction_columns = {column["name"] for column in inspector.get_columns("ml_predictions")}
    assert {"target_time", "lead_hours", "forecast_temp", "actual_precipitation"} <= prediction_columns
    assert {
        "forecast_wind_speed",
        "forecast_wind_direction",
        "actual_wind_speed",
        "actual_wind_direction",
    } <= prediction_columns

    observation_columns = {column["name"] for column in inspector.get_columns("weather_observations")}
    assert {"wind_direction"} <= observation_columns

    supporter_columns = {column["name"] for column in inspector.get_columns("supporters")}
    assert {"email_encrypted", "email_lookup_hash", "donation_count", "last_checkout_session_id"} <= supporter_columns

    supporter_token_columns = {column["name"] for column in inspector.get_columns("supporter_tokens")}
    assert {"supporter_id", "token_hash", "last_seen_at"} <= supporter_token_columns
