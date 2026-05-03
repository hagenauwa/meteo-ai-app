"""
routers/ml.py — endpoint ML pubblici e operativi.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import require_admin_access
from database import City, get_db

router = APIRouter()


class _LazyMlModel:
    def __getattr__(self, name: str):
        import importlib

        module = importlib.import_module("ml_model")
        return getattr(module, name)


ml_model = _LazyMlModel()


class EnrichCityPayload(BaseModel):
    name: str
    lat: float
    lon: float
    region: str | None = None
    province: str | None = None


class EnrichCurrentPayload(BaseModel):
    temp: float
    humidity: float | None = 50.0
    clouds: float | None = 50.0
    wind_speed: float | None = 0.0
    wind_deg: float | None = 0.0
    precipitation: float | None = 0.0
    weather_code: int | None = None


class EnrichDayTempPayload(BaseModel):
    min: float
    max: float
    day: float


class EnrichDayPayload(BaseModel):
    dt: str
    temp: EnrichDayTempPayload
    humidity: float | None = 50.0
    cloud_cover: float | None = 55.0
    wind_speed: float | None = 0.0
    wind_deg: float | None = 0.0
    pop: float | None = 0.0
    precipitation_sum: float | None = 0.0
    weather_code: int | None = None


class EnrichRequest(BaseModel):
    city: EnrichCityPayload
    current: EnrichCurrentPayload
    daily: list[EnrichDayPayload] = Field(default_factory=list, min_length=1, max_length=16)


def _resolve_city_context(city: str, db: Session) -> tuple[float, float, str]:
    q_lower = city.strip().lower()
    city_row = (
        db.query(City)
        .filter(City.name_lower.like(f"{q_lower}%"))
        .order_by(City.name_lower)
        .first()
    )
    lat = city_row.lat if city_row else 43.0
    lon = city_row.lon if city_row else 12.0
    region = city_row.region if city_row else "Sconosciuta"
    return lat, lon, region


def _resolve_region_for_enrich(payload: EnrichCityPayload, db: Session) -> str:
    if payload.region:
        return payload.region

    city_row = (
        db.query(City)
        .filter(City.lat == payload.lat, City.lon == payload.lon)
        .order_by(City.locality_type)
        .first()
    )
    if not city_row and payload.name:
        q_lower = payload.name.strip().lower()
        city_row = (
            db.query(City)
            .filter(City.name_lower.like(f"{q_lower}%"))
            .order_by(City.name_lower)
            .first()
        )

    return city_row.region if city_row and city_row.region else "Sconosciuta"


@router.get("/correction")
async def get_correction(
    city: str = Query(...),
    temp: float = Query(...),
    humidity: float = Query(50.0),
    cloud_cover: float = Query(50.0),
    hour: int | None = Query(None),
    lead_hours: int = Query(0, ge=0, le=240),
    forecast_precipitation: float | None = Query(None),
    forecast_wind_speed: float | None = Query(None),
    forecast_wind_direction: float | None = Query(None),
    forecast_weather_code: int | None = Query(None),
    db: Session = Depends(get_db),
):
    now = datetime.now()
    if hour is None:
        hour = now.hour

    lat, lon, region = _resolve_city_context(city, db)
    return ml_model.predict_correction(
        temp=temp,
        humidity=humidity,
        hour=hour,
        month=now.month,
        lat=lat,
        lon=lon,
        region=region,
        cloud_cover=cloud_cover,
        lead_hours=lead_hours,
        forecast_precipitation=forecast_precipitation,
        forecast_wind_speed=forecast_wind_speed,
        forecast_wind_direction=forecast_wind_direction,
        forecast_weather_code=forecast_weather_code,
    )


@router.get("/stats")
def get_stats():
    return ml_model.get_stats()


@router.post("/enrich")
async def enrich_forecast(
    payload: EnrichRequest,
    db: Session = Depends(get_db),
):
    now = datetime.now()
    region = _resolve_region_for_enrich(payload.city, db)

    correction = ml_model.predict_correction(
        temp=payload.current.temp,
        humidity=payload.current.humidity or 50.0,
        hour=now.hour,
        month=now.month,
        lat=payload.city.lat,
        lon=payload.city.lon,
        region=region,
        cloud_cover=payload.current.clouds or 50.0,
        lead_hours=0,
        forecast_precipitation=payload.current.precipitation,
        forecast_wind_speed=payload.current.wind_speed,
        forecast_wind_direction=payload.current.wind_deg,
        forecast_weather_code=payload.current.weather_code,
    )
    rain = ml_model.predict_rain_probability(
        forecast_temp=payload.current.temp,
        humidity=payload.current.humidity or 50.0,
        hour=now.hour,
        month=now.month,
        lat=payload.city.lat,
        lon=payload.city.lon,
        region=region,
        cloud_cover=payload.current.clouds or 50.0,
        lead_hours=0,
        city_name=payload.city.name,
    )

    daily_ml: list[dict] = []
    for index, day in enumerate(payload.daily):
        daily_ml.append(
            ml_model.build_daily_insight(
                day=day.model_dump(mode="python"),
                lat=payload.city.lat,
                lon=payload.city.lon,
                region=region,
                lead_hours=max(0, (index * 24) + 14),
                city_name=payload.city.name,
            )
        )

    return {
        "ml": {
            "correction": correction,
            "rain_prediction": rain,
            "summary": ml_model.get_public_summary(),
        },
        "daily_ml": daily_ml,
    }


@router.get("/rain-prediction")
async def get_rain_prediction(
    city: str = Query(...),
    temp: float = Query(...),
    humidity: float = Query(60.0),
    hour: int | None = Query(None),
    cloud_cover: float = Query(50.0),
    lead_hours: int = Query(0, ge=0, le=240),
    db: Session = Depends(get_db),
):
    now = datetime.now()
    if hour is None:
        hour = now.hour

    lat, lon, region = _resolve_city_context(city, db)
    return ml_model.predict_rain_probability(
        forecast_temp=temp,
        humidity=humidity,
        hour=hour,
        month=now.month,
        lat=lat,
        lon=lon,
        region=region,
        cloud_cover=cloud_cover,
        lead_hours=lead_hours,
        city_name=city,
    )


@router.post("/train")
async def force_train(
    min_samples: int = Query(100),
    _: None = Depends(require_admin_access),
):
    result = await __import__("asyncio").to_thread(ml_model.train, min_samples)
    if result["success"]:
        await __import__("asyncio").to_thread(ml_model.load_latest_model)
    return result
