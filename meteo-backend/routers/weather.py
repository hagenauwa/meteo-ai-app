"""
routers/weather.py — endpoint meteo pubblico con insight ML compositi.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import City, get_db
import ml_model
from weather_service import fetch_single_city, format_weather_for_frontend

router = APIRouter()


def _resolve_city(
    *,
    db: Session,
    city: str | None,
    lat: float | None,
    lon: float | None,
    name: str | None,
) -> dict:
    city_name = name or city or "Sconosciuta"
    city_lat = lat
    city_lon = lon
    city_row = None

    if city and (lat is None or lon is None):
        q_lower = city.strip().lower()
        city_row = (
            db.query(City)
            .filter(City.name_lower.like(f"{q_lower}%"))
            .order_by(func.length(City.name_lower))
            .first()
        )
        if not city_row:
            city_row = (
                db.query(City)
                .filter(City.name_lower.like(f"%{q_lower}%"))
                .order_by(func.length(City.name_lower))
                .first()
            )
        if not city_row:
            raise HTTPException(status_code=404, detail=f"Città '{city}' non trovata nel database")

        city_lat = city_row.lat
        city_lon = city_row.lon
        city_name = city_row.name

    if city_lat is None or city_lon is None:
        raise HTTPException(status_code=400, detail="Fornisci 'city' oppure 'lat' e 'lon'")

    if not city_row:
        city_row = (
            db.query(City)
            .filter(City.lat == city_lat, City.lon == city_lon)
            .order_by(City.locality_type)
            .first()
        )

    return {
        "name": city_name,
        "lat": city_lat,
        "lon": city_lon,
        "city_row": city_row,
    }


@router.get("/weather")
async def get_weather(
    city: str | None = Query(None, description="Nome città"),
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    name: str | None = Query(None),
    include_ml: bool = Query(True, description="Se true include insight ML"),
    db: Session = Depends(get_db),
):
    resolved = _resolve_city(db=db, city=city, lat=lat, lon=lon, name=name)

    raw = await fetch_single_city(resolved["lat"], resolved["lon"])
    if not raw:
        raise HTTPException(status_code=502, detail="Impossibile ottenere dati meteo da Open-Meteo")

    formatted = format_weather_for_frontend(raw, resolved["name"])
    city_row = resolved["city_row"]

    if include_ml and formatted:
        now = datetime.now()
        region = city_row.region if city_row else "Sconosciuta"
        current = formatted["current"]
        stats = ml_model.get_stats()
        correction = ml_model.predict_correction(
            temp=current["temp"],
            humidity=current.get("humidity", 50),
            hour=now.hour,
            month=now.month,
            lat=resolved["lat"],
            region=region,
            cloud_cover=current.get("clouds", 50),
            lead_hours=0,
        )
        rain = ml_model.predict_rain_probability(
            forecast_temp=current["temp"],
            humidity=current.get("humidity", 50),
            hour=now.hour,
            month=now.month,
            lat=resolved["lat"],
            region=region,
            cloud_cover=current.get("clouds", 50),
            lead_hours=0,
        )
        formatted["ml"] = {
            "correction": correction,
            "rain_prediction": rain,
            "summary": ml_model.get_public_summary(),
            "stats": stats,
        }

        for index, day in enumerate(formatted.get("daily", [])):
            day["ml"] = ml_model.build_daily_insight(
                day=day,
                lat=resolved["lat"],
                region=region,
                lead_hours=max(0, (index * 24) + 14),
            )

    if city_row:
        formatted["city"] = {
            "id": city_row.id,
            "name": city_row.name,
            "region": city_row.region,
            "province": city_row.province,
            "locality_type": city_row.locality_type,
        }

    return formatted
