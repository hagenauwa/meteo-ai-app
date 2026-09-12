"""Preserve station provenance and validation state without rewriting history."""

from alembic import op
import sqlalchemy as sa

revision = "20260912_0001"
down_revision = "20260822_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("weather_observations", sa.Column("station_id", sa.Text(), nullable=True))
    op.add_column("weather_observations", sa.Column("station_distance_km", sa.Float(), nullable=True))
    op.add_column("ml_predictions", sa.Column("actual_station_id", sa.Text(), nullable=True))
    op.add_column("ml_predictions", sa.Column("actual_station_distance_km", sa.Float(), nullable=True))
    op.add_column("ml_model_store", sa.Column("validation_state", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("ml_model_store", "validation_state")
    op.drop_column("ml_predictions", "actual_station_distance_km")
    op.drop_column("ml_predictions", "actual_station_id")
    op.drop_column("weather_observations", "station_distance_km")
    op.drop_column("weather_observations", "station_id")
