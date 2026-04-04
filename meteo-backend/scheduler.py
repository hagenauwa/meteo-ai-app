"""
scheduler.py — ciclo orario di raccolta osservazioni, verifica forecast e training ML.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from config import settings
from database import City, MlModelStore, MlPrediction, SessionLocal, WeatherObservation
from weather_service import fetch_all_cities_weather
import ml_model

MIN_VERIFIED_FOR_TRAINING = 500
RETRAIN_EVERY_HOURS = 6
OBSERVATION_RETENTION_DAYS = 30
PREDICTION_RETENTION_DAYS = 45

_last_training: datetime | None = None
scheduler = AsyncIOScheduler(timezone="Europe/Rome")


def _db_get_cities() -> list[dict]:
    with SessionLocal() as db:
        rows = db.query(City.id, City.name, City.lat, City.lon).filter(
            City.locality_type == "comune"
        ).all()
        return [{"id": row.id, "name": row.name, "lat": row.lat, "lon": row.lon} for row in rows]


def _db_save_cycle_data(payload: dict) -> tuple[int, int]:
    observations = payload.get("observations", [])
    predictions = payload.get("predictions", [])

    obs_objects = [
        WeatherObservation(
            city_id=obs["city_id"],
            observed_at=obs["observed_at"],
            temp=obs["temp"],
            humidity=obs.get("humidity"),
            cloud_cover=obs.get("cloud_cover"),
            wind_speed=obs.get("wind_speed"),
            precipitation=obs.get("precipitation", 0.0),
        )
        for obs in observations
        if obs.get("temp") is not None
    ]

    pred_objects = [
        MlPrediction(
            city_id=pred["city_id"],
            predicted_at=pred["predicted_at"],
            target_time=pred["target_time"],
            lead_hours=pred["lead_hours"],
            forecast_source=pred.get("forecast_source", "open-meteo"),
            predicted_temp=pred["forecast_temp"],
            forecast_temp=pred["forecast_temp"],
            humidity=pred.get("humidity"),
            hour=pred["target_time"].hour,
            verified=False,
            precipitation=pred.get("forecast_precipitation"),
            weather_code=pred.get("forecast_weather_code"),
            forecast_precipitation=pred.get("forecast_precipitation"),
            forecast_weather_code=pred.get("forecast_weather_code"),
            forecast_cloud_cover=pred.get("forecast_cloud_cover"),
        )
        for pred in predictions
        if pred.get("forecast_temp") is not None
    ]

    with SessionLocal() as db:
        if obs_objects:
            db.bulk_save_objects(obs_objects)
        if pred_objects:
            db.bulk_save_objects(pred_objects)
        db.commit()

    return len(obs_objects), len(pred_objects)


def _db_verify_predictions(observations: list[dict]) -> tuple[int, float]:
    if not observations:
        return 0, 0.0

    verified_count = 0
    with SessionLocal() as db:
        for obs in observations:
            observed_at = obs["observed_at"].replace(minute=0, second=0, microsecond=0)
            result = db.execute(
                text("""
                    UPDATE ml_predictions
                    SET actual_temp = :actual_temp,
                        actual_precipitation = :actual_precipitation,
                        actual_weather_code = :actual_weather_code,
                        actual_cloud_cover = :actual_cloud_cover,
                        error = :actual_temp - COALESCE(forecast_temp, predicted_temp),
                        verified = :v_true,
                        verified_at = :verified_at
                    WHERE city_id = :city_id
                      AND verified = :v_false
                      AND target_time = :target_time
                """),
                {
                    "actual_temp": obs["temp"],
                    "actual_precipitation": obs.get("precipitation"),
                    "actual_weather_code": obs.get("weather_code"),
                    "actual_cloud_cover": obs.get("cloud_cover"),
                    "verified_at": obs["observed_at"],
                    "city_id": obs["city_id"],
                    "target_time": observed_at,
                    "v_true": True,
                    "v_false": False,
                },
            )
            verified_count += result.rowcount

        db.commit()
        avg_error = db.execute(
            text("""
                SELECT AVG(ABS(error))
                FROM ml_predictions
                WHERE verified = true
                  AND error IS NOT NULL
            """)
        ).scalar()

    return verified_count, float(avg_error or 0.0)


def _db_count_verified() -> int:
    with SessionLocal() as db:
        return db.query(MlPrediction).filter(MlPrediction.verified.is_(True)).count()


def _db_cleanup(now: datetime) -> dict:
    obs_cutoff = now - timedelta(days=OBSERVATION_RETENTION_DAYS)
    pred_cutoff = now - timedelta(days=PREDICTION_RETENTION_DAYS)

    with SessionLocal() as db:
        deleted_obs = db.query(WeatherObservation).filter(
            WeatherObservation.observed_at < obs_cutoff
        ).delete()
        deleted_pred = db.query(MlPrediction).filter(
            MlPrediction.predicted_at < pred_cutoff
        ).delete()

        model_ids = [
            row.id
            for row in db.query(MlModelStore.id)
            .order_by(MlModelStore.trained_at.desc())
            .offset(settings.max_model_store_records)
            .all()
        ]
        deleted_models = 0
        if model_ids:
            deleted_models = db.query(MlModelStore).filter(MlModelStore.id.in_(model_ids)).delete(
                synchronize_session=False
            )

        db.commit()

    return {
        "deleted_observations": deleted_obs,
        "deleted_predictions": deleted_pred,
        "deleted_models": deleted_models,
    }


async def hourly_cycle():
    global _last_training

    print(f"\n{'=' * 60}")
    print(f"[CYCLE] CICLO AUTO-LEARNING — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}")

    cities = await asyncio.to_thread(_db_get_cities)
    if not cities:
        print("[WARN] Nessuna città nel DB")
        return

    payload = await fetch_all_cities_weather(cities)
    observations = payload.get("observations", [])
    predictions = payload.get("predictions", [])
    if not observations:
        print("[WARN] Nessuna osservazione scaricata")
        return

    n_obs, n_pred = await asyncio.to_thread(_db_save_cycle_data, payload)
    print(f"[SAVE] Salvate {n_obs} osservazioni e {n_pred} previsioni future")

    verified_count, avg_error = await asyncio.to_thread(_db_verify_predictions, observations)
    print(f"[OK] Verificate {verified_count} predictions (errore medio: {avg_error:.2f}°C)")

    now = datetime.now(timezone.utc)
    total_verified = await asyncio.to_thread(_db_count_verified)
    should_retrain = (
        total_verified >= MIN_VERIFIED_FOR_TRAINING
        and (_last_training is None or (now - _last_training).total_seconds() >= RETRAIN_EVERY_HOURS * 3600)
    )

    if should_retrain:
        print(f"[TRAIN] Avvio training su {total_verified} campioni verificati")
        result = await asyncio.to_thread(ml_model.train, 100)
        if result["success"]:
            _last_training = now
            print(
                f"[DONE] Modello temperatura aggiornato — MAE: {result['mae']:.3f} "
                f"(baseline {result['baseline_mae']:.3f})"
            )
            if result.get("rain_model_ready"):
                print(
                    f"[DONE] Modello pioggia — Accuracy: {result.get('rain_accuracy', 0):.3f} "
                    f"(baseline {result.get('rain_baseline_accuracy', 0):.3f})"
                )
            elif result.get("rain_message"):
                print(f"[INFO] Modello pioggia non promosso: {result['rain_message']}")
        else:
            print(f"[WARN] Training non promosso: {result.get('message')}")

    cleanup = await asyncio.to_thread(_db_cleanup, now)
    if any(cleanup.values()):
        print(
            f"[CLEAN] obs={cleanup['deleted_observations']} "
            f"pred={cleanup['deleted_predictions']} models={cleanup['deleted_models']}"
        )

    print("[OK] Ciclo completato — prossimo tra 1 ora\n")


def start_scheduler():
    scheduler.add_job(
        hourly_cycle,
        trigger=IntervalTrigger(hours=1),
        id="hourly_cycle",
        name="Raccolta meteo + verifica forecast + training ML",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    print("[SCHED] Scheduler avviato — ciclo ogni ora attivo")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[SCHED] Scheduler fermato")


async def run_cycle_now():
    await hourly_cycle()
