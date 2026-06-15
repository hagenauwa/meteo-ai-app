"""Pytest fixtures per il backend meteo-ai-app."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Usa un file temporaneo condiviso invece di :memory: perche' il codice del
# backend crea nuove SessionLocal() in molti punti e :memory: e' isolato per
# connessione.
_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DATABASE_URL = f"sqlite:///{_db_file.name}"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from database import Base  # noqa: E402


@pytest.fixture(scope="function")
def db_engine() -> Generator:
    """Engine SQLite temporaneo fresco per ogni test."""
    from database import DATABASE_URL

    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator:
    """Sessione DB legata a un engine temporaneo."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function", autouse=True)
def _cleanup_db_file() -> Generator:
    yield
    # Tronca il file DB tra i test per evitare interferenze.
    _db_file.seek(0)
    _db_file.truncate()
