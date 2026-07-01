"""Add high-value rain forecast features to ml_predictions.

Raccoglie i predittori pioggia forniti gratis da Open-Meteo e finora scartati:
precipitation_probability (POP), surface_pressure, dew_point_2m, cape. Serviranno
al modello ML una volta accumulati abbastanza campioni verificati.

Revision ID: 20260701_0001
Revises: 20260514_0001
Create Date: 2026-07-01 22:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260701_0001"
down_revision = "20260514_0001"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    ml_prediction_columns = {
        "forecast_precipitation_probability": sa.Column(
            "forecast_precipitation_probability", sa.Float(), nullable=True
        ),
        "forecast_surface_pressure": sa.Column("forecast_surface_pressure", sa.Float(), nullable=True),
        "forecast_dew_point": sa.Column("forecast_dew_point", sa.Float(), nullable=True),
        "forecast_cape": sa.Column("forecast_cape", sa.Float(), nullable=True),
    }
    for column_name, column in ml_prediction_columns.items():
        if _has_table(inspector, "ml_predictions") and not _has_column(inspector, "ml_predictions", column_name):
            op.add_column("ml_predictions", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for column_name in [
        "forecast_cape",
        "forecast_dew_point",
        "forecast_surface_pressure",
        "forecast_precipitation_probability",
    ]:
        if _has_table(inspector, "ml_predictions") and _has_column(inspector, "ml_predictions", column_name):
            op.drop_column("ml_predictions", column_name)
