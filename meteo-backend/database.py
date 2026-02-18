"""
database.py — SQLAlchemy models e connessione PostgreSQL
"""
import os
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, Text, Float,
    Boolean, DateTime, LargeBinary, ForeignKey, Index
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
    population = Column(Integer)

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
    """Previsione salvata per essere verificata dopo 1-6 ore."""
    __tablename__ = "ml_predictions"

    id             = Column(BigInteger, primary_key=True)
    city_id        = Column(Integer, ForeignKey("cities.id"), nullable=False)
    predicted_at   = Column(DateTime(timezone=True), nullable=False)
    predicted_temp = Column(Float, nullable=False)
    humidity       = Column(Float)
    hour           = Column(Integer)
    verified       = Column(Boolean, default=False)
    actual_temp    = Column(Float)
    error          = Column(Float)      # actual_temp - predicted_temp
    verified_at    = Column(DateTime(timezone=True))
    precipitation  = Column(Float, nullable=True)   # mm misurati all'ora T
    weather_code   = Column(Integer, nullable=True)  # WMO code all'ora T

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
Index("idx_pred_verified",  MlPrediction.verified)
Index("idx_cities_name",    City.name_lower)


def get_db():
    """Dependency FastAPI per ottenere una sessione DB."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Crea tutte le tabelle se non esistono e applica le migrazioni colonne."""
    Base.metadata.create_all(bind=engine)
    _migrate_columns()
    print("[OK] Database inizializzato")


def _migrate_columns():
    """
    Aggiunge colonne nuove alle tabelle esistenti (compatibile PostgreSQL e SQLite).
    ALTER TABLE ... ADD COLUMN IF NOT EXISTS funziona su PostgreSQL;
    su SQLite usiamo try/except perché non supporta IF NOT EXISTS.
    """
    migrations = [
        ("ml_predictions", "precipitation", "FLOAT"),
        ("ml_predictions", "weather_code",  "INTEGER"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                if _is_sqlite:
                    # SQLite: prova ad aggiungere, ignora errore se esiste già
                    conn.execute(
                        __import__("sqlalchemy").text(
                            f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                        )
                    )
                else:
                    # PostgreSQL: supporta IF NOT EXISTS
                    conn.execute(
                        __import__("sqlalchemy").text(
                            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
                        )
                    )
                conn.commit()
                print(f"[MIGR] Aggiunta colonna {table}.{column}")
            except Exception:
                conn.rollback()  # colonna già esistente, nessun problema
