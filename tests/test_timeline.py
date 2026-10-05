from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from conftest import HOME, SCHOOL, T0, north_of

from air_notify.config import Messages, Settings
from air_notify.geofence import Fix
from air_notify.history import History
from air_notify.timeline import day_events


def fix(minutes: float, zone, meters: float = 0) -> Fix:
    lat, lon = north_of(zone, meters)
    return Fix(T0 + timedelta(minutes=minutes), lat, lon, 20)


def test_events_newest_first_with_the_alert_wording(paths):
    settings = Settings(
        zones=(replace(SCHOOL, arrive="Chegou na escola"), HOME),
        messages=Messages(arrive="Chegou em {zone}", leave="Saiu de {zone}"),
    )
    history = History(paths.history, 30)
    history.append(
        [
            fix(-12 * 60, HOME),  # the evening before: at home
            fix(10, HOME, 500),  # left home (outside both zones)
            fix(40, SCHOOL),  # arrived at school
            fix(300, SCHOOL, 600),  # left school
        ],
        now=T0,
    )

    events = day_events(history, (T0 + timedelta(minutes=10)).astimezone().date(), settings)

    assert [(e["zone"], e["transition"]) for e in events] == [
        ("School", "leave"),
        ("School", "arrive"),
        ("Home", "leave"),  # known only because of the previous day's report
    ]
    assert events[1]["label"] == "Chegou na escola"  # the zone's own text wins
    assert events[2]["label"] == "Saiu de Home"
    assert events[0]["t"] > events[1]["t"] > events[2]["t"]


def test_no_reports_no_events(paths):
    assert day_events(History(paths.history, 30), T0.date(), Settings(zones=(SCHOOL,))) == []
