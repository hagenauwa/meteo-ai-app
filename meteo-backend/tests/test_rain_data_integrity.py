"""Regressioni su provenienza, tempi e validazione operativa della pioggia."""

import importlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import event
from sqlalchemy.orm import attributes, sessionmaker

import ml_model
import notification_utils
import scheduler
import trusted_observation_service as observations
from database import City, MlModelStore, MlPrediction, WeatherObservation
from scripts import run_ml_cycle


@pytest.fixture
def sessions(db_engine, monkeypatch):
    factory = sessionmaker(bind=db_engine)
    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    monkeypatch.setattr(ml_model, "SessionLocal", factory)
    monkeypatch.setattr(
        scheduler,
        "settings",
        SimpleNamespace(
            ml_require_trusted_observations=True,
            ml_trusted_observation_sources=("station", observations.METEOSTAT_SOURCE),
            ml_training_allowed_provinces=("Massa-Carrara",),
        ),
    )
    monkeypatch.setattr(
        ml_model,
        "settings",
        SimpleNamespace(
            ml_require_trusted_observations=True,
            ml_trusted_observation_sources=("station", observations.METEOSTAT_SOURCE),
            ml_training_allowed_provinces=("Massa-Carrara",),
            ml_forecast_leads=(1, 3, 6),
            ml_v2_enabled=True,
            ml_v2_shadow_only=False,
            ml_v2_rollout_percent=100,
            ml_kpi_window_days=14,
        ),
    )
    with factory() as db:
        for city_id in (1, 2):
            db.add(
                City(
                    id=city_id,
                    name=f"Comune {city_id}",
                    name_lower=f"comune {city_id}",
                    province="Massa-Carrara",
                    region="Toscana",
                    lat=44.0,
                    lon=10.1,
                )
            )
        db.commit()
    return factory


def _prediction(target, **overrides):
    values = dict(
        city_id=1,
        predicted_at=target - timedelta(hours=1),
        target_time=target,
        lead_hours=1,
        predicted_temp=20.0,
        forecast_temp=20.0,
        verified=False,
    )
    values.update(overrides)
    return MlPrediction(**values)


def test_verification_handles_postgres_aware_targets_and_repairs_legacy_labels(sessions):
    target = datetime(2026, 9, 10, 12)
    with sessions() as db:
        db.add(_prediction(target, verified=True, actual_source="meteostat", actual_precipitation=0.0))
        db.commit()

    # Il DB SQLite esegue la query; il loader riproduce DateTime(timezone=True)
    # di PostgreSQL, anche quando la sessione usa un offset diverso da UTC.
    def aware_target(instance, context):
        aware = instance.target_time.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        attributes.set_committed_value(instance, "target_time", aware)

    event.listen(MlPrediction, "load", aware_target)
    try:
        count, error = scheduler._db_verify_predictions(
            [
                {
                    "city_id": 1,
                    "observed_at": target.replace(tzinfo=timezone.utc),
                    "temp": 21.0,
                    "precipitation": 1.5,
                    "observation_source": observations.METEOSTAT_SOURCE,
                    "observation_interval_minutes": 60,
                    "station_id": "16125",
                    "station_distance_km": 7.6,
                }
            ]
        )
    finally:
        event.remove(MlPrediction, "load", aware_target)
    assert count == 1
    assert error == 1.0
    with sessions() as db:
        row = db.query(MlPrediction).one()
        assert row.target_time == target
        assert row.actual_source == observations.METEOSTAT_SOURCE
        assert row.actual_precipitation == 1.5
        assert row.actual_station_id == "16125"
        assert row.actual_station_distance_km == 7.6
        assert row.verified_at > target


def test_training_excludes_legacy_data_and_deduplicates_station_events(sessions):
    target = datetime(2026, 9, 10, 12)
    with sessions() as db:
        for city_id, distance in ((1, 12.0), (2, 3.0)):
            for lead in (1, 3):
                db.add(
                    _prediction(
                        target,
                        city_id=city_id,
                        lead_hours=lead,
                        verified=True,
                        actual_temp=21.0,
                        error=1.0,
                        verified_at=target + timedelta(days=1),
                        actual_source=observations.METEOSTAT_SOURCE,
                        actual_precipitation=0.5,
                        actual_interval_minutes=60,
                        actual_station_id="16125",
                        actual_station_distance_km=distance,
                    )
                )
        db.add(
            _prediction(
                target + timedelta(hours=1),
                verified=True,
                actual_temp=21.0,
                error=1.0,
                actual_source="meteostat",
                actual_precipitation=5.0,
            )
        )
        db.commit()
        rows = ml_model._prepare_training_rows(db)
        assert len(rows) == 2
        assert {row["city_id"] for row in rows} == {2}
        assert {row["lead_hours"] for row in rows} == {1, 3}
        assert all(row["hour"] == 12 for row in rows)
        # Una verifica tardiva non rende recente l'evento per il training.
        assert ml_model._prepare_training_rows(db, window_start=target + timedelta(hours=2)) == []


def test_cycle_replay_keeps_original_forecast_snapshot_and_station(sessions, monkeypatch):
    target = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    snapshots = []

    def snapshot(pred, city):
        snapshots.append(pred)
        return {"evaluation_rain_probability": 0.7, "evaluation_generated_at": pred["predicted_at"]}

    monkeypatch.setattr(ml_model, "build_evaluation_snapshot", snapshot)
    prediction = dict(
        city_id=1, predicted_at=target - timedelta(hours=1), target_time=target, lead_hours=1, forecast_temp=20.0
    )
    observation = dict(
        city_id=1,
        observed_at=target,
        temp=21.0,
        precipitation=0.2,
        observation_source=observations.METEOSTAT_SOURCE,
        station_id="16125",
        station_distance_km=7.6,
    )
    payload = {"predictions": [prediction, dict(prediction)], "observations": [observation, dict(observation)]}
    assert scheduler._db_save_cycle_data(payload) == (1, 1)
    assert scheduler._db_save_cycle_data(payload) == (0, 0)
    assert len(snapshots) == 1
    with sessions() as db:
        assert db.query(MlPrediction).one().evaluation_rain_probability == 0.7
        assert db.query(WeatherObservation).one().station_id == "16125"


def test_backfill_includes_pending_city_and_excludes_expired_targets(sessions):
    now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    with sessions() as db:
        db.add(_prediction(now - timedelta(days=3), city_id=2))
        db.add(_prediction(now - timedelta(days=8)))
        db.commit()
    cities, start = scheduler._db_observation_backfill([{"id": 1}], now)
    assert {city["id"] for city in cities} == {1, 2}
    assert start == (now - timedelta(days=3)).replace(tzinfo=None)


def test_station_fallback_uses_measured_rain_and_bounds_backfill(monkeypatch):
    frame = pd.DataFrame({"distance": [1000, 5000, 36000]}, index=["near", "next", "far"])
    monkeypatch.setattr(observations.ms.stations, "nearby", lambda *a, **kw: frame)
    index = pd.MultiIndex.from_tuples(
        [(station, pd.Timestamp("2026-09-12T10:00Z")) for station in ("near", "next", "far")], names=["station", "time"]
    )
    hourly = pd.DataFrame({"temp": [20, 21, 22], "prcp": [float("nan"), 0.6, 2], "cldc": [0, 8, 9]}, index=index)
    calls = []

    def fetch(stations, start, end, **kwargs):
        calls.append((stations, start, end))
        assert observations.ms.config.include_model_data is False
        return SimpleNamespace(fetch=lambda: hourly)

    monkeypatch.setattr(observations.ms, "hourly", fetch)
    now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    result = observations.fetch_meteostat_observations(
        [{"id": 1, "lat": 44, "lon": 10}], now=now, start_time=now - timedelta(days=90)
    )
    assert calls == [(["near", "next"], now - timedelta(days=7), now - timedelta(hours=2))]
    assert len(result) == 1
    assert result[0]["station_id"] == "next"
    assert result[0]["precipitation"] == 0.6
    assert result[0]["cloud_cover"] == 100


def _shadow_rows(start, count=200, model_id=42):
    return [
        {
            "target_time": start + timedelta(hours=i),
            "city_id": 1,
            "actual_station_id": "16125",
            "evaluation_generated_at": start + timedelta(hours=i - 1),
            "evaluation_model_store_id": model_id,
            "actual_precipitation": float(i % 2),
            "shadow_v1_rain_probability": 0.6 if i % 2 else 0.4,
            "shadow_v1_rain_threshold": 0.5,
            "shadow_v2_rain_probability": 0.9 if i % 2 else 0.1,
            "shadow_v2_rain_threshold": 0.5,
        }
        for i in range(count)
    ]


def test_shadow_validation_survives_restart_and_requires_new_windows(sessions, monkeypatch):
    monkeypatch.setattr(ml_model, "_ensure_latest_model_loaded", lambda: None)
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", 42)
    monkeypatch.setattr(ml_model, "_shadow_state", {})
    monkeypatch.setattr(ml_model, "_runtime_force_v1", False)
    monkeypatch.setattr(ml_model, "_rain_pipeline_v2", object())
    monkeypatch.setattr(ml_model, "_condition_pipeline_v2", None)
    with sessions() as db:
        db.add(MlModelStore(id=42, trained_at=datetime(2026, 8, 1)))
        db.commit()
    rows = _shadow_rows(datetime(2026, 8, 2))
    # V1 ha precisione perfetta ma recall scarso: V2 migliora entrambi i KPI.
    for row in rows:
        row["shadow_v1_rain_probability"] = 0.4
    monkeypatch.setattr(ml_model, "_prepare_training_rows", lambda *a, **kw: rows)
    first = ml_model.evaluate_shadow_window()
    assert first["pass"] is True
    assert first["consecutive_positive_windows"] == 1
    with sessions() as db:
        persisted = db.get(MlModelStore, 42).validation_state
    ml_model._restore_shadow_state(None)
    ml_model._restore_shadow_state(persisted)
    assert ml_model._shadow_state["consecutive_positive_windows"] == 1
    assert ml_model.evaluate_shadow_window()["checked"] is False
    assert ml_model._can_use_v2_live() is False
    second_rows = _shadow_rows(datetime(2026, 8, 12))
    for row in second_rows:
        row["shadow_v1_rain_probability"] = 0.4
    rows.extend(second_rows)
    assert ml_model.evaluate_shadow_window()["consecutive_positive_windows"] == 2
    assert ml_model._can_use_v2_live() is True
    # Un successivo peggioramento azzera il permesso e persiste il rollback.
    failed_rows = _shadow_rows(datetime(2026, 8, 22))
    for row in failed_rows:
        row["shadow_v2_rain_probability"] = 0.5
    rows.extend(failed_rows)
    assert ml_model.evaluate_shadow_window()["pass"] is False
    with sessions() as db:
        persisted = db.get(MlModelStore, 42).validation_state
    ml_model._restore_shadow_state(persisted)
    assert ml_model._runtime_force_v1 is True
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", 43)
    ml_model._restore_shadow_state(persisted)
    assert ml_model._shadow_state["consecutive_positive_windows"] == 0


@pytest.mark.parametrize(
    "raw",
    [
        '{"model_store_id":42,"consecutive_positive_windows":"2"}',
        '{"model_store_id":42,"last_target_time":"invalid"}',
        "[]",
        "broken",
    ],
)
def test_invalid_persisted_validation_fails_closed(monkeypatch, raw):
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", 42)
    monkeypatch.setattr(ml_model, "_shadow_state", {})
    monkeypatch.setattr(ml_model, "_runtime_force_v1", False)
    ml_model._restore_shadow_state(raw)
    assert ml_model._shadow_state["consecutive_positive_windows"] == 0


def test_alert_validation_uses_actual_notification_threshold_and_independent_events(monkeypatch):
    rows = _shadow_rows(datetime(2026, 8, 1))
    for row in rows:
        row.update(
            lead_hours=1, forecast_precipitation_probability=50, forecast_weather_code=61, forecast_precipitation=0.5
        )
    monkeypatch.setattr(
        ml_model, "_rain_probability_for_row", lambda row, *args: 0.9 if row["actual_precipitation"] else 0.1
    )
    bucket = ml_model._lead_bucket_name(1)
    good = ml_model._compute_rain_kpis_by_bucket(rows, "v1", {"rain_threshold_v1": 0.3})[bucket]
    assert good["alert_validated"] is True
    # F1 alla soglia 0.3 sarebbe perfetto, ma gli avvisi >=0.5 perderebbero la pioggia.
    monkeypatch.setattr(
        ml_model, "_rain_probability_for_row", lambda row, *args: 0.4 if row["actual_precipitation"] else 0.1
    )
    bad = ml_model._compute_rain_kpis_by_bucket(rows, "v1", {"rain_threshold_v1": 0.3})[bucket]
    assert bad["rain_f1"] == 1.0
    assert bad["alert_validated"] is False
    duplicates = ml_model._compute_rain_kpis_by_bucket(rows[:20] * 20, "v1")[bucket]
    assert duplicates["samples"] == 400
    assert duplicates["independent_samples"] == 20
    assert duplicates["alert_validated"] is False


@pytest.mark.parametrize("probability", [None, 0.05, float("nan")])
def test_unvalidated_or_invalid_ml_keeps_provider_alert(monkeypatch, probability):
    captured = []

    def ml(**kwargs):
        captured.append(kwargs)
        return {"rain_probability": probability, "model_ready": True, "will_rain": False}

    monkeypatch.setattr(notification_utils, "get_ml_rain_probability", ml)
    result = notification_utils.check_hourly_rain_adaptive(
        {
            "time": ["2026-08-28T18:00"],
            "precipitation_probability": [90],
            "weather_code": [61],
            "precipitation": [0.8],
        },
        lat=44,
        lon=10,
        city_name="Massa",
        region="Toscana",
        now=datetime(2026, 8, 28, 17, 15, tzinfo=ZoneInfo("Europe/Rome")),
    )
    assert result is not None
    assert result["trigger_reason"] == "provider_wmo_fallback"
    assert captured[0]["hour"] == 16


@pytest.mark.parametrize("day, utc_hour", [("2026-08-28", 12), ("2026-01-28", 13)])
def test_daily_rain_preserves_provider_and_temperature_features_use_utc(monkeypatch, day, utc_hour):
    captured = []

    def correction(**kwargs):
        captured.append(kwargs)
        return {"model_ready": True, "correction": 0.5}

    monkeypatch.setattr(ml_model, "predict_correction", correction)
    monkeypatch.setattr(ml_model, "predict_rain_probability", lambda **kw: pytest.fail("daily input to hourly model"))
    monkeypatch.setattr(ml_model, "predict_condition_outlook", lambda **kw: pytest.fail("daily input to hourly model"))
    result = ml_model.build_daily_insight(
        day={"dt": day, "pop": 0.82, "temp": {"day": 20, "min": 15, "max": 25}, "weather_code": 61},
        lat=44,
        region="Toscana",
        lead_hours=14,
    )
    assert result["rain_probability"] == 0.82
    assert result["rain_blend_weight"] == 0.0
    assert result["model_variant"] == "provider"
    assert captured[0]["hour"] == utc_hour
    assert result["temperature_delta"] == 0.5


def test_frozen_statistics_do_not_rerun_models_or_include_late_snapshots(monkeypatch):
    rows = _shadow_rows(datetime(2026, 8, 1), count=2)
    for row in rows:
        row.update(lead_hours=1, forecast_precipitation_probability=50)
    late = dict(rows[0], evaluation_generated_at=rows[0]["target_time"])
    monkeypatch.setattr(ml_model, "_prepare_training_rows", lambda *a, **kw: [*rows, late])
    monkeypatch.setattr(ml_model, "_rain_probability_for_row", lambda *a, **kw: pytest.fail("retrospective inference"))
    filtered = ml_model._recent_rows_for_kpis(object(), datetime(2026, 8, 1))
    assert filtered == rows
    metrics = ml_model._compute_frozen_variant_kpis(filtered, "v2")
    assert metrics["rain_brier"] == pytest.approx(0.01)
    assert metrics["provider_rain_brier"] == 0.25
    buckets = ml_model._compute_rain_kpis_by_bucket(filtered, "v2", frozen=True)
    assert buckets[ml_model._lead_bucket_name(1)]["rain_brier"] == pytest.approx(0.01)


def test_promotion_cannot_use_training_score_when_external_holdout_is_missing():
    gate = ml_model._rain_v2_gate({}, {}, {"brier": 0.01, "baseline_brier": 0.5, "f1": 1.0, "baseline_f1": 0.0})
    assert gate["pass"] is False


@pytest.mark.parametrize("status", ["failed", "success", "skipped"])
def test_cron_exposes_cycle_failure_to_process(monkeypatch, status):
    monkeypatch.setattr(run_ml_cycle, "init_db", lambda: None)
    monkeypatch.setattr(run_ml_cycle.ml_model, "load_latest_model", lambda: False)

    async def cycle():
        return {"last_cycle_status": status, "last_cycle_message": "test"}

    monkeypatch.setattr(run_ml_cycle, "hourly_cycle", cycle)
    if status == "failed":
        with pytest.raises(RuntimeError, match="Ciclo ML fallito"):
            run_ml_cycle.main()
    else:
        run_ml_cycle.main()


@pytest.mark.parametrize(
    "age, streak, last_pass, expected",
    [
        (25, 1, True, True),
        (24 * 8, 0, None, False),
        (12, 0, False, False),
        (12, 2, True, False),
    ],
)
def test_retraining_gives_shadow_candidate_time_but_does_not_keep_failed_model(age, streak, last_pass, expected):
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    summary = {"rain_model_v2_ready": True, "shadow": {"consecutive_positive_windows": streak, "last_pass": last_pass}}
    assert scheduler._should_wait_for_shadow_validation(summary, now - timedelta(hours=age), now) is expected


def test_running_process_refreshes_validation_for_same_model(sessions, monkeypatch):
    trained_at = datetime(2026, 9, 1)
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", 42)
    monkeypatch.setattr(ml_model, "_loaded_model_trained_at", trained_at)
    monkeypatch.setattr(ml_model, "_last_model_version_check_at", None)
    monkeypatch.setattr(ml_model, "_shadow_state", {})
    monkeypatch.setattr(ml_model, "_runtime_force_v1", False)
    monkeypatch.setattr(ml_model, "load_latest_model", lambda: pytest.fail("unchanged model must not reload"))
    with sessions() as db:
        db.add(
            MlModelStore(
                id=42,
                trained_at=trained_at,
                validation_state=json.dumps(
                    {
                        "model_store_id": 42,
                        "consecutive_positive_windows": 2,
                        "runtime_force_v1": False,
                    }
                ),
            )
        )
        db.commit()
    ml_model._ensure_latest_model_loaded(force=True)
    assert ml_model._can_use_v2_live() is True
    with sessions() as db:
        db.get(MlModelStore, 42).validation_state = json.dumps(
            {
                "model_store_id": 42,
                "consecutive_positive_windows": 0,
                "runtime_force_v1": True,
            }
        )
        db.commit()
    ml_model._ensure_latest_model_loaded(force=True)
    assert ml_model._can_use_v2_live() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_hour", [None, 0])
async def test_rain_api_converts_local_hour_and_month_to_utc(monkeypatch, requested_hour):
    router = importlib.import_module("routers.ml")
    captured = {}
    monkeypatch.setattr(router, "_rome_now", lambda: datetime(2026, 1, 1, 0, 30, tzinfo=ZoneInfo("Europe/Rome")))
    monkeypatch.setattr(
        router, "_resolve_city_context", lambda *a: {"resolved": True, "lat": 44.0, "lon": 10.1, "region": "Toscana"}
    )

    def predict(**kwargs):
        captured.update(kwargs)
        return {"model_ready": False}

    monkeypatch.setattr(router.ml_model, "predict_rain_probability", predict)
    await router.get_rain_prediction(city="Massa", temp=20, hour=requested_hour, db=object())
    assert captured["hour"] == 23
    assert captured["month"] == 12
