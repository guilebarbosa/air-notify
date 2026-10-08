"""Geofences (circles and custom outlines) with hysteresis. Pure functions: no I/O, no clock."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .config import Circle, Outline, Zone

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


def outside_by_m(shape: Circle | Outline, lat: float, lon: float) -> float:
    """How far a point is outside the shape's edge, in metres: 0 or less when it's inside."""
    if isinstance(shape, Circle):
        return distance_m(shape.lat, shape.lon, lat, lon) - shape.radius_m
    edges = _edges_around(shape.corners, lat, lon)
    if _contains_origin(edges):
        return 0.0
    return min(_origin_to_segment(a, b) for a, b in edges)


def classify(zone: Zone, fix: Fix, exit_buffer_m: float) -> Presence | None:
    """
    INSIDE within the zone, OUTSIDE more than exit_buffer_m beyond its edge.

    Returns None inside the buffer band, meaning "keep the previous state". This hysteresis
    stops GPS jitter around the edge from producing arrive/leave/arrive spam.
    """
    d = outside_by_m(zone.shape, fix.lat, fix.lon)
    if d <= 0:
        return Presence.INSIDE
    if d > exit_buffer_m:
        return Presence.OUTSIDE
    return None


# Outlines are measured on a flat map centred on the point (x east, y north, in metres), with
# the point at (0, 0). Over the few kilometres a zone spans, the Earth's curvature doesn't matter.
type _XY = tuple[float, float]


def _edges_around(corners: tuple[tuple[float, float], ...], lat: float, lon: float) -> list[tuple[_XY, _XY]]:
    m_per_degree = math.radians(1) * EARTH_RADIUS_M
    shrink = math.cos(math.radians(lat))  # a degree of longitude gets shorter away from the equator
    xy = [((c_lon - lon) * shrink * m_per_degree, (c_lat - lat) * m_per_degree) for c_lat, c_lon in corners]
    return list(zip(xy, xy[1:] + xy[:1], strict=True))  # the last corner joins back to the first


def _contains_origin(edges: list[tuple[_XY, _XY]]) -> bool:
    """
    Ray casting: follow a line from the point due east and count the edges it crosses. Each
    crossing goes in or out of the shape, so an odd count means the point is inside. Works for
    any outline, concave ones included.
    """
    inside = False
    for (x1, y1), (x2, y2) in edges:
        if (y1 > 0) != (y2 > 0):  # the edge spans the ray's height...
            x = x1 - y1 * (x2 - x1) / (y2 - y1)
            if x > 0:  # ...and crosses it east of the point
                inside = not inside
    return inside


def _origin_to_segment(a: _XY, b: _XY) -> float:
    """Distance from the point to the nearest spot on the edge a–b."""
    (x1, y1), (x2, y2) = a, b
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    # How far along the edge the nearest spot is (0 = at a, 1 = at b).
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length2))
    return math.hypot(x1 + t * dx, y1 + t * dy)


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

        changes: list[Event] = []
        for zone in zones:
            new = classify(zone, fix, exit_buffer_m)
            old = new_presence.get(zone.name)
            if new is None or new == old:
                continue
            new_presence[zone.name] = new
            if old is not None:
                transition = Transition.ARRIVE if new is Presence.INSIDE else Transition.LEAVE
                changes.append(Event(zone.name, transition, fix.timestamp))
        # One fix can leave a zone and enter another: leaving comes first, whatever the zone order.
        events.extend(sorted(changes, key=lambda e: e.transition is Transition.ARRIVE))

    return new_presence, last_ts, events
