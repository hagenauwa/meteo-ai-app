"""
routers/ml.py — Endpoint ML per il frontend

GET /api/ml/correction?city=Roma&temp=23.5&humidity=60&hour=14
GET /api/ml/stats
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session

from database import get_db, City, MlPrediction
import ml_model

router = APIRouter()


@router.get("/correction")
async def get_correction(
    city:     str   = Query(...),
    temp:     float = Query(...),
    humidity: float = Query(50.0),
    hour:     int   = Query(None),
    db:       Session = Depends(get_db)
):
    """
    Predice la correzione ML da applicare alla temperatura.
    Salva anche la prediction per futura verifica.
    """
    now = datetime.now(timezone.utc)
    if hour is None:
        hour = now.hour

    # Cerca la città nel DB per avere lat e regione
    q_lower = city.strip().lower()
    city_row = (
        db.query(City)
        .filter(City.name_lower.like(f"{q_lower}%"))
        .order_by(City.name_lower)
        .first()
    )

    lat    = city_row.lat    if city_row else 43.0
    region = city_row.region if city_row else "Sconosciuta"
    month  = now.month

    # Calcola correzione
    result = ml_model.predict_correction(
        temp=temp,
        humidity=humidity,
        hour=hour,
        month=month,
        lat=lat,
        region=region
    )

    # Salva prediction per futura verifica
    if city_row:
        pred = MlPrediction(
            city_id        = city_row.id,
            predicted_at   = now,
            predicted_temp = temp,
            humidity       = humidity,
            hour           = hour,
            verified       = False
        )
        db.add(pred)
        db.commit()

    return result


@router.get("/stats")
def get_stats():
    """Restituisce statistiche sul modello ML e le predictions."""
    return ml_model.get_stats()


@router.post("/train")
async def force_train(min_samples: int = Query(100)):
    """Forza un re-training manuale del modello."""
    import asyncio
    result = await asyncio.to_thread(ml_model.train, min_samples)
    if result["success"]:
        ml_model.load_latest_model()
    return result
