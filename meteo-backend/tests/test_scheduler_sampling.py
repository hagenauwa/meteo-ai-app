"""Test campionamento leggero del ciclo ML."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import scheduler


def _city(city_id: int, region: str, province: str, population: int) -> dict:
    return {
        "id": city_id,
        "name": f"City {city_id}",
        "lat": 40.0 + (city_id / 100),
        "lon": 10.0 + (city_id / 100),
        "region": region,
        "province": province,
        "population": population,
    }


def test_select_training_cities_keeps_core_and_balances_rotating_sample(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "settings",
        SimpleNamespace(
            ml_city_sample_size=12,
            ml_city_core_size=3,
            ml_cycle_every_hours=6,
        ),
    )
    cities = [
        _city(city_id, f"Region {city_id % 3}", f"PR{city_id % 6}", 1000 - city_id)
        for city_id in range(1, 31)
    ]
    now = datetime(2026, 4, 26, 6, tzinfo=timezone.utc)

    selected = scheduler._select_training_cities(cities, now)

    assert len(selected) == 12
    selected_ids = {city["id"] for city in selected}
    assert {1, 2, 3}.issubset(selected_ids)
    assert len({city["region"] for city in selected}) >= 3
    assert selected == scheduler._select_training_cities(cities, now)


def test_select_training_cities_rotates_between_cycle_windows(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "settings",
        SimpleNamespace(
            ml_city_sample_size=12,
            ml_city_core_size=3,
            ml_cycle_every_hours=6,
        ),
    )
    cities = [
        _city(city_id, f"Region {city_id % 4}", f"PR{city_id % 8}", 1000 - city_id)
        for city_id in range(1, 41)
    ]
    first_window = datetime(2026, 4, 26, 6, tzinfo=timezone.utc)
    second_window = first_window + timedelta(hours=6)

    first_ids = {city["id"] for city in scheduler._select_training_cities(cities, first_window)}
    second_ids = {city["id"] for city in scheduler._select_training_cities(cities, second_window)}

    assert {1, 2, 3}.issubset(first_ids)
    assert {1, 2, 3}.issubset(second_ids)
    assert first_ids != second_ids
