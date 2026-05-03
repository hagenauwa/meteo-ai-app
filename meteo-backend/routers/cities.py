"""
routers/cities.py — ricerca città e indice compatto versionato.
"""
from __future__ import annotations

import time
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from config import settings
from database import City, get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemi Pydantic
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Cache in-memory per ricerche autocomplete (TTL 5 minuti)
# ---------------------------------------------------------------------------
_SEARCH_CACHE: dict[str, tuple[float, list[CityIndexItem]]] = {}
_CACHE_TTL = 300  # secondi


# ---------------------------------------------------------------------------
# Helper interni
# ---------------------------------------------------------------------------
def _norm_name(name: str) -> str:
    """Normalizza un nome per confronto testuale."""
    return name.strip().lower()


def _coord_key(coord: float) -> float:
    """Arrotonda una coordinata a 4 decimali per deduplicazione."""
    return round(coord, 4)


def _text_rank(name: str, q_lower: str) -> int:
    """
    Restituisce un punteggio di rank testuale:
    0 = match esatto, 1 = prefix, 2 = contains, 3 = nessun match.
    """
    n = _norm_name(name)
    if n == q_lower:
        return 0
    if n.startswith(q_lower):
        return 1
    if q_lower in n:
        return 2
    return 3


# ---------------------------------------------------------------------------
# Endpoint esistenti (INVARIATI)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Nuovo endpoint: Autocomplete unificato DB + Open-Meteo fallback
# ---------------------------------------------------------------------------
@router.get("/cities/search", response_model=List[CityIndexItem])
def search_cities_autocomplete(
    response: Response,
    q: str = Query(..., min_length=2, description="Testo di ricerca"),
    limit: int = Query(8, ge=1, le=20),
    scope: str = Query("all", pattern="^(comuni|localita|all)$"),
    db: Session = Depends(get_db),
):
    """
    Ricerca autocomplete che unisce il database locale (8.000+ comuni)
    con fallback su Open-Meteo Geocoding. I risultati sono deduplicati
    per (nome normalizzato, lat/lon arrotondati a 4 decimali) e ordinati
    per rilevanza: esatto match > prefix > contains > popolazione.
    """
    q_lower = q.strip().lower()
    cache_key = f"{scope}:{limit}:{q_lower}"

    # 1. Cache in-memory ------------------------------------------------------
    now = time.time()
    cached = _SEARCH_CACHE.get(cache_key)
    if cached:
        ts, items = cached
        if now - ts < _CACHE_TTL:
            response.headers["Cache-Control"] = "public, max-age=300"
            return items

    # 2. Ricerca nel DB locale -----------------------------------------------
    type_priority = case((City.locality_type == "comune", 0), else_=1)
    base_query = db.query(
        City.name,
        City.region,
        City.province,
        City.lat,
        City.lon,
        City.locality_type,
    )
    if scope == "comuni":
        base_query = base_query.filter(City.locality_type == "comune")
    elif scope == "localita":
        base_query = base_query.filter(City.locality_type == "localita")

    # --- Prefix match ---
    prefix_rows = (
        base_query
        .filter(City.name_lower.like(f"{q_lower}%"))
        .order_by(type_priority, func.length(City.name_lower))
        .limit(limit)
        .all()
    )

    candidates: list[tuple[CityIndexItem, int]] = []
    seen_keys: set[tuple[str, float, float]] = set()
    for r in prefix_rows:
        key = (_norm_name(r.name), _coord_key(r.lat), _coord_key(r.lon))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append((
            CityIndexItem(
                name=r.name,
                region=r.region,
                province=r.province,
                lat=r.lat,
                lon=r.lon,
                locality_type=r.locality_type,
            ),
            0,  # popolazione non disponibile per i record locali
        ))

    # --- Contains match (solo se mancano risultati) ---
    if len(candidates) < limit:
        already_names = {_norm_name(c[0].name) for c in candidates}
        contains_rows = (
            base_query
            .filter(City.name_lower.like(f"%{q_lower}%"))
            .order_by(type_priority, func.length(City.name_lower))
            .limit(limit * 2)  # buffer per filtro dedup in Python
            .all()
        )
        for r in contains_rows:
            if _norm_name(r.name) in already_names:
                continue
            key = (_norm_name(r.name), _coord_key(r.lat), _coord_key(r.lon))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            already_names.add(_norm_name(r.name))
            candidates.append((
                CityIndexItem(
                    name=r.name,
                    region=r.region,
                    province=r.province,
                    lat=r.lat,
                    lon=r.lon,
                    locality_type=r.locality_type,
                ),
                0,
            ))
            if len(candidates) >= limit:
                break

    # 3. Fallback Open-Meteo Geocoding ---------------------------------------
    if len(candidates) < limit:
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={
                        "name": q,
                        "count": limit * 3,
                        "language": "it",
                        "format": "json",
                        "countryCode": "IT",
                    },
                    headers={"bypass-tunnel-reminder": "true"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    om_results = data.get("results") or []
                    for item in om_results:
                        if item.get("country_code") != "IT":
                            continue
                        name = item.get("name", "")
                        lat = float(item.get("latitude", 0))
                        lon = float(item.get("longitude", 0))
                        key = (_norm_name(name), _coord_key(lat), _coord_key(lon))
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        population = item.get("population") or 0
                        candidates.append((
                            CityIndexItem(
                                name=name,
                                region=item.get("admin1"),
                                province=item.get("admin2"),
                                lat=lat,
                                lon=lon,
                                locality_type=None,
                            ),
                            population,
                        ))
                        if len(candidates) >= limit:
                            break
        except Exception:
            # In caso di errore di rete/time-out di Open-Meteo, restituisci
            # silenziosamente solo i risultati del DB senza fallire.
            pass

    # 4. Ranking finale e limit ----------------------------------------------
    def _sort_key(c: tuple[CityIndexItem, int]) -> tuple[int, int]:
        item, pop = c
        tr = _text_rank(item.name, q_lower)
        # Se il match testuale è forte (0-2), la popolazione non influenza.
        # Se è un fallback senza match testuale (3), ordina per popolazione disc.
        pop_score = -pop if tr >= 3 else 0
        return (tr, pop_score)

    candidates.sort(key=_sort_key)
    results = [c[0] for c in candidates[:limit]]

    # 5. Salva in cache e ritorna --------------------------------------------
    _SEARCH_CACHE[cache_key] = (now, results)

    # Pulizia preventiva della cache se diventa troppo grande
    if len(_SEARCH_CACHE) > 2000:
        _SEARCH_CACHE.clear()

    response.headers["Cache-Control"] = "public, max-age=300"
    return results

@router.get("/cities/{city_id}", response_model=CityResult)
def get_city(city_id: int, db: Session = Depends(get_db)):
    city = db.query(City).filter(City.id == city_id).first()
    if not city:
        raise HTTPException(status_code=404, detail="Città non trovata")
    return city

