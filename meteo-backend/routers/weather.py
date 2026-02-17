"""
routers/weather.py — Dati meteo per il frontend

GET /api/weather?city=Roma
GET /api/weather?lat=41.9&lon=12.5&name=Roma

Sostituisce la Netlify Function weather.js.
Usa Open-Meteo (gratuito, nessuna chiave).
"""
from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db, City
from weather_service import fetch_single_city, format_weather_for_frontend

router = APIRouter()


@router.get("/weather")
async def get_weather(
    city: str | None = Query(None, description="Nome città"),
    lat:  float | None = Query(None),
    lon:  float | None = Query(None),
    name: str | None = Query(None),
    db:   Session = Depends(get_db)
):
    """
    Restituisce meteo attuale + previsioni orarie e giornaliere.
    Ricerca la città nel DB ISTAT se non fornite le coordinate.
    """
    city_name = name or city or "Sconosciuta"
    city_lat  = lat
    city_lon  = lon

    # Se fornito il nome, cerca nel DB
    if city and (lat is None or lon is None):
        q_lower = city.strip().lower()
        found = (
            db.query(City)
            .filter(City.name_lower.like(f"{q_lower}%"))
            .order_by(func.length(City.name_lower))
            .first()
        )
        if not found:
            # Fallback: ricerca contenitiva
            found = (
                db.query(City)
                .filter(City.name_lower.like(f"%{q_lower}%"))
                .order_by(func.length(City.name_lower))
                .first()
            )
        if not found:
            raise HTTPException(status_code=404, detail=f"Città '{city}' non trovata nel database")

        city_lat  = found.lat
        city_lon  = found.lon
        city_name = found.name

    if city_lat is None or city_lon is None:
        raise HTTPException(status_code=400, detail="Fornisci 'city' oppure 'lat' e 'lon'")

    # Chiama Open-Meteo
    raw = await fetch_single_city(city_lat, city_lon)
    if not raw:
        raise HTTPException(status_code=502, detail="Impossibile ottenere dati meteo da Open-Meteo")

    return format_weather_for_frontend(raw, city_name)
