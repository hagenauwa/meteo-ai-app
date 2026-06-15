"""
routers/advanced.py — endpoint meteo avanzato con dati qualità dell'aria.

Chiama in parallelo il weather_service per i dati base e l'Open-Meteo
Air Quality API per indici UV, PM10, PM2.5, AQI.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from routers.weather import _resolve_city
from weather_service import fetch_single_city, format_weather_for_frontend

router = APIRouter()

AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


async def _fetch_air_quality(lat: float, lon: float) -> dict | None:
    """Chiama Open-Meteo Air Quality API; restituisce None in caso di errore."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "pm10,pm2_5,european_aqi,us_aqi,uv_index",
        "forecast_days": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(AIR_QUALITY_URL, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        print(f"[WARN] Air Quality API fallita per lat={lat} lon={lon}: {exc}")
        return None


@router.get("/weather/advanced")
async def get_weather_advanced(
    city: str | None = Query(None, description="Nome città"),
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    name: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Restituisce dati meteo base + blocchi advanced (qualità aria, UV)."""
    resolved = await _resolve_city(db=db, city=city, lat=lat, lon=lon, name=name)

    # Esegui le due chiamate in parallelo
    base_task = asyncio.create_task(fetch_single_city(resolved["lat"], resolved["lon"]))
    aq_task = asyncio.create_task(_fetch_air_quality(resolved["lat"], resolved["lon"]))

    raw = await base_task
    aq_data = await aq_task

    if not raw:
        raise HTTPException(status_code=502, detail="Impossibile ottenere dati meteo da Open-Meteo")

    formatted = format_weather_for_frontend(raw, resolved["name"])

    advanced = {
        "uv_index": None,
        "pm10": None,
        "pm2_5": None,
        "european_aqi": None,
        "us_aqi": None,
        "source": "open-meteo-air-quality",
    }

    if aq_data:
        current_aq = aq_data.get("current", {})
        # Cast espliciti per rispettare il contratto di tipo
        advanced["uv_index"] = float(uv) if (uv := current_aq.get("uv_index")) is not None else None
        advanced["pm10"] = float(pm10) if (pm10 := current_aq.get("pm10")) is not None else None
        advanced["pm2_5"] = float(pm25) if (pm25 := current_aq.get("pm2_5")) is not None else None
        advanced["european_aqi"] = int(eaqi) if (eaqi := current_aq.get("european_aqi")) is not None else None
        advanced["us_aqi"] = int(uaqi) if (uaqi := current_aq.get("us_aqi")) is not None else None

    return {
        "current": formatted.get("current"),
        "hourly": formatted.get("hourly", []),
        "daily": formatted.get("daily", []),
        "advanced": advanced,
    }
