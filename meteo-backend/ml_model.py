"""
ml_model.py — Modello ML scikit-learn per correzione temperatura

Algoritmo: Ridge Regression
Features: ora del giorno, mese, latitudine, umidità, cloud cover, regione (encoded)
Target: errore = actual_temp - predicted_temp

Il modello viene serializzato (pickle) e salvato in PostgreSQL (tabella ml_model_store).
"""
import io
import pickle
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error

from sqlalchemy.orm import Session
from database import SessionLocal, MlPrediction, MlModelStore, City

# Pipeline globale caricata in memoria all'avvio
_pipeline: Optional[Pipeline] = None
_label_encoder: Optional[LabelEncoder] = None
_known_regions: list = []


def _build_features(hour: int, month: int, lat: float, humidity: float,
                    cloud_cover: float, region: str) -> np.ndarray:
    """Costruisce il vettore features normalizzato per una singola osservazione."""
    global _label_encoder, _known_regions

    # Encoding regione
    region_code = 0
    if _label_encoder and region in _known_regions:
        region_code = int(_label_encoder.transform([region])[0])

    return np.array([[hour, month, lat, humidity or 50.0, cloud_cover or 50.0, region_code]])


def train(min_samples: int = 100) -> dict:
    """
    Addestra il modello Ridge Regression sulle previsioni verificate.
    Salva il modello serializzato nel DB.
    Ritorna dizionario con metriche.
    """
    global _pipeline, _label_encoder, _known_regions

    db: Session = SessionLocal()
    try:
        # Carica predictions verificate con join su cities per avere lat e region
        rows = (
            db.query(
                MlPrediction.predicted_temp,
                MlPrediction.humidity,
                MlPrediction.hour,
                MlPrediction.error,
                MlPrediction.predicted_at,
                City.lat,
                City.region
            )
            .join(City, MlPrediction.city_id == City.id)
            .filter(MlPrediction.verified == True)
            .filter(MlPrediction.error.isnot(None))
            .all()
        )

        if len(rows) < min_samples:
            return {
                "success": False,
                "message": f"Dati insufficienti: {len(rows)} campioni (minimo {min_samples})"
            }

        print(f"[TRAIN] Training su {len(rows)} campioni verificati...")

        # Prepara features
        regions = list(set(r.region or "Sconosciuta" for r in rows))
        _known_regions = regions
        le = LabelEncoder()
        le.fit(regions)
        _label_encoder = le

        X, y = [], []
        for r in rows:
            region = r.region or "Sconosciuta"
            region_code = int(le.transform([region])[0])
            month = r.predicted_at.month if r.predicted_at else 6
            X.append([
                r.hour or 12,
                month,
                r.lat or 43.0,
                r.humidity or 50.0,
                50.0,           # cloud_cover non disponibile nelle predictions, default 50
                region_code
            ])
            y.append(r.error)

        X = np.array(X)
        y = np.array(y)

        # Split train/validation
        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

        # Pipeline: StandardScaler + Ridge
        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("ridge",  Ridge(alpha=1.0))
        ])
        pipeline.fit(X_train, y_train)

        # Valutazione
        y_pred = pipeline.predict(X_val)
        mae = float(mean_absolute_error(y_val, y_pred))

        print(f"[OK] Modello addestrato — MAE: {mae:.3f}°C su {len(X_val)} campioni di validazione")

        # Serializza modello (pipeline + label encoder)
        model_data = pickle.dumps({"pipeline": pipeline, "le": le, "regions": regions})

        # Salva in DB
        record = MlModelStore(
            trained_at  = datetime.now(timezone.utc),
            model_bytes = model_data,
            mae         = mae,
            n_samples   = len(rows)
        )
        db.add(record)
        db.commit()

        # Aggiorna istanza globale
        _pipeline = pipeline

        return {
            "success":    True,
            "mae":        mae,
            "n_samples":  len(rows),
            "trained_at": record.trained_at.isoformat()
        }

    except Exception as e:
        print(f"[ERROR] Errore training ML: {e}")
        return {"success": False, "message": str(e)}
    finally:
        db.close()


def load_latest_model() -> bool:
    """Carica l'ultimo modello salvato dal DB in memoria."""
    global _pipeline, _label_encoder, _known_regions

    db: Session = SessionLocal()
    try:
        record = db.query(MlModelStore).order_by(MlModelStore.trained_at.desc()).first()
        if not record or not record.model_bytes:
            print("[INFO]  Nessun modello ML salvato nel DB")
            return False

        data = pickle.loads(record.model_bytes)
        _pipeline     = data["pipeline"]
        _label_encoder = data["le"]
        _known_regions = data["regions"]
        print(f"[OK] Modello ML caricato (addestrato: {record.trained_at}, MAE: {record.mae:.3f}°C)")
        return True
    except Exception as e:
        print(f"[WARN]  Errore caricamento modello: {e}")
        return False
    finally:
        db.close()


def predict_correction(
    temp: float,
    humidity: float,
    hour: int,
    month: int,
    lat: float,
    region: str,
    cloud_cover: float = 50.0
) -> dict:
    """
    Predice la correzione da applicare alla temperatura.
    Ritorna dict con correction (°C) e corrected_temp.
    """
    global _pipeline

    if _pipeline is None:
        return {"correction": 0.0, "corrected_temp": temp, "model_ready": False}

    try:
        features = _build_features(hour, month, lat, humidity, cloud_cover, region)
        correction = float(_pipeline.predict(features)[0])

        # Limite sicurezza: max ±5°C
        correction = max(-5.0, min(5.0, correction))

        # Confidence basata su valore assoluto della correzione
        if abs(correction) < 0.3:
            confidence = "bassa"
        elif abs(correction) < 1.0:
            confidence = "media"
        else:
            confidence = "alta"

        return {
            "correction":     round(correction, 2),
            "corrected_temp": round(temp + correction, 1),
            "model_ready":    True,
            "confidence":     confidence
        }
    except Exception as e:
        return {"correction": 0.0, "corrected_temp": temp, "model_ready": False, "error": str(e)}


def get_stats() -> dict:
    """Ritorna statistiche sul modello e sulle predictions."""
    db: Session = SessionLocal()
    try:
        total = db.query(MlPrediction).count()
        verified = db.query(MlPrediction).filter(MlPrediction.verified == True).count()

        latest_model = db.query(MlModelStore).order_by(MlModelStore.trained_at.desc()).first()

        avg_error = None
        if verified > 0:
            errors = db.query(MlPrediction.error).filter(
                MlPrediction.verified == True,
                MlPrediction.error.isnot(None)
            ).all()
            avg_error = round(float(np.mean([abs(e[0]) for e in errors])), 3)

        return {
            "total_predictions":    total,
            "verified_predictions": verified,
            "avg_error_celsius":    avg_error,
            "model_ready":          _pipeline is not None,
            "model_trained_at":     latest_model.trained_at.isoformat() if latest_model else None,
            "model_mae":            latest_model.mae if latest_model else None,
            "model_samples":        latest_model.n_samples if latest_model else None,
        }
    finally:
        db.close()
