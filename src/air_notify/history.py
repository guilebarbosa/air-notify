"""
Location history: one JSON object per line, in plain text (mode 0600), kept for N days.

    {"t": "2026-09-30T08:12:05+02:00", "lat": 52.12345, "lon": 13.12345, "acc": 35}
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .geofence import Fix

logger = logging.getLogger(__name__)


class History:
    def __init__(self, path: Path, keep_days: int) -> None:
        self._path = path
        self._keep = timedelta(days=keep_days)
        self._pruned_on: date | None = None

    def append(self, fixes: Iterable[Fix], now: datetime) -> int:
        """Append fixes oldest-first; prunes old entries once a day. Returns how many were written."""
        if self._pruned_on != now.date():
            self.prune(now)

        lines = [
            json.dumps(
                {
                    "t": f.timestamp.astimezone().isoformat(timespec="seconds"),
                    "lat": round(f.lat, 6),
                    "lon": round(f.lon, 6),
                    "acc": f.accuracy_m,
                }
            )
            + "\n"
            for f in sorted(fixes, key=lambda f: f.timestamp)
        ]
        if lines:
            fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a") as f:
                f.write("".join(lines))
        return len(lines)

    def prune(self, now: datetime) -> None:
        """Drop entries older than the retention period."""
        self._pruned_on = now.date()
        if not self._path.exists():
            return
        cutoff = now - self._keep
        lines = self._path.read_text().splitlines(keepends=True)
        kept = [line for line in lines if (e := _parse(line)) is not None and _time(e) >= cutoff]
        if len(kept) == len(lines):
            return

        # mkstemp creates the file with mode 0600; os.replace makes the rewrite atomic.
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".history-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.writelines(kept)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        logger.info("History: dropped %d entries older than %d days", len(lines) - len(kept), self._keep.days)

    def days(self) -> list[tuple[date, int]]:
        """Recorded days (local time) with their number of points, newest first."""
        counts = Counter(_time(e).date() for e in self._entries())
        return sorted(counts.items(), reverse=True)

    def points(self, day: date) -> list[dict[str, Any]]:
        """That day's entries (local time), oldest first."""
        return sorted((e for e in self._entries() if _time(e).date() == day), key=_time)

    def _entries(self) -> list[dict[str, Any]]:
        try:
            text = self._path.read_text()
        except FileNotFoundError:
            return []
        return [e for line in text.splitlines() if (e := _parse(line)) is not None]


def _parse(line: str) -> dict[str, Any] | None:
    # A half-written last line (power cut mid-append) is skipped rather than fatal.
    try:
        entry = json.loads(line)
        _time(entry)
        float(entry["lat"]), float(entry["lon"])
    except ValueError, KeyError, TypeError:
        return None
    return entry


def _time(entry: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(entry["t"]).astimezone()
