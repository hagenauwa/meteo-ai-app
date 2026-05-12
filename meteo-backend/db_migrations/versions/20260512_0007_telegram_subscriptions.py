"""Add telegram_subscriptions table.

Revision ID: 20260512_0007
Revises: 20260511_0006
Create Date: 2026-05-12 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260512_0007"
down_revision = "20260511_0006"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "telegram_subscriptions"):
        return

    op.create_table(
        "telegram_subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("user_name", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("linking_code", sa.String(10), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rain_alerts_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("daily_forecast_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("daily_forecast_hour", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("last_rain_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_daily_forecast_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_telegram_subscriptions_chat_id", "telegram_subscriptions", ["chat_id"])
    op.create_index("idx_telegram_subscriptions_linking_code", "telegram_subscriptions", ["linking_code"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "telegram_subscriptions"):
        return

    op.drop_index("idx_telegram_subscriptions_linking_code", table_name="telegram_subscriptions")
    op.drop_index("idx_telegram_subscriptions_chat_id", table_name="telegram_subscriptions")
    op.drop_table("telegram_subscriptions")
