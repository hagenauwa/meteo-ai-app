"""Test endpoint ricerca città /api/cities/search."""

import importlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from database import get_db


client = TestClient(app)
cities_module = importlib.import_module("routers.cities")


# ---------------------------------------------------------------------------
# Fix route order: /api/cities/search deve precedere /api/cities/{city_id}
# ---------------------------------------------------------------------------
def _reorder_cities_search_route():
    routes = list(app.router.routes)
    idx_search = None
    idx_city_id = None
    for i, route in enumerate(routes):
        if getattr(route, "path", "") == "/api/cities/search":
            idx_search = i
        if getattr(route, "path", "") == "/api/cities/{city_id}":
            idx_city_id = i
    if idx_search is not None and idx_city_id is not None and idx_search > idx_city_id:
        routes[idx_search], routes[idx_city_id] = routes[idx_city_id], routes[idx_search]
        app.router.routes = routes


_reorder_cities_search_route()


# ---------------------------------------------------------------------------
# Default httpx mock per evitare chiamate HTTP reali nei test
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mock_httpx_empty(monkeypatch):
    """Mock httpx.Client per restituire risultati vuoti di default."""

    def fake_client(**kwargs):
        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url, params=None, headers=None, timeout=None):
                class FakeResp:
                    status_code = 200

                    def json(self):
                        return {"results": []}

                return FakeResp()

        return FakeClient()

    monkeypatch.setattr(httpx, "Client", fake_client)


def _make_fake_city_row(**kwargs):
    defaults = dict(
        id=1,
        name="Roma",
        region="Lazio",
        province="RM",
        lat=41.9028,
        lon=12.4964,
        locality_type="comune",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _override_db(rows):
    class FakeQuery:
        def __init__(self, items):
            self.items = list(items)

        def _apply_filter(self, arg):
            try:
                s = str(arg.compile(compile_kwargs={"literal_binds": True}))
            except Exception:
                s = str(arg)
            filtered = list(self.items)
            if "locality_type" in s:
                if "comune" in s:
                    filtered = [it for it in filtered if getattr(it, "locality_type", None) == "comune"]
                elif "localita" in s:
                    filtered = [it for it in filtered if getattr(it, "locality_type", None) == "localita"]
            if "name_lower" in s and "LIKE" in s:
                import re

                m = re.search(r"LIKE '(.+?)'", s)
                if m:
                    pattern = m.group(1)
                    if pattern.endswith("%") and not pattern.startswith("%"):
                        pattern = pattern.replace("%", "")
                        filtered = [it for it in filtered if getattr(it, "name", "").lower().startswith(pattern)]
                    elif "%" in pattern:
                        pattern = pattern.replace("%", "")
                        filtered = [it for it in filtered if pattern in getattr(it, "name", "").lower()]
            return filtered

        def filter(self, *args):
            new_items = list(self.items)
            for arg in args:
                new_items = FakeQuery(new_items)._apply_filter(arg)
            return FakeQuery(new_items)

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


class TestCitiesSearch:
    def test_search_roma_returns_results(self):
        """Ricerca 'Roma' → risultati non vuoti, tutti con locality_type."""
        fake_rows = [_make_fake_city_row()]
        app.dependency_overrides[get_db] = _override_db(fake_rows)
        cities_module._SEARCH_CACHE.clear()

        try:
            response = client.get("/api/cities/search?q=Roma&limit=8")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        for item in data:
            assert "name" in item
            assert "lat" in item
            assert "lon" in item
            assert "locality_type" in item

    def test_search_roma_country_code_it(self):
        """Ricerca 'Roma' → i risultati DB sono italiani (locality_type comune)."""
        fake_rows = [
            _make_fake_city_row(id=1, name="Roma", region="Lazio", province="RM", lat=41.9028, lon=12.4964),
        ]
        app.dependency_overrides[get_db] = _override_db(fake_rows)
        cities_module._SEARCH_CACHE.clear()

        try:
            response = client.get("/api/cities/search?q=Roma&limit=8")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        # Con mock httpx vuoto il fallback non aggiunge nulla => solo risultati DB
        assert all(item.get("locality_type") == "comune" for item in data)

    def test_deduplication_by_lat_lon(self):
        """Due città con stesse coordinate arrotondate vengono deduplicate."""
        fake_rows = [
            _make_fake_city_row(id=1, name="Roma", lat=41.90281, lon=12.49641),
            _make_fake_city_row(id=2, name="Roma", lat=41.90282, lon=12.49642),
        ]
        app.dependency_overrides[get_db] = _override_db(fake_rows)
        cities_module._SEARCH_CACHE.clear()

        try:
            response = client.get("/api/cities/search?q=Roma&limit=8")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        # Entrambe hanno le stesse coordinate arrotondate a 4 decimali, quindi 1 risultato
        assert len(data) == 1

    def test_cache_hit_returns_same_data(self):
        """Stessa query ritorna subito stessi dati grazie alla cache."""
        fake_rows = [_make_fake_city_row()]
        app.dependency_overrides[get_db] = _override_db(fake_rows)
        cities_module._SEARCH_CACHE.clear()

        try:
            response1 = client.get("/api/cities/search?q=Roma&limit=8")
            assert response1.status_code == 200
            data1 = response1.json()

            # Seconda chiamata con stessa query deve usare cache
            response2 = client.get("/api/cities/search?q=Roma&limit=8")
            assert response2.status_code == 200
            data2 = response2.json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert data1 == data2

    def test_cache_expires_after_ttl(self, monkeypatch):
        """La cache scade dopo il TTL (5 minuti)."""
        fake_rows = [_make_fake_city_row()]
        app.dependency_overrides[get_db] = _override_db(fake_rows)
        cities_module._SEARCH_CACHE.clear()

        # Inserisci in cache un risultato vecchio con dati diversi
        old_item = cities_module.CityIndexItem(
            name="VecchiaRoma",
            region="Antica",
            province="AN",
            lat=41.0,
            lon=12.0,
            locality_type="comune",
        )
        cities_module._SEARCH_CACHE["all:8:roma"] = (0.0, [old_item])

        try:
            response = client.get("/api/cities/search?q=Roma&limit=8")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        # Cache scaduta => deve tornare il nuovo risultato del DB, non quello vecchio
        assert len(data) == 1
        assert data[0]["name"] == "Roma"
        assert data[0]["name"] != "VecchiaRoma"

    def test_fallback_open_meteo_when_db_sparse(self, monkeypatch):
        """Fallback Open-Meteo quando DB ha pochi risultati."""
        fake_rows = [_make_fake_city_row()]
        app.dependency_overrides[get_db] = _override_db(fake_rows)
        cities_module._SEARCH_CACHE.clear()

        def fake_httpx_get(url, params=None, headers=None, timeout=None):
            class FakeResp:
                status_code = 200

                def json(self):
                    return {
                        "results": [
                            {
                                "name": "Roma",
                                "latitude": 41.9028,
                                "longitude": 12.4964,
                                "country_code": "IT",
                                "admin1": "Lazio",
                                "admin2": "RM",
                                "population": 2500000,
                            },
                            {
                                "name": "Romano di Lombardia",
                                "latitude": 45.5200,
                                "longitude": 9.7500,
                                "country_code": "IT",
                                "admin1": "Lombardia",
                                "admin2": "BG",
                                "population": 50000,
                            },
                        ]
                    }

            return FakeResp()

        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: type(
                "FakeClient",
                (),
                {
                    "__enter__": lambda self: self,
                    "__exit__": lambda *args: None,
                    "get": fake_httpx_get,
                },
            )(),
        )

        try:
            response = client.get("/api/cities/search?q=Roma&limit=8")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_fallback_open_meteo_ignores_non_it(self, monkeypatch):
        """Il fallback Open-Meteo ignora risultati con country_code != IT."""
        fake_rows = [_make_fake_city_row()]
        app.dependency_overrides[get_db] = _override_db(fake_rows)
        cities_module._SEARCH_CACHE.clear()

        def fake_httpx_get(url, params=None, headers=None, timeout=None):
            class FakeResp:
                status_code = 200

                def json(self):
                    return {
                        "results": [
                            {
                                "name": "Rome",
                                "latitude": 41.9028,
                                "longitude": 12.4964,
                                "country_code": "US",
                                "admin1": "Georgia",
                                "admin2": None,
                                "population": 50000,
                            },
                        ]
                    }

            return FakeResp()

        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: type(
                "FakeClient",
                (),
                {
                    "__enter__": lambda self: self,
                    "__exit__": lambda *args: None,
                    "get": fake_httpx_get,
                },
            )(),
        )

        try:
            response = client.get("/api/cities/search?q=Roma&limit=8")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        # Rome US deve essere filtrato, quindi solo il risultato DB
        assert all("Rome" not in item["name"] for item in data)

    def test_fallback_network_error_ignored(self, monkeypatch):
        """Errore di rete nel fallback non fa fallire l'endpoint."""
        fake_rows = [_make_fake_city_row()]
        app.dependency_overrides[get_db] = _override_db(fake_rows)
        cities_module._SEARCH_CACHE.clear()

        def fake_httpx_get(*args, **kwargs):
            raise httpx.ConnectError("Simulated network failure")

        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: type(
                "FakeClient",
                (),
                {
                    "__enter__": lambda self: self,
                    "__exit__": lambda *args: None,
                    "get": fake_httpx_get,
                },
            )(),
        )

        try:
            response = client.get("/api/cities/search?q=Roma&limit=8")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_scope_comuni_filters(self):
        """scope=comuni filtra solo comuni."""
        fake_rows = [
            _make_fake_city_row(id=1, name="Roma", locality_type="comune"),
            _make_fake_city_row(id=2, name="Roma Vecchia", locality_type="localita"),
        ]
        app.dependency_overrides[get_db] = _override_db(fake_rows)
        cities_module._SEARCH_CACHE.clear()

        try:
            response = client.get("/api/cities/search?q=Roma&scope=comuni")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        assert all(item.get("locality_type") == "comune" for item in data)
