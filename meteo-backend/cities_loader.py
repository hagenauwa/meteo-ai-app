"""
cities_loader.py — Carica tutti i comuni italiani da CSV ISTAT nel database.

Dataset: https://github.com/matteocontrini/comuni-json
         oppure ISTAT: https://www.istat.it/it/files//2011/01/comuni_italiani_geo.csv

Il CSV atteso ha le colonne (con header):
  nome, regione, provincia, lat, lon, popolazione (opzionale)

Eseguire una volta: python cities_loader.py
"""
import csv
import os
import sys
from pathlib import Path

from sqlalchemy.orm import Session
from database import engine, init_db, City

CSV_PATH = Path(__file__).parent / "data" / "comuni_italiani.csv"

# Colonne attese nel CSV (case-insensitive)
COL_ALIASES = {
    "nome":       ["nome", "name", "denominazione_ita", "comune"],
    "regione":    ["regione", "region", "nome_regione"],
    "provincia":  ["provincia", "province", "sigla_provincia", "nome_provincia"],
    "lat":        ["lat", "latitude", "latitudine"],
    "lon":        ["lon", "lng", "longitude", "longitudine"],
    "popolazione":["popolazione", "population", "pop"],
}


def _find_col(header: list, aliases: list) -> str | None:
    """Trova il nome della colonna nell'header dato un elenco di alias."""
    header_lower = [h.strip().lower() for h in header]
    for alias in aliases:
        if alias.lower() in header_lower:
            return header[header_lower.index(alias.lower())]
    return None


def load_cities(truncate: bool = False) -> int:
    """
    Legge il CSV e inserisce/aggiorna i comuni nel database.
    Se truncate=True, cancella tutto prima di reinserire.
    Ritorna il numero di righe inserite.
    """
    if not CSV_PATH.exists():
        print(f"[ERROR] CSV non trovato: {CSV_PATH}")
        print("   Scarica il file da:")
        print("   https://raw.githubusercontent.com/matteocontrini/comuni-json/master/comuni.json")
        print("   oppure usa lo script download_cities.py")
        return 0

    init_db()

    with Session(engine) as session:
        if truncate:
            session.query(City).delete()
            session.commit()
            print("[DEL]  Tabella cities svuotata")

        # Conta già presenti
        existing = session.query(City).count()
        if existing > 0 and not truncate:
            print(f"[INFO]  Database ha già {existing} città. Usa truncate=True per ricaricare.")
            return existing

        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []

            col_nome     = _find_col(header, COL_ALIASES["nome"])
            col_regione  = _find_col(header, COL_ALIASES["regione"])
            col_prov     = _find_col(header, COL_ALIASES["provincia"])
            col_lat      = _find_col(header, COL_ALIASES["lat"])
            col_lon      = _find_col(header, COL_ALIASES["lon"])
            col_pop      = _find_col(header, COL_ALIASES["popolazione"])

            if not col_nome or not col_lat or not col_lon:
                print(f"[ERROR] Colonne obbligatorie mancanti. Header trovato: {header}")
                return 0

            batch = []
            count = 0
            for row in reader:
                try:
                    lat = float(row[col_lat].replace(",", "."))
                    lon = float(row[col_lon].replace(",", "."))
                except (ValueError, KeyError):
                    continue

                name = row[col_nome].strip()
                if not name:
                    continue

                city = City(
                    name       = name,
                    name_lower = name.lower(),
                    region     = row.get(col_regione, "").strip() if col_regione else None,
                    province   = row.get(col_prov, "").strip() if col_prov else None,
                    lat        = lat,
                    lon        = lon,
                    population = int(row[col_pop]) if col_pop and row.get(col_pop, "").isdigit() else None
                )
                batch.append(city)
                count += 1

                if len(batch) >= 500:
                    session.bulk_save_objects(batch)
                    session.commit()
                    batch = []
                    print(f"  ... inserite {count} città", end="\r")

            if batch:
                session.bulk_save_objects(batch)
                session.commit()

    print(f"\n[OK] Caricati {count} comuni italiani nel database")
    return count


def download_and_load():
    """
    Scarica il dataset comuni da GitHub, geocodifica le coordinate
    tramite Open-Meteo geocoding API (gratuita), e carica nel DB.
    Operazione una-tantum: richiede ~2-3 minuti per ~7.900 comuni.
    """
    import json, asyncio
    import httpx

    GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
    COMUNI_URL = "https://raw.githubusercontent.com/matteocontrini/comuni-json/master/comuni.json"

    async def _run():
        # 1. Scarica lista comuni (nomi + regioni, senza coordinate)
        print("[DL] Scaricando lista comuni da GitHub...")
        async with httpx.AsyncClient() as client:
            r = await client.get(COMUNI_URL, timeout=60)
            r.raise_for_status()
            data = r.json()
        print(f"[OK] {len(data)} comuni scaricati")

        # 2. Geocodifica in parallelo con Open-Meteo (max 20 richieste concorrenti)
        print("[GEO] Geocodifica coordinate via Open-Meteo (potrebbe richiedere 2-3 minuti)...")
        semaphore = asyncio.Semaphore(20)
        coords_map: dict = {}

        async def geocode_one(comune_name: str, client: httpx.AsyncClient):
            async with semaphore:
                try:
                    r = await client.get(GEO_URL, params={
                        "name": comune_name, "count": 1,
                        "language": "it", "format": "json",
                        "country_code": "IT"
                    }, timeout=15)
                    result = r.json().get("results", [])
                    if result:
                        return comune_name, result[0]["latitude"], result[0]["longitude"]
                except Exception:
                    pass
                return comune_name, None, None

        async with httpx.AsyncClient() as client:
            tasks = [geocode_one(c["nome"], client) for c in data]
            done = 0
            results = []
            for coro in asyncio.as_completed(tasks):
                name, lat, lon = await coro
                results.append((name, lat, lon))
                if lat is not None:
                    coords_map[name] = (lat, lon)
                done += 1
                if done % 200 == 0:
                    print(f"  ... {done}/{len(tasks)} ({len(coords_map)} con coordinate)", end="\r")

        print(f"\n[OK] Geocodificate {len(coords_map)}/{len(data)} città")

        # 3. Scrivi CSV
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["nome", "regione", "provincia", "lat", "lon", "popolazione"])
            for comune in data:
                nome = comune.get("nome", "")
                lat, lon = coords_map.get(nome, (None, None))
                if lat is None:
                    continue   # Salta comuni senza coordinate
                writer.writerow([
                    nome,
                    comune.get("regione", {}).get("nome", ""),
                    comune.get("provincia", {}).get("nome", ""),
                    lat, lon,
                    comune.get("popolazione", "")
                ])
                written += 1

        print(f"[OK] CSV salvato: {CSV_PATH} ({written} comuni con coordinate)")

    asyncio.run(_run())
    return load_cities(truncate=True)


if __name__ == "__main__":
    if "--download" in sys.argv:
        download_and_load()
    elif "--reload" in sys.argv:
        load_cities(truncate=True)
    else:
        if not CSV_PATH.exists():
            print("CSV non trovato. Scarico automaticamente da GitHub...")
            download_and_load()
        else:
            load_cities()
