"""
database.py — SQLAlchemy models, connessione DB e bootstrap Alembic.
"""

import os
from pathlib import Path
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    BigInteger,
    Text,
    String,
    Float,
    Boolean,
    DateTime,
    LargeBinary,
    ForeignKey,
    Index,
    text,
    func,
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

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    name_lower = Column(Text, nullable=False)  # ricerca case-insensitive
    region = Column(Text)
    province = Column(Text)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    population = Column(Integer)
    locality_type = Column(Text, default="comune")  # "comune" (ISTAT) o "localita" (GeoNames)

    observations = relationship("WeatherObservation", back_populates="city", lazy="dynamic")
    predictions = relationship("MlPrediction", back_populates="city", lazy="dynamic")


class WeatherObservation(Base):
    """Valore di riferimento raccolto dal cron, con provenienza esplicita."""

    __tablename__ = "weather_observations"

    id = Column(BigInteger, primary_key=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    temp = Column(Float, nullable=False)
    humidity = Column(Float)
    cloud_cover = Column(Float)
    wind_speed = Column(Float)
    wind_direction = Column(Float)
    precipitation = Column(Float)
    observation_source = Column(Text, nullable=False, default="unknown")
    observation_interval_minutes = Column(Integer)
    station_id = Column(Text, nullable=True)
    station_distance_km = Column(Float, nullable=True)

    city = relationship("City", back_populates="observations")


class MlPrediction(Base):
    """Previsione meteo salvata con target futuro per la verifica successiva."""

    __tablename__ = "ml_predictions"

    id = Column(BigInteger, primary_key=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False)
    predicted_at = Column(DateTime(timezone=True), nullable=False)
    target_time = Column(DateTime(timezone=True), nullable=True)
    lead_hours = Column(Integer, nullable=True)
    forecast_source = Column(Text, default="open-meteo")
    predicted_temp = Column(Float, nullable=False)
    forecast_temp = Column(Float, nullable=True)
    humidity = Column(Float)  # umidità prevista all'orario target
    hour = Column(Integer)
    verified = Column(Boolean, default=False)
    actual_temp = Column(Float)
    error = Column(Float)  # actual_temp - predicted_temp
    verified_at = Column(DateTime(timezone=True))
    precipitation = Column(Float, nullable=True)  # compat legacy / forecast
    weather_code = Column(Integer, nullable=True)  # compat legacy / forecast
    forecast_precipitation = Column(Float, nullable=True)
    forecast_weather_code = Column(Integer, nullable=True)
    forecast_cloud_cover = Column(Float, nullable=True)
    forecast_wind_speed = Column(Float, nullable=True)
    forecast_wind_direction = Column(Float, nullable=True)
    # Predittori pioggia ad alto valore forniti gratis da Open-Meteo (raccolti dal
    # cron per il modello ML, popolati a partire da luglio 2026).
    forecast_precipitation_probability = Column(Float, nullable=True)  # POP % (0-100)
    forecast_surface_pressure = Column(Float, nullable=True)  # hPa
    forecast_dew_point = Column(Float, nullable=True)  # dew point 2m in °C
    forecast_cape = Column(Float, nullable=True)  # CAPE J/kg (potenziale convettivo)
    actual_precipitation = Column(Float, nullable=True)
    actual_weather_code = Column(Integer, nullable=True)
    actual_cloud_cover = Column(Float, nullable=True)
    actual_wind_speed = Column(Float, nullable=True)
    actual_wind_direction = Column(Float, nullable=True)
    actual_source = Column(Text, nullable=True)
    actual_interval_minutes = Column(Integer, nullable=True)
    actual_station_id = Column(Text, nullable=True)
    actual_station_distance_km = Column(Float, nullable=True)
    # Snapshot immutabile del modello disponibile quando il forecast è emesso.
    # Permette metriche prequential senza ricalcolare oggi un modello sul passato.
    evaluation_model_store_id = Column(Integer, nullable=True)
    evaluation_model_variant = Column(Text, nullable=True)
    evaluation_corrected_temp = Column(Float, nullable=True)
    evaluation_rain_probability = Column(Float, nullable=True)
    evaluation_rain_threshold = Column(Float, nullable=True)
    evaluation_condition_code = Column(Integer, nullable=True)
    evaluation_rain_blend_weight = Column(Float, nullable=True)
    evaluation_generated_at = Column(DateTime(timezone=True), nullable=True)
    # Coppia shadow V1/V2 congelata allo stesso istante. Questi campi rendono il
    # gate di rollout realmente prequential: nessun modello corrente viene
    # ricalcolato retrospettivamente sulle righe già verificate.
    shadow_v1_rain_probability = Column(Float, nullable=True)
    shadow_v1_rain_threshold = Column(Float, nullable=True)
    shadow_v1_condition_code = Column(Integer, nullable=True)
    shadow_v2_rain_probability = Column(Float, nullable=True)
    shadow_v2_rain_threshold = Column(Float, nullable=True)
    shadow_v2_condition_code = Column(Integer, nullable=True)

    city = relationship("City", back_populates="predictions")


class MlModelStore(Base):
    """Modello scikit-learn serializzato (pickle)."""

    __tablename__ = "ml_model_store"

    id = Column(Integer, primary_key=True)
    trained_at = Column(DateTime(timezone=True), nullable=False)
    model_bytes = Column(LargeBinary)  # pickle del Pipeline scikit-learn
    mae = Column(Float)  # Mean Absolute Error sul validation set
    n_samples = Column(Integer)
    validation_state = Column(Text, nullable=True)


class MlTrainingState(Base):
    """Stato persistente dell'ultimo ciclo/training ML."""

    __tablename__ = "ml_training_state"

    id = Column(Integer, primary_key=True)
    last_cycle_started_at = Column(DateTime(timezone=True))
    last_cycle_completed_at = Column(DateTime(timezone=True))
    last_cycle_status = Column(Text)
    last_cycle_message = Column(Text)
    last_cycle_observations = Column(Integer)
    last_cycle_predictions = Column(Integer)
    last_cycle_verified = Column(Integer)
    last_cycle_avg_error = Column(Float)
    last_successful_train_at = Column(DateTime(timezone=True))
    verified_count_at_last_train = Column(Integer, nullable=False, default=0)
    last_model_store_id = Column(Integer)
    last_model_trained_at = Column(DateTime(timezone=True))


class Supporter(Base):
    """Supporter che ha completato almeno una donazione."""

    __tablename__ = "supporters"

    id = Column(Integer, primary_key=True)
    email_encrypted = Column(LargeBinary, nullable=False)
    email_lookup_hash = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    donation_count = Column(Integer, nullable=False, default=0)
    last_donation_at = Column(DateTime(timezone=True))
    last_amount_cents = Column(Integer)
    last_currency = Column(Text)
    stripe_customer_id = Column(Text)
    stripe_payment_intent_id = Column(Text)
    last_checkout_session_id = Column(Text)

    tokens = relationship("SupporterToken", back_populates="supporter", lazy="dynamic")


class SupporterToken(Base):
    """Token opaco per riconoscere nello stesso browser un supporter noto."""

    __tablename__ = "supporter_tokens"

    id = Column(Integer, primary_key=True)
    supporter_id = Column(Integer, ForeignKey("supporters.id"), nullable=False)
    token_hash = Column(Text, nullable=False, unique=True)
    user_agent_hash = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)

    supporter = relationship("Supporter", back_populates="tokens")


class PushSubscription(Base):
    """Sottoscrizione push Web (Web Push API) per notifiche meteo."""

    __tablename__ = "push_subscriptions"

    id = Column(BigInteger, primary_key=True, index=True)
    endpoint = Column(Text, nullable=False)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(255), nullable=False)
    city = Column(String(100), nullable=True)  # città preferita per alert
    rain_alerts_enabled = Column(Boolean, default=False, nullable=False)
    last_rain_alert_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TelegramSubscription(Base):
    """Sottoscrizione Telegram per notifiche meteo."""

    __tablename__ = "telegram_subscriptions"

    id = Column(BigInteger, primary_key=True, index=True)
    chat_id = Column(BigInteger, nullable=True, unique=True)  # Telegram chat ID (valorizzato dopo il linking)
    user_name = Column(String(100), nullable=True)  # username Telegram
    city = Column(String(100), nullable=True)  # città preferita per le notifiche
    city_lat = Column(Float, nullable=True)
    city_lon = Column(Float, nullable=True)
    city_region = Column(String(100), nullable=True)
    city_province = Column(String(100), nullable=True)
    linking_code = Column(String(10), nullable=True, index=True)  # codice OTP temporaneo
    client_token_hash = Column(String(64), nullable=True, unique=True, index=True)
    linking_code_expires_at = Column(DateTime(timezone=True), nullable=True)
    linked_at = Column(DateTime(timezone=True), nullable=True)  # quando il linking è stato completato
    rain_alerts_enabled = Column(Boolean, default=False, nullable=False)
    daily_forecast_enabled = Column(Boolean, default=False, nullable=False)
    daily_forecast_hour = Column(Integer, default=8, nullable=False)  # ora preferita (0-23)
    last_rain_alert_at = Column(DateTime(timezone=True), nullable=True)
    last_daily_forecast_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TelegramRainAlert(Base):
    """Avviso pioggia inviato, con dati sufficienti per deduplica e verifica."""

    __tablename__ = "telegram_rain_alerts"

    id = Column(BigInteger, primary_key=True)
    subscription_id = Column(BigInteger, ForeignKey("telegram_subscriptions.id"), nullable=False)
    city = Column(String(100), nullable=False)
    city_lat = Column(Float, nullable=False)
    city_lon = Column(Float, nullable=False)
    forecast_interval_start = Column(DateTime(timezone=True), nullable=False)
    forecast_interval_end = Column(DateTime(timezone=True), nullable=False)
    precipitation_probability = Column(Float)
    precipitation_mm = Column(Float)
    weather_code = Column(Integer)
    ml_probability = Column(Float)
    trigger_reason = Column(String(50))
    sent_at = Column(DateTime(timezone=True), nullable=False)
    verification_status = Column(String(20), nullable=False, default="pending")
    observed_precipitation_mm = Column(Float)
    verified_at = Column(DateTime(timezone=True))


# Indici per performance (compatibili sia SQLite che PostgreSQL)
Index("idx_obs_city_time", WeatherObservation.city_id, WeatherObservation.observed_at)
Index("idx_pred_city_time", MlPrediction.city_id, MlPrediction.predicted_at)
Index("idx_pred_target_time", MlPrediction.city_id, MlPrediction.target_time)
Index("idx_pred_verify_lookup", MlPrediction.city_id, MlPrediction.target_time, MlPrediction.verified)
Index("idx_pred_verified", MlPrediction.verified)
Index("idx_cities_name", City.name_lower)
Index("idx_cities_type", City.locality_type)
Index("idx_ml_training_state_last_train", MlTrainingState.last_successful_train_at)
Index("idx_supporters_email_lookup_hash", Supporter.email_lookup_hash)
Index("idx_supporter_tokens_supporter_id", SupporterToken.supporter_id)
Index("idx_supporter_tokens_token_hash", SupporterToken.token_hash)
Index("idx_push_subscriptions_endpoint", PushSubscription.endpoint)
Index("idx_telegram_subscriptions_chat_id", TelegramSubscription.chat_id)
Index("idx_telegram_subscriptions_linking_code", TelegramSubscription.linking_code)
Index("idx_telegram_subscriptions_client_token_hash", TelegramSubscription.client_token_hash)
Index("idx_telegram_rain_alert_subscription_sent", TelegramRainAlert.subscription_id, TelegramRainAlert.sent_at)
Index("idx_telegram_rain_alert_pending", TelegramRainAlert.verification_status, TelegramRainAlert.forecast_interval_end)


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

    backend_dir = Path(__file__).parent
    alembic_ini = backend_dir / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(backend_dir / "db_migrations"))
    config.set_main_option("prepend_sys_path", str(backend_dir))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(config, "head")
