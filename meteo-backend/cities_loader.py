"""
cities_loader.py — Carica comuni italiani (ISTAT) e località (GeoNames) nel database.

Comuni ISTAT (~7.700): da CSV GitHub matteocontrini/comuni-json
Località GeoNames (~50.000+): da https://download.geonames.org/export/dump/IT.zip

Eseguire una volta: python cities_loader.py
  --download     Scarica e carica comuni ISTAT
  --geonames     Scarica e carica località GeoNames
  --reload       Ricarica comuni da CSV locale
"""
import csv
import os
import sys
import zipfile
import io
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy import func
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
                    name          = name,
                    name_lower    = name.lower(),
                    region        = row.get(col_regione, "").strip() if col_regione else None,
                    province      = row.get(col_prov, "").strip() if col_prov else None,
                    lat           = lat,
                    lon           = lon,
                    population    = int(row[col_pop]) if col_pop and row.get(col_pop, "").isdigit() else None,
                    locality_type = "comune"
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


# ---------- GeoNames: tutte le località italiane ----------

GEONAMES_URL = "https://download.geonames.org/export/dump/IT.zip"
GEONAMES_DIR = Path(__file__).parent / "data"

# Mapping GeoNames admin1_code → nome regione italiana
ADMIN1_TO_REGION = {
    "01": "Abruzzo",     "02": "Basilicata",   "03": "Calabria",
    "04": "Campania",    "05": "Emilia-Romagna","06": "Friuli Venezia Giulia",
    "07": "Lazio",       "08": "Liguria",       "09": "Lombardia",
    "10": "Marche",      "11": "Molise",        "12": "Piemonte",
    "13": "Puglia",      "14": "Sardegna",      "15": "Sicilia",
    "16": "Toscana",     "17": "Trentino-Alto Adige", "18": "Umbria",
    "19": "Valle d'Aosta", "20": "Veneto",
}

# Feature codes di tipo "populated place" da includere
POPULATED_FEATURES = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC",
                       "PPLF", "PPLL", "PPLQ", "PPLR", "PPLS", "PPLX"}


def load_geonames() -> int:
    """
    Scarica IT.zip da GeoNames, estrae le località (feature class P),
    esclude i duplicati con i comuni ISTAT già presenti, e inserisce
    le nuove località con locality_type="localita".
    Ritorna il numero di località inserite.
    """
    import httpx

    init_db()

    # Controlla se ci sono già località GeoNames nel DB
    with Session(engine) as session:
        existing_geonames = session.query(City).filter(City.locality_type == "localita").count()
        if existing_geonames > 0:
            print(f"[INFO] {existing_geonames} località GeoNames già presenti nel DB. Saltando.")
            return existing_geonames

    # 1. Scarica IT.zip
    zip_path = GEONAMES_DIR / "IT.zip"
    txt_path = GEONAMES_DIR / "IT.txt"
    GEONAMES_DIR.mkdir(parents=True, exist_ok=True)

    if not txt_path.exists():
        print(f"[DL] Scaricando GeoNames IT.zip...")
        r = httpx.get(GEONAMES_URL, timeout=120, follow_redirects=True)
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(r.content)
        print(f"[OK] Download completato ({len(r.content) // 1024} KB)")

        # 2. Estrai IT.txt
        with zipfile.ZipFile(zip_path) as zf:
            zf.extract("IT.txt", GEONAMES_DIR)
        print(f"[OK] Estratto IT.txt")
    else:
        print(f"[INFO] IT.txt già presente, uso file locale")

    # 3. Carica comuni esistenti per deduplica (nome_lower → set di coordinate)
    with Session(engine) as session:
        existing_comuni = {}
        for c in session.query(City.name_lower, City.lat, City.lon).filter(City.locality_type == "comune").all():
            existing_comuni.setdefault(c.name_lower, []).append((c.lat, c.lon))

    # 4. Parsa IT.txt (TSV con colonne GeoNames standard)
    # Colonne: 0=geonameid, 1=name, 2=asciiname, 3=alternatenames,
    #          4=latitude, 5=longitude, 6=feature_class, 7=feature_code,
    #          8=country_code, 9=cc2, 10=admin1_code, 11=admin2,
    #          12=admin3, 13=admin4, 14=population, ...
    batch = []
    count = 0
    skipped_dupes = 0

    with open(txt_path, encoding="utf-8") as f:
        for line in f:
            cols = line.strip().split("\t")
            if len(cols) < 15:
                continue

            feature_class = cols[6]
            feature_code = cols[7]

            # Solo luoghi abitati
            if feature_class != "P" or feature_code not in POPULATED_FEATURES:
                continue

            name = cols[1].strip()
            if not name:
                continue

            try:
                lat = float(cols[4])
                lon = float(cols[5])
            except ValueError:
                continue

            name_lower = name.lower()
            admin1 = cols[10]
            region = ADMIN1_TO_REGION.get(admin1, "")
            pop_str = cols[14]
            population = int(pop_str) if pop_str.isdigit() and int(pop_str) > 0 else None

            # Deduplica: se esiste un comune ISTAT con stesso nome e coordinate vicine (<5km), skip
            is_dupe = False
            if name_lower in existing_comuni:
                for (ex_lat, ex_lon) in existing_comuni[name_lower]:
                    # Approssimazione: 0.05° ≈ 5km
                    if abs(lat - ex_lat) < 0.05 and abs(lon - ex_lon) < 0.05:
                        is_dupe = True
                        break
            if is_dupe:
                skipped_dupes += 1
                continue

            batch.append(City(
                name          = name,
                name_lower    = name_lower,
                region        = region,
                province      = None,   # GeoNames non ha provincia diretta
                lat           = lat,
                lon           = lon,
                population    = population,
                locality_type = "localita"
            ))
            count += 1

    # 5. Inserisci in batch
    with Session(engine) as session:
        for i in range(0, len(batch), 500):
            session.bulk_save_objects(batch[i:i+500])
            session.commit()
            print(f"  ... inserite {min(i+500, count)} località", end="\r")

    print(f"\n[OK] Caricate {count} località GeoNames (esclusi {skipped_dupes} duplicati con comuni ISTAT)")
    return count


if __name__ == "__main__":
    if "--download" in sys.argv:
        download_and_load()
    elif "--geonames" in sys.argv:
        load_geonames()
    elif "--reload" in sys.argv:
        load_cities(truncate=True)
    else:
        if not CSV_PATH.exists():
            print("CSV non trovato. Scarico automaticamente da GitHub...")
            download_and_load()
        else:
            load_cities()
        # Dopo i comuni ISTAT, carica anche GeoNames
        load_geonames()
