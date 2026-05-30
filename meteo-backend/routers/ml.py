"""
routers/ml.py — endpoint ML pubblici e operativi.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import require_admin_access
from database import City, get_db

router = APIRouter()
ROME_TZ = ZoneInfo("Europe/Rome")
CITY_COORDINATE_TOLERANCE = 0.05


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


class MlWarning(TypedDict):
    code: str
    message: str
    reason: str


class CityResolution(TypedDict):
    resolved: bool
    ambiguous: bool
    city: str | None
    lat: float | None
    lon: float | None
    region: str | None
    province: str | None
    warning: MlWarning | None


def _fetch_city_rows(city: str, db: Session, *, limit: int = 2) -> list[City]:
    q_lower = city.strip().lower()
    if not q_lower:
        return []

    query = (
        db.query(City)
        .filter(City.name_lower.like(f"{q_lower}%"))
        .order_by(City.name_lower, City.locality_type)
    )
    if hasattr(query, "_rows"):
        return cast(list[City], getattr(query, "_rows")[:limit])
    if not hasattr(query, "limit"):
        first_result = query.first()
        return [first_result] if first_result is not None else []
    return query.limit(limit).all()


def _make_warning(code: str, message: str, reason: str) -> MlWarning:
    return {
        "code": code,
        "message": message,
        "reason": reason,
    }


def _make_resolution(
    *,
    resolved: bool,
    ambiguous: bool,
    city: str | None,
    lat: float | None,
    lon: float | None,
    region: str | None,
    warning: MlWarning | None,
    province: str | None = None,
) -> CityResolution:
    return {
        "resolved": resolved,
        "ambiguous": ambiguous,
        "city": city,
        "lat": lat,
        "lon": lon,
        "region": region,
        "province": province,
        "warning": warning,
    }


def _resolve_city_context(city: str, db: Session) -> CityResolution:
    matches = _fetch_city_rows(city, db)
    requested_city = city.strip() or city
    if not matches:
        return _make_resolution(
            resolved=False,
            ambiguous=False,
            city=requested_city,
            lat=None,
            lon=None,
            region=None,
            warning=_make_warning(
                "ML_CITY_UNRESOLVED",
                "ML disabilitato: citta non riconosciuta.",
                f"unknown city: {requested_city}",
            ),
        )

    if len(matches) > 1:
        return _make_resolution(
            resolved=False,
            ambiguous=True,
            city=requested_city,
            lat=None,
            lon=None,
            region=None,
            warning=_make_warning(
                "ML_CITY_AMBIGUOUS",
                "ML disabilitato: citta ambigua.",
                f"multiple city matches for '{requested_city}'",
            ),
        )

    city_row = matches[0]
    city_name = cast(str, cast(object, city_row.name))
    city_lat = cast(float, cast(object, city_row.lat))
    city_lon = cast(float, cast(object, city_row.lon))
    city_region = cast(str | None, cast(object, city_row.region))
    city_province = cast(str | None, cast(object, city_row.province))
    return _make_resolution(
        resolved=True,
        ambiguous=False,
        city=city_name,
        lat=city_lat,
        lon=city_lon,
        region=city_region or "Sconosciuta",
        province=city_province,
        warning=None,
    )


def _resolve_city_for_enrich(payload: EnrichCityPayload, db: Session) -> CityResolution:
    resolution = _resolve_city_context(payload.name, db)
    if not resolution["resolved"]:
        return resolution

    resolved_lat = resolution["lat"]
    resolved_lon = resolution["lon"]
    if resolved_lat is None or resolved_lon is None:
        return _make_resolution(
            resolved=False,
            ambiguous=False,
            city=payload.name,
            lat=None,
            lon=None,
            region=None,
            warning=_make_warning(
                "ML_CITY_UNRESOLVED",
                "ML disabilitato: coordinate non disponibili per la citta richiesta.",
                f"missing coordinates for '{payload.name}'",
            ),
        )

    lat_delta = abs(payload.lat - resolved_lat)
    lon_delta = abs(payload.lon - resolved_lon)
    if lat_delta > CITY_COORDINATE_TOLERANCE or lon_delta > CITY_COORDINATE_TOLERANCE:
        return _make_resolution(
            resolved=False,
            ambiguous=False,
            city=payload.name,
            lat=None,
            lon=None,
            region=None,
            warning=_make_warning(
                "ML_CITY_UNRESOLVED",
                "ML disabilitato: coordinate non coerenti con la citta richiesta.",
                (
                    f"coordinates differ by more than {CITY_COORDINATE_TOLERANCE:.2f} "
                    f"for '{payload.name}'"
                ),
            ),
        )

    return _make_resolution(
        resolved=True,
        ambiguous=False,
        city=resolution["city"],
        lat=payload.lat,
        lon=payload.lon,
        region=payload.region or resolution["region"] or "Sconosciuta",
        province=resolution["province"],
        warning=None,
    )


def _disabled_ml_payload(warning: MlWarning) -> dict[str, object]:
    return {
        "ml": {
            "enabled": False,
            "warning": warning,
            "correction": None,
            "rain_prediction": None,
            "summary": ml_model.get_public_summary(),
        },
        "daily_ml": [],
    }


def _disabled_prediction_payload(*, warning: MlWarning, temp: float | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "enabled": False,
        "warning": warning,
        "model_ready": False,
        "confidence": "bassa",
    }
    if temp is None:
        payload["rain_probability"] = None
        payload["will_rain"] = None
    else:
        payload["correction"] = 0.0
        payload["corrected_temp"] = temp
    return payload


def _warning_from_model_status(status: str) -> MlWarning:
    return _make_warning(
        "ML_MODEL_DISABLED",
        "ML disabilitato: modello non disponibile.",
        f"model unavailable: {status}",
    )


def _invalid_input_warning(reason: str) -> MlWarning:
    return _make_warning(
        "ML_INVALID_INPUT",
        "ML disabilitato: parametri non validi.",
        reason,
    )


def _out_of_area_warning(city: str | None) -> MlWarning:
    return _make_warning(
        "ML_OUT_OF_AREA",
        "Modello ML non disponibile per questa zona: mostrata la previsione standard.",
        f"city outside ML coverage area: {city}",
    )


def _parse_float_query(
    value: str,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> tuple[float | None, MlWarning | None]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None, _invalid_input_warning(f"invalid {field_name}: {value}")

    if minimum is not None and parsed < minimum:
        return None, _invalid_input_warning(f"invalid {field_name}: below minimum {minimum}")
    if maximum is not None and parsed > maximum:
        return None, _invalid_input_warning(f"invalid {field_name}: above maximum {maximum}")
    return parsed, None


def _parse_int_query(
    value: str,
    *,
    field_name: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> tuple[int | None, MlWarning | None]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, _invalid_input_warning(f"invalid {field_name}: {value}")

    if minimum is not None and parsed < minimum:
        return None, _invalid_input_warning(f"invalid {field_name}: below minimum {minimum}")
    if maximum is not None and parsed > maximum:
        return None, _invalid_input_warning(f"invalid {field_name}: above maximum {maximum}")
    return parsed, None


def _normalize_prediction_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    if normalized.get("model_ready") is False:
        warning_status = normalized.get("warning_status")
        if isinstance(warning_status, str) and warning_status:
            normalized["enabled"] = False
            normalized["warning"] = _warning_from_model_status(warning_status)
    return normalized


def _rome_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(ROME_TZ)


def _representative_daily_datetime(date_text: str) -> datetime:
    return datetime.fromisoformat(date_text).replace(hour=14, minute=0, second=0, microsecond=0, tzinfo=ROME_TZ)


def _representative_daily_lead_hours(*, now: datetime, date_text: str) -> int:
    representative_time = _representative_daily_datetime(date_text)
    lead_delta = representative_time - now.astimezone(ROME_TZ)
    return max(0, int(lead_delta.total_seconds() // 3600))


@router.get("/correction")
async def get_correction(
    city: str = Query(...),
    temp: str = Query(...),
    humidity: str = Query("50.0"),
    cloud_cover: str = Query("50.0"),
    hour: str | None = Query(None),
    lead_hours: int = Query(0, ge=0, le=240),
    forecast_precipitation: float | None = Query(None),
    forecast_wind_speed: float | None = Query(None),
    forecast_wind_direction: float | None = Query(None),
    forecast_weather_code: int | None = Query(None),
    db: Session = Depends(get_db),
):
    now = _rome_now()
    parsed_temp, temp_warning = _parse_float_query(temp, field_name="temp")
    if temp_warning is not None:
        return _disabled_prediction_payload(temp=None, warning=temp_warning)

    parsed_humidity, humidity_warning = _parse_float_query(
        humidity,
        field_name="humidity",
        minimum=0.0,
        maximum=100.0,
    )
    if humidity_warning is not None:
        return _disabled_prediction_payload(temp=parsed_temp, warning=humidity_warning)

    parsed_cloud_cover, cloud_cover_warning = _parse_float_query(
        cloud_cover,
        field_name="cloud_cover",
        minimum=0.0,
        maximum=100.0,
    )
    if cloud_cover_warning is not None:
        return _disabled_prediction_payload(temp=parsed_temp, warning=cloud_cover_warning)

    if hour is None:
        parsed_hour = now.hour
    else:
        parsed_hour, hour_warning = _parse_int_query(hour, field_name="hour", minimum=0, maximum=23)
        if hour_warning is not None:
            return _disabled_prediction_payload(temp=parsed_temp, warning=hour_warning)

    resolution = _resolve_city_context(city, db)
    if not resolution["resolved"]:
        warning = resolution["warning"]
        if warning is None:
            warning = _make_warning("ML_CITY_UNRESOLVED", "ML disabilitato.", "missing warning details")
        return _disabled_prediction_payload(temp=parsed_temp, warning=warning)

    return _normalize_prediction_payload(ml_model.predict_correction(
        temp=parsed_temp,
        humidity=parsed_humidity,
        hour=parsed_hour,
        month=now.month,
        lat=resolution["lat"],
        lon=resolution["lon"],
        region=resolution["region"],
        cloud_cover=parsed_cloud_cover,
        lead_hours=lead_hours,
        forecast_precipitation=forecast_precipitation,
        forecast_wind_speed=forecast_wind_speed,
        forecast_wind_direction=forecast_wind_direction,
        forecast_weather_code=forecast_weather_code,
    ))


@router.get("/stats")
def get_stats():
    stats = dict(ml_model.get_stats())
    if "model_status" not in stats or "model_load_warning" not in stats or "model_ready" not in stats:
        summary = dict(ml_model.get_public_summary())
        stats.setdefault("model_status", summary.get("model_status"))
        stats.setdefault("model_load_warning", summary.get("model_load_warning"))
        stats.setdefault("model_ready", summary.get("model_ready"))
    return stats


@router.post("/enrich")
async def enrich_forecast(
    payload: EnrichRequest,
    db: Session = Depends(get_db),
):
    now = _rome_now()
    resolution = _resolve_city_for_enrich(payload.city, db)
    if not resolution["resolved"]:
        warning = resolution["warning"]
        if warning is None:
            warning = _make_warning("ML_CITY_UNRESOLVED", "ML disabilitato.", "missing warning details")
        return _disabled_ml_payload(warning)

    # Serving onesto: il modello è addestrato solo su alcune province. Fuori da
    # quell'area non estrapoliamo, ma dichiariamo il ML non disponibile.
    if not ml_model.is_city_in_ml_coverage(resolution["province"]):
        return _disabled_ml_payload(_out_of_area_warning(resolution["city"]))

    region = resolution["region"]

    correction = ml_model.predict_correction(
        temp=payload.current.temp,
        humidity=payload.current.humidity or 50.0,
        hour=now.hour,
        month=now.month,
        lat=resolution["lat"],
        lon=resolution["lon"],
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
        lat=resolution["lat"],
        lon=resolution["lon"],
        region=region,
        cloud_cover=payload.current.clouds or 50.0,
        lead_hours=0,
        city_name=payload.city.name,
    )

    daily_ml: list[dict[str, object]] = []
    for day in payload.daily:
        insight = ml_model.build_daily_insight(
            day=day.model_dump(mode="python"),
            lat=resolution["lat"],
            lon=resolution["lon"],
            region=region,
            lead_hours=_representative_daily_lead_hours(now=now, date_text=day.dt),
            city_name=payload.city.name,
        )
        # Echeggia la data così il frontend può allineare l'insight al giorno
        # corretto per data (non per indice), evitando disallineamenti.
        if isinstance(insight, dict):
            insight = {**insight, "dt": day.dt}
        daily_ml.append(insight)

    return {
        "ml": {
            "enabled": True,
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
    now = _rome_now()
    if hour is None:
        hour = now.hour

    resolution = _resolve_city_context(city, db)
    if not resolution["resolved"]:
        warning = resolution["warning"]
        if warning is None:
            warning = _make_warning("ML_CITY_UNRESOLVED", "ML disabilitato.", "missing warning details")
        return _disabled_prediction_payload(warning=warning)

    return ml_model.predict_rain_probability(
        forecast_temp=temp,
        humidity=humidity,
        hour=hour,
        month=now.month,
        lat=resolution["lat"],
        lon=resolution["lon"],
        region=resolution["region"],
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
