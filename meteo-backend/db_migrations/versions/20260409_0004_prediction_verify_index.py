"""Add composite index for prediction verification lookups.

Revision ID: 20260409_0004
Revises: 20260404_0003
Create Date: 2026-04-09 11:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260409_0004"
down_revision = "20260404_0003"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "ml_predictions") and not _has_index(
        inspector, "ml_predictions", "idx_pred_verify_lookup"
    ):
        op.create_index(
            "idx_pred_verify_lookup",
            "ml_predictions",
            ["city_id", "target_time", "verified"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "ml_predictions") and _has_index(inspector, "ml_predictions", "idx_pred_verify_lookup"):
        op.drop_index("idx_pred_verify_lookup", table_name="ml_predictions")
