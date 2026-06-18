from datetime import datetime, timedelta, timezone
import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scheduler
from database import Base, City, MlPrediction

ml_router = importlib.import_module("routers.ml")


def test_should_retrain_uses_new_verified_when_retention_lowered_total():
    now = datetime(2026, 6, 16, 12, tzinfo=timezone.utc)

    assert scheduler._should_retrain(
        total_verified=scheduler.MIN_VERIFIED_FOR_TRAINING - 75,
        new_verified_since_last=scheduler.settings.ml_min_new_verified_for_retrain,
        last_training=now - timedelta(hours=scheduler.RETRAIN_EVERY_HOURS + 1),
        now=now,
        model_ready=True,
    )


def test_should_not_retrain_before_interval_even_with_enough_new_samples():
    now = datetime(2026, 6, 16, 12, tzinfo=timezone.utc)

    assert not scheduler._should_retrain(
        total_verified=scheduler.MIN_VERIFIED_FOR_TRAINING + 100,
        new_verified_since_last=scheduler.settings.ml_min_new_verified_for_retrain + 100,
        last_training=now - timedelta(hours=1),
        now=now,
        model_ready=True,
    )


def test_db_verify_predictions_matches_aware_observation_to_naive_target(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'ml-test.db'}")
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(scheduler, "SessionLocal", TestingSessionLocal)

    target_time = datetime(2026, 6, 16, 10, 0, 0)
    with TestingSessionLocal() as db:
        db.add(
            City(
                id=1,
                name="Massa",
                name_lower="massa",
                region="Toscana",
                province="Massa-Carrara",
                lat=44.0,
                lon=10.1,
                locality_type="comune",
            )
        )
        db.add(
            MlPrediction(
                id=1,
                city_id=1,
                predicted_at=target_time - timedelta(hours=1),
                target_time=target_time,
                lead_hours=1,
                predicted_temp=19.0,
                forecast_temp=20.0,
                humidity=80.0,
                verified=False,
            )
        )
        db.commit()

    verified_count, avg_error = scheduler._db_verify_predictions(
        [
            {
                "city_id": 1,
                "observed_at": target_time.replace(tzinfo=timezone.utc, minute=23, second=45),
                "temp": 21.5,
                "precipitation": 1.2,
                "weather_code": 61,
                "cloud_cover": 90.0,
                "wind_speed": 12.0,
                "wind_direction": 180.0,
            }
        ]
    )

    assert verified_count == 1
    assert avg_error == pytest.approx(1.5)
    with TestingSessionLocal() as db:
        prediction = db.get(MlPrediction, 1)
        assert prediction.verified is True
        assert prediction.verified_at == target_time
        assert prediction.actual_precipitation == 1.2


@pytest.mark.asyncio
async def test_rain_prediction_endpoint_passes_forecast_features_to_model(monkeypatch):
    captured = {}

    def fake_resolve_city_context(city, db):
        return {
            "resolved": True,
            "lat": 44.0,
            "lon": 10.1,
            "region": "Toscana",
            "warning": None,
        }

    def fake_predict_rain_probability(**kwargs):
        captured.update(kwargs)
        return {"model_ready": True, "rain_probability": 0.8, "model_variant": "v2"}

    monkeypatch.setattr(ml_router, "_resolve_city_context", fake_resolve_city_context)
    monkeypatch.setattr(ml_router.ml_model, "predict_rain_probability", fake_predict_rain_probability)

    result = await ml_router.get_rain_prediction(
        city="Massa",
        temp=20.0,
        humidity=75.0,
        hour=9,
        cloud_cover=88.0,
        lead_hours=3,
        forecast_precipitation=2.4,
        forecast_wind_speed=14.0,
        forecast_wind_direction=210.0,
        forecast_weather_code=61,
        db=object(),
    )

    assert result["model_variant"] == "v2"
    assert captured["forecast_precipitation"] == 2.4
    assert captured["forecast_wind_speed"] == 14.0
    assert captured["forecast_wind_direction"] == 210.0
    assert captured["forecast_weather_code"] == 61
    assert captured["city_name"] == "Massa"


def test_db_verify_predictions_bulk_multi_city_dedup(tmp_path, monkeypatch):
    """Bulk lookup: 2 citta x 2 target_times + 1 obs duplicata.

    Verifica che (a) il bulk lookup matchi tutte le predizioni non verificate,
    (b) un'osservazione duplicata su (city_id, target_time) non verifichi due
    volte la stessa predizione (fix del double-count latente del .first() loop).
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'ml-bulk.db'}")
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(scheduler, "SessionLocal", TestingSessionLocal)

    t1 = datetime(2026, 6, 16, 10, 0, 0)
    t2 = datetime(2026, 6, 16, 11, 0, 0)

    with TestingSessionLocal() as db:
        db.add(
            City(
                id=1,
                name="Massa",
                name_lower="massa",
                region="Toscana",
                province="Massa-Carrara",
                lat=44.0,
                lon=10.1,
                locality_type="comune",
            )
        )
        db.add(
            City(
                id=2,
                name="Lucca",
                name_lower="lucca",
                region="Toscana",
                province="Lucca",
                lat=43.8,
                lon=10.5,
                locality_type="comune",
            )
        )
        # 4 predizioni non verificate: 2 citta x 2 target_time
        pred_id = 1
        for cid in (1, 2):
            for target in (t1, t2):
                db.add(
                    MlPrediction(
                        id=pred_id,
                        city_id=cid,
                        predicted_at=target - timedelta(hours=1),
                        target_time=target,
                        lead_hours=1,
                        predicted_temp=19.0,
                        forecast_temp=20.0,
                        humidity=80.0,
                        verified=False,
                    )
                )
                pred_id += 1
        db.commit()

    # 5 osservazioni: 4 univoche + 1 duplicata su (city_id=1, target_time=t1)
    observations = []
    for cid, target in [(1, t1), (1, t2), (2, t1), (2, t2), (1, t1)]:
        observations.append(
            {
                "city_id": cid,
                "observed_at": target.replace(tzinfo=timezone.utc, minute=23, second=45),
                "temp": 21.5,
                "precipitation": 1.2,
                "weather_code": 61,
                "cloud_cover": 90.0,
                "wind_speed": 12.0,
                "wind_direction": 180.0,
            }
        )

    verified_count, _ = scheduler._db_verify_predictions(observations)

    # 4 predizioni verificate, non 5: l'obs duplicata non deve contare due volte
    assert verified_count == 4
    with TestingSessionLocal() as db:
        verified = db.query(MlPrediction).filter(MlPrediction.verified.is_(True)).all()
        assert len(verified) == 4
        # Nessuna predizione verificata due volte (verified_at impostato una sola volta)
        assert all(p.verified_at is not None for p in verified)
