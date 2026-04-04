"""
routers/cities.py — ricerca città e indice compatto versionato.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from config import settings
from database import City, get_db

router = APIRouter()


class CityResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    region: str | None
    province: str | None
    lat: float
    lon: float
    locality_type: str | None = "comune"


class CityIndexItem(BaseModel):
    name: str
    region: str | None
    province: str | None
    lat: float
    lon: float
    locality_type: str | None = "comune"


@router.get("/cities/index", response_model=List[CityIndexItem])
def get_cities_index(
    response: Response,
    scope: str = Query("comuni", pattern="^(comuni|localita|all)$"),
    version: str = Query("v2"),
    db: Session = Depends(get_db),
):
    """
    Restituisce un indice città compatto e cacheabile.
    `scope=comuni` è il default per il frontend pubblico.
    """
    query = db.query(
        City.name,
        City.region,
        City.province,
        City.lat,
        City.lon,
        City.locality_type,
    )
    if scope == "comuni":
        query = query.filter(City.locality_type == "comune")
    elif scope == "localita":
        query = query.filter(City.locality_type == "localita")

    rows = query.order_by(City.locality_type, City.name_lower).all()
    response.headers["Cache-Control"] = f"public, max-age={settings.cities_index_cache_seconds}"
    response.headers["X-Cities-Index-Version"] = version
    return [
        CityIndexItem(
            name=row.name,
            region=row.region,
            province=row.province,
            lat=row.lat,
            lon=row.lon,
            locality_type=row.locality_type,
        )
        for row in rows
    ]


@router.get("/cities", response_model=List[CityResult])
def search_cities(
    q: str = Query(..., min_length=1, description="Testo di ricerca"),
    limit: int = Query(8, ge=1, le=20),
    scope: str = Query("all", pattern="^(comuni|localita|all)$"),
    db: Session = Depends(get_db),
):
    q_lower = q.strip().lower()
    type_priority = case((City.locality_type == "comune", 0), else_=1)

    base_query = db.query(City)
    if scope == "comuni":
        base_query = base_query.filter(City.locality_type == "comune")
    elif scope == "localita":
        base_query = base_query.filter(City.locality_type == "localita")

    starts_with = (
        base_query
        .filter(City.name_lower.like(f"{q_lower}%"))
        .order_by(type_priority, func.length(City.name_lower))
        .limit(limit)
        .all()
    )
    results = list(starts_with)

    if len(results) < limit:
        already_ids = [city.id for city in results]
        contains_query = base_query.filter(City.name_lower.like(f"%{q_lower}%"))
        if already_ids:
            contains_query = contains_query.filter(~City.id.in_(already_ids))
        contains = (
            contains_query
            .order_by(type_priority, func.length(City.name_lower))
            .limit(limit - len(results))
            .all()
        )
        results.extend(contains)

    return results


@router.get("/cities/{city_id}", response_model=CityResult)
def get_city(city_id: int, db: Session = Depends(get_db)):
    city = db.query(City).filter(City.id == city_id).first()
    if not city:
        raise HTTPException(status_code=404, detail="Città non trovata")
    return city
