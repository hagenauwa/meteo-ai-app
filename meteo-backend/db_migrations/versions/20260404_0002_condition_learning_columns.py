"""Add wind features for condition-learning models.

Revision ID: 20260404_0002
Revises: 20260404_0001
Create Date: 2026-04-04 19:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260404_0002"
down_revision = "20260404_0001"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    weather_observation_columns = {
        "wind_direction": sa.Column("wind_direction", sa.Float(), nullable=True),
    }
    for column_name, column in weather_observation_columns.items():
        if _has_table(inspector, "weather_observations") and not _has_column(inspector, "weather_observations", column_name):
            op.add_column("weather_observations", column)

    inspector = sa.inspect(bind)
    ml_prediction_columns = {
        "forecast_wind_speed": sa.Column("forecast_wind_speed", sa.Float(), nullable=True),
        "forecast_wind_direction": sa.Column("forecast_wind_direction", sa.Float(), nullable=True),
        "actual_wind_speed": sa.Column("actual_wind_speed", sa.Float(), nullable=True),
        "actual_wind_direction": sa.Column("actual_wind_direction", sa.Float(), nullable=True),
    }
    for column_name, column in ml_prediction_columns.items():
        if _has_table(inspector, "ml_predictions") and not _has_column(inspector, "ml_predictions", column_name):
            op.add_column("ml_predictions", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for column_name in [
        "actual_wind_direction",
        "actual_wind_speed",
        "forecast_wind_direction",
        "forecast_wind_speed",
    ]:
        if _has_table(inspector, "ml_predictions") and _has_column(inspector, "ml_predictions", column_name):
            op.drop_column("ml_predictions", column_name)

    inspector = sa.inspect(bind)
    if _has_table(inspector, "weather_observations") and _has_column(inspector, "weather_observations", "wind_direction"):
        op.drop_column("weather_observations", "wind_direction")
