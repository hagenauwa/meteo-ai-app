"""Test per il sottosistema ML."""
from __future__ import annotations

from datetime import datetime, timezone

from database import City, MlPrediction


class TestCityResolution:
    def test_resolve_exact_match_wins_over_prefix(self, db_session):
        from routers.ml import _resolve_city_context

        db_session.add_all(
            [
                City(name="Roma", name_lower="roma", region="Lazio", province="Roma", lat=41.9, lon=12.5),
                City(
                    name="Romano di Lombardia",
                    name_lower="romano di lombardia",
                    region="Lombardia",
                    province="Bergamo",
                    lat=45.5,
                    lon=9.7,
                ),
            ]
        )
        db_session.commit()

        resolution = _resolve_city_context("Roma", db_session)
        assert resolution["resolved"] is True
        assert resolution["ambiguous"] is False
        assert resolution["city"] == "Roma"

    def test_resolve_ambiguous_when_no_exact_match(self, db_session):
        from routers.ml import _resolve_city_context

        db_session.add_all(
            [
                City(name="Romano", name_lower="romano", region="Veneto", province="Vicenza", lat=45.5, lon=11.3),
                City(
                    name="Romano di Lombardia",
                    name_lower="romano di lombardia",
                    region="Lombardia",
                    province="Bergamo",
                    lat=45.5,
                    lon=9.7,
                ),
            ]
        )
        db_session.commit()

        # "Roman" e' prefix per entrambe ma non exact match di nessuna.
        resolution = _resolve_city_context("Roman", db_session)
        assert resolution["resolved"] is False
        assert resolution["ambiguous"] is True

    def test_resolve_unknown_city(self, db_session):
        from routers.ml import _resolve_city_context

        resolution = _resolve_city_context("CittàInesistente123", db_session)
        assert resolution["resolved"] is False
        assert resolution["warning"]["code"] == "ML_CITY_UNRESOLVED"


class TestCoverage:
    def test_is_city_in_ml_coverage(self):
        from unittest.mock import patch

        import ml_model

        with patch.object(ml_model.settings, "ml_training_allowed_provinces", ("Massa-Carrara", "Firenze")):
            assert ml_model.is_city_in_ml_coverage("Massa-Carrara") is True
            assert ml_model.is_city_in_ml_coverage("massa-carrara") is True
            assert ml_model.is_city_in_ml_coverage("Milano") is False

    def test_is_city_in_ml_coverage_global_when_empty(self):
        from unittest.mock import patch

        import ml_model

        with patch.object(ml_model.settings, "ml_training_allowed_provinces", ()):
            assert ml_model.is_city_in_ml_coverage("Qualsiasi") is True


class TestPureFunctions:
    def test_lead_bucket_names(self):
        from ml_model import _lead_bucket_name

        assert _lead_bucket_name(0) == "short"
        assert _lead_bucket_name(6) == "short"
        assert _lead_bucket_name(7) == "intraday"
        assert _lead_bucket_name(24) == "intraday"
        assert _lead_bucket_name(25) == "day1"
        assert _lead_bucket_name(240) == "day8_plus"
        assert _lead_bucket_name(None) == "short"

    def test_condition_from_inputs(self):
        from ml_model import _condition_from_inputs

        assert _condition_from_inputs(weather_code=0, cloud_cover=10, precipitation=0) == "sereno"
        assert _condition_from_inputs(weather_code=2, cloud_cover=40, precipitation=0) == "parzialmente nuvoloso"
        assert _condition_from_inputs(weather_code=3, cloud_cover=80, precipitation=0) == "nuvoloso"
        assert _condition_from_inputs(weather_code=61, cloud_cover=50, precipitation=0) == "pioggia"
        assert _condition_from_inputs(weather_code=0, cloud_cover=10, precipitation=0.2) == "pioggia"

    def test_split_train_validation(self):
        import numpy as np

        from ml_model import _split_train_validation

        X = np.arange(100).reshape(-1, 1)
        y = np.arange(100)
        split = _split_train_validation(X, y)
        assert split is not None
        X_train, X_val, y_train, y_val = split
        assert len(X_train) == 80
        assert len(X_val) == 20


class TestDataPreparation:
    def test_prepare_training_rows_filters_by_province(self, db_session):
        from unittest.mock import patch

        from config import settings
        from ml_model import _prepare_training_rows

        city_in = City(
            name="Massa", name_lower="massa", region="Toscana", province="Massa-Carrara", lat=44.0, lon=10.1
        )
        city_out = City(
            name="Milano", name_lower="milano", region="Lombardia", province="Milano", lat=45.5, lon=9.2
        )
        db_session.add_all([city_in, city_out])
        db_session.flush()

        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        pred_in = MlPrediction(
            city_id=city_in.id,
            predicted_at=now,
            target_time=now,
            predicted_temp=20.0,
            forecast_temp=19.0,
            actual_temp=20.5,
            error=1.5,
            verified=True,
            verified_at=now,
        )
        pred_out = MlPrediction(
            city_id=city_out.id,
            predicted_at=now,
            target_time=now,
            predicted_temp=20.0,
            forecast_temp=19.0,
            actual_temp=20.5,
            error=1.5,
            verified=True,
            verified_at=now,
        )
        db_session.add_all([pred_in, pred_out])
        db_session.commit()

        with patch.object(settings, "ml_training_allowed_provinces", ("Massa-Carrara",)):
            rows = _prepare_training_rows(db_session)
            assert len(rows) == 1
            assert rows[0]["province"] == "Massa-Carrara"

    def test_verify_predictions(self, db_session):
        from scheduler import _db_verify_predictions

        city = City(name="Massa", name_lower="massa", region="Toscana", province="Massa-Carrara", lat=44.0, lon=10.1)
        db_session.add(city)
        db_session.flush()

        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        pred = MlPrediction(
            city_id=city.id,
            predicted_at=now,
            target_time=now,
            lead_hours=1,
            predicted_temp=18.0,
            forecast_temp=18.0,
            verified=False,
        )
        db_session.add(pred)
        db_session.commit()

        observations = [
            {
                "city_id": city.id,
                "observed_at": now,
                "temp": 20.0,
                "precipitation": 0.0,
            }
        ]
        verified, avg_error = _db_verify_predictions(observations)
        assert verified == 1
        db_session.refresh(pred)
        assert pred.verified is True
        assert pred.actual_temp == 20.0
        assert pred.error == 2.0


class TestServingFallbacks:
    def test_predict_correction_without_model(self):
        from ml_model import predict_correction

        result = predict_correction(
            temp=20.0,
            humidity=50.0,
            hour=12,
            month=6,
            lat=44.0,
            lon=10.0,
            region="Toscana",
            cloud_cover=30.0,
            lead_hours=0,
        )
        assert result["model_ready"] is False
        assert result["correction"] == 0.0
        assert result["corrected_temp"] == 20.0

    def test_predict_rain_without_model(self):
        from ml_model import predict_rain_probability

        result = predict_rain_probability(
            forecast_temp=20.0,
            humidity=50.0,
            hour=12,
            month=6,
            lat=44.0,
            lon=10.0,
            region="Toscana",
            cloud_cover=30.0,
            lead_hours=0,
        )
        assert result["model_ready"] is False
