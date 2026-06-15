"""Add stable client token hash and linking code expiry to telegram subscriptions.

Revision ID: 20260514_0001
Revises: 20260512_0007
Create Date: 2026-05-14 00:01:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260514_0001"
down_revision = "20260512_0007"
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
    chat_big_integer = sa.Integer() if bind.dialect.name == "sqlite" else sa.BigInteger()

    if not _has_table(inspector, "telegram_subscriptions"):
        op.create_table(
            "telegram_subscriptions",
            sa.Column("id", pk_integer, primary_key=True),
            sa.Column("chat_id", chat_big_integer, nullable=True, unique=True),
            sa.Column("user_name", sa.String(length=100), nullable=True),
            sa.Column("city", sa.String(length=100), nullable=True),
            sa.Column("linking_code", sa.String(length=10), nullable=True),
            sa.Column("client_token_hash", sa.String(length=64), nullable=True),
            sa.Column("linking_code_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rain_alerts_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("daily_forecast_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("daily_forecast_hour", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("last_rain_alert_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_daily_forecast_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    else:
        if not _has_column(inspector, "telegram_subscriptions", "client_token_hash"):
            op.add_column(
                "telegram_subscriptions",
                sa.Column("client_token_hash", sa.String(length=64), nullable=True),
            )
        if not _has_column(inspector, "telegram_subscriptions", "linking_code_expires_at"):
            op.add_column(
                "telegram_subscriptions",
                sa.Column("linking_code_expires_at", sa.DateTime(timezone=True), nullable=True),
            )

    inspector = sa.inspect(bind)
    indexes = [
        ("telegram_subscriptions", "idx_telegram_subscriptions_chat_id", ["chat_id"], False),
        ("telegram_subscriptions", "idx_telegram_subscriptions_linking_code", ["linking_code"], False),
        ("telegram_subscriptions", "idx_telegram_subscriptions_client_token_hash", ["client_token_hash"], True),
    ]
    for table_name, index_name, columns, unique in indexes:
        if _has_table(inspector, table_name) and not _has_index(inspector, table_name, index_name):
            op.create_index(index_name, table_name, columns, unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name, index_name in [
        ("telegram_subscriptions", "idx_telegram_subscriptions_client_token_hash"),
        ("telegram_subscriptions", "idx_telegram_subscriptions_linking_code"),
        ("telegram_subscriptions", "idx_telegram_subscriptions_chat_id"),
    ]:
        if _has_table(inspector, table_name) and _has_index(inspector, table_name, index_name):
            op.drop_index(index_name, table_name=table_name)

    inspector = sa.inspect(bind)
    for column_name in ["linking_code_expires_at", "client_token_hash"]:
        if _has_table(inspector, "telegram_subscriptions") and _has_column(
            inspector, "telegram_subscriptions", column_name
        ):
            op.drop_column("telegram_subscriptions", column_name)
