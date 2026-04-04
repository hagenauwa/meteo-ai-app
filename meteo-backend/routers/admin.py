"""
routers/admin.py — endpoint amministrativi protetti.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from auth import require_admin_access
from database import City, MlPrediction, SessionLocal, WeatherObservation

router = APIRouter(dependencies=[Depends(require_admin_access)])


@router.get("/status")
def get_status():
    db = SessionLocal()
    try:
        n_cities = db.query(City).count()
        n_obs = db.query(WeatherObservation).count()
        n_pred = db.query(MlPrediction).count()
        n_verif = db.query(MlPrediction).filter(MlPrediction.verified.is_(True)).count()

        import ml_model
        from scheduler import scheduler as sch

        return {
            "database": {
                "cities": n_cities,
                "weather_observations": n_obs,
                "ml_predictions": n_pred,
                "ml_verified": n_verif,
            },
            "ml": ml_model.get_stats(),
            "scheduler": [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": str(job.next_run_time),
                }
                for job in sch.get_jobs()
            ],
        }
    finally:
        db.close()


@router.post("/run-cycle")
async def run_cycle_now(background_tasks: BackgroundTasks):
    from scheduler import run_cycle_now as _run

    background_tasks.add_task(_run)
    return {"message": "Ciclo avviato in background"}


@router.post("/load-cities")
def load_cities_endpoint(
    reload: bool = Query(False, description="Se True, cancella e reinserisce tutto"),
):
    from pathlib import Path

    from cities_loader import download_and_load, load_cities

    csv_path = Path(__file__).parent.parent / "data" / "comuni_italiani.csv"
    count = download_and_load() if not csv_path.exists() else load_cities(truncate=reload)
    return {"loaded": count, "message": f"Caricati {count} comuni"}
