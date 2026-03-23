"""
scheduler.py — Cron job orario per raccolta dati meteo e auto-learning ML

Ogni ora:
  1. Carica tutte le città da PostgreSQL
  2. Chiama Open-Meteo bulk API (80 chiamate per ~8.000 comuni)
  3. Salva osservazioni nel DB
  4. Verifica predictions di 1-6 ore fa (calcola errore)
  5. Se abbastanza dati verificati → re-training scikit-learn

NOTA: tutte le operazioni DB sincrone vengono eseguite con asyncio.to_thread
per non bloccare l'event loop — questo evita i timeout di /health su Render.
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import SessionLocal, City, WeatherObservation, MlPrediction
from weather_service import fetch_all_cities_weather
import ml_model

# Soglia per avviare re-training automatico
MIN_VERIFIED_FOR_TRAINING = 500
# Ogni quante ore ri-addestrare (per non farlo a ogni ciclo)
RETRAIN_EVERY_HOURS = 6

_last_training: datetime | None = None
scheduler = AsyncIOScheduler(timezone="Europe/Rome")


# ---------------------------------------------------------------------------
# Funzioni DB sincrone — chiamate tramite asyncio.to_thread
# ---------------------------------------------------------------------------

def _db_get_cities() -> list[dict]:
    """Carica i comuni ISTAT dal DB. Sincrona, gira in thread."""
    with SessionLocal() as db:
        rows = db.query(City.id, City.name, City.lat, City.lon).filter(
            City.locality_type == "comune"
        ).all()
        return [{"id": r.id, "name": r.name, "lat": r.lat, "lon": r.lon} for r in rows]


def _db_save_observations(observations: list[dict], now: datetime) -> tuple[int, int]:
    """
    Salva WeatherObservation e MlPrediction in batch.
    Ritorna (n_obs, n_pred).
    Sincrona, gira in thread.
    """
    obs_objects = []
    pred_objects = []
    for obs in observations:
        if obs.get("temp") is None:
            continue
        obs_objects.append(WeatherObservation(
            city_id       = obs["city_id"],
            observed_at   = now,
            temp          = obs["temp"],
            humidity      = obs.get("humidity"),
            cloud_cover   = obs.get("cloud_cover"),
            wind_speed    = obs.get("wind_speed"),
            precipitation = obs.get("precipitation", 0.0)
        ))
        pred_objects.append(MlPrediction(
            city_id        = obs["city_id"],
            predicted_at   = now,
            predicted_temp = obs["temp"],
            humidity       = obs.get("humidity"),
            hour           = now.hour,
            verified       = False,
            precipitation  = obs.get("precipitation", 0.0),
            weather_code   = obs.get("weather_code")
        ))

    with SessionLocal() as db:
        db.bulk_save_objects(obs_objects)
        db.bulk_save_objects(pred_objects)
        db.commit()

    return len(obs_objects), len(pred_objects)


def _db_verify_predictions(observations: list[dict], now: datetime) -> tuple[int, float]:
    """
    Verifica predictions di 1-6 ore fa usando SQL UPDATE diretto per città,
    evitando di caricare migliaia di oggetti in memoria Python.
    Ritorna (verified_count, avg_error).
    Sincrona, gira in thread.
    """
    window_start = now - timedelta(hours=6)
    window_end   = now - timedelta(hours=1)

    # Mappa city_id → temp attuale
    current_temps = {
        obs["city_id"]: obs["temp"]
        for obs in observations
        if obs.get("temp") is not None
    }

    verified_count = 0
    total_error = 0.0

    with SessionLocal() as db:
        for city_id, actual_temp in current_temps.items():
            result = db.execute(
                text("""
                    UPDATE ml_predictions
                    SET actual_temp = :actual,
                        error       = :actual - predicted_temp,
                        verified    = :v_true,
                        verified_at = :now
                    WHERE city_id    = :city_id
                      AND verified   = :v_false
                      AND predicted_at >= :start
                      AND predicted_at <= :end
                """),
                {
                    "actual":  actual_temp,
                    "now":     now,
                    "city_id": city_id,
                    "start":   window_start,
                    "end":     window_end,
                    "v_true":  True,
                    "v_false": False,
                }
            )
            verified_count += result.rowcount

        db.commit()

        # Calcola errore medio ultime 24h con query aggregata (senza caricare righe)
        cutoff = now - timedelta(hours=24)
        row = db.execute(
            text("""
                SELECT AVG(ABS(error))
                FROM ml_predictions
                WHERE verified = true
                  AND verified_at >= :cutoff
                  AND error IS NOT NULL
            """),
            {"cutoff": cutoff}
        ).fetchone()
        avg_error = float(row[0]) if row and row[0] else 0.0

    return verified_count, avg_error


def _db_count_verified() -> int:
    """Conta le predictions verificate totali. Sincrona, gira in thread."""
    with SessionLocal() as db:
        return db.query(MlPrediction).filter(MlPrediction.verified == True).count()


def _db_cleanup(cutoff: datetime) -> int:
    """Elimina osservazioni più vecchie di 30 giorni. Sincrona, gira in thread."""
    with SessionLocal() as db:
        deleted = db.query(WeatherObservation).filter(
            WeatherObservation.observed_at < cutoff
        ).delete()
        db.commit()
        return deleted


# ---------------------------------------------------------------------------
# Job principale
# ---------------------------------------------------------------------------

async def hourly_cycle():
    """Job principale eseguito ogni ora."""
    global _last_training
    print(f"\n{'='*60}")
    print(f"[CYCLE] CICLO AUTO-LEARNING — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # 1. Carica città in thread (non blocca l'event loop)
    cities = await asyncio.to_thread(_db_get_cities)

    if not cities:
        print("[WARN]  Nessuna città nel DB. Esegui prima: python cities_loader.py")
        return

    print(f"[LOC] {len(cities)} città da aggiornare")

    # 2. Scarica meteo in bulk (già async)
    observations = await fetch_all_cities_weather(cities)

    if not observations:
        print("[WARN]  Nessuna osservazione scaricata")
        return

    now = datetime.now(timezone.utc)

    # 3. Salva osservazioni in thread
    n_obs, n_pred = await asyncio.to_thread(_db_save_observations, observations, now)
    print(f"[SAVE] Salvate {n_obs} osservazioni meteo, {n_pred} predictions")

    # 4. Verifica predictions in thread (usa SQL UPDATE, non carica oggetti in memoria)
    verified_count, avg_error = await asyncio.to_thread(_db_verify_predictions, observations, now)
    print(f"[OK] Verificate {verified_count} predictions (errore medio: {avg_error:.2f}°C)")

    # 5. Auto-training se abbastanza dati e non ri-addestrato di recente
    total_verified = await asyncio.to_thread(_db_count_verified)
    should_retrain = (
        total_verified >= MIN_VERIFIED_FOR_TRAINING and
        (_last_training is None or
         (now - _last_training).total_seconds() > RETRAIN_EVERY_HOURS * 3600)
    )

    if should_retrain:
        print(f"[TRAIN] Avvio re-training ({total_verified} campioni verificati)...")
        result = await asyncio.to_thread(ml_model.train, 100)
        if result["success"]:
            _last_training = now
            print(f"[DONE] Modello aggiornato — MAE: {result['mae']:.3f}°C su {result['n_samples']} campioni")
        else:
            print(f"[WARN]  Training fallito: {result.get('message')}")
        rain_result = await asyncio.to_thread(ml_model.train_rain_model, 100)
        if rain_result.get("success"):
            print(f"[DONE] Modello pioggia — Accuracy: {rain_result.get('accuracy', 0):.3f}")
        else:
            print(f"[INFO]  Modello pioggia: {rain_result.get('message', 'dati insufficienti')}")

    # 6. Pulizia dati vecchi (mantieni max 30 giorni di osservazioni)
    cutoff = now - timedelta(days=30)
    deleted = await asyncio.to_thread(_db_cleanup, cutoff)
    if deleted:
        print(f"[DEL]  Eliminate {deleted} osservazioni > 30 giorni")

    print(f"[OK] Ciclo completato — prossimo tra 1 ora\n")


# ---------------------------------------------------------------------------
# Keep-alive e scheduler
# ---------------------------------------------------------------------------

async def _keepalive_ping():
    """Pinga il proprio /health ogni 10 minuti per evitare lo spin-down su Render free tier."""
    own_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not own_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(f"{own_url}/health")
    except Exception:
        pass


def start_scheduler():
    """Avvia APScheduler con il job orario."""
    scheduler.add_job(
        hourly_cycle,
        trigger=IntervalTrigger(hours=1),
        id="hourly_cycle",
        name="Raccolta meteo + auto-learning ML",
        replace_existing=True,
        max_instances=1       # Non sovrapporre esecuzioni
    )
    scheduler.add_job(
        _keepalive_ping,
        trigger=IntervalTrigger(minutes=10),
        id="keepalive",
        name="Keep-alive ping (anti spin-down Render)",
        replace_existing=True,
    )
    scheduler.start()
    print("[SCHED] Scheduler avviato — ciclo orario attivo")
    print(f"   Prossima esecuzione: tra 1 ora")


def stop_scheduler():
    """Ferma lo scheduler (chiamato allo shutdown FastAPI)."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[SCHED] Scheduler fermato")


async def run_cycle_now():
    """Forza esecuzione immediata del ciclo (usato dall'endpoint /api/admin/run-cycle)."""
    await hourly_cycle()
