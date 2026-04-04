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
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)

    assert "cities" in inspector.get_table_names()
    assert "weather_observations" in inspector.get_table_names()
    assert "ml_predictions" in inspector.get_table_names()
    assert "ml_model_store" in inspector.get_table_names()

    prediction_columns = {column["name"] for column in inspector.get_columns("ml_predictions")}
    assert {"target_time", "lead_hours", "forecast_temp", "actual_precipitation"} <= prediction_columns
