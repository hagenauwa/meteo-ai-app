"""Add supporter donations tables.

Revision ID: 20260404_0003
Revises: 20260404_0002
Create Date: 2026-04-04 21:35:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260404_0003"
down_revision = "20260404_0002"
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

    if not _has_table(inspector, "supporters"):
        op.create_table(
            "supporters",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email_encrypted", sa.LargeBinary(), nullable=False),
            sa.Column("email_lookup_hash", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("donation_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_donation_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_amount_cents", sa.Integer(), nullable=True),
            sa.Column("last_currency", sa.Text(), nullable=True),
            sa.Column("stripe_customer_id", sa.Text(), nullable=True),
            sa.Column("stripe_payment_intent_id", sa.Text(), nullable=True),
            sa.Column("last_checkout_session_id", sa.Text(), nullable=True),
        )

    inspector = sa.inspect(bind)
    supporter_columns = {
        "email_encrypted": sa.Column("email_encrypted", sa.LargeBinary(), nullable=False),
        "email_lookup_hash": sa.Column("email_lookup_hash", sa.Text(), nullable=False),
        "created_at": sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        "donation_count": sa.Column("donation_count", sa.Integer(), nullable=False, server_default="0"),
        "last_donation_at": sa.Column("last_donation_at", sa.DateTime(timezone=True), nullable=True),
        "last_amount_cents": sa.Column("last_amount_cents", sa.Integer(), nullable=True),
        "last_currency": sa.Column("last_currency", sa.Text(), nullable=True),
        "stripe_customer_id": sa.Column("stripe_customer_id", sa.Text(), nullable=True),
        "stripe_payment_intent_id": sa.Column("stripe_payment_intent_id", sa.Text(), nullable=True),
        "last_checkout_session_id": sa.Column("last_checkout_session_id", sa.Text(), nullable=True),
    }
    for column_name, column in supporter_columns.items():
        if _has_table(inspector, "supporters") and not _has_column(inspector, "supporters", column_name):
            op.add_column("supporters", column)

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "supporter_tokens"):
        op.create_table(
            "supporter_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("supporter_id", sa.Integer(), sa.ForeignKey("supporters.id"), nullable=False),
            sa.Column("token_hash", sa.Text(), nullable=False),
            sa.Column("user_agent_hash", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        )

    inspector = sa.inspect(bind)
    token_columns = {
        "supporter_id": sa.Column("supporter_id", sa.Integer(), sa.ForeignKey("supporters.id"), nullable=False),
        "token_hash": sa.Column("token_hash", sa.Text(), nullable=False),
        "user_agent_hash": sa.Column("user_agent_hash", sa.Text(), nullable=True),
        "created_at": sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        "last_seen_at": sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    }
    for column_name, column in token_columns.items():
        if _has_table(inspector, "supporter_tokens") and not _has_column(inspector, "supporter_tokens", column_name):
            op.add_column("supporter_tokens", column)

    inspector = sa.inspect(bind)
    indexes = [
        ("supporters", "idx_supporters_email_lookup_hash", ["email_lookup_hash"]),
        ("supporter_tokens", "idx_supporter_tokens_supporter_id", ["supporter_id"]),
        ("supporter_tokens", "idx_supporter_tokens_token_hash", ["token_hash"]),
    ]
    for table_name, index_name, columns in indexes:
        if _has_table(inspector, table_name) and not _has_index(inspector, table_name, index_name):
            op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name, index_name in [
        ("supporter_tokens", "idx_supporter_tokens_token_hash"),
        ("supporter_tokens", "idx_supporter_tokens_supporter_id"),
        ("supporters", "idx_supporters_email_lookup_hash"),
    ]:
        if _has_table(inspector, table_name) and _has_index(inspector, table_name, index_name):
            op.drop_index(index_name, table_name=table_name)

    inspector = sa.inspect(bind)
    if _has_table(inspector, "supporter_tokens"):
        op.drop_table("supporter_tokens")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "supporters"):
        op.drop_table("supporters")
