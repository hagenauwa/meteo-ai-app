"""Integration-style coverage for one mocked scheduler cycle."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import Base, City, MlPrediction, MlTrainingState
import scheduler


@pytest.fixture
def scheduler_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_testing = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_testing)
    return session_testing


@pytest.fixture(autouse=True)
def scheduler_test_defaults(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "settings",
        SimpleNamespace(
            ml_city_sample_size=2,
            ml_city_core_size=1,
            ml_cycle_every_hours=6,
            ml_observation_retention_days=30,
            ml_prediction_retention_days=30,
            max_model_store_records=5,
            ml_min_new_verified_for_retrain=1,
        ),
    )
    monkeypatch.setattr(scheduler, "MIN_VERIFIED_FOR_TRAINING", 1)
    monkeypatch.setattr(scheduler, "RETRAIN_EVERY_HOURS", 1)
    monkeypatch.setattr(scheduler, "_cycle_seed", lambda now: 4242)
    monkeypatch.setattr(scheduler.ml_model, "get_public_summary", lambda: {"model_ready": False})
    monkeypatch.setattr(scheduler.ml_model, "evaluate_shadow_window", lambda: {"checked": False})

    async def check_rain_alerts():
        return {"sent": 0}

    async def check_telegram_rain_alerts():
        return {"sent": 0}

    async def check_telegram_daily_forecasts():
        return {"sent": 0}

    monkeypatch.setitem(
        sys.modules,
        "rain_alert_service",
        SimpleNamespace(check_rain_alerts=check_rain_alerts),
    )
    monkeypatch.setitem(
        sys.modules,
        "telegram_notify_service",
        SimpleNamespace(
            check_telegram_rain_alerts=check_telegram_rain_alerts,
            check_telegram_daily_forecasts=check_telegram_daily_forecasts,
        ),
    )


def _seed_cities(session_factory):
    with session_factory() as db:
        db.add_all(
            [
                City(
                    id=1,
                    name="Roma",
                    name_lower="roma",
                    region="Lazio",
                    province="RM",
                    lat=41.9,
                    lon=12.5,
                    population=100,
                    locality_type="comune",
                ),
                City(
                    id=2,
                    name="Milano",
                    name_lower="milano",
                    region="Lombardia",
                    province="MI",
                    lat=45.46,
                    lon=9.19,
                    population=90,
                    locality_type="comune",
                ),
                City(
                    id=3,
                    name="Arezzo",
                    name_lower="arezzo",
                    region="Toscana",
                    province="AR",
                    lat=43.46,
                    lon=11.88,
                    population=80,
                    locality_type="comune",
                ),
                City(
                    id=4,
                    name="Localita Test",
                    name_lower="localita test",
                    region="Lazio",
                    province="RM",
                    lat=41.0,
                    lon=12.0,
                    population=10,
                    locality_type="localita",
                ),
            ]
        )
        db.commit()


def test_hourly_cycle_success_persists_training_state_and_calls_cleanup(monkeypatch, scheduler_db):
    _seed_cities(scheduler_db)
    sampled_cities = scheduler._db_get_cities()
    observed_at = datetime(2026, 4, 27, 10, 0)

    with scheduler_db() as db:
        db.add(
            MlPrediction(
                city_id=sampled_cities[0]["id"],
                predicted_at=observed_at - timedelta(hours=1),
                target_time=observed_at,
                lead_hours=1,
                forecast_source="open-meteo",
                predicted_temp=19.0,
                forecast_temp=19.0,
                humidity=60.0,
                hour=observed_at.hour,
                verified=False,
            )
        )
        db.commit()

    fetch_calls = []
    cleanup_calls = []
    train_calls = []

    async def fake_fetch_all_cities_weather(cities):
        fetch_calls.append([city["id"] for city in cities])
        target_city = cities[0]
        return {
            "observations": [
                {
                    "city_id": target_city["id"],
                    "observed_at": observed_at,
                    "temp": 21.5,
                    "humidity": 55.0,
                    "cloud_cover": 30.0,
                    "wind_speed": 11.0,
                    "wind_direction": 180.0,
                    "precipitation": 0.2,
                    "weather_code": 61,
                }
            ],
            "predictions": [
                {
                    "city_id": target_city["id"],
                    "predicted_at": observed_at,
                    "target_time": observed_at + timedelta(hours=1),
                    "lead_hours": 1,
                    "forecast_source": "open-meteo",
                    "forecast_temp": 22.0,
                    "humidity": 50.0,
                    "forecast_precipitation": 0.1,
                    "forecast_weather_code": 2,
                    "forecast_cloud_cover": 20.0,
                    "forecast_wind_speed": 10.0,
                    "forecast_wind_direction": 170.0,
                }
            ],
        }

    def fake_cleanup(now):
        cleanup_calls.append(now)
        return {
            "deleted_observations": 0,
            "deleted_predictions": 0,
            "deleted_models": 0,
        }

    def fake_train(min_samples):
        train_calls.append(min_samples)
        return {
            "success": True,
            "mae": 0.8,
            "baseline_mae": 1.1,
            "rain_model_ready": False,
            "condition_model_ready": False,
        }

    def fake_verify_predictions(observations):
        with scheduler_db() as db:
            prediction = db.query(MlPrediction).filter(MlPrediction.target_time == observed_at).one()
            prediction.verified = True
            prediction.actual_temp = observations[0]["temp"]
            prediction.error = observations[0]["temp"] - prediction.forecast_temp
            db.commit()
        return 1, 2.5

    monkeypatch.setattr(scheduler, "fetch_all_cities_weather", fake_fetch_all_cities_weather)
    monkeypatch.setattr(scheduler, "_db_cleanup", fake_cleanup)
    monkeypatch.setattr(scheduler, "_db_verify_predictions", fake_verify_predictions)
    monkeypatch.setattr(scheduler.ml_model, "train", fake_train)
    monkeypatch.setattr(
        scheduler,
        "_db_latest_model_info",
        lambda: {"id": 77, "trained_at": observed_at + timedelta(minutes=5)},
    )

    result = asyncio.run(scheduler.hourly_cycle())

    assert fetch_calls == [[city["id"] for city in sampled_cities]]
    assert len(fetch_calls[0]) == 2
    assert 1 in fetch_calls[0]
    assert 4 not in fetch_calls[0]
    assert len(cleanup_calls) == 2
    assert train_calls == [100]
    assert result["last_cycle_status"] == "success"
    assert result["last_cycle_message"] == "train_success"
    assert result["last_cycle_observations"] == 1
    assert result["last_cycle_predictions"] == 1
    assert result["last_cycle_verified"] == 1
    assert result["verified_count_at_last_train"] == 1
    assert result["last_model_store_id"] == 77
    assert result["last_successful_train_at"] is not None

    with scheduler_db() as db:
        verified_prediction = db.query(MlPrediction).filter(MlPrediction.target_time == observed_at).one()
        state = db.get(MlTrainingState, scheduler.TRAINING_STATE_ID)

        assert verified_prediction.verified is True
        assert verified_prediction.actual_temp == 21.5
        assert verified_prediction.error == pytest.approx(2.5)
        assert state is not None
        assert state.last_cycle_status == "success"
        assert state.last_cycle_message == "train_success"
        assert state.last_cycle_observations == 1
        assert state.last_cycle_predictions == 1
        assert state.last_cycle_verified == 1
        assert state.verified_count_at_last_train == 1


def test_db_save_cycle_data_persists_new_rain_forecast_features(scheduler_db):
    with scheduler_db() as db:
        db.add(
            City(
                id=1,
                name="Roma",
                name_lower="roma",
                region="Lazio",
                province="RM",
                lat=41.9,
                lon=12.5,
                population=100,
                locality_type="comune",
            )
        )
        db.commit()

    payload = {
        "observations": [],
        "predictions": [
            {
                "city_id": 1,
                "predicted_at": datetime(2026, 7, 1, 10, 0),
                "target_time": datetime(2026, 7, 1, 11, 0),
                "lead_hours": 1,
                "forecast_source": "open-meteo",
                "forecast_temp": 22.0,
                "humidity": 50.0,
                "forecast_precipitation": 0.1,
                "forecast_weather_code": 2,
                "forecast_cloud_cover": 20.0,
                "forecast_wind_speed": 10.0,
                "forecast_wind_direction": 170.0,
                "forecast_precipitation_probability": 65,
                "forecast_surface_pressure": 1009.0,
                "forecast_dew_point": 14.0,
                "forecast_cape": 800.0,
            }
        ],
    }

    n_obs, n_pred = scheduler._db_save_cycle_data(payload)
    assert (n_obs, n_pred) == (0, 1)

    with scheduler_db() as db:
        prediction = db.query(MlPrediction).one()
        assert prediction.forecast_precipitation_probability == 65
        assert prediction.forecast_surface_pressure == 1009.0
        assert prediction.forecast_dew_point == 14.0
        assert prediction.forecast_cape == 800.0


def test_count_verified_since_uses_timestamp_not_retention_affected_total(scheduler_db):
    with scheduler_db() as db:
        db.add(
            City(
                id=10,
                name="Massa",
                name_lower="massa",
                region="Toscana",
                province="Massa-Carrara",
                lat=44.04,
                lon=10.14,
                population=100,
                locality_type="comune",
            )
        )
        last_train_at = datetime(2026, 5, 21, 6, tzinfo=timezone.utc)
        before_target = last_train_at - timedelta(hours=1)
        after_target = last_train_at + timedelta(hours=1)
        db.add_all(
            [
                MlPrediction(
                    city_id=10,
                    predicted_at=before_target - timedelta(hours=1),
                    target_time=before_target,
                    lead_hours=1,
                    predicted_temp=18.0,
                    forecast_temp=18.0,
                    verified=True,
                    actual_temp=18.5,
                    error=0.5,
                    verified_at=before_target,
                ),
                MlPrediction(
                    city_id=10,
                    predicted_at=after_target - timedelta(hours=1),
                    target_time=after_target,
                    lead_hours=1,
                    predicted_temp=19.0,
                    forecast_temp=19.0,
                    verified=True,
                    actual_temp=20.0,
                    error=1.0,
                    verified_at=after_target,
                ),
            ]
        )
        db.commit()

    assert scheduler._db_count_verified_since(last_train_at) == 1


def test_telegram_notifications_cycle_runs_both_checks(monkeypatch):
    calls = []

    async def fake_rain():
        calls.append("rain")
        return {"sent": 1}

    async def fake_daily():
        calls.append("daily")
        return {"sent": 2}

    monkeypatch.setitem(
        sys.modules,
        "telegram_notify_service",
        SimpleNamespace(
            check_telegram_rain_alerts=fake_rain,
            check_telegram_daily_forecasts=fake_daily,
        ),
    )

    result = asyncio.run(scheduler.telegram_notifications_cycle())

    assert calls == ["rain", "daily"]
    assert result == {"rain_alerts": {"sent": 1}, "daily_forecasts": {"sent": 2}}


def test_telegram_notifications_cycle_swallows_errors(monkeypatch):
    async def boom():
        raise RuntimeError("telegram down")

    async def fake_daily():
        return {"sent": 0}

    monkeypatch.setitem(
        sys.modules,
        "telegram_notify_service",
        SimpleNamespace(
            check_telegram_rain_alerts=boom,
            check_telegram_daily_forecasts=fake_daily,
        ),
    )

    result = asyncio.run(scheduler.telegram_notifications_cycle())

    assert result == {"error": "telegram down"}


class _FakeScheduler:
    """Registra le add_job senza avviare un vero AsyncIOScheduler."""

    running = True  # fa uscire start_scheduler prima di scheduler.start()

    def __init__(self):
        self.jobs = []

    def add_job(self, func, **kwargs):
        self.jobs.append((kwargs.get("id"), func))


def test_start_scheduler_registers_telegram_job_when_token_set(monkeypatch):
    fake = _FakeScheduler()
    monkeypatch.setattr(scheduler, "scheduler", fake)
    monkeypatch.setattr(
        scheduler,
        "settings",
        SimpleNamespace(ml_cycle_every_hours=1, telegram_bot_token="123:abc"),
    )

    scheduler.start_scheduler()

    job_ids = [job_id for job_id, _ in fake.jobs]
    assert "hourly_cycle" in job_ids
    assert "telegram_notifications" in job_ids


def test_start_scheduler_skips_telegram_job_without_token(monkeypatch):
    fake = _FakeScheduler()
    monkeypatch.setattr(scheduler, "scheduler", fake)
    monkeypatch.setattr(
        scheduler,
        "settings",
        SimpleNamespace(ml_cycle_every_hours=1, telegram_bot_token=""),
    )

    scheduler.start_scheduler()

    job_ids = [job_id for job_id, _ in fake.jobs]
    assert "hourly_cycle" in job_ids
    assert "telegram_notifications" not in job_ids


def test_hourly_cycle_failure_marks_state_without_reraising(monkeypatch, scheduler_db):
    _seed_cities(scheduler_db)

    cleanup_calls = []

    async def fake_fetch_all_cities_weather(cities):
        raise RuntimeError("mock upstream failure")

    def fake_cleanup(now):
        cleanup_calls.append(now)
        return {
            "deleted_observations": 0,
            "deleted_predictions": 0,
            "deleted_models": 0,
        }

    monkeypatch.setattr(scheduler, "fetch_all_cities_weather", fake_fetch_all_cities_weather)
    monkeypatch.setattr(scheduler, "_db_cleanup", fake_cleanup)

    result = asyncio.run(scheduler.hourly_cycle())

    assert len(cleanup_calls) == 1
    assert result["last_cycle_status"] == "failed"
    assert result["last_cycle_message"] == "mock upstream failure"
    assert result["last_cycle_observations"] == 0
    assert result["last_cycle_predictions"] == 0
    assert result["last_cycle_verified"] == 0

    with scheduler_db() as db:
        state = db.get(MlTrainingState, scheduler.TRAINING_STATE_ID)

        assert state is not None
        assert state.last_cycle_status == "failed"
        assert state.last_cycle_message == "mock upstream failure"
        assert state.last_cycle_started_at is not None
        assert state.last_cycle_completed_at is not None
