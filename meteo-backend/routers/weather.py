"""
routers/weather.py — endpoint meteo pubblico con insight ML compositi.
"""

from __future__ import annotations

from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import City, get_db
from weather_service import fetch_single_city, format_weather_for_frontend

router = APIRouter()


class _LazyMlModel:
    def __getattr__(self, name: str):
        import importlib

        module = importlib.import_module("ml_model")
        return getattr(module, name)


ml_model = _LazyMlModel()

CITY_COORDINATE_FALLBACKS = {
    "roma": {"name": "Roma", "lat": 41.9028, "lon": 12.4964},
    "milano": {"name": "Milano", "lat": 45.4642, "lon": 9.19},
    "napoli": {"name": "Napoli", "lat": 40.8518, "lon": 14.2681},
    "torino": {"name": "Torino", "lat": 45.0703, "lon": 7.6869},
    "palermo": {"name": "Palermo", "lat": 38.1157, "lon": 13.3615},
}


async def _geocode_city(city: str) -> dict | None:
    fallback = CITY_COORDINATE_FALLBACKS.get(city.strip().lower())
    if fallback:
        return fallback

    params = {"name": city, "count": 1, "language": "it", "format": "json", "countryCode": "IT"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get("https://geocoding-api.open-meteo.com/v1/search", params=params)
            response.raise_for_status()
            results = response.json().get("results") or []
    except Exception as exc:
        print(f"[WARN] Geocoding fallback fallito per '{city}': {exc}")
        return None

    if not results:
        return None
    match = results[0]
    return {"name": match.get("name") or city, "lat": match.get("latitude"), "lon": match.get("longitude")}


def _provider_ml_block(current: dict, reason: str) -> dict:
    temp = current.get("temp")
    return {
        "correction": {
            "original_temp": temp,
            "corrected_temp": temp,
            "correction": 0.0,
            "confidence": 0.0,
            "model_ready": False,
            "reason": reason,
        },
        "rain_prediction": {
            "rain_probability": current.get("rain_probability"),
            "model_ready": False,
            "reason": reason,
        },
        "summary": {"model_ready": False, "reason": reason},
        "stats": {},
    }


async def _resolve_city(
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
    db_available = True

    if city and (lat is None or lon is None):
        q_lower = city.strip().lower()
        try:
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
        except SQLAlchemyError as exc:
            db_available = False
            print(f"[WARN] DB non disponibile durante risoluzione città: {exc}")

        if not city_row:
            geocoded = await _geocode_city(city)
            if not geocoded:
                raise HTTPException(status_code=404, detail=f"Città '{city}' non trovata")
            city_lat = geocoded["lat"]
            city_lon = geocoded["lon"]
            city_name = geocoded["name"]
        else:
            city_lat = city_row.lat
            city_lon = city_row.lon
            city_name = city_row.name

    if city_lat is None or city_lon is None:
        raise HTTPException(status_code=400, detail="Fornisci 'city' oppure 'lat' e 'lon'")

    if not city_row:
        try:
            city_row = (
                db.query(City).filter(City.lat == city_lat, City.lon == city_lon).order_by(City.locality_type).first()
            )
        except SQLAlchemyError:
            db_available = False

    return {
        "name": city_name,
        "lat": city_lat,
        "lon": city_lon,
        "city_row": city_row,
        "db_available": db_available,
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
    resolved = await _resolve_city(db=db, city=city, lat=lat, lon=lon, name=name)

    raw = await fetch_single_city(resolved["lat"], resolved["lon"])
    if not raw:
        raise HTTPException(status_code=502, detail="Impossibile ottenere dati meteo da Open-Meteo")

    formatted = format_weather_for_frontend(raw, resolved["name"])
    city_row = resolved["city_row"]

    if include_ml and formatted and resolved["db_available"]:
        now = datetime.now()
        region = city_row.region if city_row else "Sconosciuta"
        current = formatted["current"]
        try:
            stats = ml_model.get_cached_stats(allow_stale=True)
            if stats is None:
                stats = {
                    "total_predictions": None,
                    "verified_predictions": None,
                    "avg_error_celsius": None,
                    "lead_time_error": [],
                    "rain_brier_14d": None,
                    "rain_f1_14d": None,
                    "condition_macro_f1_14d": None,
                    "temp_mae_14d_by_lead": [],
                    "temp_mae_14d_by_bucket": [],
                    "model_variant": "provider",
                    **ml_model.get_public_summary(),
                }
            correction = ml_model.predict_correction(
                temp=current["temp"],
                humidity=current.get("humidity", 50),
                hour=now.hour,
                month=now.month,
                lat=resolved["lat"],
                lon=resolved["lon"],
                region=region,
                cloud_cover=current.get("clouds", 50),
                lead_hours=0,
                forecast_precipitation=current.get("precipitation"),
                forecast_wind_speed=current.get("wind_speed"),
                forecast_wind_direction=current.get("wind_deg"),
                forecast_weather_code=current.get("weather_code"),
            )
            rain = ml_model.predict_rain_probability(
                forecast_temp=current["temp"],
                humidity=current.get("humidity", 50),
                hour=now.hour,
                month=now.month,
                lat=resolved["lat"],
                lon=resolved["lon"],
                region=region,
                cloud_cover=current.get("clouds", 50),
                lead_hours=0,
                forecast_precipitation=current.get("precipitation"),
                forecast_wind_speed=current.get("wind_speed"),
                forecast_wind_direction=current.get("wind_deg"),
                forecast_weather_code=current.get("weather_code"),
                city_name=resolved["name"],
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
                    lon=resolved["lon"],
                    region=region,
                    lead_hours=max(0, (index * 24) + 14),
                    city_name=resolved["name"],
                )
        except Exception as exc:
            print(f"[WARN] ML non disponibile per /api/weather: {exc}")
            formatted["ml"] = _provider_ml_block(current, "ml_unavailable")
    elif include_ml and formatted:
        formatted["ml"] = _provider_ml_block(formatted["current"], "database_unavailable")

    if city_row:
        formatted["city"] = {
            "id": city_row.id,
            "name": city_row.name,
            "region": city_row.region,
            "province": city_row.province,
            "locality_type": city_row.locality_type,
        }

    return formatted
