"""Test per gli endpoint città."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from database import get_db


client = TestClient(app)


def make_fake_city(
    *,
    city_id=1,
    name="Roma",
    region="Lazio",
    province="RM",
    lat=41.9,
    lon=12.5,
    locality_type="comune",
):
    return SimpleNamespace(
        id=city_id,
        name=name,
        region=region,
        province=province,
        lat=lat,
        lon=lon,
        locality_type=locality_type,
        name_lower=name.lower(),
    )


def override_db(rows):
    class FakeQuery:
        def __init__(self, items):
            self.items = items

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, limit):
            self.items = self.items[:limit]
            return self

        def all(self):
            return self.items

        def first(self):
            return self.items[0] if self.items else None

    class FakeDb:
        def query(self, *args, **kwargs):
            return FakeQuery(rows)

    def _override():
        yield FakeDb()

    return _override


def test_cities_index_returns_cacheable_payload():
    fake_rows = [make_fake_city(), make_fake_city(city_id=2, name="Milano", region="Lombardia", province="MI")]
    app.dependency_overrides[get_db] = override_db(fake_rows)
    try:
        response = client.get("/api/cities/index?scope=comuni&version=v2")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.headers["Cache-Control"].startswith("public")
    assert response.headers["X-Cities-Index-Version"] == "v2"
    item = response.json()[0]
    assert set(item.keys()) == {"name", "region", "province", "lat", "lon", "locality_type"}


def test_cities_search_returns_list():
    fake_rows = [make_fake_city(name="Roma"), make_fake_city(city_id=2, name="Rovigo", region="Veneto", province="RO")]
    app.dependency_overrides[get_db] = override_db(fake_rows)
    try:
        response = client.get("/api/cities?q=ro&limit=2")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert isinstance(response.json(), list)
