"""Test configurazione backend."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config


def test_ml_training_bounds_defaults(monkeypatch):
    monkeypatch.delenv("ML_TRAINING_WINDOW_DAYS", raising=False)
    monkeypatch.delenv("ML_TRAINING_MAX_ROWS", raising=False)

    settings = config.load_settings()

    assert settings.ml_training_window_days == 30
    assert settings.ml_training_max_rows == 60000


def test_ml_training_bounds_have_minimums(monkeypatch):
    monkeypatch.setenv("ML_TRAINING_WINDOW_DAYS", "1")
    monkeypatch.setenv("ML_TRAINING_MAX_ROWS", "10")

    settings = config.load_settings()

    assert settings.ml_training_window_days == 3
    assert settings.ml_training_max_rows == 1000
