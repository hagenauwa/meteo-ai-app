"""Add persistent ML training state table.

Revision ID: 20260415_0005
Revises: 20260409_0004
Create Date: 2026-04-15 22:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260415_0005"
down_revision = "20260409_0004"
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

    if not _has_table(inspector, "ml_training_state"):
        op.create_table(
            "ml_training_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("last_cycle_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_cycle_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_cycle_status", sa.Text(), nullable=True),
            sa.Column("last_cycle_message", sa.Text(), nullable=True),
            sa.Column("last_cycle_observations", sa.Integer(), nullable=True),
            sa.Column("last_cycle_predictions", sa.Integer(), nullable=True),
            sa.Column("last_cycle_verified", sa.Integer(), nullable=True),
            sa.Column("last_cycle_avg_error", sa.Float(), nullable=True),
            sa.Column("last_successful_train_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_count_at_last_train", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_model_store_id", sa.Integer(), nullable=True),
            sa.Column("last_model_trained_at", sa.DateTime(timezone=True), nullable=True),
        )

    inspector = sa.inspect(bind)
    columns = {
        "last_cycle_started_at": sa.Column("last_cycle_started_at", sa.DateTime(timezone=True), nullable=True),
        "last_cycle_completed_at": sa.Column("last_cycle_completed_at", sa.DateTime(timezone=True), nullable=True),
        "last_cycle_status": sa.Column("last_cycle_status", sa.Text(), nullable=True),
        "last_cycle_message": sa.Column("last_cycle_message", sa.Text(), nullable=True),
        "last_cycle_observations": sa.Column("last_cycle_observations", sa.Integer(), nullable=True),
        "last_cycle_predictions": sa.Column("last_cycle_predictions", sa.Integer(), nullable=True),
        "last_cycle_verified": sa.Column("last_cycle_verified", sa.Integer(), nullable=True),
        "last_cycle_avg_error": sa.Column("last_cycle_avg_error", sa.Float(), nullable=True),
        "last_successful_train_at": sa.Column("last_successful_train_at", sa.DateTime(timezone=True), nullable=True),
        "verified_count_at_last_train": sa.Column("verified_count_at_last_train", sa.Integer(), nullable=False, server_default="0"),
        "last_model_store_id": sa.Column("last_model_store_id", sa.Integer(), nullable=True),
        "last_model_trained_at": sa.Column("last_model_trained_at", sa.DateTime(timezone=True), nullable=True),
    }
    for column_name, column in columns.items():
        if _has_table(inspector, "ml_training_state") and not _has_column(inspector, "ml_training_state", column_name):
            op.add_column("ml_training_state", column)

    inspector = sa.inspect(bind)
    if _has_table(inspector, "ml_training_state") and not _has_index(inspector, "ml_training_state", "idx_ml_training_state_last_train"):
        op.create_index(
            "idx_ml_training_state_last_train",
            "ml_training_state",
            ["last_successful_train_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "ml_training_state") and _has_index(inspector, "ml_training_state", "idx_ml_training_state_last_train"):
        op.drop_index("idx_ml_training_state_last_train", table_name="ml_training_state")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "ml_training_state"):
        op.drop_table("ml_training_state")
