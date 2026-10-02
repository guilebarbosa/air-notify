from __future__ import annotations

from datetime import datetime, time

import pytest

from air_notify.config import ConfigError, parse_settings

ZONE = {"name": "A", "lat": 1.0, "lon": 1.0, "radius_m": 10}
SCHEDULE = [
    {"time": "07:00", "interval": 15},
    {"time": "17:00", "interval": 20},
    {"time": "20:00", "interval": 25},
    {"time": "00:00", "interval": 30},
]


def local(hm: str) -> datetime:
    return datetime.fromisoformat(f"2026-10-02T{hm}").astimezone()


@pytest.fixture
def settings():
    return parse_settings({"zones": [ZONE], "intervals": SCHEDULE})


@pytest.mark.parametrize(
    ("at", "minutes"),
    [("00:00", 30), ("03:00", 30), ("06:59", 30), ("07:00", 15), ("16:59", 15), ("17:00", 20), ("23:59", 25)],
)
def test_interval_at(settings, at, minutes):
    assert settings.interval_at(local(at)) == minutes


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        ("03:00", "03:30"),  # plain 30 min
        ("06:55", "07:10"),  # 15-min interval starts at 07:00, but never sooner than 15 min after
        ("06:40", "07:00"),  # ... and right at 07:00 when that's already 15+ min later
        ("16:50", "17:05"),  # getting longer at 17:00 doesn't stretch the current wait
        ("23:50", "00:15"),  # across midnight
    ],
)
def test_next_poll(settings, after, expected):
    assert f"{settings.next_poll(local(after)):%H:%M}" == expected


def test_without_intervals_uses_the_default():
    settings = parse_settings({"zones": [ZONE], "poll_interval_minutes": 20})
    assert settings.interval_at(local("12:00")) == 20
    assert f"{settings.next_poll(local('12:00')):%H:%M}" == "12:20"


def test_toml_time_values_and_sorting():
    settings = parse_settings(
        {"zones": [ZONE], "intervals": [{"time": time(20, 0), "interval": 25}, {"time": "07:00", "interval": 15}]}
    )
    assert [i.start for i in settings.intervals] == [time(7, 0), time(20, 0)]


@pytest.mark.parametrize(
    "intervals",
    [
        [{"time": "07:00", "interval": 10}],  # below the 15-min floor
        [{"time": 700, "interval": 15}],  # unquoted
        [{"time": "7am", "interval": 15}],
        [{"time": "07:00", "interval": 15}, {"time": "07:00", "interval": 20}],
        [{"time": "07:00", "minutes": 15}],
    ],
)
def test_invalid_intervals(intervals):
    with pytest.raises(ConfigError):
        parse_settings({"zones": [ZONE], "intervals": intervals})
