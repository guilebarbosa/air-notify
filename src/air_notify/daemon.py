"""The polling loop and its safeguards. Every safeguard that kicks in sends an alert."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import random
import signal
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import IO, Protocol

import aiohttp

from . import geofence
from .config import Paths, Settings
from .geofence import Fix
from .keystore import NTFY, SecretStore
from .notify import Alert, Notifier, event_alert
from .state import Pause, State, load_state, save_state
from .tracker import ErrorKind, FetchError, SetupError, Tracker

logger = logging.getLogger(__name__)

POLL_JITTER_S = 90  # only ever added to the interval, never subtracted
IDLE_CHECK_S = 60  # how often the loop wakes to check for `resume`/`login` while waiting
NETWORK_RETRY_S = 60  # one quick retry before calling it an outage (e.g. Wi-Fi after wake)
CRASH_WINDOW = timedelta(hours=1)
CRASH_LIMIT = 3
MAX_PENDING_ALERTS = 50

_RESUME_HINTS = {
    "auth": "Run `air-notify login` to resume.",
    "setup": "It resumes by itself once setup is done.",
}


class TrackerLike(Protocol):
    async def fetch(self) -> list[Fix]: ...

    async def reload(self) -> None: ...


class NotifierLike(Protocol):
    async def flush(self, pending: list[Alert]) -> list[Alert]: ...


def _now() -> datetime:
    return datetime.now().astimezone()


class Daemon:
    def __init__(
        self,
        settings: Settings,
        paths: Paths,
        tracker: TrackerLike,
        notifier: NotifierLike,
        *,
        now: Callable[[], datetime] = _now,
        jitter: Callable[[], float] = lambda: random.uniform(0, POLL_JITTER_S),  # noqa: S311 (timing jitter)
    ) -> None:
        self._settings = settings
        self._paths = paths
        self._tracker = tracker
        self._notifier = notifier
        self._now = now
        self._jitter = jitter
        self.state: State = load_state(paths.state)

    # --- lifecycle -------------------------------------------------------------------------

    def start(self) -> None:
        """Mark the daemon as running; detect an unclean previous exit and crash loops."""
        now = self._now()
        if self.state.running:
            recent = [t for t in self.state.unclean_exits if now - t < CRASH_WINDOW]
            self.state.unclean_exits = [*recent, now]
            if len(self.state.unclean_exits) >= CRASH_LIMIT:
                if self.state.paused is None:
                    self._pause("crash_loop", f"{len(self.state.unclean_exits)} unexpected exits within an hour")
            else:
                self._alert(
                    Alert("air-notify restarted", "Restarted after an unexpected exit.", ("information_source",))
                )
        self.state.running = True
        self._save()

    def stop(self) -> None:
        """Clean shutdown (SIGTERM/SIGINT)."""
        self.state.running = False
        self._save()

    # --- loop --------------------------------------------------------------------------------

    async def tick(self) -> float:
        """Run one loop iteration. Returns seconds until the next one is due."""
        await self._handle_resume_request()
        await self._flush_alerts()

        if self.state.paused is not None:
            return IDLE_CHECK_S
        if (due_in := self._due_in()) > 0:
            return due_in

        await self._poll()
        await self._flush_alerts()
        return self._due_in()

    def _due_in(self) -> float:
        if self.state.next_poll_at is None:
            return 0
        return max(0.0, (self.state.next_poll_at - self._now()).total_seconds())

    async def _handle_resume_request(self) -> None:
        """`air-notify resume` and `air-notify login` drop a flag file; consume it."""
        try:
            self._paths.resume_flag.unlink()
        except FileNotFoundError:
            return

        # Always reload: `login` may have written a new session to the secret store.
        try:
            await self._tracker.reload()
        except SetupError as e:
            self.require_setup(str(e))
            return

        if self.state.paused is not None:
            # next_poll_at stays as reserved by the last poll, so resuming right after a
            # rate limit still waits out the 15-minute spacing.
            logger.info("Resuming (was paused: %s)", self.state.paused.detail)
            self.state.paused = None
            self.state.unclean_exits = []
        self._save()

    async def _poll(self) -> None:
        now = self._now()
        # Reserve the next slot *before* the request, so a crash mid-poll can't cause an
        # early re-poll after launchd restarts us.
        interval = timedelta(minutes=self._settings.poll_interval_minutes, seconds=self._jitter())
        self.state.next_poll_at = now + interval
        self._save()

        try:
            fixes = await self._tracker.fetch()
        except FetchError as e:
            self._on_fetch_error(e, now)
        else:
            self._on_fixes(fixes, now)
        self._save()

    def _on_fetch_error(self, error: FetchError, now: datetime) -> None:
        logger.warning("Fetch failed (%s): %s", error.kind, error.detail)
        if error.kind is ErrorKind.AUTH:
            self._pause("auth", error.detail)
        elif error.kind is ErrorKind.APPLE:
            self._pause("apple", error.detail)
        else:
            self.state.network_failures += 1
            if self.state.network_failures == 1:
                self.state.next_poll_at = now + timedelta(seconds=NETWORK_RETRY_S)
            elif self.state.network_failures == 2:
                minutes = round(self._settings.poll_interval_minutes)
                self._alert(
                    Alert(
                        "air-notify can't reach Apple",
                        f"{error.detail}. Retrying every {minutes} min; you'll get a message when it recovers.",
                        ("warning",),
                    )
                )

    def _on_fixes(self, fixes: list[Fix], now: datetime) -> None:
        if self.state.network_failures >= 2:
            self._alert(Alert("air-notify recovered", "Apple is reachable again.", ("white_check_mark",), 2))
        self.state.network_failures = 0

        presence, last_ts, events = geofence.process(
            self.state.presence,
            self.state.last_report_ts,
            fixes,
            self._settings.zones,
            max_accuracy_m=self._settings.max_accuracy_m,
            exit_buffer_m=self._settings.exit_buffer_m,
        )
        self.state.presence, self.state.last_report_ts = presence, last_ts
        for event in events:
            logger.info("%s %s at %s", event.transition, event.zone, event.timestamp.isoformat(timespec="minutes"))
            self._alert(event_alert(event, now, self._settings.messages))
        logger.info("Poll ok: %d report(s), %d event(s)", len(fixes), len(events))

    # --- safeguards & alerts ---------------------------------------------------------------

    def require_setup(self, detail: str) -> None:
        """Park the daemon until `login`/`import-airtag` finish (they drop the resume flag)."""
        self._pause("setup", detail)
        self._save()

    def setup_complete(self) -> None:
        """The secrets are all saved now; lift a setup pause (other pauses stay)."""
        if self.state.paused is not None and self.state.paused.reason == "setup":
            self.state.paused = None
            self._save()

    def _pause(self, reason: str, detail: str) -> None:
        self.state.paused = Pause(reason, detail, self._now())
        logger.warning("Polling stopped (%s): %s", reason, detail)
        hint = _RESUME_HINTS.get(reason, "Run `air-notify resume` when ready.")
        self._alert(Alert("air-notify stopped", f"{detail.rstrip('.')}. Polling is stopped. {hint}", ("warning",), 4))

    def _alert(self, alert: Alert) -> None:
        self.state.pending_alerts = [*self.state.pending_alerts, alert][-MAX_PENDING_ALERTS:]

    async def _flush_alerts(self) -> None:
        if not self.state.pending_alerts:
            return
        remaining = await self._notifier.flush(self.state.pending_alerts)
        if remaining != self.state.pending_alerts:
            self.state.pending_alerts = remaining
            self._save()

    def _save(self) -> None:
        save_state(self._paths.state, self.state)


# --- process entry point ---------------------------------------------------------------------


def acquire_lock(paths: Paths) -> IO[str] | None:
    """Single-instance lock: two daemons would double the request rate."""
    f = paths.lock.open("a")
    paths.lock.chmod(0o600)
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


async def run_daemon(settings: Settings, paths: Paths, store: SecretStore) -> int:
    """
    Exit codes (launchd restarts only on non-zero): 0 = stopped cleanly or needs manual
    setup, 1 = transient failure worth a restart.
    """
    lock = acquire_lock(paths)
    if lock is None:
        logger.error("Another air-notify daemon is already running")
        return 0

    ntfy = store.get(NTFY)
    if ntfy is None:
        logger.error("No ntfy topic saved; can't send alerts. Run `air-notify set-ntfy`.")
        return 0

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        notifier = Notifier(http, settings.ntfy_server, ntfy["topic"], ntfy.get("token"))
        tracker = Tracker(store, paths.anisette_libs)
        daemon = Daemon(settings, paths, tracker, notifier)
        daemon.start()
        try:
            await tracker.open()
        except SetupError as e:
            logger.error("%s", e)
            daemon.require_setup(str(e))
        else:
            daemon.setup_complete()

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        clean = False
        try:
            while not stop.is_set():
                tick = asyncio.create_task(daemon.tick())
                stopping = asyncio.create_task(stop.wait())
                done, _ = await asyncio.wait({tick, stopping}, return_when=asyncio.FIRST_COMPLETED)
                if stopping in done:
                    tick.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await tick
                    break
                stopping.cancel()
                delay = min(tick.result(), IDLE_CHECK_S)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay)
            clean = True
        finally:
            # Only a signal-driven exit counts as clean; a crash leaves `running` set so the
            # next start alerts and counts it toward the crash-loop safeguard.
            if clean:
                daemon.stop()
            await tracker.close()
            logger.info("Stopped")
    return 0
