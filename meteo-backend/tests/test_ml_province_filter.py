"""Test filtro provinciale per training ML pioggia."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import Base, City, MlPrediction
import ml_model
import scheduler


def _settings_with_provinces(*provinces: str) -> SimpleNamespace:
    return SimpleNamespace(
        ml_city_sample_size=20,
        ml_city_core_size=5,
        ml_cycle_every_hours=6,
        ml_training_allowed_provinces=tuple(provinces),
        ml_training_window_days=30,
        ml_training_max_rows=60000,
    )


def _city(city_id: int, name: str, province: str, population: int = 100) -> City:
    return City(
        id=city_id,
        name=name,
        name_lower=name.lower(),
        region="Toscana",
        province=province,
        lat=44.0 + city_id / 100,
        lon=10.0 + city_id / 100,
        population=population,
        locality_type="comune",
    )


def _prediction(city_id: int, target_time: datetime) -> MlPrediction:
    return MlPrediction(
        city_id=city_id,
        predicted_at=target_time - timedelta(hours=1),
        target_time=target_time,
        lead_hours=1,
        forecast_source="open-meteo",
        predicted_temp=18.0,
        forecast_temp=18.0,
        humidity=75.0,
        hour=target_time.hour,
        verified=True,
        actual_temp=19.0,
        error=1.0,
        verified_at=target_time,
        forecast_precipitation=0.2,
        actual_precipitation=0.4,
    )


def test_scheduler_training_city_sample_can_be_limited_to_massa_carrara(monkeypatch):
    monkeypatch.setattr(scheduler, "settings", _settings_with_provinces("Massa-Carrara"))
    cities = [
        {"id": 1, "name": "Massa", "region": "Toscana", "province": "Massa-Carrara", "population": 100},
        {"id": 2, "name": "Carrara", "region": "Toscana", "province": "MS", "population": 90},
        {"id": 3, "name": "Lucca", "region": "Toscana", "province": "Lucca", "population": 80},
    ]

    selected = scheduler._select_training_cities(cities, datetime(2026, 5, 21, tzinfo=timezone.utc))

    assert [city["name"] for city in selected] == ["Massa"]


def test_prepare_training_rows_can_be_limited_to_massa_carrara(monkeypatch):
    monkeypatch.setattr(ml_model, "settings", _settings_with_provinces("Massa-Carrara"))
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionTesting = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    target_time = datetime(2026, 5, 21, 12, tzinfo=timezone.utc)

    with SessionTesting() as db:
        db.add_all(
            [
                _city(1, "Massa", "Massa-Carrara"),
                _city(2, "Lucca", "Lucca"),
            ]
        )
        db.add_all(
            [
                _prediction(1, target_time),
                _prediction(2, target_time),
            ]
        )
        db.commit()

        rows = ml_model._prepare_training_rows(
            db,
            window_start=target_time - timedelta(days=1),
            limit=100,
        )

    assert len(rows) == 1
    assert rows[0]["province"] == "Massa-Carrara"
    assert rows[0]["lat"] == 44.01
