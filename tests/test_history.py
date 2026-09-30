from __future__ import annotations

import json
import stat
from datetime import timedelta

from conftest import SCHOOL, T0, north_of

from air_notify.geofence import Fix
from air_notify.history import History


def fix(minutes: float, meters: float = 0, accuracy: float = 20) -> Fix:
    lat, lon = north_of(SCHOOL, meters)
    return Fix(T0 + timedelta(minutes=minutes), lat, lon, accuracy)


def test_append_writes_private_json_lines(paths):
    history = History(paths.history, keep_days=30)
    assert history.append([fix(10), fix(0)], now=T0) == 2

    assert stat.S_IMODE(paths.history.stat().st_mode) == 0o600
    lines = [json.loads(line) for line in paths.history.read_text().splitlines()]
    assert [line["t"] for line in lines] == [
        fix(0).timestamp.astimezone().isoformat(timespec="seconds"),
        fix(10).timestamp.astimezone().isoformat(timespec="seconds"),
    ]
    assert set(lines[0]) == {"t", "lat", "lon", "acc"}


def test_days_and_points(paths):
    history = History(paths.history, keep_days=30)
    history.append([fix(0), fix(5), fix(24 * 60)], now=T0)

    days = history.days()
    assert [n for _, n in days] == [1, 2]  # newest day first
    assert days[0][0] > days[1][0]
    points = history.points(days[1][0])
    assert [p["t"] for p in points] == sorted(p["t"] for p in points)
    assert len(points) == 2


def test_prune_drops_old_entries_once_a_day(paths):
    history = History(paths.history, keep_days=2)
    history.append([fix(-3 * 24 * 60), fix(-1 * 24 * 60)], now=T0 - timedelta(days=5))  # first write, nothing old yet
    assert len(paths.history.read_text().splitlines()) == 2

    history.append([fix(0)], now=T0)  # a new day: prunes before appending
    kept = [json.loads(line)["t"] for line in paths.history.read_text().splitlines()]
    assert len(kept) == 2  # the 3-day-old entry is gone
    assert stat.S_IMODE(paths.history.stat().st_mode) == 0o600
    assert [p.name for p in paths.root.iterdir()] == ["history.jsonl"]  # no temp files left


def test_half_written_line_is_skipped(paths):
    history = History(paths.history, keep_days=30)
    history.append([fix(0)], now=T0)
    with paths.history.open("a") as f:
        f.write('{"t": "2026-09-29T08:10:00+00:00", "lat": 52.0')  # power cut mid-write
    assert sum(n for _, n in history.days()) == 1


def test_missing_file_is_empty(paths):
    assert History(paths.history, keep_days=30).days() == []
