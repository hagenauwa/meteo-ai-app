"""
database.py — SQLAlchemy models, connessione DB e bootstrap Alembic.
"""
import os
from pathlib import Path
from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, Text, Float,
    Boolean, DateTime, LargeBinary, ForeignKey, Index, text
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Usa SQLite di default (nessuna installazione richiesta su Windows)
# Per usare PostgreSQL: DATABASE_URL=postgresql://user:pass@host/meteo_ai nel .env
_default_db = f"sqlite:///{Path(__file__).parent / 'meteo_ai.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", _default_db)

# Neon/Supabase usano "postgresql://" ma SQLAlchemy richiede "postgresql+psycopg2://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

_is_sqlite = DATABASE_URL.startswith("sqlite")
_engine_kwargs = {"pool_pre_ping": True} if not _is_sqlite else {"connect_args": {"check_same_thread": False}}

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# SQLite non supporta BigInteger nativamente — usiamo Integer come fallback
BigInteger = BigInteger if not _is_sqlite else Integer


class Base(DeclarativeBase):
    pass


class City(Base):
    __tablename__ = "cities"

    id         = Column(Integer, primary_key=True)
    name       = Column(Text, nullable=False)
    name_lower = Column(Text, nullable=False)   # ricerca case-insensitive
    region     = Column(Text)
    province   = Column(Text)
    lat        = Column(Float, nullable=False)
    lon        = Column(Float, nullable=False)
    population    = Column(Integer)
    locality_type = Column(Text, default="comune")  # "comune" (ISTAT) o "localita" (GeoNames)

    observations = relationship("WeatherObservation", back_populates="city", lazy="dynamic")
    predictions  = relationship("MlPrediction", back_populates="city", lazy="dynamic")


class WeatherObservation(Base):
    """Osservazione meteo reale raccolta ogni ora dal cron job."""
    __tablename__ = "weather_observations"

    id          = Column(BigInteger, primary_key=True)
    city_id     = Column(Integer, ForeignKey("cities.id"), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    temp        = Column(Float, nullable=False)
    humidity    = Column(Float)
    cloud_cover = Column(Float)
    wind_speed  = Column(Float)
    precipitation = Column(Float)

    city = relationship("City", back_populates="observations")


class MlPrediction(Base):
    """Previsione meteo salvata con target futuro per la verifica successiva."""
    __tablename__ = "ml_predictions"

    id             = Column(BigInteger, primary_key=True)
    city_id        = Column(Integer, ForeignKey("cities.id"), nullable=False)
    predicted_at   = Column(DateTime(timezone=True), nullable=False)
    target_time    = Column(DateTime(timezone=True), nullable=True)
    lead_hours     = Column(Integer, nullable=True)
    forecast_source = Column(Text, default="open-meteo")
    predicted_temp = Column(Float, nullable=False)
    forecast_temp  = Column(Float, nullable=True)
    humidity       = Column(Float)  # umidità prevista all'orario target
    hour           = Column(Integer)
    verified       = Column(Boolean, default=False)
    actual_temp    = Column(Float)
    error          = Column(Float)      # actual_temp - predicted_temp
    verified_at    = Column(DateTime(timezone=True))
    precipitation  = Column(Float, nullable=True)   # compat legacy / forecast
    weather_code   = Column(Integer, nullable=True)  # compat legacy / forecast
    forecast_precipitation = Column(Float, nullable=True)
    forecast_weather_code  = Column(Integer, nullable=True)
    forecast_cloud_cover   = Column(Float, nullable=True)
    actual_precipitation   = Column(Float, nullable=True)
    actual_weather_code    = Column(Integer, nullable=True)
    actual_cloud_cover     = Column(Float, nullable=True)

    city = relationship("City", back_populates="predictions")


class MlModelStore(Base):
    """Modello scikit-learn serializzato (pickle)."""
    __tablename__ = "ml_model_store"

    id          = Column(Integer, primary_key=True)
    trained_at  = Column(DateTime(timezone=True), nullable=False)
    model_bytes = Column(LargeBinary)   # pickle del Pipeline scikit-learn
    mae         = Column(Float)         # Mean Absolute Error sul validation set
    n_samples   = Column(Integer)


# Indici per performance (compatibili sia SQLite che PostgreSQL)
Index("idx_obs_city_time",  WeatherObservation.city_id, WeatherObservation.observed_at)
Index("idx_pred_city_time", MlPrediction.city_id, MlPrediction.predicted_at)
Index("idx_pred_target_time", MlPrediction.city_id, MlPrediction.target_time)
Index("idx_pred_verified",  MlPrediction.verified)
Index("idx_cities_name",    City.name_lower)
Index("idx_cities_type",    City.locality_type)


def get_db():
    """Dependency FastAPI per ottenere una sessione DB."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Allinea lo schema al `head` Alembic."""
    run_migrations()
    print("[OK] Database inizializzato")


def db_healthcheck() -> bool:
    """Verifica minima di connettività al database."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def run_migrations():
    """Esegue `alembic upgrade head` sul database configurato."""
    from alembic import command
    from alembic.config import Config

    alembic_ini = Path(__file__).parent / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(config, "head")
