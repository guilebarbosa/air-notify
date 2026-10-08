from __future__ import annotations

import math

import pytest
from conftest import HOME, SCHOOL, at, north_of

from air_notify.config import Outline, Zone
from air_notify.geofence import Event, Fix, Presence, Transition, classify, distance_m, outside_by_m, process


def fix(minutes: float, zone=SCHOOL, meters: float = 0, accuracy: float = 20) -> Fix:
    lat, lon = north_of(zone, meters)
    return Fix(at(minutes), lat, lon, accuracy)


def run(fixes, presence=None, last_ts=None, max_accuracy_m=100, exit_buffer_m=50):
    return process(
        presence or {},
        last_ts,
        fixes,
        (SCHOOL, HOME),
        max_accuracy_m=max_accuracy_m,
        exit_buffer_m=exit_buffer_m,
    )


def test_distance_one_degree_latitude():
    assert distance_m(52, 5, 53, 5) == pytest.approx(111_195, rel=1e-3)


@pytest.mark.parametrize(
    ("meters", "expected"),
    [(0, Presence.INSIDE), (149, Presence.INSIDE), (175, None), (199, None), (201, Presence.OUTSIDE)],
)
def test_classify_with_hysteresis_band(meters, expected):
    assert classify(SCHOOL, fix(0, meters=meters), exit_buffer_m=50) == expected


def test_first_observation_is_silent():
    presence, last_ts, events = run([fix(0)])
    assert presence == {"School": Presence.INSIDE, "Home": Presence.OUTSIDE}
    assert last_ts == at(0)
    assert events == []


def test_arrive_and_leave():
    presence, _, events = run([fix(0, meters=500), fix(10), fix(20, meters=500)])
    assert events == [
        Event("School", Transition.ARRIVE, at(10)),
        Event("School", Transition.LEAVE, at(20)),
    ]
    assert presence["School"] is Presence.OUTSIDE


def test_jitter_in_band_does_not_flap():
    fixes = [fix(0), fix(10, meters=160), fix(20, meters=140), fix(30, meters=190), fix(40, meters=145)]
    _, _, events = run(fixes)
    assert events == []


def test_inaccurate_fix_advances_timestamp_but_not_presence():
    presence, last_ts, events = run([fix(10, meters=500, accuracy=250)], presence={"School": Presence.INSIDE})
    assert events == []
    assert presence["School"] is Presence.INSIDE
    assert last_ts == at(10)


def test_already_processed_fixes_are_skipped():
    presence = {"School": Presence.INSIDE, "Home": Presence.OUTSIDE}
    _, last_ts, events = run([fix(5, meters=500), fix(10, meters=500)], presence=presence, last_ts=at(10))
    assert events == []
    assert last_ts == at(10)


def test_out_of_order_input_is_processed_chronologically():
    _, _, events = run([fix(20, meters=500), fix(0, meters=500), fix(10)])
    assert [e.transition for e in events] == [Transition.ARRIVE, Transition.LEAVE]


def test_same_timestamp_prefers_most_accurate():
    # Two finders reported at the same second; the accurate one says inside.
    _, _, events = run(
        [fix(10, meters=500, accuracy=90), fix(10, meters=0, accuracy=10)],
        presence={"School": Presence.OUTSIDE, "Home": Presence.OUTSIDE},
    )
    assert events == [Event("School", Transition.ARRIVE, at(10))]


def test_moving_between_zones():
    presence = {"School": Presence.INSIDE, "Home": Presence.OUTSIDE}
    _, _, events = run([fix(10, zone=HOME)], presence=presence)
    assert events == [Event("School", Transition.LEAVE, at(10)), Event("Home", Transition.ARRIVE, at(10))]


def test_one_fix_leaving_and_arriving_reports_the_leave_first():
    # The other way round from the zone order (School, Home): still leave first, then arrive.
    presence = {"School": Presence.OUTSIDE, "Home": Presence.INSIDE}
    _, _, events = run([fix(10, zone=SCHOOL)], presence=presence)
    assert events == [Event("Home", Transition.LEAVE, at(10)), Event("School", Transition.ARRIVE, at(10))]


def test_removed_zone_state_is_dropped():
    presence, _, _ = run([], presence={"Old": Presence.INSIDE, "School": Presence.INSIDE})
    assert presence == {"School": Presence.INSIDE}


# --- custom outlines ---------------------------------------------------------------------------


def point(east_m: float, north_m: float) -> tuple[float, float]:
    """A spot this many metres east and north of (52, 5)."""
    return 52 + north_m / 111_195, 5 + east_m / (111_195 * math.cos(math.radians(52)))


# An L, 200 m on each side, with the top-right 100 m square cut out:
#   (0,200)─(100,200)
#      │        │
#      │     (100,100)─(200,100)
#      │                  │
#    (0,0)─────────────(200,0)
L_SHAPE = Zone(
    "Park",
    Outline(tuple(point(e, n) for e, n in [(0, 0), (200, 0), (200, 100), (100, 100), (100, 200), (0, 200)])),
)


@pytest.mark.parametrize(
    ("east", "north", "expected"),
    [
        (50, 50, Presence.INSIDE),
        (150, 50, Presence.INSIDE),
        (50, 150, Presence.INSIDE),
        (50, 100, Presence.INSIDE),  # level with two corners: the crossing count must still be right
        (130, 130, None),  # in the cut-out, 30 m from the edges: the hysteresis band
        (160, 160, Presence.OUTSIDE),  # in the cut-out, 60 m from the edges
        (100, -40, None),  # 40 m below the bottom edge
        (100, -60, Presence.OUTSIDE),
        (500, 50, Presence.OUTSIDE),
    ],
)
def test_outline_with_hysteresis_band(east, north, expected):
    lat, lon = point(east, north)
    assert classify(L_SHAPE, Fix(at(0), lat, lon, 20), exit_buffer_m=50) == expected


@pytest.mark.parametrize(
    ("east", "north", "outside"),
    [(160, 160, 60), (300, 50, 100), (250, 150, math.hypot(50, 50)), (-30, -40, 50)],
)
def test_outline_distance_to_the_nearest_edge_or_corner(east, north, outside):
    assert outside_by_m(L_SHAPE.shape, *point(east, north)) == pytest.approx(outside, abs=0.5)


def test_arrive_and_leave_an_outline():
    def at_spot(minutes, east, north):
        return Fix(at(minutes), *point(east, north), 20)

    fixes = [at_spot(0, 500, 50), at_spot(10, 50, 150), at_spot(20, 160, 160)]
    _, _, events = process({}, None, fixes, (L_SHAPE,), max_accuracy_m=100, exit_buffer_m=50)
    assert events == [Event("Park", Transition.ARRIVE, at(10)), Event("Park", Transition.LEAVE, at(20))]
