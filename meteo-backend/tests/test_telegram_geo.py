from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, City, TelegramRainAlert, TelegramSubscription, WeatherObservation
import telegram_notify_service


def test_avenza_inherits_ml_province_from_nearest_municipality(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(telegram_notify_service, "SessionLocal", session_factory)

    with session_factory() as db:
        db.add_all(
            [
                City(
                    id=1,
                    name="Avenza",
                    name_lower="avenza",
                    region="Toscana",
                    province=None,
                    lat=44.05,
                    lon=10.06667,
                    population=10_000,
                    locality_type="localita",
                ),
                City(
                    id=2,
                    name="Carrara",
                    name_lower="carrara",
                    region="Toscana",
                    province="Massa-Carrara",
                    lat=44.0793,
                    lon=10.0977,
                    population=60_000,
                    locality_type="comune",
                ),
                City(
                    id=3,
                    name="La Spezia",
                    name_lower="la spezia",
                    region="Liguria",
                    province="La Spezia",
                    lat=44.1025,
                    lon=9.8241,
                    population=90_000,
                    locality_type="comune",
                ),
            ]
        )
        db.commit()

    region, province = telegram_notify_service._lookup_city_geo("Avenza", 44.05, 10.06667)

    assert region == "Toscana"
    assert province == "Massa-Carrara"


def test_avenza_alert_is_verified_with_nearest_municipality_observation(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(telegram_notify_service, "SessionLocal", session_factory)
    monkeypatch.setattr(
        telegram_notify_service,
        "settings",
        SimpleNamespace(ml_trusted_observation_sources=("meteostat",)),
    )
    interval_end = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)

    with session_factory() as db:
        db.add_all(
            [
                City(
                    id=1,
                    name="Avenza",
                    name_lower="avenza",
                    region="Toscana",
                    province=None,
                    lat=44.05,
                    lon=10.06667,
                    locality_type="localita",
                ),
                City(
                    id=2,
                    name="Carrara",
                    name_lower="carrara",
                    region="Toscana",
                    province="Massa-Carrara",
                    lat=44.0793,
                    lon=10.0977,
                    locality_type="comune",
                ),
                TelegramSubscription(id=10, chat_id=123, city="Avenza"),
                TelegramRainAlert(
                    id=20,
                    subscription_id=10,
                    city="Avenza",
                    city_lat=44.05,
                    city_lon=10.06667,
                    forecast_interval_start=interval_end - timedelta(hours=1),
                    forecast_interval_end=interval_end,
                    sent_at=interval_end - timedelta(hours=1),
                    verification_status="pending",
                ),
                WeatherObservation(
                    id=30,
                    city_id=2,
                    observed_at=interval_end,
                    temp=27.0,
                    precipitation=0.0,
                    observation_source="meteostat",
                    observation_interval_minutes=60,
                ),
            ]
        )
        db.commit()

    result = telegram_notify_service._verify_pending_alerts(interval_end + timedelta(hours=1))

    assert result == {"checked": 1, "verified": 1}
    with session_factory() as db:
        alert = db.get(TelegramRainAlert, 20)
        assert alert.verification_status == "false_alarm"
        assert alert.observed_precipitation_mm == 0.0
