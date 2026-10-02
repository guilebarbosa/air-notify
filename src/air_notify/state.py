"""Non-secret daemon state, persisted as JSON (mode 0600, atomic writes)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .geofence import Presence
from .notify import Alert


@dataclass
class Pause:
    reason: str  # "auth" | "apple" | "crash_loop"
    detail: str
    since: datetime


@dataclass
class ManualCheck:
    """Outcome of a check you asked for (viewer button or `air-notify poll`)."""

    at: datetime
    status: str  # "ok" | "failed" | "cooldown" | "stopped"
    detail: str


@dataclass
class State:
    presence: dict[str, Presence] = field(default_factory=dict)
    last_report_ts: datetime | None = None
    # Reserved before each request, so restarts and crash loops can't poll early.
    next_poll_at: datetime | None = None
    last_poll_at: datetime | None = None
    last_manual: ManualCheck | None = None
    paused: Pause | None = None
    network_failures: int = 0
    # True while the daemon runs; still True at startup means the last run died uncleanly.
    running: bool = False
    unclean_exits: list[datetime] = field(default_factory=list)
    pending_alerts: list[Alert] = field(default_factory=list)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def load_state(path: Path) -> State:
    try:
        raw: dict[str, Any] = json.loads(path.read_text())
    except FileNotFoundError:
        return State()

    paused = raw.get("paused")
    manual = raw.get("last_manual")
    return State(
        presence={name: Presence(p) for name, p in raw.get("presence", {}).items()},
        last_report_ts=_dt(raw.get("last_report_ts")),
        next_poll_at=_dt(raw.get("next_poll_at")),
        last_poll_at=_dt(raw.get("last_poll_at")),
        last_manual=(
            ManualCheck(datetime.fromisoformat(manual["at"]), manual["status"], manual["detail"]) if manual else None
        ),
        paused=Pause(paused["reason"], paused["detail"], datetime.fromisoformat(paused["since"])) if paused else None,
        network_failures=raw.get("network_failures", 0),
        running=raw.get("running", False),
        unclean_exits=[datetime.fromisoformat(t) for t in raw.get("unclean_exits", [])],
        pending_alerts=[Alert.from_json(a) for a in raw.get("pending_alerts", [])],
    )


def save_state(path: Path, state: State) -> None:
    raw = {
        "presence": {name: str(p) for name, p in state.presence.items()},
        "last_report_ts": _iso(state.last_report_ts),
        "next_poll_at": _iso(state.next_poll_at),
        "last_poll_at": _iso(state.last_poll_at),
        "last_manual": (
            {
                "at": state.last_manual.at.isoformat(),
                "status": state.last_manual.status,
                "detail": state.last_manual.detail,
            }
            if state.last_manual
            else None
        ),
        "paused": (
            {"reason": state.paused.reason, "detail": state.paused.detail, "since": state.paused.since.isoformat()}
            if state.paused
            else None
        ),
        "network_failures": state.network_failures,
        "running": state.running,
        "unclean_exits": [t.isoformat() for t in state.unclean_exits],
        "pending_alerts": [a.to_json() for a in state.pending_alerts],
    }
    # mkstemp creates the file with mode 0600; os.replace makes the write atomic.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(raw, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
