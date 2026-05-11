"""
scheduler.py — ciclo orario di raccolta osservazioni, verifica forecast e training ML.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.base import SchedulerAlreadyRunningError, SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from config import settings
from database import City, MlModelStore, MlPrediction, MlTrainingState, SessionLocal, WeatherObservation
from weather_service import fetch_all_cities_weather
import ml_model

MIN_VERIFIED_FOR_TRAINING = 500
RETRAIN_EVERY_HOURS = 6
OBSERVATION_RETENTION_DAYS = settings.ml_observation_retention_days
PREDICTION_RETENTION_DAYS = settings.ml_prediction_retention_days
TRAINING_STATE_ID = 1

scheduler = AsyncIOScheduler(timezone="Europe/Rome")


def _db_get_cities() -> list[dict]:
    with SessionLocal() as db:
        rows = db.query(
            City.id,
            City.name,
            City.lat,
            City.lon,
            City.region,
            City.province,
            City.population,
        ).filter(City.locality_type == "comune").all()
        cities = [
            {
                "id": row.id,
                "name": row.name,
                "lat": row.lat,
                "lon": row.lon,
                "region": row.region,
                "province": row.province,
                "population": row.population,
            }
            for row in rows
        ]
        return _select_training_cities(cities, datetime.now(timezone.utc))


def _stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def _city_group_key(city: dict) -> tuple[str, str]:
    return (
        str(city.get("region") or "Sconosciuta").strip().lower(),
        str(city.get("province") or "Sconosciuta").strip().lower(),
    )


def _cycle_seed(now: datetime) -> int:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    window_seconds = max(1, settings.ml_cycle_every_hours) * 3600
    return int(now.timestamp() // window_seconds)


def _select_training_cities(cities: list[dict], now: datetime | None = None) -> list[dict]:
    """Seleziona un campione stabile, bilanciato e rotante per contenere il carico DB."""
    sample_size = min(len(cities), settings.ml_city_sample_size)
    if sample_size <= 0 or len(cities) <= sample_size:
        return sorted(cities, key=lambda city: int(city["id"]))

    core_size = min(sample_size, settings.ml_city_core_size)
    seed = _cycle_seed(now or datetime.now(timezone.utc))

    core = sorted(
        cities,
        key=lambda city: (
            -(int(city.get("population") or 0)),
            str(city.get("name") or "").lower(),
            int(city["id"]),
        ),
    )[:core_size]
    selected_by_id = {int(city["id"]): city for city in core}
    remaining = [city for city in cities if int(city["id"]) not in selected_by_id]
    target_remaining = sample_size - len(selected_by_id)

    groups: dict[tuple[str, str], list[dict]] = {}
    for city in remaining:
        groups.setdefault(_city_group_key(city), []).append(city)

    ordered_groups = sorted(
        groups.items(),
        key=lambda item: _stable_int(f"{seed}:group:{item[0][0]}:{item[0][1]}"),
    )
    for _, group_cities in ordered_groups:
        group_cities.sort(key=lambda city: _stable_int(f"{seed}:city:{city['id']}"))

    while len(selected_by_id) < sample_size and ordered_groups:
        progressed = False
        for _, group_cities in ordered_groups:
            if len(selected_by_id) >= sample_size:
                break
            while group_cities:
                candidate = group_cities.pop(0)
                candidate_id = int(candidate["id"])
                if candidate_id not in selected_by_id:
                    selected_by_id[candidate_id] = candidate
                    progressed = True
                    break
        if not progressed:
            break

    selected = list(selected_by_id.values())
    if len(selected) < sample_size:
        fallback = sorted(
            remaining,
            key=lambda city: _stable_int(f"{seed}:fallback:{city['id']}"),
        )
        for city in fallback:
            if len(selected_by_id) >= sample_size:
                break
            selected_by_id.setdefault(int(city["id"]), city)
        selected = list(selected_by_id.values())

    selected.sort(key=lambda city: int(city["id"]))
    print(
        f"[ML] Campione città: {len(selected)}/{len(cities)} "
        f"(core={len(core)}, rotating={max(0, len(selected) - len(core))}, "
        f"target_rotating={target_remaining})"
    )
    return selected


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
            wind_direction=obs.get("wind_direction"),
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
            forecast_wind_speed=pred.get("forecast_wind_speed"),
            forecast_wind_direction=pred.get("forecast_wind_direction"),
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
                        actual_wind_speed = :actual_wind_speed,
                        actual_wind_direction = :actual_wind_direction,
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
                    "actual_wind_speed": obs.get("wind_speed"),
                    "actual_wind_direction": obs.get("wind_direction"),
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


def _db_get_or_create_training_state(db) -> MlTrainingState:
    state = db.get(MlTrainingState, TRAINING_STATE_ID)
    if state is None:
        state = MlTrainingState(
            id=TRAINING_STATE_ID,
            verified_count_at_last_train=0,
            last_cycle_status="never_run",
        )
        db.add(state)
        db.flush()
    return state


def _serialize_training_state(state: MlTrainingState) -> dict:
    return {
        "last_cycle_started_at": state.last_cycle_started_at.isoformat() if state.last_cycle_started_at else None,
        "last_cycle_completed_at": state.last_cycle_completed_at.isoformat() if state.last_cycle_completed_at else None,
        "last_cycle_status": state.last_cycle_status,
        "last_cycle_message": state.last_cycle_message,
        "last_cycle_observations": state.last_cycle_observations,
        "last_cycle_predictions": state.last_cycle_predictions,
        "last_cycle_verified": state.last_cycle_verified,
        "last_cycle_avg_error": state.last_cycle_avg_error,
        "last_successful_train_at": state.last_successful_train_at.isoformat() if state.last_successful_train_at else None,
        "verified_count_at_last_train": int(state.verified_count_at_last_train or 0),
        "last_model_store_id": state.last_model_store_id,
        "last_model_trained_at": state.last_model_trained_at.isoformat() if state.last_model_trained_at else None,
    }


def _empty_training_state() -> dict:
    return {
        "last_cycle_started_at": None,
        "last_cycle_completed_at": None,
        "last_cycle_status": "unknown",
        "last_cycle_message": None,
        "last_cycle_observations": None,
        "last_cycle_predictions": None,
        "last_cycle_verified": None,
        "last_cycle_avg_error": None,
        "last_successful_train_at": None,
        "verified_count_at_last_train": 0,
        "last_model_store_id": None,
        "last_model_trained_at": None,
    }


def _db_update_training_state(**fields) -> dict:
    with SessionLocal() as db:
        state = _db_get_or_create_training_state(db)
        for key, value in fields.items():
            setattr(state, key, value)
        db.commit()
        db.refresh(state)
        return _serialize_training_state(state)


def _db_read_training_state() -> dict:
    try:
        with SessionLocal() as db:
            state = _db_get_or_create_training_state(db)
            db.commit()
            return _serialize_training_state(state)
    except Exception:
        return _empty_training_state()


def _db_latest_model_info() -> dict | None:
    with SessionLocal() as db:
        record = db.query(MlModelStore.id, MlModelStore.trained_at).order_by(MlModelStore.trained_at.desc()).first()
        if not record:
            return None
        return {
            "id": int(record.id),
            "trained_at": record.trained_at,
        }


def get_training_state_summary() -> dict:
    return _db_read_training_state()


def _db_cleanup(now: datetime) -> dict:
    obs_cutoff = now - timedelta(days=settings.ml_observation_retention_days)
    pred_cutoff = now - timedelta(days=settings.ml_prediction_retention_days)

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
    cycle_started_at = datetime.now(timezone.utc)
    print(f"\n{'=' * 60}")
    print(f"[CYCLE] CICLO AUTO-LEARNING — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}")
    await asyncio.to_thread(
        _db_update_training_state,
        last_cycle_started_at=cycle_started_at,
        last_cycle_status="running",
        last_cycle_message="cycle_started",
    )

    n_obs = 0
    n_pred = 0
    verified_count = 0
    avg_error = 0.0
    total_verified = 0
    try:
        cities = await asyncio.to_thread(_db_get_cities)
        if not cities:
            print("[WARN] Nessuna città nel DB")
            await asyncio.to_thread(
                _db_update_training_state,
                last_cycle_completed_at=datetime.now(timezone.utc),
                last_cycle_status="skipped",
                last_cycle_message="no_cities",
                last_cycle_observations=0,
                last_cycle_predictions=0,
                last_cycle_verified=0,
                last_cycle_avg_error=0.0,
            )
            return

        cleanup = await asyncio.to_thread(_db_cleanup, cycle_started_at)
        if any(cleanup.values()):
            print(
                f"[CLEAN] pre-save obs={cleanup['deleted_observations']} "
                f"pred={cleanup['deleted_predictions']} models={cleanup['deleted_models']}"
            )

        payload = await fetch_all_cities_weather(cities)
        observations = payload.get("observations", [])
        predictions = payload.get("predictions", [])
        if not observations:
            print("[WARN] Nessuna osservazione scaricata")
            await asyncio.to_thread(
                _db_update_training_state,
                last_cycle_completed_at=datetime.now(timezone.utc),
                last_cycle_status="skipped",
                last_cycle_message="no_observations",
                last_cycle_observations=0,
                last_cycle_predictions=len(predictions),
                last_cycle_verified=0,
                last_cycle_avg_error=0.0,
            )
            return

        n_obs, n_pred = await asyncio.to_thread(_db_save_cycle_data, payload)
        print(f"[SAVE] Salvate {n_obs} osservazioni e {n_pred} previsioni future")

        verified_count, avg_error = await asyncio.to_thread(_db_verify_predictions, observations)
        print(f"[OK] Verificate {verified_count} predictions (errore medio: {avg_error:.2f}°C)")

        now = datetime.now(timezone.utc)
        total_verified = await asyncio.to_thread(_db_count_verified)
        training_state = await asyncio.to_thread(_db_read_training_state)
        last_training_iso = training_state.get("last_successful_train_at")
        last_training = datetime.fromisoformat(last_training_iso) if last_training_iso else None
        verified_at_last_train = int(training_state.get("verified_count_at_last_train") or 0)
        new_verified_since_last = max(0, total_verified - verified_at_last_train)
        model_ready = bool(ml_model.get_public_summary().get("model_ready"))
        should_retrain = (
            total_verified >= MIN_VERIFIED_FOR_TRAINING
            and (last_training is None or (now - last_training).total_seconds() >= RETRAIN_EVERY_HOURS * 3600)
            and (
                not model_ready
                or new_verified_since_last >= settings.ml_min_new_verified_for_retrain
            )
        )

        cycle_message = "retrain_skipped"
        if should_retrain:
            print(
                f"[TRAIN] Avvio training su {total_verified} campioni verificati "
                f"(nuovi dal precedente: {new_verified_since_last})"
            )
            result = await asyncio.to_thread(ml_model.train, 100)
            if result["success"]:
                latest_model = await asyncio.to_thread(_db_latest_model_info)
                cycle_message = "train_success"
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
                if result.get("condition_model_ready"):
                    print(
                        f"[DONE] Modello condizioni — Accuracy: {result.get('condition_accuracy', 0):.3f} "
                        f"(baseline {result.get('condition_baseline_accuracy', 0):.3f})"
                    )
                elif result.get("condition_message"):
                    print(f"[INFO] Modello condizioni non promosso: {result['condition_message']}")
                await asyncio.to_thread(
                    _db_update_training_state,
                    last_successful_train_at=now,
                    verified_count_at_last_train=total_verified,
                    last_model_store_id=latest_model.get("id") if latest_model else None,
                    last_model_trained_at=latest_model.get("trained_at") if latest_model else None,
                )
            else:
                cycle_message = f"train_failed:{result.get('message') or 'unknown'}"
                print(f"[WARN] Training non promosso: {result.get('message')}")
        else:
            cycle_message = (
                f"retrain_skipped:total_verified={total_verified};"
                f"new_verified_since_last={new_verified_since_last};"
                f"min_new_required={settings.ml_min_new_verified_for_retrain}"
            )
            print(
                f"[TRAIN] Skip retrain: total_verified={total_verified} "
                f"new_verified_since_last={new_verified_since_last} "
                f"min_new_required={settings.ml_min_new_verified_for_retrain}"
            )

        shadow_state = await asyncio.to_thread(ml_model.evaluate_shadow_window)
        if shadow_state.get("checked"):
            print(
                "[SHADOW] checked pass=%s streak=%s rollout_allowed=%s force_v1=%s"
                % (
                    shadow_state.get("pass"),
                    shadow_state.get("consecutive_positive_windows"),
                    shadow_state.get("rollout_allowed"),
                    shadow_state.get("runtime_force_v1"),
                )
            )

        cleanup = await asyncio.to_thread(_db_cleanup, now)
        if any(cleanup.values()):
            print(
                f"[CLEAN] post-train obs={cleanup['deleted_observations']} "
                f"pred={cleanup['deleted_predictions']} models={cleanup['deleted_models']}"
            )

        # Controllo allerte pioggia
        try:
            from rain_alert_service import check_rain_alerts
            rain_result = await check_rain_alerts()
            if rain_result.get("sent", 0) > 0:
                print(f"[RAIN] {rain_result['sent']} allerte pioggia inviate")
        except Exception as rain_exc:
            print(f"[WARN] Errore controllo allerte pioggia: {rain_exc}")

        await asyncio.to_thread(
            _db_update_training_state,
            last_cycle_completed_at=datetime.now(timezone.utc),
            last_cycle_status="success",
            last_cycle_message=cycle_message,
            last_cycle_observations=n_obs,
            last_cycle_predictions=n_pred,
            last_cycle_verified=verified_count,
            last_cycle_avg_error=avg_error,
        )
        print("[OK] Ciclo completato — prossimo tra 1 ora\n")
    except Exception as exc:
        await asyncio.to_thread(
            _db_update_training_state,
            last_cycle_completed_at=datetime.now(timezone.utc),
            last_cycle_status="failed",
            last_cycle_message=str(exc),
            last_cycle_observations=n_obs,
            last_cycle_predictions=n_pred,
            last_cycle_verified=verified_count,
            last_cycle_avg_error=avg_error,
        )
        raise


def start_scheduler():
    scheduler.add_job(
        hourly_cycle,
        trigger=IntervalTrigger(hours=settings.ml_cycle_every_hours),
        id="hourly_cycle",
        name="Raccolta meteo + verifica forecast + training ML",
        replace_existing=True,
        max_instances=1,
    )

    if scheduler.running:
        print("[SCHED] Scheduler gia avviato — configurazione confermata")
        return

    try:
        scheduler.start()
    except SchedulerAlreadyRunningError:
        pass

    print(f"[SCHED] Scheduler avviato — ciclo ogni {settings.ml_cycle_every_hours} ore attivo")


def stop_scheduler():
    if not scheduler.running:
        print("[SCHED] Scheduler gia fermo")
        return

    try:
        scheduler.shutdown(wait=False)
    except SchedulerNotRunningError:
        return

    print("[SCHED] Scheduler fermato")


async def run_cycle_now():
    await hourly_cycle()
