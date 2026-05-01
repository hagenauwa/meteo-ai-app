"""Test configurazione backend."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config


def test_ml_training_bounds_defaults(monkeypatch):
    monkeypatch.delenv("ML_TRAINING_WINDOW_DAYS", raising=False)
    monkeypatch.delenv("ML_TRAINING_MAX_ROWS", raising=False)
    monkeypatch.delenv("ML_CITY_SAMPLE_SIZE", raising=False)
    monkeypatch.delenv("ML_CITY_CORE_SIZE", raising=False)
    monkeypatch.delenv("ML_FORECAST_LEADS", raising=False)
    monkeypatch.delenv("ML_CYCLE_EVERY_HOURS", raising=False)
    monkeypatch.delenv("ML_OBSERVATION_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("ML_PREDICTION_RETENTION_DAYS", raising=False)

    settings = config.load_settings()

    assert settings.ml_training_window_days == 30
    assert settings.ml_training_max_rows == 60000
    assert settings.ml_city_sample_size == 800
    assert settings.ml_city_core_size == 100
    assert settings.ml_forecast_leads == (1, 3, 6, 14, 38, 86, 158)
    assert settings.ml_cycle_every_hours == 1
    assert settings.ml_observation_retention_days == 21
    assert settings.ml_prediction_retention_days == 21


def test_ml_training_bounds_have_minimums(monkeypatch):
    monkeypatch.setenv("ML_TRAINING_WINDOW_DAYS", "1")
    monkeypatch.setenv("ML_TRAINING_MAX_ROWS", "10")
    monkeypatch.setenv("ML_CITY_SAMPLE_SIZE", "0")
    monkeypatch.setenv("ML_CITY_CORE_SIZE", "-1")
    monkeypatch.setenv("ML_FORECAST_LEADS", "0,3,999,bad")
    monkeypatch.setenv("ML_CYCLE_EVERY_HOURS", "0")
    monkeypatch.setenv("ML_OBSERVATION_RETENTION_DAYS", "0")
    monkeypatch.setenv("ML_PREDICTION_RETENTION_DAYS", "0")

    settings = config.load_settings()

    assert settings.ml_training_window_days == 3
    assert settings.ml_training_max_rows == 1000
    assert settings.ml_city_sample_size == 1
    assert settings.ml_city_core_size == 0
    assert settings.ml_forecast_leads == (1, 3, 240)
    assert settings.ml_cycle_every_hours == 1
    assert settings.ml_observation_retention_days == 1
    assert settings.ml_prediction_retention_days == 1
