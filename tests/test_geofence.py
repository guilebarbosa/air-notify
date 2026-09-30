from __future__ import annotations

import pytest
from conftest import HOME, SCHOOL, at, north_of

from air_notify.geofence import Event, Fix, Presence, Transition, classify, distance_m, process


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


def test_removed_zone_state_is_dropped():
    presence, _, _ = run([], presence={"Old": Presence.INSIDE, "School": Presence.INSIDE})
    assert presence == {"School": Presence.INSIDE}
