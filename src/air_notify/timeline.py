"""A day's arrivals and departures, recomputed from the history with the same rules as the alerts."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from . import geofence
from .config import Settings
from .geofence import Fix, Transition
from .history import History
from .notify import format_time


def _fixes(entries: list[dict[str, Any]]) -> list[Fix]:
    return [Fix(datetime.fromisoformat(e["t"]), float(e["lat"]), float(e["lon"]), float(e["acc"])) for e in entries]


def day_events(history: History, day: date, settings: Settings) -> list[dict[str, str]]:
    """
    Arrive/leave events for `day`, newest first, labelled like the alerts ([messages] and per-zone text).

    The previous day's reports set where the day starts, so leaving home in the morning is an event.
    """
    rules = {"max_accuracy_m": settings.max_accuracy_m, "exit_buffer_m": settings.exit_buffer_m}
    previous = _fixes(history.points(day - timedelta(days=1)))
    presence, last_ts, _ = geofence.process({}, None, previous, settings.zones, **rules)
    _, _, events = geofence.process(presence, last_ts, _fixes(history.points(day)), settings.zones, **rules)

    result = []
    for event in reversed(events):
        messages = settings.messages_for(event.zone)
        template = messages.arrive if event.transition is Transition.ARRIVE else messages.leave
        result.append(
            {
                "t": event.timestamp.astimezone().isoformat(timespec="seconds"),
                "zone": event.zone,
                "transition": str(event.transition),
                "label": template.format(zone=event.zone, time=format_time(event.timestamp, event.timestamp)),
            }
        )
    return result
