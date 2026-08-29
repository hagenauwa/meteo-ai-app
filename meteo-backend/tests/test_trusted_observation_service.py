from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import trusted_observation_service as service


def test_fetch_meteostat_observations_maps_station_rows_to_cities(monkeypatch):
    station_frame = pd.DataFrame(
        {"name": ["Sarzana / Luni"], "distance": [7621.0]},
        index=pd.Index(["16125"], name="id"),
    )
    hourly_index = pd.MultiIndex.from_tuples(
        [
            ("16125", pd.Timestamp("2026-08-28T14:00:00Z")),
            ("16125", pd.Timestamp("2026-08-28T15:00:00Z")),
        ],
        names=["station", "time"],
    )
    hourly_frame = pd.DataFrame(
        {
            "temp": [32.2, 32.1],
            "prcp": [0.0, 0.4],
            "rhum": [53.0, 56.0],
            "cldc": [5.0, 7.0],
            "wspd": [11.1, 9.0],
            "wdir": [163.0, 170.0],
        },
        index=hourly_index,
    )

    monkeypatch.setattr(service.ms.stations, "nearby", lambda *args, **kwargs: station_frame)

    class FakeHourly:
        def fetch(self):
            return hourly_frame

    captured = {}

    def fake_hourly(stations, start, end, **kwargs):
        captured.update({"stations": stations, "start": start, "end": end, **kwargs})
        return FakeHourly()

    monkeypatch.setattr(service.ms, "hourly", fake_hourly)
    cities = [
        {"id": 1, "name": "Carrara", "lat": 44.08, "lon": 10.10},
        {"id": 2, "name": "Massa", "lat": 44.04, "lon": 10.14},
    ]

    observations = service.fetch_meteostat_observations(
        cities,
        now=datetime(2026, 8, 28, 17, 20, tzinfo=timezone.utc),
    )

    assert captured["stations"] == ["16125"]
    assert captured["timezone"] == "UTC"
    assert len(observations) == 4
    assert {item["city_id"] for item in observations} == {1, 2}
    assert all(item["observation_source"] == "meteostat" for item in observations)
    assert all(item["observation_interval_minutes"] == 60 for item in observations)
    rainy = [item for item in observations if item["precipitation"] == 0.4]
    assert len(rainy) == 2
    assert all(item["observed_at"].tzinfo == timezone.utc for item in observations)


def test_fetch_meteostat_observations_rejects_rows_without_rain_measurement(monkeypatch):
    station_frame = pd.DataFrame(
        {"name": ["Sarzana / Luni"]},
        index=pd.Index(["16125"], name="id"),
    )
    hourly_index = pd.MultiIndex.from_tuples(
        [("16125", pd.Timestamp("2026-08-28T15:00:00Z"))],
        names=["station", "time"],
    )
    hourly_frame = pd.DataFrame({"temp": [25.0], "prcp": [float("nan")]}, index=hourly_index)
    monkeypatch.setattr(service.ms.stations, "nearby", lambda *args, **kwargs: station_frame)

    class FakeHourly:
        def fetch(self):
            return hourly_frame

    monkeypatch.setattr(service.ms, "hourly", lambda *args, **kwargs: FakeHourly())

    result = service.fetch_meteostat_observations(
        [{"id": 1, "lat": 44.05, "lon": 10.07}],
        now=datetime(2026, 8, 28, 18, tzinfo=timezone.utc),
    )

    assert result == []
