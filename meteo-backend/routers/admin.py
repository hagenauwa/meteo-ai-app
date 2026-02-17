"""
routers/admin.py — Endpoint amministrativi

GET  /api/admin/status       — Stato del sistema
POST /api/admin/run-cycle    — Forza ciclo orario manuale
POST /api/admin/load-cities  — Carica/ricarica comuni ISTAT nel DB
"""
from fastapi import APIRouter, BackgroundTasks, Query
from database import SessionLocal, City, WeatherObservation, MlPrediction

router = APIRouter()


@router.get("/status")
def get_status():
    """Stato generale del sistema."""
    db = SessionLocal()
    try:
        n_cities = db.query(City).count()
        n_obs    = db.query(WeatherObservation).count()
        n_pred   = db.query(MlPrediction).count()
        n_verif  = db.query(MlPrediction).filter(MlPrediction.verified == True).count()

        import ml_model
        ml_stats = ml_model.get_stats()

        from scheduler import scheduler as sch
        jobs = []
        for job in sch.get_jobs():
            jobs.append({
                "id":       job.id,
                "name":     job.name,
                "next_run": str(job.next_run_time)
            })

        return {
            "database": {
                "cities":              n_cities,
                "weather_observations": n_obs,
                "ml_predictions":       n_pred,
                "ml_verified":          n_verif
            },
            "ml":       ml_stats,
            "scheduler": jobs
        }
    finally:
        db.close()


@router.post("/run-cycle")
async def run_cycle_now(background_tasks: BackgroundTasks):
    """Forza esecuzione immediata del ciclo orario."""
    from scheduler import run_cycle_now as _run
    background_tasks.add_task(_run)
    return {"message": "Ciclo avviato in background"}


@router.post("/load-cities")
def load_cities_endpoint(
    reload: bool = Query(False, description="Se True, cancella e reinserisce tutto")
):
    """Carica/ricarica i comuni italiani da CSV ISTAT nel DB."""
    from cities_loader import load_cities, download_and_load
    import os
    from pathlib import Path

    csv_path = Path(__file__).parent.parent / "data" / "comuni_italiani.csv"

    if not csv_path.exists():
        count = download_and_load()
    else:
        count = load_cities(truncate=reload)

    return {"loaded": count, "message": f"Caricati {count} comuni"}
