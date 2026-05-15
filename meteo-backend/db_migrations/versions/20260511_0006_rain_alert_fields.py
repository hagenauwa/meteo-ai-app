"""Add rain alert fields to push_subscriptions.

Revision ID: 20260511_0006
Revises: 20260415_0005
Create Date: 2026-05-11 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260511_0006"
down_revision = "20260415_0005"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "push_subscriptions"):
        return

    if _has_column(inspector, "push_subscriptions", "rain_alerts_enabled"):
        return

    op.add_column(
        "push_subscriptions",
        sa.Column("rain_alerts_enabled", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "push_subscriptions",
        sa.Column("last_rain_alert_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "push_subscriptions"):
        return

    if _has_column(inspector, "push_subscriptions", "last_rain_alert_at"):
        op.drop_column("push_subscriptions", "last_rain_alert_at")

    if _has_column(inspector, "push_subscriptions", "rain_alerts_enabled"):
        op.drop_column("push_subscriptions", "rain_alerts_enabled")
