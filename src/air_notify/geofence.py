"""Circle geofences with hysteresis. Pure functions: no I/O, no clock."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .config import Zone

EARTH_RADIUS_M = 6_371_008.8


class Presence(StrEnum):
    INSIDE = "inside"
    OUTSIDE = "outside"


class Transition(StrEnum):
    ARRIVE = "arrive"
    LEAVE = "leave"


@dataclass(frozen=True)
class Fix:
    """A decrypted location report, reduced to what geofencing needs."""

    timestamp: datetime
    lat: float
    lon: float
    accuracy_m: float


@dataclass(frozen=True)
class Event:
    zone: str
    transition: Transition
    timestamp: datetime


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (haversine) distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def classify(zone: Zone, fix: Fix, exit_buffer_m: float) -> Presence | None:
    """
    INSIDE within the radius, OUTSIDE beyond radius + buffer.

    Returns None inside the buffer band, meaning "keep the previous state". This hysteresis
    stops GPS jitter around the edge from producing arrive/leave/arrive spam.
    """
    d = distance_m(zone.lat, zone.lon, fix.lat, fix.lon)
    if d <= zone.radius_m:
        return Presence.INSIDE
    if d > zone.radius_m + exit_buffer_m:
        return Presence.OUTSIDE
    return None


def process(
    presence: Mapping[str, Presence],
    last_ts: datetime | None,
    fixes: Iterable[Fix],
    zones: Sequence[Zone],
    *,
    max_accuracy_m: float,
    exit_buffer_m: float,
) -> tuple[dict[str, Presence], datetime | None, list[Event]]:
    """
    Apply new fixes oldest-first and return (presence, newest processed timestamp, events).

    - Fixes at or before `last_ts` were handled by an earlier poll and are skipped.
    - Fixes less accurate than `max_accuracy_m` advance `last_ts` but never change presence.
    - A zone's first classification is recorded silently (no event), e.g. on first run.
    - State for zones no longer in the config is dropped.
    """
    names = {z.name for z in zones}
    new_presence = {name: p for name, p in presence.items() if name in names}
    events: list[Event] = []

    # For equal timestamps, the most accurate fix goes first and the rest are skipped as seen.
    for fix in sorted(fixes, key=lambda f: (f.timestamp, f.accuracy_m)):
        if last_ts is not None and fix.timestamp <= last_ts:
            continue
        last_ts = fix.timestamp
        if fix.accuracy_m > max_accuracy_m:
            continue

        for zone in zones:
            new = classify(zone, fix, exit_buffer_m)
            old = new_presence.get(zone.name)
            if new is None or new == old:
                continue
            new_presence[zone.name] = new
            if old is not None:
                transition = Transition.ARRIVE if new is Presence.INSIDE else Transition.LEAVE
                events.append(Event(zone.name, transition, fix.timestamp))

    return new_presence, last_ts, events
