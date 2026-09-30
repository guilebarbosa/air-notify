from __future__ import annotations

import stat

from conftest import at

from air_notify.geofence import Presence
from air_notify.notify import Alert
from air_notify.state import Pause, State, load_state, save_state


def test_missing_file_gives_default_state(paths):
    assert load_state(paths.state) == State()


def test_round_trip_with_private_permissions(paths):
    state = State(
        presence={"School": Presence.INSIDE},
        last_report_ts=at(0),
        next_poll_at=at(15),
        paused=Pause("apple", "Apple rate limit (HTTP 429)", at(1)),
        network_failures=2,
        running=True,
        unclean_exits=[at(2)],
        pending_alerts=[Alert("t", "m", ("warning",), 4)],
    )
    save_state(paths.state, state)

    assert load_state(paths.state) == state
    assert stat.S_IMODE(paths.state.stat().st_mode) == 0o600
    assert [p.name for p in paths.root.iterdir()] == ["state.json"]  # no temp files left behind
