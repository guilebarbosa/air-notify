from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import SCHOOL, T0, north_of

from air_notify.config import Settings
from air_notify.daemon import CRASH_LIMIT, IDLE_CHECK_S, NETWORK_RETRY_S, Daemon
from air_notify.geofence import Fix, Presence
from air_notify.history import History
from air_notify.notify import Alert
from air_notify.tracker import ErrorKind, FetchError, SetupError


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeTracker:
    def __init__(self) -> None:
        self.results: list[list[Fix] | FetchError] = []
        self.fetches = 0
        self.reloads = 0
        self.reload_error: SetupError | None = None

    async def fetch(self) -> list[Fix]:
        self.fetches += 1
        result = self.results.pop(0) if self.results else []
        if isinstance(result, FetchError):
            raise result
        return result

    async def reload(self) -> None:
        self.reloads += 1
        if self.reload_error:
            raise self.reload_error


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[Alert] = []
        self.reachable = True

    async def flush(self, pending: list[Alert]) -> list[Alert]:
        if not self.reachable:
            return list(pending)
        self.sent.extend(pending)
        return []


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tracker():
    return FakeTracker()


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def make_daemon(settings, paths, tracker, notifier, clock):
    def make() -> Daemon:
        return Daemon(settings, paths, tracker, notifier, now=clock, jitter=lambda: 0)

    return make


def fix_at(clock: Clock, meters: float) -> Fix:
    lat, lon = north_of(SCHOOL, meters)
    return Fix(clock.now - timedelta(minutes=5), lat, lon, 20)


async def test_polls_every_15_minutes_and_sends_events(make_daemon, tracker, notifier, clock):
    daemon = make_daemon()
    daemon.start()

    tracker.results = [[fix_at(clock, 500)]]
    assert await daemon.tick() == 15 * 60
    assert notifier.sent == []  # first observation is silent

    clock.advance(10 * 60)
    assert await daemon.tick() == 5 * 60  # not due yet: no fetch
    assert tracker.fetches == 1

    clock.advance(5 * 60)
    tracker.results = [[fix_at(clock, 0)]]
    await daemon.tick()
    assert [a.title for a in notifier.sent] == ["Arrived at School"]
    assert daemon.state.presence["School"] is Presence.INSIDE


async def test_events_use_the_zones_own_text(paths, tracker, notifier, clock):
    settings = Settings(zones=(replace(SCHOOL, arrive="Chegou na escola"),))
    daemon = Daemon(settings, paths, tracker, notifier, now=clock, jitter=lambda: 0)
    daemon.start()
    tracker.results = [[fix_at(clock, 500)]]
    await daemon.tick()
    clock.advance(15 * 60)
    tracker.results = [[fix_at(clock, 0)]]
    await daemon.tick()
    assert [a.title for a in notifier.sent] == ["Chegou na escola"]


@pytest.mark.parametrize(
    ("error", "reason", "hint"),
    [
        (FetchError(ErrorKind.AUTH, "Apple login needed"), "auth", "air-notify login"),
        (FetchError(ErrorKind.APPLE, "Apple rate limit (HTTP 429)"), "apple", "air-notify resume"),
        (FetchError(ErrorKind.APPLE, "Unexpected error (KeyError)"), "apple", "air-notify resume"),
    ],
)
async def test_apple_side_errors_stop_polling_with_one_alert(
    make_daemon, tracker, notifier, clock, error, reason, hint
):
    daemon = make_daemon()
    daemon.start()
    tracker.results = [error]

    await daemon.tick()
    for _ in range(5):
        clock.advance(60 * 60)
        assert await daemon.tick() == IDLE_CHECK_S

    assert tracker.fetches == 1  # never contacted Apple again
    assert daemon.state.paused is not None and daemon.state.paused.reason == reason
    (alert,) = notifier.sent
    assert alert.title == "air-notify stopped"
    assert error.detail.rstrip(".") in alert.message and hint in alert.message


async def test_pause_survives_restart_and_resume_clears_it(make_daemon, tracker, notifier, clock, paths):
    daemon = make_daemon()
    daemon.start()
    tracker.results = [FetchError(ErrorKind.APPLE, "Apple rate limit (HTTP 429)")]
    await daemon.tick()
    daemon.stop()

    restarted = make_daemon()
    restarted.start()
    clock.advance(24 * 60 * 60)
    await restarted.tick()
    assert tracker.fetches == 1
    assert restarted.state.paused is not None

    paths.resume_flag.touch()
    await restarted.tick()
    assert restarted.state.paused is None
    assert tracker.reloads == 1
    assert tracker.fetches == 2  # the last poll was a day ago, so it polls right away
    assert not paths.resume_flag.exists()


async def test_resume_right_after_rate_limit_keeps_15_minute_spacing(make_daemon, tracker, clock, paths):
    daemon = make_daemon()
    daemon.start()
    tracker.results = [FetchError(ErrorKind.APPLE, "Apple rate limit (HTTP 429)")]
    await daemon.tick()

    clock.advance(2 * 60)
    paths.resume_flag.touch()
    assert await daemon.tick() == 13 * 60
    assert daemon.state.paused is None
    assert tracker.fetches == 1


async def test_resume_with_missing_setup_stays_paused(make_daemon, tracker, notifier, paths):
    daemon = make_daemon()
    daemon.start()
    daemon.require_setup("No AirTag keys in the Keychain. Run `air-notify import-airtag`.")
    tracker.reload_error = SetupError("No AirTag keys in the Keychain. Run `air-notify import-airtag`.")

    paths.resume_flag.touch()
    await daemon.tick()
    assert daemon.state.paused is not None and daemon.state.paused.reason == "setup"
    assert tracker.fetches == 0


async def test_setup_pause_lifts_once_keychain_items_exist(make_daemon, tracker):
    daemon = make_daemon()
    daemon.require_setup("No Apple session in the Keychain. Run `air-notify login`.")
    daemon.setup_complete()
    assert daemon.state.paused is None

    daemon._pause("apple", "Apple rate limit (HTTP 429)")
    daemon.setup_complete()
    assert daemon.state.paused is not None  # other pauses are untouched


async def test_network_outage_quick_retry_then_single_alert_then_recovery(make_daemon, tracker, notifier, clock):
    daemon = make_daemon()
    daemon.start()
    down = FetchError(ErrorKind.NETWORK, "Can't reach Apple (ClientConnectorError)")
    tracker.results = [down, down, down, down]

    assert await daemon.tick() == NETWORK_RETRY_S  # blip: quick retry, no alert yet
    assert notifier.sent == []

    clock.advance(NETWORK_RETRY_S)
    assert await daemon.tick() == 15 * 60
    assert [a.title for a in notifier.sent] == ["air-notify can't reach Apple"]

    for _ in range(2):
        clock.advance(15 * 60)
        await daemon.tick()
    assert len(notifier.sent) == 1  # no repeats during the outage
    assert daemon.state.paused is None  # keeps retrying

    clock.advance(15 * 60)
    tracker.results = [[]]
    await daemon.tick()
    assert [a.title for a in notifier.sent][-1] == "air-notify recovered"
    assert daemon.state.network_failures == 0


async def test_single_network_blip_sends_nothing(make_daemon, tracker, notifier, clock):
    daemon = make_daemon()
    daemon.start()
    tracker.results = [FetchError(ErrorKind.NETWORK, "Can't reach Apple (TimeoutError)"), []]
    await daemon.tick()
    clock.advance(NETWORK_RETRY_S)
    await daemon.tick()
    assert notifier.sent == []


async def test_restart_respects_reserved_poll_slot(make_daemon, tracker, clock):
    daemon = make_daemon()
    daemon.start()
    await daemon.tick()
    daemon.stop()

    clock.advance(5 * 60)
    restarted = make_daemon()
    restarted.start()
    assert await restarted.tick() == 10 * 60
    assert tracker.fetches == 1


async def test_unclean_exit_alerts_and_crash_loop_stops_polling(make_daemon, tracker, notifier, clock):
    daemon = make_daemon()
    daemon.start()  # never stopped: simulates a crash

    for i in range(1, CRASH_LIMIT):
        clock.advance(5 * 60)
        crashed = make_daemon()
        crashed.start()
        await crashed.tick()
        assert notifier.sent[-1].title == "air-notify restarted"
        assert crashed.state.paused is None, f"paused too early at restart {i}"

    clock.advance(5 * 60)
    looping = make_daemon()
    looping.start()
    await looping.tick()
    assert looping.state.paused is not None and looping.state.paused.reason == "crash_loop"
    assert notifier.sent[-1].title == "air-notify stopped"


async def test_alerts_queue_while_ntfy_is_unreachable(make_daemon, tracker, notifier, clock, paths):
    daemon = make_daemon()
    daemon.start()
    notifier.reachable = False
    tracker.results = [FetchError(ErrorKind.AUTH, "Apple login needed")]
    await daemon.tick()
    assert notifier.sent == []
    assert len(daemon.state.pending_alerts) == 1

    notifier.reachable = True
    clock.advance(IDLE_CHECK_S)
    await make_daemon().tick()  # also survives a restart: the queue is persisted
    assert [a.title for a in notifier.sent] == ["air-notify stopped"]


async def test_records_each_new_report_once(settings, paths, tracker, notifier, clock):
    history = History(paths.history, keep_days=30)
    daemon = Daemon(settings, paths, tracker, notifier, history=history, now=clock, jitter=lambda: 0)
    daemon.start()
    first = fix_at(clock, 500)
    tracker.results = [[first]]
    await daemon.tick()
    clock.advance(15 * 60)
    second = fix_at(clock, 0)
    tracker.results = [[first, second]]  # Apple returns the older report again
    await daemon.tick()

    (day, count), *_ = history.days()
    assert count == 2
    assert [p["acc"] for p in history.points(day)] == [first.accuracy_m, second.accuracy_m]


async def test_history_write_failure_alerts_once_and_keeps_polling(settings, paths, tracker, notifier, clock):
    paths.history.mkdir()  # can't open a directory for appending
    daemon = Daemon(settings, paths, tracker, notifier, history=History(paths.history, 30), now=clock, jitter=lambda: 0)
    daemon.start()
    for _ in range(3):
        tracker.results = [[fix_at(clock, 500)]]
        await daemon.tick()
        clock.advance(15 * 60)

    assert tracker.fetches == 3
    assert [a.title for a in notifier.sent] == ["air-notify history failed"]
