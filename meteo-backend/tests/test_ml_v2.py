"""Unit test mirati per ML v2 (feature engineering, calibrazione, horizon blending)."""

import importlib
import pickle
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ml_model = importlib.import_module("ml_model")


class _FakeModelQuery:
    def __init__(self, records):
        if isinstance(records, list):
            self.records = records
        else:
            self.records = [records] if records else []

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return self.records

    def first(self):
        return self.records[0] if self.records else None


class _FakeModelSession:
    def __init__(self, records):
        self.records = records

    def query(self, *args, **kwargs):
        return _FakeModelQuery(self.records)

    def close(self):
        return None


class _PickleablePipeline:
    n_features_in_ = 6

    def predict(self, features):
        return np.array([0.5])


def test_rain_feature_vector_v2_shape_and_missing_flags():
    features = ml_model._build_rain_features_v2(
        forecast_temp=18.0,
        humidity=None,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=None,
        lead_hours=3,
        forecast_precipitation=None,
        forecast_wind_speed=None,
        forecast_wind_direction=180.0,
        forecast_weather_code=None,
    )

    assert features.shape == (1, 34)
    assert features[0, -9:].tolist() == [1.0] * 9


def test_temperature_feature_vector_v2_includes_lead_bucket_flags():
    features = ml_model._build_temperature_features_v2(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert features.shape == (1, 26)
    assert features[0, 15:21].tolist() == [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def test_predict_correction_supports_legacy_temperature_models(monkeypatch):
    class FakePipeline:
        def __init__(self):
            self.last_shape = None
            self.n_features_in_ = 6

        def predict(self, features):
            self.last_shape = features.shape
            return np.array([1.2])

    fake_pipeline = FakePipeline()
    monkeypatch.setattr(ml_model, "_pipeline", fake_pipeline)
    monkeypatch.setattr(ml_model, "_temperature_feature_variant", "v1")

    result = ml_model.predict_correction(
        temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert fake_pipeline.last_shape == (1, 6)
    assert result["model_ready"] is True
    assert result["model_variant"] == "legacy"
    assert result["corrected_temp"] == 19.2


def test_predict_correction_disables_saturated_legacy_models(monkeypatch):
    class FakePipeline:
        n_features_in_ = 6

        def predict(self, features):
            return np.array([9.0])

    monkeypatch.setattr(ml_model, "_pipeline", FakePipeline())
    monkeypatch.setattr(ml_model, "_temperature_feature_variant", "v1")
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", None)

    result = ml_model.predict_correction(
        temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert result["model_ready"] is False
    assert result["model_variant"] == "provider"


def test_predict_rain_probability_supports_legacy_models(monkeypatch):
    class FakePipeline:
        def __init__(self):
            self.last_shape = None
            self.n_features_in_ = 6

        def predict_proba(self, features):
            self.last_shape = features.shape
            return np.array([[0.8, 0.2]])

    fake_pipeline = FakePipeline()
    monkeypatch.setattr(ml_model, "_rain_pipeline", fake_pipeline)
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", None)

    result = ml_model.predict_rain_probability(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert fake_pipeline.last_shape == (1, 6)
    assert result["model_ready"] is True
    assert result["model_variant"] == "legacy"
    assert result["rain_probability"] == 0.2


def test_predict_rain_probability_applies_v1_platt_calibration(monkeypatch):
    """Il ramo v1 deve servire la probabilità CALIBRATA (Platt), non quella grezza."""

    class FakePipeline:
        n_features_in_ = 6

        def predict_proba(self, features):
            # Probabilità grezza gonfiata dal class_weight='balanced'
            return np.array([[0.1, 0.9]])

    platt = {"coef": 0.5, "intercept": -1.0}
    monkeypatch.setattr(ml_model, "_rain_pipeline", FakePipeline())
    monkeypatch.setattr(ml_model, "_rain_pipeline_v2", None)
    monkeypatch.setattr(ml_model, "_rain_platt_v1", platt)
    monkeypatch.setattr(ml_model, "_ensure_latest_model_loaded", lambda **kwargs: None)

    result = ml_model.predict_rain_probability(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        lead_hours=6,
        forecast_precipitation=0.4,
        forecast_weather_code=61,
    )

    expected = round(float(ml_model._apply_platt(0.9, platt)), 3)
    assert result["model_ready"] is True
    assert result["rain_probability"] == expected
    # La calibrazione deve ridurre la probabilità gonfiata (de-inflazione)
    assert result["rain_probability"] < 0.9


def test_optimal_f1_threshold_identifies_positives_for_rare_event():
    # Probabilità calibrate basse (evento raro): a 0.5 non si predice mai pioggia.
    probs = np.array([0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4])
    y = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    threshold, f1 = ml_model._optimal_f1_threshold(probs, y)
    # A 0.5 nessun positivo verrebbe predetto (tutte le prob <= 0.4): la soglia
    # ottimale deve essere più bassa e dare F1 > 0.
    assert 0.0 < threshold <= 0.4
    assert f1 > 0.0


def test_prequential_shadow_kpis_use_only_frozen_pair():
    rows = []
    for index in range(240):
        wet = index % 2 == 0
        rows.append(
            {
                "actual_precipitation": 1.0 if wet else 0.0,
                "actual_weather_code": 61 if wet else 0,
                "actual_cloud_cover": 90.0 if wet else 5.0,
                "shadow_v1_rain_probability": 0.2 if wet else 0.8,
                "shadow_v1_rain_threshold": 0.5,
                "shadow_v2_rain_probability": 0.9 if wet else 0.1,
                "shadow_v2_rain_threshold": 0.5,
                "shadow_v1_condition_code": ml_model.CONDITION_TO_CODE["sereno" if wet else "pioggia"],
                "shadow_v2_condition_code": ml_model.CONDITION_TO_CODE["pioggia" if wet else "sereno"],
            }
        )

    v1, v2 = ml_model._compute_prequential_shadow_kpis(rows)

    assert v1["rain_samples"] == v2["rain_samples"] == 240
    assert v2["rain_brier"] < v1["rain_brier"]
    assert v2["rain_f1"] > v1["rain_f1"]
    assert v2["condition_macro_f1"] > v1["condition_macro_f1"]


def _synthetic_rain_rows(n=240, seed=0):
    """Righe verificate sintetiche con una regola di pioggia NON-lineare.

    La pioggia dipende da un'interazione (umidità alta E nuvole alte) combinata in
    XOR con un weather_code piovoso: un modello lineare non la separa, un gradient
    boosting sì. Serve per esercitare il training della pipeline pioggia end-to-end.
    """
    rng = np.random.default_rng(seed)
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        humidity = float(rng.uniform(30, 100))
        cloud = float(rng.uniform(0, 100))
        wcode = int(rng.choice([0, 1, 2, 3, 61, 80]))
        wet_core = humidity > 75 and cloud > 65
        code_wet = wcode in (61, 80)
        prob = 0.9 if (wet_core ^ code_wet) else 0.06
        actual = float(rng.uniform(0.3, 5.0)) if rng.random() < prob else 0.0
        rows.append(
            {
                "target_time": base + timedelta(hours=i),
                "verified_at": base + timedelta(hours=i),
                "forecast_temp": float(rng.uniform(5, 30)),
                "humidity": humidity,
                "hour": i % 24,
                "month": 6,
                "lat": 43.9,
                "lon": 10.2,
                "cloud_cover": cloud,
                "lead_hours": int(rng.choice([1, 3, 6, 14, 38])),
                "region": "Toscana",
                "province": "Massa-Carrara",
                "forecast_precipitation": float(max(0.0, rng.normal(0.2, 0.5))),
                "forecast_weather_code": wcode,
                "forecast_wind_speed": float(rng.uniform(0, 30)),
                "forecast_wind_direction": float(rng.uniform(0, 360)),
                "actual_precipitation": actual,
                "actual_weather_code": wcode,
                "actual_cloud_cover": cloud,
                "actual_wind_speed": None,
                "actual_wind_direction": None,
            }
        )
    return rows


def test_rain_pipeline_v2_uses_gradient_boosting_and_beats_baseline():
    """Il modello pioggia v2 deve essere un gradient boosting che batte il baseline.

    Blocca il contratto della migrazione da LogisticRegression a
    HistGradientBoostingClassifier: su un pattern non-lineare deve promuovere e
    calibrare meglio del predittore a probabilità costante.
    """
    rows = _synthetic_rain_rows()
    encoder = ml_model._encode_regions(rows)

    result = ml_model._train_rain_pipeline_v2(rows, encoder)

    assert result["success"] is True, result.get("message")
    clf = result["pipeline"].named_steps["clf"]
    assert isinstance(clf, HistGradientBoostingClassifier)
    assert result["brier"] < result["baseline_brier"]
    assert result["f1"] > 0.5
    # La pipeline addestrata deve restare servibile via predict_proba.
    proba = result["pipeline"].predict_proba(np.zeros((1, 34)))
    assert proba.shape == (1, 2)


def test_split_train_cal_test_is_disjoint_ordered_and_holds_out_test():
    """Fondamento della valutazione onesta: train/cal/test contigui e disgiunti.

    Se cal e test si sovrapponessero, il gate misurerebbe l'F1 sugli stessi dati
    usati per scegliere la soglia (auto-promozione ottimistica). Il test deve
    restare ~20% in coda, come il vecchio validation.
    """
    X = np.arange(100).reshape(-1, 1)
    y = np.arange(100) % 2
    split = ml_model._split_train_cal_test(X, y)
    assert split is not None
    X_train, X_cal, X_test, _, _, _ = split

    assert (len(X_train), len(X_cal), len(X_test)) == (65, 15, 20)
    # Contigue, ordinate temporalmente e senza sovrapposizioni.
    reconstructed = np.concatenate([X_train, X_cal, X_test]).ravel().tolist()
    assert reconstructed == list(range(100))
    # Sotto la soglia minima non si può valutare onestamente.
    assert ml_model._split_train_cal_test(np.arange(10).reshape(-1, 1), np.zeros(10)) is None


def test_provider_rain_probability_proxy_prefers_real_pop():
    """Con la POP reale di Open-Meteo (Fase 1) il proxy la usa (POP/100), non l'euristica."""
    real_pop_row = {
        "forecast_precipitation_probability": 90,
        "forecast_precipitation": 0.0,
        "forecast_weather_code": 0,
        "cloud_cover": 10.0,
    }
    heuristic_row = {
        "forecast_precipitation_probability": None,
        "forecast_precipitation": 0.0,
        "forecast_weather_code": 0,
        "cloud_cover": 10.0,
    }

    # POP reale -> 0.9, ignorando l'euristica "cielo sereno".
    assert abs(ml_model._provider_rain_probability_proxy(real_pop_row) - 0.9) < 1e-6
    # Senza POP ricade sull'euristica (sereno, nessuna pioggia prevista) -> bassa.
    assert ml_model._provider_rain_probability_proxy(heuristic_row) < 0.2


def test_is_city_in_ml_coverage_respects_allowed_provinces(monkeypatch):
    monkeypatch.setattr(
        ml_model,
        "settings",
        SimpleNamespace(ml_training_allowed_provinces=("Massa-Carrara", "Lucca")),
    )
    assert ml_model.is_city_in_ml_coverage("Massa-Carrara") is True
    assert ml_model.is_city_in_ml_coverage("Lucca") is True
    assert ml_model.is_city_in_ml_coverage("Milano") is False
    assert ml_model.is_city_in_ml_coverage(None) is False


def test_is_city_in_ml_coverage_global_when_unconfigured(monkeypatch):
    monkeypatch.setattr(
        ml_model,
        "settings",
        SimpleNamespace(ml_training_allowed_provinces=()),
    )
    assert ml_model.is_city_in_ml_coverage("Milano") is True


def test_predict_rain_probability_uses_v2_when_v1_is_not_available(monkeypatch):
    class FakeRainV2Pipeline:
        def predict_proba(self, features):
            assert features.shape == (1, 34)
            return np.array([[0.3, 0.7]])

    monkeypatch.setattr(ml_model, "_rain_pipeline", None)
    monkeypatch.setattr(ml_model, "_rain_pipeline_v2", FakeRainV2Pipeline())
    monkeypatch.setattr(ml_model, "_rain_platt_v2", None)
    monkeypatch.setattr(ml_model, "_ensure_latest_model_loaded", lambda **kwargs: None)

    result = ml_model.predict_rain_probability(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
        force_variant="v2",
    )

    assert result["model_ready"] is True
    assert result["model_variant"] == "v2"
    assert result["rain_probability"] == 0.7


def test_predict_rain_probability_keeps_v1_when_only_condition_v2_was_promoted(monkeypatch):
    class FakeRainV1Pipeline:
        n_features_in_ = 6

        def predict_proba(self, features):
            return np.array([[0.8, 0.2]])

    monkeypatch.setattr(ml_model, "_rain_pipeline", FakeRainV1Pipeline())
    monkeypatch.setattr(ml_model, "_rain_pipeline_v2", None)
    monkeypatch.setattr(ml_model, "_rain_platt_v1", None)
    monkeypatch.setattr(ml_model, "_ensure_latest_model_loaded", lambda **kwargs: None)

    result = ml_model.predict_rain_probability(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        lead_hours=72,
        force_variant="v2",
    )

    assert result["model_ready"] is True
    assert result["model_variant"] == "legacy"
    assert result["rain_probability"] == 0.2


def test_predict_rain_probability_v2_uses_optimal_threshold(monkeypatch):
    """La soglia v2 ottimizzata (non 0.5 fissa) deve guidare will_rain ed essere
    esposta in response. Copre il fix dell'asimmetria v1/v2."""

    class FakeRainV2Pipeline:
        def predict_proba(self, features):
            return np.array([[0.3, 0.7]])

    monkeypatch.setattr(ml_model, "_rain_pipeline", None)
    monkeypatch.setattr(ml_model, "_rain_pipeline_v2", FakeRainV2Pipeline())
    monkeypatch.setattr(ml_model, "_rain_platt_v2", None)
    monkeypatch.setattr(ml_model, "_rain_threshold_v2", 0.35)
    monkeypatch.setattr(ml_model, "_ensure_latest_model_loaded", lambda **kwargs: None)

    result = ml_model.predict_rain_probability(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
        force_variant="v2",
    )

    assert result["model_ready"] is True
    assert result["model_variant"] == "v2"
    assert result["rain_probability"] == 0.7
    assert result["rain_threshold"] == 0.35
    # 0.7 >= 0.35 -> will_rain True (con 0.5 fissa sarebbe comunque True, ma la
    # soglia esposta deve essere quella calibrata)
    assert result["will_rain"] is True


def test_predict_rain_probability_v2_falls_back_to_0_5_when_threshold_missing(monkeypatch):
    """Modelli legacy senza rain_threshold_v2 -> fallback 0.5 (backward-compat)."""

    class FakeRainV2Pipeline:
        def predict_proba(self, features):
            return np.array([[0.6, 0.4]])

    monkeypatch.setattr(ml_model, "_rain_pipeline", None)
    monkeypatch.setattr(ml_model, "_rain_pipeline_v2", FakeRainV2Pipeline())
    monkeypatch.setattr(ml_model, "_rain_platt_v2", None)
    monkeypatch.setattr(ml_model, "_rain_threshold_v2", None)
    monkeypatch.setattr(ml_model, "_ensure_latest_model_loaded", lambda **kwargs: None)

    result = ml_model.predict_rain_probability(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        force_variant="v2",
    )

    assert result["model_ready"] is True
    assert result["rain_threshold"] == 0.5
    # prob 0.4 < 0.5 -> will_rain False
    assert result["will_rain"] is False


def test_predict_condition_outlook_supports_legacy_models(monkeypatch):
    class FakePipeline:
        def __init__(self):
            self.last_shape = None
            self.n_features_in_ = 11

        def predict_proba(self, features):
            self.last_shape = features.shape
            return np.array([[0.1, 0.7, 0.1, 0.1]])

        def predict(self, features):
            return np.array([1])

    fake_pipeline = FakePipeline()
    monkeypatch.setattr(ml_model, "_condition_pipeline", fake_pipeline)
    monkeypatch.setattr(ml_model, "_loaded_model_store_id", None)

    result = ml_model.predict_condition_outlook(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
    )

    assert fake_pipeline.last_shape == (1, 11)
    assert result["model_ready"] is True
    assert result["model_variant"] == "legacy"
    assert result["expected_condition"] == "parzialmente nuvoloso"


def test_predict_condition_outlook_uses_v2_when_v1_is_not_available(monkeypatch):
    class FakeConditionV2Pipeline:
        def predict_proba(self, features):
            assert features.shape == (1, 27)
            return np.array([[0.1, 0.1, 0.1, 0.7]])

    monkeypatch.setattr(ml_model, "_condition_pipeline", None)
    monkeypatch.setattr(ml_model, "_condition_pipeline_v2", FakeConditionV2Pipeline())
    monkeypatch.setattr(ml_model, "_condition_platt_v2", None)
    monkeypatch.setattr(ml_model, "_ensure_latest_model_loaded", lambda **kwargs: None)

    result = ml_model.predict_condition_outlook(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        cloud_cover=45.0,
        lead_hours=72,
        forecast_precipitation=0.4,
        forecast_wind_speed=18.0,
        forecast_wind_direction=180.0,
        forecast_weather_code=61,
        force_variant="v2",
    )

    assert result["model_ready"] is True
    assert result["model_variant"] == "v2"
    assert result["expected_condition"] == "pioggia"


def test_platt_scaler_produces_bounded_probabilities():
    raw_probs = np.array([0.1, 0.2, 0.4, 0.55, 0.6, 0.8, 0.9, 0.3, 0.7, 0.85] * 6)
    y = np.array([0, 0, 0, 1, 1, 1, 1, 0, 1, 1] * 6)

    params = ml_model._fit_platt_scaler(raw_probs, y)
    assert params is not None

    calibrated = [ml_model._apply_platt(float(prob), params) for prob in raw_probs]
    assert all(0.0 < prob < 1.0 for prob in calibrated)


def test_v2_gates_are_independent_when_v1_component_is_missing():
    rain_gate = ml_model._rain_v2_gate(
        {},
        {},
        {
            "brier": 0.04,
            "baseline_brier": 0.08,
            "f1": 0.4,
            "baseline_f1": 0.0,
        },
    )
    condition_gate = ml_model._condition_v2_gate(
        {},
        {},
        {
            "macro_f1": 0.55,
            "baseline_macro_f1": 0.45,
        },
    )

    assert rain_gate["pass"] is True
    assert rain_gate["source"] == "training_baseline"
    assert condition_gate["pass"] is True
    assert condition_gate["source"] == "training_baseline"


def test_stats_variant_helpers_expose_v2_when_v1_component_is_missing(monkeypatch):
    monkeypatch.setattr(ml_model, "_rain_pipeline", None)
    monkeypatch.setattr(ml_model, "_rain_pipeline_v2", object())
    monkeypatch.setattr(ml_model, "_condition_pipeline", object())
    monkeypatch.setattr(ml_model, "_condition_pipeline_v2", object())
    monkeypatch.setattr(ml_model, "_global_model_variant_for_stats", lambda: "v1")

    assert ml_model._rain_model_variant_for_stats() == "v2"
    assert ml_model._condition_model_variant_for_stats() == "v1"


def test_daily_insight_applies_horizon_support_rules(monkeypatch):
    monkeypatch.setattr(
        ml_model,
        "predict_correction",
        lambda **kwargs: {
            "model_ready": True,
            "correction": 0.0,
            "corrected_temp": kwargs["temp"],
            "confidence": "alta",
        },
    )
    monkeypatch.setattr(
        ml_model,
        "predict_rain_probability",
        lambda **kwargs: {
            "model_ready": True,
            "rain_probability": 0.8,
            "will_rain": True,
            "confidence": "alta",
            "model_variant": "v2",
        },
    )
    monkeypatch.setattr(
        ml_model,
        "predict_condition_outlook",
        lambda **kwargs: {
            "model_ready": True,
            "expected_condition": "pioggia",
            "display_condition": "Pioggia probabile",
            "confidence": "alta",
            "source": "ml",
            "probability": 0.8,
            "model_variant": "v2",
        },
    )
    monkeypatch.setattr(ml_model, "_resolve_live_model_variant", lambda city_name=None: "v2")
    monkeypatch.setattr(
        ml_model,
        "_blend_profiles",
        {
            "v1": {},
            "v2": {
                "intraday": {
                    "ml_weight": 0.5,
                    "samples": 300,
                    "rain_brier": 0.1,
                    "provider_brier": 0.2,
                },
                "day2_3": {
                    "ml_weight": 0.25,
                    "samples": 300,
                    "rain_brier": 0.1,
                    "provider_brier": 0.2,
                },
                "day8_plus": {"ml_weight": 0.0},
            },
        },
    )

    day = {
        "dt": "2026-04-11",
        "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
        "humidity": 70,
        "cloud_cover": 50,
        "wind_speed": 8,
        "wind_deg": 180,
        "pop": 0.2,
        "weather_code": 1,
    }

    full = ml_model.build_daily_insight(day=day, lat=41.9, lon=12.5, region="Lazio", lead_hours=24, city_name="Roma")
    limited = ml_model.build_daily_insight(day=day, lat=41.9, lon=12.5, region="Lazio", lead_hours=72, city_name="Roma")
    provider_only = ml_model.build_daily_insight(
        day=day,
        lat=41.9,
        lon=12.5,
        region="Lazio",
        lead_hours=192,
        city_name="Roma",
    )

    assert full["horizon_support"] == "full"
    assert full["model_variant"] == "v2"
    assert full["rain_probability"] == 0.5  # 50% provider + 50% ML

    assert limited["horizon_support"] == "limited"
    assert limited["model_variant"] == "v2"
    assert limited["rain_probability"] == 0.35  # 75% provider + 25% ML

    assert provider_only["horizon_support"] == "provider_only"
    assert provider_only["model_variant"] == "provider"
    assert provider_only["rain_probability"] == 0.2


def test_daily_insight_low_pop_clear_code_does_not_claim_rain(monkeypatch):
    monkeypatch.setattr(
        ml_model,
        "predict_correction",
        lambda **kwargs: {"model_ready": False, "correction": 0.0, "corrected_temp": kwargs["temp"]},
    )
    monkeypatch.setattr(
        ml_model,
        "predict_rain_probability",
        lambda **kwargs: {"model_ready": False, "model_variant": "provider"},
    )

    def provider_condition(**kwargs):
        label = ml_model._condition_from_inputs(
            weather_code=kwargs["forecast_weather_code"],
            cloud_cover=kwargs["cloud_cover"],
            precipitation=kwargs["forecast_precipitation"],
        )
        return {
            "model_ready": False,
            "expected_condition": label,
            "display_condition": ml_model._condition_display(label),
            "confidence": "media",
            "source": "provider",
            "model_variant": "provider",
        }

    monkeypatch.setattr(ml_model, "predict_condition_outlook", provider_condition)

    day = {
        "dt": "2026-04-11",
        "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
        "humidity": 70,
        "cloud_cover": 10,
        "wind_speed": 8,
        "wind_deg": 180,
        "pop": 0.15,
        "precipitation_sum": 0.0,
        "weather_code": 1,
    }

    insight = ml_model.build_daily_insight(day=day, lat=41.9, lon=12.5, region="Lazio", lead_hours=14, city_name="Roma")

    assert insight["expected_condition"] == "sereno"
    assert insight["display_condition"] == "Cielo sereno"
    assert "Pioggia probabile" not in insight["summary"]


def test_daily_insight_exposes_provider_condition_for_frontend_impact_checks(monkeypatch):
    monkeypatch.setattr(
        ml_model,
        "predict_correction",
        lambda **kwargs: {"model_ready": False, "correction": 0.0, "corrected_temp": kwargs["temp"]},
    )
    monkeypatch.setattr(
        ml_model,
        "predict_rain_probability",
        lambda **kwargs: {"model_ready": False, "model_variant": "provider"},
    )
    monkeypatch.setattr(
        ml_model,
        "predict_condition_outlook",
        lambda **kwargs: {
            "model_ready": True,
            "expected_condition": "pioggia",
            "display_condition": "Pioggia probabile",
            "confidence": "media",
            "source": "ml",
            "model_variant": "v1",
            "provider_condition": "sereno",
        },
    )

    day = {
        "dt": "2026-04-11",
        "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
        "humidity": 70,
        "cloud_cover": 10,
        "wind_speed": 8,
        "wind_deg": 180,
        "pop": 0.15,
        "precipitation_sum": 0.0,
        "weather_code": 1,
    }

    insight = ml_model.build_daily_insight(day=day, lat=41.9, lon=12.5, region="Lazio", lead_hours=14, city_name="Roma")

    assert insight["condition_source"] == "ml"
    assert insight["provider_condition"] == "sereno"
    assert insight["expected_condition"] == "pioggia"


def test_daily_insight_rain_code_or_real_precipitation_claims_rain(monkeypatch):
    monkeypatch.setattr(
        ml_model,
        "predict_correction",
        lambda **kwargs: {"model_ready": False, "correction": 0.0, "corrected_temp": kwargs["temp"]},
    )
    monkeypatch.setattr(
        ml_model,
        "predict_rain_probability",
        lambda **kwargs: {"model_ready": False, "model_variant": "provider"},
    )
    monkeypatch.setattr(
        ml_model,
        "predict_condition_outlook",
        lambda **kwargs: {
            "model_ready": False,
            "expected_condition": "sereno",
            "display_condition": "Cielo sereno",
            "confidence": "media",
            "source": "provider",
            "model_variant": "provider",
        },
    )

    day = {
        "dt": "2026-04-11",
        "temp": {"min": 10.0, "max": 20.0, "day": 15.0},
        "humidity": 70,
        "cloud_cover": 10,
        "wind_speed": 8,
        "wind_deg": 180,
        "pop": 0.2,
        "precipitation_sum": 1.2,
        "weather_code": 1,
    }

    insight = ml_model.build_daily_insight(day=day, lat=41.9, lon=12.5, region="Lazio", lead_hours=14, city_name="Roma")

    assert insight["expected_condition"] == "pioggia"
    assert insight["display_condition"] == "Pioggia probabile"
    assert "Scenario asciutto" not in insight["summary"]


def test_load_latest_model_rejects_incompatible_sklearn_pickle(monkeypatch):
    payload = {
        "model_format_version": ml_model.MODEL_FORMAT_VERSION,
        "sklearn_version": "1.5.2",
        "pipeline": object(),
        "rain_pipeline": object(),
        "condition_pipeline": object(),
        "le": object(),
        "baseline_mae": 1.2,
    }
    record = SimpleNamespace(
        id=7,
        trained_at=SimpleNamespace(isoformat=lambda: "2026-04-16T10:00:00+00:00"),
        mae=1.1,
        n_samples=500,
        model_bytes=ml_model._encode_model_payload(payload),
    )

    monkeypatch.setattr(ml_model, "SessionLocal", lambda: _FakeModelSession(record))
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")

    loaded = ml_model.load_latest_model()

    assert loaded is False
    assert ml_model._pipeline is None
    summary = ml_model.get_public_summary()
    assert summary["model_ready"] is False
    assert summary["rain_model_ready"] is False
    assert summary["condition_model_ready"] is False
    assert summary["model_sklearn_version"] == "1.5.2"
    assert summary["model_load_warning"] == "incompatible_model_sklearn"

    correction = ml_model.predict_correction(
        temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
    )
    rain = ml_model.predict_rain_probability(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
    )
    condition = ml_model.predict_condition_outlook(
        forecast_temp=18.0,
        humidity=70.0,
        hour=13,
        month=4,
        lat=41.9,
        lon=12.5,
        region="Lazio",
    )

    assert correction["model_variant"] == "provider"
    assert correction["model_ready"] is False
    assert rain["model_variant"] == "provider"
    assert rain["model_ready"] is False
    assert condition["model_variant"] == "provider"
    assert condition["model_ready"] is False


def test_load_latest_model_skips_incompatible_and_loads_older_compatible(monkeypatch):
    incompatible_payload = {
        "model_format_version": ml_model.MODEL_FORMAT_VERSION,
        "sklearn_version": "1.5.2",
        "pipeline": _PickleablePipeline(),
        "rain_pipeline": None,
        "condition_pipeline": None,
        "le": object(),
    }
    compatible_payload = {
        "model_format_version": ml_model.MODEL_FORMAT_VERSION,
        "sklearn_version": "1.6.1",
        "pipeline": _PickleablePipeline(),
        "rain_pipeline": None,
        "condition_pipeline": None,
        "temperature_feature_variant": "v1",
        "blend_profiles": {"v1": {}, "v2": {}},
        "le": object(),
        "regions": ["Lazio"],
        "baseline_mae": 1.2,
    }
    records = [
        SimpleNamespace(
            id=12,
            trained_at=SimpleNamespace(isoformat=lambda: "2026-04-17T12:00:00+00:00"),
            mae=0.7,
            n_samples=900,
            model_bytes=ml_model._encode_model_payload(incompatible_payload),
        ),
        SimpleNamespace(
            id=11,
            trained_at=SimpleNamespace(isoformat=lambda: "2026-04-16T12:00:00+00:00"),
            mae=0.8,
            n_samples=800,
            model_bytes=ml_model._encode_model_payload(compatible_payload),
        ),
    ]

    monkeypatch.setattr(ml_model, "SessionLocal", lambda: _FakeModelSession(records))
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")

    loaded = ml_model.load_latest_model()

    assert loaded is True
    summary = ml_model.get_public_summary()
    assert summary["model_ready"] is True
    assert summary["model_mae"] == 0.8
    assert summary["model_load_warning"].startswith("loaded_older_compatible_model")
    assert summary["model_load_attempts"][0]["loaded"] is False
    assert summary["model_load_attempts"][1]["loaded"] is True


def test_load_latest_model_accepts_matching_sklearn_pickle(monkeypatch):
    payload = {
        "model_format_version": ml_model.MODEL_FORMAT_VERSION,
        "sklearn_version": "1.6.1",
        "pipeline": _PickleablePipeline(),
        "rain_pipeline": None,
        "condition_pipeline": None,
        "rain_pipeline_v2": None,
        "condition_pipeline_v2": None,
        "rain_platt_v2": None,
        "condition_platt_v2": None,
        "temperature_feature_variant": "v1",
        "blend_profiles": {"v1": {}, "v2": {}},
        "le": object(),
        "regions": ["Lazio"],
    }
    record = SimpleNamespace(
        id=8,
        trained_at=SimpleNamespace(isoformat=lambda: "2026-04-16T11:00:00+00:00"),
        mae=0.9,
        n_samples=800,
        model_bytes=ml_model._encode_model_payload(payload),
    )

    monkeypatch.setattr(ml_model, "SessionLocal", lambda: _FakeModelSession(record))
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")

    loaded = ml_model.load_latest_model()

    assert loaded is True
    summary = ml_model.get_public_summary()
    assert summary["model_sklearn_version"] == "1.6.1"
    assert summary["model_format_version"] == ml_model.MODEL_FORMAT_VERSION
    assert summary["model_load_warning"] is None
    assert summary["model_mae"] == 0.9


def test_load_latest_model_rejects_legacy_payload_without_metadata(monkeypatch):
    payload = {
        "pipeline": object(),
        "rain_pipeline": object(),
        "condition_pipeline": object(),
        "le": object(),
    }
    record = SimpleNamespace(
        id=9,
        trained_at=SimpleNamespace(isoformat=lambda: "2026-04-16T12:00:00+00:00"),
        mae=1.3,
        n_samples=300,
        model_bytes=pickle.dumps(payload),
    )

    monkeypatch.setattr(ml_model, "SessionLocal", lambda: _FakeModelSession(record))
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")

    loaded = ml_model.load_latest_model()

    assert loaded is False
    summary = ml_model.get_public_summary()
    assert summary["model_format_version"] == 1
    assert summary["model_sklearn_version"] is None
    assert summary["model_load_warning"] == "incompatible_model_format"


def test_load_latest_model_clears_state_on_malformed_payload(monkeypatch):
    monkeypatch.setattr(ml_model, "_pipeline", object())
    monkeypatch.setattr(ml_model, "_rain_pipeline", object())
    monkeypatch.setattr(
        ml_model,
        "_latest_summary",
        {
            **ml_model._empty_model_summary(),
            "model_ready": True,
            "model_mae": 0.7,
            "baseline_mae": 1.1,
            "rain_accuracy": 0.8,
            "model_samples": 999,
            "model_trained_at": "2026-04-15T00:00:00+00:00",
        },
    )
    record = SimpleNamespace(
        id=10,
        trained_at=SimpleNamespace(isoformat=lambda: "2026-04-16T13:00:00+00:00"),
        mae=1.4,
        n_samples=250,
        model_bytes=b"MLMETA {bad json}\nnot-a-pickle",
    )

    monkeypatch.setattr(ml_model, "SessionLocal", lambda: _FakeModelSession(record))

    loaded = ml_model.load_latest_model()

    assert loaded is False
    assert ml_model._pipeline is None
    assert ml_model._rain_pipeline is None
    summary = ml_model.get_public_summary()
    assert summary["model_ready"] is False
    assert summary["model_mae"] == 1.4
    assert summary["baseline_mae"] is None
    assert summary["rain_accuracy"] is None
    assert summary["model_samples"] == 250
    assert summary["model_trained_at"] == "2026-04-16T13:00:00+00:00"
    assert summary["model_load_warning"] == "corrupt_model_blob"


def test_load_latest_model_rejects_unsupported_format_version(monkeypatch):
    payload = {
        "model_format_version": 999,
        "sklearn_version": "1.6.1",
        "pipeline": _PickleablePipeline(),
        "rain_pipeline": None,
        "condition_pipeline": None,
        "le": object(),
    }
    record = SimpleNamespace(
        id=11,
        trained_at=SimpleNamespace(isoformat=lambda: "2026-04-16T14:00:00+00:00"),
        mae=0.8,
        n_samples=700,
        model_bytes=ml_model._encode_model_payload(payload),
    )

    monkeypatch.setattr(ml_model, "SessionLocal", lambda: _FakeModelSession(record))
    monkeypatch.setattr(ml_model.sklearn, "__version__", "1.6.1")

    loaded = ml_model.load_latest_model()

    assert loaded is False
    summary = ml_model.get_public_summary()
    assert summary["model_format_version"] == 999
    assert summary["model_load_warning"] == "incompatible_model_format"


def test_train_uses_bounded_training_rows(monkeypatch):
    calls = []

    class FakeSession:
        def close(self):
            return None

    monkeypatch.setattr(ml_model, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        ml_model,
        "settings",
        SimpleNamespace(
            ml_training_window_days=7,
            ml_training_max_rows=1234,
        ),
    )

    def fake_prepare_training_rows(db, *, window_start=None, limit=None):
        calls.append((window_start, limit))
        return []

    monkeypatch.setattr(ml_model, "_prepare_training_rows", fake_prepare_training_rows)

    result = ml_model.train(min_samples=10)

    assert result["success"] is False
    assert "Dati insufficienti" in result["message"]
    assert len(calls) == 1
    window_start, limit = calls[0]
    assert limit == 1234
    assert window_start is not None
    assert window_start.tzinfo is not None


def test_train_failure_reports_temperature_v1_and_v2_diagnostics(monkeypatch):
    class FakeSession:
        def close(self):
            return None

    rows = [
        {
            "target_time": datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc),
            "verified_at": datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc),
            "region": "Lazio",
        }
        for _ in range(20)
    ]
    monkeypatch.setattr(ml_model, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        ml_model,
        "settings",
        SimpleNamespace(
            ml_training_window_days=7,
            ml_training_max_rows=100,
            ml_kpi_window_days=14,
        ),
    )
    monkeypatch.setattr(ml_model, "_prepare_training_rows", lambda *args, **kwargs: rows)
    monkeypatch.setattr(ml_model, "_encode_regions", lambda rows: object())
    monkeypatch.setattr(
        ml_model,
        "_train_temperature_pipeline",
        lambda rows: {
            "success": False,
            "message": "v1 baseline non battuto",
            "mae": 0.6,
            "baseline_mae": 0.4,
            "feature_variant": "v1",
        },
    )
    monkeypatch.setattr(
        ml_model,
        "_train_temperature_pipeline_v2",
        lambda rows, encoder: {
            "success": False,
            "message": "v2 baseline non battuto",
            "mae": 0.5,
            "baseline_mae": 0.3,
            "feature_variant": "v2",
        },
    )
    monkeypatch.setattr(
        ml_model, "_train_rain_pipeline", lambda rows, encoder: {"success": False, "message": "rain off"}
    )
    monkeypatch.setattr(
        ml_model, "_train_condition_pipeline", lambda rows, encoder: {"success": False, "message": "condition off"}
    )
    monkeypatch.setattr(
        ml_model, "_train_rain_pipeline_v2", lambda rows, encoder: {"success": False, "message": "rain v2 off"}
    )
    monkeypatch.setattr(
        ml_model,
        "_train_condition_pipeline_v2",
        lambda rows, encoder: {"success": False, "message": "condition v2 off"},
    )

    result = ml_model.train(min_samples=10)

    assert result["success"] is False
    assert "temperature_v1" in result["message"]
    assert "temperature_v2" in result["message"]
    assert result["training_diagnostics"]["temperature_v1"]["mae"] == 0.6
    assert result["training_diagnostics"]["temperature_v2"]["baseline_mae"] == 0.3
