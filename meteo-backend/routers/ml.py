"""
routers/ml.py — endpoint ML pubblici e operativi.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import require_admin_access
from database import City, get_db
import ml_model

router = APIRouter()


def _resolve_city_context(city: str, db: Session) -> tuple[float, str]:
    q_lower = city.strip().lower()
    city_row = (
        db.query(City)
        .filter(City.name_lower.like(f"{q_lower}%"))
        .order_by(City.name_lower)
        .first()
    )
    lat = city_row.lat if city_row else 43.0
    region = city_row.region if city_row else "Sconosciuta"
    return lat, region


@router.get("/correction")
async def get_correction(
    city: str = Query(...),
    temp: float = Query(...),
    humidity: float = Query(50.0),
    cloud_cover: float = Query(50.0),
    hour: int | None = Query(None),
    lead_hours: int = Query(0, ge=0, le=24),
    db: Session = Depends(get_db),
):
    now = datetime.now()
    if hour is None:
        hour = now.hour

    lat, region = _resolve_city_context(city, db)
    return ml_model.predict_correction(
        temp=temp,
        humidity=humidity,
        hour=hour,
        month=now.month,
        lat=lat,
        region=region,
        cloud_cover=cloud_cover,
        lead_hours=lead_hours,
    )


@router.get("/stats")
def get_stats():
    return ml_model.get_stats()


@router.get("/rain-prediction")
async def get_rain_prediction(
    city: str = Query(...),
    temp: float = Query(...),
    humidity: float = Query(60.0),
    hour: int | None = Query(None),
    cloud_cover: float = Query(50.0),
    lead_hours: int = Query(0, ge=0, le=24),
    db: Session = Depends(get_db),
):
    now = datetime.now()
    if hour is None:
        hour = now.hour

    lat, region = _resolve_city_context(city, db)
    return ml_model.predict_rain_probability(
        forecast_temp=temp,
        humidity=humidity,
        hour=hour,
        month=now.month,
        lat=lat,
        region=region,
        cloud_cover=cloud_cover,
        lead_hours=lead_hours,
    )


@router.post("/train")
async def force_train(
    min_samples: int = Query(100),
    _: None = Depends(require_admin_access),
):
    result = await __import__("asyncio").to_thread(ml_model.train, min_samples)
    if result["success"]:
        ml_model.load_latest_model()
    return result
