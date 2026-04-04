"""Test auth admin endpoint."""
import importlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
import auth


client = TestClient(app)
admin_module = importlib.import_module("routers.admin")


def test_admin_status_requires_token_in_production(monkeypatch):
    monkeypatch.setattr(auth, "settings", SimpleNamespace(is_production=True, admin_api_token="secret"))
    response = client.get("/api/admin/status")
    assert response.status_code == 403


def test_admin_status_accepts_valid_token_in_production(monkeypatch):
    monkeypatch.setattr(auth, "settings", SimpleNamespace(is_production=True, admin_api_token="secret"))
    monkeypatch.setattr(admin_module, "SessionLocal", lambda: SimpleNamespace(
        query=lambda *args, **kwargs: SimpleNamespace(
            count=lambda: 0,
            filter=lambda *a, **k: SimpleNamespace(count=lambda: 0),
        ),
        close=lambda: None,
    ))
    monkeypatch.setattr(importlib.import_module("ml_model"), "get_stats", lambda: {"verified_predictions": 0})
    monkeypatch.setattr(
        importlib.import_module("scheduler"),
        "scheduler",
        SimpleNamespace(get_jobs=lambda: []),
    )
    response = client.get("/api/admin/status", headers={"x-admin-token": "secret"})
    assert response.status_code == 200
