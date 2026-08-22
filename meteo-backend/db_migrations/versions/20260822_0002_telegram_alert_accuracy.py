"""Persist Telegram locations and rain-alert verification data.

Revision ID: 20260822_0002
Revises: 20260821_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_0002"
down_revision = "20260821_0001"
branch_labels = None
depends_on = None


def upgrade():
    big_integer = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.add_column("telegram_subscriptions", sa.Column("city_lat", sa.Float(), nullable=True))
    op.add_column("telegram_subscriptions", sa.Column("city_lon", sa.Float(), nullable=True))
    op.add_column("telegram_subscriptions", sa.Column("city_region", sa.String(length=100), nullable=True))
    op.add_column("telegram_subscriptions", sa.Column("city_province", sa.String(length=100), nullable=True))

    op.create_table(
        "telegram_rain_alerts",
        sa.Column("id", big_integer, primary_key=True),
        sa.Column(
            "subscription_id",
            big_integer,
            sa.ForeignKey("telegram_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("city_lat", sa.Float(), nullable=False),
        sa.Column("city_lon", sa.Float(), nullable=False),
        sa.Column("forecast_interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("precipitation_probability", sa.Float(), nullable=True),
        sa.Column("precipitation_mm", sa.Float(), nullable=True),
        sa.Column("weather_code", sa.Integer(), nullable=True),
        sa.Column("ml_probability", sa.Float(), nullable=True),
        sa.Column("trigger_reason", sa.String(length=50), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("observed_precipitation_mm", sa.Float(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_telegram_rain_alert_subscription_sent",
        "telegram_rain_alerts",
        ["subscription_id", "sent_at"],
    )
    op.create_index(
        "idx_telegram_rain_alert_pending",
        "telegram_rain_alerts",
        ["verification_status", "forecast_interval_end"],
    )


def downgrade():
    op.drop_index("idx_telegram_rain_alert_pending", table_name="telegram_rain_alerts")
    op.drop_index("idx_telegram_rain_alert_subscription_sent", table_name="telegram_rain_alerts")
    op.drop_table("telegram_rain_alerts")
    op.drop_column("telegram_subscriptions", "city_province")
    op.drop_column("telegram_subscriptions", "city_region")
    op.drop_column("telegram_subscriptions", "city_lon")
    op.drop_column("telegram_subscriptions", "city_lat")
