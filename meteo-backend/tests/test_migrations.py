"""Smoke test per migrazioni Alembic."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

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
    assert "ml_training_state" in inspector.get_table_names()
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
    assert {
        "forecast_precipitation_probability",
        "forecast_surface_pressure",
        "forecast_dew_point",
        "forecast_cape",
    } <= prediction_columns
    prediction_indexes = {index["name"] for index in inspector.get_indexes("ml_predictions")}
    assert "idx_pred_verify_lookup" in prediction_indexes

    observation_columns = {column["name"] for column in inspector.get_columns("weather_observations")}
    assert {"wind_direction"} <= observation_columns

    training_columns = {column["name"] for column in inspector.get_columns("ml_training_state")}
    assert {"last_cycle_status", "last_successful_train_at", "verified_count_at_last_train"} <= training_columns
    training_indexes = {index["name"] for index in inspector.get_indexes("ml_training_state")}
    assert "idx_ml_training_state_last_train" in training_indexes

    supporter_columns = {column["name"] for column in inspector.get_columns("supporters")}
    assert {"email_encrypted", "email_lookup_hash", "donation_count", "last_checkout_session_id"} <= supporter_columns

    supporter_token_columns = {column["name"] for column in inspector.get_columns("supporter_tokens")}
    assert {"supporter_id", "token_hash", "last_seen_at"} <= supporter_token_columns


def test_observation_validation_migration_preserves_existing_model_and_prediction(tmp_path):
    backend_root = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'existing_model.db'}"
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(backend_root / "db_migrations"))
    command.upgrade(cfg, "20260822_0002")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_model_store (id, trained_at, model_bytes, n_samples) VALUES (1, '2026-08-28', :blob, 500)"
            ),
            {"blob": b"original-model"},
        )
        conn.execute(text("INSERT INTO cities (id, name, name_lower, lat, lon) VALUES (1, 'Comune', 'comune', 44, 10)"))
        conn.execute(
            text(
                "INSERT INTO ml_predictions (id, city_id, predicted_at, target_time, predicted_temp, actual_source, verified) VALUES (1, 1, '2026-08-28', '2026-08-29', 20, 'meteostat', true)"
            )
        )

    for _ in range(2):
        command.upgrade(cfg, "head")
        inspector = inspect(engine)
        assert {"station_id", "station_distance_km"} <= {
            col["name"] for col in inspector.get_columns("weather_observations")
        }
        assert {"actual_station_id", "actual_station_distance_km"} <= {
            col["name"] for col in inspector.get_columns("ml_predictions")
        }
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT model_bytes, validation_state FROM ml_model_store WHERE id = 1")
            ).one() == (b"original-model", None)
            assert conn.execute(text("SELECT actual_source, verified FROM ml_predictions WHERE id = 1")).one() == (
                "meteostat",
                1,
            )
        command.downgrade(cfg, "20260822_0002")
    engine.dispose()
