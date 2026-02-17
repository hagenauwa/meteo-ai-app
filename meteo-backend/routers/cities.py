"""
routers/cities.py — Ricerca città italiane

GET /api/cities?q=val+di+cornia&limit=8
→ Restituisce città che matchano la query con ricerca fuzzy (trigram PostgreSQL)
"""
from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db, City

router = APIRouter()


class CityResult(BaseModel):
    id:       int
    name:     str
    region:   str | None
    province: str | None
    lat:      float
    lon:      float

    class Config:
        from_attributes = True


@router.get("/cities", response_model=List[CityResult])
def search_cities(
    q:     str   = Query(..., min_length=1, description="Testo di ricerca"),
    limit: int   = Query(8, ge=1, le=20),
    db:    Session = Depends(get_db)
):
    """
    Ricerca fuzzy su nome città. Restituisce al massimo `limit` risultati.
    Usa ILIKE per ricerca case-insensitive + pg_trgm per similarità.
    """
    q_lower = q.strip().lower()

    # Prima priorità: inizia con la query
    starts_with = (
        db.query(City)
        .filter(City.name_lower.like(f"{q_lower}%"))
        .order_by(func.length(City.name_lower))
        .limit(limit)
        .all()
    )

    results = list(starts_with)

    # Seconda priorità: contiene la query (se non abbastanza risultati)
    if len(results) < limit:
        already_ids = {c.id for c in results}
        contains = (
            db.query(City)
            .filter(
                City.name_lower.like(f"%{q_lower}%"),
                ~City.id.in_(already_ids)
            )
            .order_by(func.length(City.name_lower))
            .limit(limit - len(results))
            .all()
        )
        results.extend(contains)

    return results


@router.get("/cities/{city_id}", response_model=CityResult)
def get_city(city_id: int, db: Session = Depends(get_db)):
    """Restituisce i dettagli di una città per ID."""
    city = db.query(City).filter(City.id == city_id).first()
    if not city:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Città non trovata")
    return city
