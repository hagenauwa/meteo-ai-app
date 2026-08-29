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

METEOSTAT_SOURCE = "meteostat"
METEOSTAT_INTERVAL_MINUTES = 60
METEOSTAT_MAX_STATION_DISTANCE_METERS = 35_000
METEOSTAT_PUBLICATION_LAG_HOURS = 2
METEOSTAT_BACKFILL_HOURS = 8


def _as_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) else None


def _utc_hour(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _nearest_station_by_city(cities: list[dict]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for city in cities:
        try:
            point = ms.Point(float(city["lat"]), float(city["lon"]))
            nearby = ms.stations.nearby(
                point,
                radius=METEOSTAT_MAX_STATION_DISTANCE_METERS,
                limit=1,
            )
            if nearby.empty:
                continue
            mapping[int(city["id"])] = str(nearby.index[0])
        except Exception as exc:
            logger.warning("meteostat_station_lookup_failed city_id=%s err=%s", city.get("id"), exc)
    return mapping


def fetch_meteostat_observations(
    cities: list[dict],
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Scarica un breve backfill orario e lo associa alle citta' campionate.

    Le righe sono marcate ``meteostat`` e con intervallo di 60 minuti, quindi
    superano il gate di provenienza usato dal training pioggia in produzione.
    Se Meteostat non e' disponibile il ciclo continua senza osservazioni fidate:
    meglio saltare una verifica che introdurre etichette sintetiche.
    """
    if not cities:
        return []

    station_by_city = _nearest_station_by_city(cities)
    station_ids = sorted(set(station_by_city.values()))
    if not station_ids:
        logger.warning("meteostat_no_station_for_sample cities=%s", len(cities))
        return []

    reference = _utc_hour(now or datetime.now(timezone.utc))
    end = reference - timedelta(hours=METEOSTAT_PUBLICATION_LAG_HOURS)
    start = end - timedelta(hours=METEOSTAT_BACKFILL_HOURS - 1)
    parameters = [
        ms.Parameter.TEMP,
        ms.Parameter.PRCP,
        ms.Parameter.RHUM,
        ms.Parameter.CLDC,
        ms.Parameter.WSPD,
        ms.Parameter.WDIR,
    ]

    try:
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
        station_id = station_by_city.get(city_id)
        if station_id is None:
            continue
        try:
            station_rows = frame.xs(station_id, level="station")
        except KeyError:
            continue

        for observed_at, row in station_rows.iterrows():
            temp = _as_float(row.get("temp"))
            precipitation = _as_float(row.get("prcp"))
            if temp is None or precipitation is None:
                continue
            timestamp = observed_at.to_pydatetime() if hasattr(observed_at, "to_pydatetime") else observed_at
            observations.append(
                {
                    "city_id": city_id,
                    "observed_at": _utc_hour(timestamp),
                    "temp": temp,
                    "humidity": _as_float(row.get("rhum")),
                    "cloud_cover": _as_float(row.get("cldc")),
                    "wind_speed": _as_float(row.get("wspd")),
                    "wind_direction": _as_float(row.get("wdir")),
                    "precipitation": max(0.0, precipitation),
                    "weather_code": None,
                    "observation_source": METEOSTAT_SOURCE,
                    "observation_interval_minutes": METEOSTAT_INTERVAL_MINUTES,
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
