"""
main.py — FastAPI app principale

Avvio: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from database import init_db, SessionLocal, City
from scheduler import start_scheduler, stop_scheduler
import ml_model

load_dotenv()


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / Shutdown dell'applicazione."""
    # --- STARTUP ---
    print("\n[METEO]  Meteo AI Backend — avvio in corso...")
    init_db()
    threading.Thread(target=_load_cities_if_empty, daemon=True).start()
    ml_model.load_latest_model()
    start_scheduler()
    print("[OK] Backend pronto\n")

    yield

    # --- SHUTDOWN ---
    stop_scheduler()
    print("[BYE] Backend fermato")


app = FastAPI(
    title="Meteo AI Backend",
    description="Backend Python per l'app meteo con auto-learning ML autonomo",
    version="2.1.0",
    lifespan=lifespan
)

# CORS — permette al frontend Netlify di chiamare questa API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # In produzione: metti l'URL Netlify esatto
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# Importa e registra i router
from routers import weather, cities, ml, chat, admin

app.include_router(weather, prefix="/api")
app.include_router(cities,  prefix="/api")
app.include_router(ml,      prefix="/api/ml")
app.include_router(chat,    prefix="/api")
app.include_router(admin,   prefix="/api/admin")


@app.get("/")
def root():
    return {
        "service": "Meteo AI Backend",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
def health():
    return {"status": "ok"}
