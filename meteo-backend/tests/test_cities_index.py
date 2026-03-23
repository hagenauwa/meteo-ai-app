"""Test per l'endpoint GET /api/cities/index"""
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

# Importa l'app — assicurati di essere nella directory meteo-backend
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from database import get_db

client = TestClient(app)


def make_fake_city(name="Roma", region="Lazio", lat=41.9, lon=12.5, locality_type="comune"):
    city = MagicMock()
    city.name = name
    city.region = region
    city.lat = lat
    city.lon = lon
    city.locality_type = locality_type
    return city


def test_cities_index_returns_list():
    """L'endpoint restituisce una lista JSON."""
    fake_cities = [make_fake_city("Roma"), make_fake_city("Milano", "Lombardia", 45.4, 9.1)]

    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = fake_cities

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/api/cities/index")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_cities_index_item_shape():
    """Ogni elemento ha name, region, lat, lon, locality_type — senza id."""
    fake_cities = [make_fake_city()]

    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = fake_cities

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/api/cities/index")
    finally:
        app.dependency_overrides.pop(get_db, None)

    item = response.json()[0]
    assert "name" in item
    assert "region" in item
    assert "lat" in item
    assert "lon" in item
    assert "locality_type" in item
    assert "id" not in item
