"""
scheduler.py — Cron job orario per raccolta dati meteo e auto-learning ML

Ogni ora:
  1. Carica tutte le città da PostgreSQL
  2. Chiama Open-Meteo bulk API (80 chiamate per ~8.000 comuni)
  3. Salva osservazioni nel DB
  4. Verifica predictions di 1-6 ore fa (calcola errore)
  5. Se abbastanza dati verificati → re-training scikit-learn
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import and_
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


async def hourly_cycle():
    """Job principale eseguito ogni ora."""
    global _last_training
    print(f"\n{'='*60}")
    print(f"[CYCLE] CICLO AUTO-LEARNING — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    db: Session = SessionLocal()
    try:
        # 1. Carica tutte le città
        cities_rows = db.query(City.id, City.name, City.lat, City.lon).all()
        cities = [{"id": r.id, "name": r.name, "lat": r.lat, "lon": r.lon} for r in cities_rows]

        if not cities:
            print("[WARN]  Nessuna città nel DB. Esegui prima: python cities_loader.py")
            return

        print(f"[LOC] {len(cities)} città da aggiornare")

        # 2. Scarica meteo in bulk
        observations = await fetch_all_cities_weather(cities)

        if not observations:
            print("[WARN]  Nessuna osservazione scaricata")
            return

        # 3. Salva osservazioni
        now = datetime.now(timezone.utc)
        obs_objects = []
        for obs in observations:
            if obs.get("temp") is None:
                continue
            obs_objects.append(WeatherObservation(
                city_id     = obs["city_id"],
                observed_at = now,
                temp        = obs["temp"],
                humidity    = obs.get("humidity"),
                cloud_cover = obs.get("cloud_cover"),
                wind_speed  = obs.get("wind_speed"),
                precipitation = obs.get("precipitation", 0.0)
            ))

        db.bulk_save_objects(obs_objects)
        print(f"[SAVE] Salvate {len(obs_objects)} osservazioni meteo")

        # 4. Salva nuove predictions (la temp attuale diventerà "actual" tra 1-6 ore)
        pred_objects = []
        for obs in observations:
            if obs.get("temp") is None:
                continue
            pred_objects.append(MlPrediction(
                city_id        = obs["city_id"],
                predicted_at   = now,
                predicted_temp = obs["temp"],
                humidity       = obs.get("humidity"),
                hour           = now.hour,
                verified       = False
            ))
        db.bulk_save_objects(pred_objects)
        print(f"[PRED] Salvate {len(pred_objects)} nuove predictions")

        # 5. Verifica predictions di 1-6 ore fa
        window_start = now - timedelta(hours=6)
        window_end   = now - timedelta(hours=1)

        unverified = db.query(MlPrediction).filter(
            and_(
                MlPrediction.verified == False,
                MlPrediction.predicted_at >= window_start,
                MlPrediction.predicted_at <= window_end
            )
        ).all()

        # Mappa city_id → temp attuale
        current_temps = {obs["city_id"]: obs["temp"] for obs in observations if obs.get("temp") is not None}

        verified_count = 0
        for pred in unverified:
            actual = current_temps.get(pred.city_id)
            if actual is not None:
                pred.actual_temp = actual
                pred.error       = actual - pred.predicted_temp
                pred.verified    = True
                pred.verified_at = now
                verified_count  += 1

        db.commit()
        print(f"[OK] Verificate {verified_count} predictions (errore medio: {_calc_avg_error(db):.2f}°C)")

        # 6. Auto-training se abbastanza dati e non ri-addestrato di recente
        total_verified = db.query(MlPrediction).filter(MlPrediction.verified == True).count()
        should_retrain = (
            total_verified >= MIN_VERIFIED_FOR_TRAINING and
            (_last_training is None or
             (now - _last_training).total_seconds() > RETRAIN_EVERY_HOURS * 3600)
        )

        if should_retrain:
            print(f"[TRAIN] Avvio re-training ({total_verified} campioni verificati)...")
            db.close()  # Chiudi sessione prima del training
            result = await asyncio.to_thread(ml_model.train, 100)
            if result["success"]:
                _last_training = now
                print(f"[DONE] Modello aggiornato — MAE: {result['mae']:.3f}°C su {result['n_samples']} campioni")
            else:
                print(f"[WARN]  Training fallito: {result.get('message')}")
            return  # db già chiuso

        # 7. Pulizia dati vecchi (mantieni max 30 giorni di osservazioni)
        cutoff = now - timedelta(days=30)
        deleted = db.query(WeatherObservation).filter(
            WeatherObservation.observed_at < cutoff
        ).delete()
        if deleted:
            print(f"[DEL]  Eliminate {deleted} osservazioni > 30 giorni")

        db.commit()

    except Exception as e:
        print(f"[ERROR] Errore nel ciclo: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            db.close()
        except Exception:
            pass

    print(f"[OK] Ciclo completato — prossimo tra 1 ora\n")


def _calc_avg_error(db: Session) -> float:
    """Calcola errore medio assoluto delle ultime 24 ore."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    errors = db.query(MlPrediction.error).filter(
        MlPrediction.verified == True,
        MlPrediction.verified_at >= cutoff,
        MlPrediction.error.isnot(None)
    ).all()
    if not errors:
        return 0.0
    return sum(abs(e[0]) for e in errors) / len(errors)


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
