"""Shared helpers for ML endpoint tests."""

from __future__ import annotations

from types import SimpleNamespace


WARNING_CITY_UNRESOLVED = "ML_CITY_UNRESOLVED"
WARNING_CITY_AMBIGUOUS = "ML_CITY_AMBIGUOUS"
MODEL_STATUS_MISSING_ROW = "missing_model_row"


def fake_city(**overrides):
    name = overrides.get("name", "Roma")
    return SimpleNamespace(
        id=overrides.get("id", 1),
        name=name,
        region=overrides.get("region", "Lazio"),
        province=overrides.get("province", "RM"),
        lat=overrides.get("lat", 41.9),
        lon=overrides.get("lon", 12.5),
        locality_type=overrides.get("locality_type", "comune"),
        name_lower=overrides.get("name_lower", name.lower()),
    )


def install_fake_db_override(app, get_db, rows=None):
    fake_rows = list(rows) if rows is not None else [fake_city()]

    class FakeQuery:
        def __init__(self, query_rows):
            self._rows = list(query_rows)

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, size):
            self._rows = self._rows[:size]
            return self

        def all(self):
            return list(self._rows)

        def first(self):
            return self._rows[0] if self._rows else None

    class FakeDb:
        def query(self, *args, **kwargs):
            return FakeQuery(fake_rows)

    def override_get_db():
        yield FakeDb()

    app.dependency_overrides[get_db] = override_get_db


def override_get_db(rows):
    fake_rows = list(rows)

    class FakeQuery:
        def __init__(self):
            self._rows = list(fake_rows)

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, size):
            self._rows = self._rows[:size]
            return self

        def all(self):
            return list(self._rows)

        def first(self):
            return self._rows[0] if self._rows else None

    class FakeDb:
        def query(self, *args, **kwargs):
            return FakeQuery()

    def _dependency():
        yield FakeDb()

    return _dependency


def assert_warning_contract(payload, *, code: str, reason_substring: str, warning_parent: str = "ml"):
    container = payload if warning_parent == "self" else payload[warning_parent]
    warning = container.get("warning") or {}

    assert container.get("enabled") is False
    assert warning.get("code") == code
    assert isinstance(warning.get("message"), str) and warning.get("message")
    assert reason_substring in (warning.get("reason") or "")
