"""Raccolta di osservazioni orarie indipendenti per la verifica del modello.

Meteostat espone misure di stazioni meteorologiche pubbliche con qualche ora di
ritardo. Quel ritardo non e' un problema per il training: il ciclo torna sulle
previsioni ancora non verificate e assegna loro la misura della stazione piu'
vicina. In questo modo una previsione Open-Meteo non viene mai verificata usando
un altro output dello stesso modello numerico.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from math import isfinite

import meteostat as ms
import pandas as pd


logger = logging.getLogger(__name__)

METEOSTAT_SOURCE = "meteostat-observed"
METEOSTAT_INTERVAL_MINUTES = 60
METEOSTAT_MAX_STATION_DISTANCE_METERS = 35_000
METEOSTAT_PUBLICATION_LAG_HOURS = 2
METEOSTAT_BACKFILL_HOURS = 8
METEOSTAT_MAX_BACKFILL_HOURS = 7 * 24
METEOSTAT_STATION_CANDIDATES = 3


def _as_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) else None


def _utc_hour(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _nearest_station_by_city(cities: list[dict]) -> dict[int, list[tuple[str, float]]]:
    mapping: dict[int, list[tuple[str, float]]] = {}
    for city in cities:
        try:
            point = ms.Point(float(city["lat"]), float(city["lon"]))
            nearby = ms.stations.nearby(
                point,
                radius=METEOSTAT_MAX_STATION_DISTANCE_METERS,
                limit=METEOSTAT_STATION_CANDIDATES,
            )
            if nearby.empty:
                continue
            candidates = []
            for station_id, station in nearby.iterrows():
                distance = _as_float(station.get("distance"))
                if distance is not None and 0 <= distance <= METEOSTAT_MAX_STATION_DISTANCE_METERS:
                    candidates.append((str(station_id), distance / 1000.0))
            mapping[int(city["id"])] = sorted(candidates, key=lambda item: (item[1], item[0]))
        except Exception as exc:
            logger.warning("meteostat_station_lookup_failed city_id=%s err=%s", city.get("id"), exc)
    return mapping


def fetch_meteostat_observations(
    cities: list[dict],
    *,
    now: datetime | None = None,
    start_time: datetime | None = None,
) -> list[dict]:
    """Scarica un breve backfill orario e lo associa alle citta' campionate.

    Le righe senza contributi modellistici sono marcate ``meteostat-observed``
    e con intervallo di 60 minuti; conservano stazione e distanza dal comune.
    Se Meteostat non e' disponibile il ciclo continua senza osservazioni fidate:
    meglio saltare una verifica che introdurre etichette sintetiche.
    """
    if not cities:
        return []

    station_by_city = _nearest_station_by_city(cities)
    station_ids = sorted({station for candidates in station_by_city.values() for station, _ in candidates})
    if not station_ids:
        logger.warning("meteostat_no_station_for_sample cities=%s", len(cities))
        return []

    reference = _utc_hour(now or datetime.now(timezone.utc))
    end = reference - timedelta(hours=METEOSTAT_PUBLICATION_LAG_HOURS)
    start = end - timedelta(hours=METEOSTAT_BACKFILL_HOURS - 1)
    if start_time is not None:
        start = max(
            reference - timedelta(hours=METEOSTAT_MAX_BACKFILL_HOURS),
            min(start, _utc_hour(start_time)),
        )
    parameters = [
        ms.Parameter.TEMP,
        ms.Parameter.PRCP,
        ms.Parameter.RHUM,
        ms.Parameter.CLDC,
        ms.Parameter.WSPD,
        ms.Parameter.WDIR,
    ]

    try:
        # Provider.HOURLY contiene anche stime modellistiche. Questo filtro
        # agisce sulle fonti originali prima dell'aggregazione di Meteostat.
        ms.config.include_model_data = False
        frame = ms.hourly(
            station_ids,
            start,
            end,
            timezone="UTC",
            parameters=parameters,
            providers=[ms.Provider.HOURLY],
        ).fetch()
    except Exception as exc:
        logger.warning("meteostat_hourly_fetch_failed stations=%s err=%s", len(station_ids), exc)
        return []

    if frame.empty:
        logger.warning("meteostat_hourly_empty stations=%s start=%s end=%s", len(station_ids), start, end)
        return []

    observations: list[dict] = []
    for city in cities:
        city_id = int(city["id"])
        used_hours: set[datetime] = set()
        for station_id, distance_km in station_by_city.get(city_id, []):
            try:
                station_rows = frame.xs(station_id, level="station")
            except KeyError:
                continue
            for observed_at, row in station_rows.iterrows():
                temp = _as_float(row.get("temp"))
                precipitation = _as_float(row.get("prcp"))
                if temp is None or precipitation is None or precipitation < 0:
                    continue
                timestamp = observed_at.to_pydatetime() if hasattr(observed_at, "to_pydatetime") else observed_at
                timestamp = _utc_hour(timestamp)
                if timestamp in used_hours or not start <= timestamp <= end:
                    continue
                used_hours.add(timestamp)
                cloud_oktas = _as_float(row.get("cldc"))
                observations.append(
                    {
                        "city_id": city_id,
                        "observed_at": timestamp,
                        "temp": temp,
                        "humidity": _as_float(row.get("rhum")),
                        "cloud_cover": cloud_oktas * 12.5
                        if cloud_oktas is not None and 0 <= cloud_oktas <= 8
                        else None,
                        "wind_speed": _as_float(row.get("wspd")),
                        "wind_direction": _as_float(row.get("wdir")),
                        "precipitation": precipitation,
                        "weather_code": None,
                        "observation_source": METEOSTAT_SOURCE,
                        "observation_interval_minutes": METEOSTAT_INTERVAL_MINUTES,
                        "station_id": station_id,
                        "station_distance_km": distance_km,
                    }
                )

    logger.info(
        "meteostat_observations_ready cities=%s mapped=%s stations=%s rows=%s start=%s end=%s",
        len(cities),
        len(station_by_city),
        len(station_ids),
        len(observations),
        start.isoformat(),
        end.isoformat(),
    )
    return observations
