from __future__ import annotations

from datetime import datetime, timedelta, UTC

import pytest

from air_notify.config import Paths, Settings, Zone

T0 = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)

# Two zones ~1.1 km apart (0.01° latitude).
SCHOOL = Zone("School", 52.0000, 5.0000, 150)
HOME = Zone("Home", 52.0100, 5.0000, 100)


def north_of(zone: Zone, meters: float) -> tuple[float, float]:
    """A point `meters` due north of the zone centre (1° latitude ≈ 111.2 km)."""
    return zone.lat + meters / 111_195, zone.lon


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
def settings() -> Settings:
    return Settings(zones=(SCHOOL, HOME))


@pytest.fixture
def paths(tmp_path) -> Paths:
    return Paths(tmp_path)
