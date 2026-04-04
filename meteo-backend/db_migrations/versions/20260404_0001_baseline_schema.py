"""Baseline schema with target-based ML predictions.

Revision ID: 20260404_0001
Revises:
Create Date: 2026-04-04 16:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260404_0001"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    pk_integer = sa.Integer() if bind.dialect.name == "sqlite" else sa.BigInteger()

    if not _has_table(inspector, "cities"):
        op.create_table(
            "cities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("name_lower", sa.Text(), nullable=False),
            sa.Column("region", sa.Text(), nullable=True),
            sa.Column("province", sa.Text(), nullable=True),
            sa.Column("lat", sa.Float(), nullable=False),
            sa.Column("lon", sa.Float(), nullable=False),
            sa.Column("population", sa.Integer(), nullable=True),
            sa.Column("locality_type", sa.Text(), nullable=True, server_default="comune"),
        )

    if not _has_table(inspector, "weather_observations"):
        op.create_table(
            "weather_observations",
            sa.Column("id", pk_integer, primary_key=True),
            sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id"), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("temp", sa.Float(), nullable=False),
            sa.Column("humidity", sa.Float(), nullable=True),
            sa.Column("cloud_cover", sa.Float(), nullable=True),
            sa.Column("wind_speed", sa.Float(), nullable=True),
            sa.Column("precipitation", sa.Float(), nullable=True),
        )

    if not _has_table(inspector, "ml_predictions"):
        op.create_table(
            "ml_predictions",
            sa.Column("id", pk_integer, primary_key=True),
            sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id"), nullable=False),
            sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("target_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lead_hours", sa.Integer(), nullable=True),
            sa.Column("forecast_source", sa.Text(), nullable=True, server_default="open-meteo"),
            sa.Column("predicted_temp", sa.Float(), nullable=False),
            sa.Column("forecast_temp", sa.Float(), nullable=True),
            sa.Column("humidity", sa.Float(), nullable=True),
            sa.Column("hour", sa.Integer(), nullable=True),
            sa.Column("verified", sa.Boolean(), nullable=True),
            sa.Column("actual_temp", sa.Float(), nullable=True),
            sa.Column("error", sa.Float(), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("precipitation", sa.Float(), nullable=True),
            sa.Column("weather_code", sa.Integer(), nullable=True),
            sa.Column("forecast_precipitation", sa.Float(), nullable=True),
            sa.Column("forecast_weather_code", sa.Integer(), nullable=True),
            sa.Column("forecast_cloud_cover", sa.Float(), nullable=True),
            sa.Column("actual_precipitation", sa.Float(), nullable=True),
            sa.Column("actual_weather_code", sa.Integer(), nullable=True),
            sa.Column("actual_cloud_cover", sa.Float(), nullable=True),
        )

    if not _has_table(inspector, "ml_model_store"):
        op.create_table(
            "ml_model_store",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("model_bytes", sa.LargeBinary(), nullable=True),
            sa.Column("mae", sa.Float(), nullable=True),
            sa.Column("n_samples", sa.Integer(), nullable=True),
        )

    inspector = sa.inspect(bind)
    ml_prediction_columns = {
        "target_time": sa.Column("target_time", sa.DateTime(timezone=True), nullable=True),
        "lead_hours": sa.Column("lead_hours", sa.Integer(), nullable=True),
        "forecast_source": sa.Column("forecast_source", sa.Text(), nullable=True, server_default="open-meteo"),
        "forecast_temp": sa.Column("forecast_temp", sa.Float(), nullable=True),
        "forecast_precipitation": sa.Column("forecast_precipitation", sa.Float(), nullable=True),
        "forecast_weather_code": sa.Column("forecast_weather_code", sa.Integer(), nullable=True),
        "forecast_cloud_cover": sa.Column("forecast_cloud_cover", sa.Float(), nullable=True),
        "actual_precipitation": sa.Column("actual_precipitation", sa.Float(), nullable=True),
        "actual_weather_code": sa.Column("actual_weather_code", sa.Integer(), nullable=True),
        "actual_cloud_cover": sa.Column("actual_cloud_cover", sa.Float(), nullable=True),
        "precipitation": sa.Column("precipitation", sa.Float(), nullable=True),
        "weather_code": sa.Column("weather_code", sa.Integer(), nullable=True),
    }
    for column_name, column in ml_prediction_columns.items():
        if not _has_column(inspector, "ml_predictions", column_name):
            op.add_column("ml_predictions", column)

    if not _has_column(inspector, "cities", "locality_type"):
        op.add_column("cities", sa.Column("locality_type", sa.Text(), nullable=True, server_default="comune"))

    inspector = sa.inspect(bind)
    indexes = [
        ("weather_observations", "idx_obs_city_time", ["city_id", "observed_at"]),
        ("ml_predictions", "idx_pred_city_time", ["city_id", "predicted_at"]),
        ("ml_predictions", "idx_pred_target_time", ["city_id", "target_time"]),
        ("ml_predictions", "idx_pred_verified", ["verified"]),
        ("cities", "idx_cities_name", ["name_lower"]),
        ("cities", "idx_cities_type", ["locality_type"]),
    ]
    for table_name, index_name, columns in indexes:
        if _has_table(inspector, table_name) and not _has_index(inspector, table_name, index_name):
            op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name, index_name in [
        ("cities", "idx_cities_type"),
        ("cities", "idx_cities_name"),
        ("ml_predictions", "idx_pred_verified"),
        ("ml_predictions", "idx_pred_target_time"),
        ("ml_predictions", "idx_pred_city_time"),
        ("weather_observations", "idx_obs_city_time"),
    ]:
        if _has_table(inspector, table_name) and _has_index(inspector, table_name, index_name):
            op.drop_index(index_name, table_name=table_name)

    for table_name in ["ml_model_store", "ml_predictions", "weather_observations", "cities"]:
        inspector = sa.inspect(bind)
        if _has_table(inspector, table_name):
            op.drop_table(table_name)
