"""Track observation provenance and accumulation interval.

Revision ID: 20260821_0001
Revises: 20260701_0001
Create Date: 2026-08-21 23:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0001"
down_revision = "20260701_0001"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    additions = {
        "weather_observations": (
            sa.Column("observation_source", sa.Text(), nullable=True),
            sa.Column("observation_interval_minutes", sa.Integer(), nullable=True),
        ),
        "ml_predictions": (
            sa.Column("actual_source", sa.Text(), nullable=True),
            sa.Column("actual_interval_minutes", sa.Integer(), nullable=True),
            sa.Column("evaluation_model_store_id", sa.Integer(), nullable=True),
            sa.Column("evaluation_model_variant", sa.Text(), nullable=True),
            sa.Column("evaluation_corrected_temp", sa.Float(), nullable=True),
            sa.Column("evaluation_rain_probability", sa.Float(), nullable=True),
            sa.Column("evaluation_rain_threshold", sa.Float(), nullable=True),
            sa.Column("evaluation_condition_code", sa.Integer(), nullable=True),
            sa.Column("evaluation_rain_blend_weight", sa.Float(), nullable=True),
            sa.Column("evaluation_generated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("shadow_v1_rain_probability", sa.Float(), nullable=True),
            sa.Column("shadow_v1_rain_threshold", sa.Float(), nullable=True),
            sa.Column("shadow_v1_condition_code", sa.Integer(), nullable=True),
            sa.Column("shadow_v2_rain_probability", sa.Float(), nullable=True),
            sa.Column("shadow_v2_rain_threshold", sa.Float(), nullable=True),
            sa.Column("shadow_v2_condition_code", sa.Integer(), nullable=True),
        ),
    }
    for table_name, columns in additions.items():
        if table_name not in inspector.get_table_names():
            continue
        for column in columns:
            if not _has_column(inspector, table_name, column.name):
                op.add_column(table_name, column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name, column_names in {
        "ml_predictions": (
            "shadow_v2_condition_code",
            "shadow_v2_rain_threshold",
            "shadow_v2_rain_probability",
            "shadow_v1_condition_code",
            "shadow_v1_rain_threshold",
            "shadow_v1_rain_probability",
            "evaluation_generated_at",
            "evaluation_rain_blend_weight",
            "evaluation_condition_code",
            "evaluation_rain_threshold",
            "evaluation_rain_probability",
            "evaluation_corrected_temp",
            "evaluation_model_variant",
            "evaluation_model_store_id",
            "actual_interval_minutes",
            "actual_source",
        ),
        "weather_observations": ("observation_interval_minutes", "observation_source"),
    }.items():
        if table_name not in inspector.get_table_names():
            continue
        for column_name in column_names:
            if _has_column(inspector, table_name, column_name):
                op.drop_column(table_name, column_name)
