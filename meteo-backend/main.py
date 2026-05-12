"""
main.py — FastAPI app principale

Avvio: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from config import settings
from database import init_db, SessionLocal, City, db_healthcheck

_bootstrap_state = {"ready": False, "error": None}


def _load_cities_if_empty():
    """Carica i comuni italiani e le località GeoNames in background se mancanti."""
    try:
        with SessionLocal() as session:
            count_comuni = session.query(City).filter(City.locality_type == "comune").count()
            count_localita = session.query(City).filter(City.locality_type == "localita").count()

        # 1. Carica comuni ISTAT se mancanti
        if count_comuni == 0:
            print("[CITIES] Database vuoto — caricamento comuni italiani in background...")
            from cities_loader import load_cities, download_and_load
            csv_path = Path(__file__).parent / "data" / "comuni_italiani.csv"
            if csv_path.exists():
                load_cities()
            else:
                download_and_load()
        else:
            print(f"[CITIES] {count_comuni} comuni ISTAT presenti nel DB")

        # 2. Carica località GeoNames se mancanti
        if count_localita == 0:
            print("[GEONAMES] Caricamento località GeoNames in background...")
            from cities_loader import load_geonames
            load_geonames()
        else:
            print(f"[GEONAMES] {count_localita} località GeoNames presenti nel DB")

    except Exception as e:
        print(f"[WARN] Caricamento città fallito: {e}")
        import traceback
        traceback.print_exc()


def _bootstrap_runtime():
    try:
        init_db()
        if settings.auto_load_cities:
            threading.Thread(target=_load_cities_if_empty, daemon=True).start()
        else:
            print("[CITIES] Bootstrap automatico disattivato in questo ambiente", flush=True)

        import ml_model

        ml_model.load_latest_model()
        if settings.enable_scheduler:
            from scheduler import start_scheduler

            start_scheduler()
        else:
            print("[SCHED] Scheduler disattivato in questo ambiente", flush=True)
        _bootstrap_state["ready"] = True
        print("[OK] Backend pronto\n", flush=True)
    except Exception as exc:
        _bootstrap_state["error"] = str(exc)
        print(f"[ERROR] Bootstrap backend fallito: {exc}", flush=True)
        import traceback

        traceback.print_exc()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / Shutdown dell'applicazione."""
    # --- STARTUP ---
    print("\n[METEO]  Meteo AI Backend — avvio in corso...", flush=True)
    threading.Thread(target=_bootstrap_runtime, daemon=True).start()

    yield

    # --- SHUTDOWN ---
    if settings.enable_scheduler:
        from scheduler import stop_scheduler

        stop_scheduler()
    print("[BYE] Backend fermato")


import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


app = FastAPI(
    title="Meteo AI Backend",
    description="Backend Python per l'app meteo con auto-learning ML autonomo",
    version="2.1.0",
    lifespan=lifespan
)

# CORS — permette al frontend Netlify di chiamare questa API
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_origin_regex=settings.cors_origin_regex,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

from rate_limiter import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# Importa e registra i router
from routers import weather, cities, ml, admin, supporters, advanced, notifications, telegram

app.include_router(weather, prefix="/api")
app.include_router(cities,  prefix="/api")
app.include_router(ml,      prefix="/api/ml")
app.include_router(admin,   prefix="/api/admin")
app.include_router(supporters, prefix="/api/supporters")
app.include_router(advanced, prefix="/api")
app.include_router(notifications, prefix="/api")
app.include_router(telegram, prefix="/api")


@app.get("/")
def root():
    return {
        "service": "Meteo AI Backend",
        "version": "2.1.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    db_ok = db_healthcheck()
    scheduler_enabled = settings.enable_scheduler

    model_summary = {"model_ready": False}
    training_summary = {}
    scheduler_running = False
    scheduler_jobs = 0
    if _bootstrap_state["ready"]:
        import ml_model
        from scheduler import get_training_state_summary, scheduler as current_scheduler

        model_summary = ml_model.get_public_summary()
        training_summary = get_training_state_summary()
        scheduler_running = bool(current_scheduler.running) if scheduler_enabled else False
        scheduler_jobs = len(current_scheduler.get_jobs())

    return {
        "status": "ready" if db_ok and not _bootstrap_state["error"] else "degraded",
        "database": {"ok": db_ok},
        "bootstrap": _bootstrap_state,
        "scheduler": {
            "enabled": scheduler_enabled,
            "running": scheduler_running,
            "jobs": scheduler_jobs,
        },
        "ml": model_summary,
        "ml_training": training_summary,
        "env": settings.app_env,
    }
