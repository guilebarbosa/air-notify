"""Paths and settings (zones, polling) loaded from a TOML file."""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Polling faster than this has gotten Apple accounts banned; see README.
MIN_POLL_MINUTES = 15


class ConfigError(ValueError):
    """The config file is missing or invalid."""


@dataclass(frozen=True)
class Paths:
    """Everything air-notify keeps on disk. Secrets are never stored here (see keystore.py)."""

    root: Path

    @classmethod
    def default(cls) -> Paths:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        root = Path(os.environ.get("AIR_NOTIFY_HOME") or config_home / "air-notify")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        return cls(root)

    @property
    def config(self) -> Path:
        return self.root / "config.toml"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def anisette_libs(self) -> Path:
        return self.root / "ani_libs.bin"

    @property
    def resume_flag(self) -> Path:
        return self.root / "resume"

    @property
    def lock(self) -> Path:
        return self.root / "daemon.lock"

    @property
    def history(self) -> Path:
        return self.root / "history.jsonl"


@dataclass(frozen=True)
class Zone:
    name: str
    lat: float
    lon: float
    radius_m: float
    # Optional alert text for this zone, overriding [messages] arrive/leave. Useful in
    # languages where the wording depends on the place ("Chegou na escola", "Chegou em casa").
    arrive: str | None = None
    leave: str | None = None


@dataclass(frozen=True)
class Messages:
    """Alert text for zone events; `{zone}` and `{time}` are filled in."""

    arrive: str = "Arrived at {zone}"
    leave: str = "Left {zone}"
    time: str = "Seen at {time}"


@dataclass(frozen=True)
class Interval:
    """From `start` (local time of day) until the next entry's start, poll every `minutes`."""

    start: time
    minutes: float


@dataclass(frozen=True)
class Viewer:
    """The map viewer. host "0.0.0.0" makes it reachable from other devices on your network."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass(frozen=True)
class Settings:
    zones: tuple[Zone, ...]
    poll_interval_minutes: float = MIN_POLL_MINUTES
    max_accuracy_m: float = 100
    exit_buffer_m: float = 50
    ntfy_server: str = "https://ntfy.sh"
    messages: Messages = Messages()
    history_days: int = 0  # 0 = don't record locations
    viewer: Viewer = Viewer()
    intervals: tuple[Interval, ...] = ()  # sorted by start; empty = poll_interval_minutes all day

    def interval_at(self, when: datetime) -> float:
        """Poll interval (minutes) in effect at `when`, local time."""
        if not self.intervals:
            return self.poll_interval_minutes
        now = when.astimezone().time()
        current = self.intervals[-1]  # before the day's first start, yesterday's last entry still applies
        for interval in self.intervals:
            if interval.start <= now:
                current = interval
        return current.minutes

    def next_poll(self, after: datetime) -> datetime:
        """
        When to poll next after polling at `after`.

        Normally `after` + the interval in effect then. If a shorter interval starts in the
        meantime (e.g. 30 -> 15 min at 07:00), poll at that start instead, but never sooner
        than MIN_POLL_MINUTES after `after`.
        """
        current = self.interval_at(after)
        due = after + timedelta(minutes=current)
        floor = after + timedelta(minutes=MIN_POLL_MINUTES)
        for start in self._starts_between(after, due):
            if self.interval_at(start) < current:
                due = min(due, max(start, floor))
        return due

    def _starts_between(self, after: datetime, until: datetime) -> Iterator[datetime]:
        today = after.astimezone().date()
        for day in (today, today + timedelta(days=1)):
            for interval in self.intervals:
                start = datetime.combine(day, interval.start).astimezone()  # local time, DST-aware
                if after < start < until:
                    yield start

    def messages_for(self, zone_name: str) -> Messages:
        """The [messages] text, with the zone's own arrive/leave if it sets them."""
        zone = next((z for z in self.zones if z.name == zone_name), None)
        if zone is None:
            return self.messages
        return replace(
            self.messages,
            arrive=zone.arrive or self.messages.arrive,
            leave=zone.leave or self.messages.leave,
        )


_SETTINGS_KEYS = {
    "poll_interval_minutes",
    "max_accuracy_m",
    "exit_buffer_m",
    "ntfy_server",
    "messages",
    "history_days",
    "viewer",
    "intervals",
    "zones",
}
_INTERVAL_KEYS = {"time", "interval"}
_VIEWER_KEYS = {"enabled", "host", "port"}
_ZONE_REQUIRED = {"name", "lat", "lon", "radius_m"}
_ZONE_OPTIONAL = {"arrive", "leave"}
_MESSAGE_KEYS = {"arrive", "leave", "time"}


def load_settings(path: Path) -> Settings:
    """Load and validate the config. Tightens its permissions to 0600 (it holds home/school coordinates)."""
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        msg = f"No config at {path}. Copy config.example.toml there and edit it."
        raise ConfigError(msg) from None
    except tomllib.TOMLDecodeError as e:
        msg = f"Invalid TOML in {path}: {e}"
        raise ConfigError(msg) from None

    if path.stat().st_mode & 0o077:
        path.chmod(0o600)
        logger.info("Restricted %s to mode 0600", path)

    return parse_settings(raw)


def parse_settings(raw: dict) -> Settings:
    if unknown := set(raw) - _SETTINGS_KEYS:
        msg = f"Unknown config keys: {', '.join(sorted(unknown))}"
        raise ConfigError(msg)

    zones = tuple(_parse_zone(z) for z in raw.get("zones", []))
    if not zones:
        msg = "Config needs at least one [[zones]] entry"
        raise ConfigError(msg)
    names = [z.name for z in zones]
    if len(set(names)) != len(names):
        msg = "Zone names must be unique"
        raise ConfigError(msg)

    settings = Settings(
        zones=zones,
        poll_interval_minutes=float(raw.get("poll_interval_minutes", MIN_POLL_MINUTES)),
        max_accuracy_m=float(raw.get("max_accuracy_m", 100)),
        exit_buffer_m=float(raw.get("exit_buffer_m", 50)),
        ntfy_server=str(raw.get("ntfy_server", "https://ntfy.sh")).rstrip("/"),
        messages=_parse_messages(raw.get("messages", {})),
        history_days=int(raw.get("history_days", 0)),
        viewer=_parse_viewer(raw.get("viewer", {})),
        intervals=_parse_intervals(raw.get("intervals", [])),
    )
    if settings.poll_interval_minutes < MIN_POLL_MINUTES:
        msg = f"poll_interval_minutes must be >= {MIN_POLL_MINUTES} to protect your Apple account"
        raise ConfigError(msg)
    if settings.max_accuracy_m <= 0 or settings.exit_buffer_m < 0:
        msg = "max_accuracy_m must be > 0 and exit_buffer_m >= 0"
        raise ConfigError(msg)
    if not settings.ntfy_server.startswith("https://"):
        msg = "ntfy_server must be an https:// URL"
        raise ConfigError(msg)
    if not 0 <= settings.history_days <= 366:
        msg = "history_days must be between 0 (off) and 366"
        raise ConfigError(msg)
    if settings.viewer.enabled and settings.history_days == 0:
        msg = "[viewer] shows the location history, so it needs history_days > 0"
        raise ConfigError(msg)
    return settings


def _parse_intervals(raw: list) -> tuple[Interval, ...]:
    intervals = []
    for entry in raw:
        if set(entry) != _INTERVAL_KEYS:
            msg = 'Each [[intervals]] entry needs exactly: time = "HH:MM" and interval = <minutes>'
            raise ConfigError(msg)
        interval = Interval(_parse_time(entry["time"]), float(entry["interval"]))
        if interval.minutes < MIN_POLL_MINUTES:
            msg = f"[[intervals]] at {interval.start:%H:%M}: interval must be >= {MIN_POLL_MINUTES} minutes"
            raise ConfigError(msg)
        intervals.append(interval)
    starts = [i.start for i in intervals]
    if len(set(starts)) != len(starts):
        msg = "[[intervals]] times must be unique"
        raise ConfigError(msg)
    return tuple(sorted(intervals, key=lambda i: i.start))


def _parse_time(value: object) -> time:
    if isinstance(value, time):  # a TOML local time, e.g. 07:00:00
        return value.replace(second=0, microsecond=0)
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%H:%M").time()
        except ValueError:
            pass
    msg = f'[[intervals]] time must look like "07:00" (in quotes), got {value!r}'
    raise ConfigError(msg)


def _parse_viewer(raw: dict) -> Viewer:
    if unknown := set(raw) - _VIEWER_KEYS:
        msg = f"Unknown [viewer] keys: {', '.join(sorted(unknown))}"
        raise ConfigError(msg)
    viewer = Viewer(
        enabled=bool(raw.get("enabled", False)),
        host=str(raw.get("host", "127.0.0.1")),
        port=int(raw.get("port", 8080)),
    )
    if not 1 <= viewer.port <= 65535:
        msg = "[viewer] port must be between 1 and 65535"
        raise ConfigError(msg)
    return viewer


def _parse_messages(raw: dict) -> Messages:
    if unknown := set(raw) - _MESSAGE_KEYS:
        msg = f"Unknown [messages] keys: {', '.join(sorted(unknown))}"
        raise ConfigError(msg)
    messages = Messages(**{key: str(value) for key, value in raw.items()})
    for key in _MESSAGE_KEYS:
        _check_template(getattr(messages, key), f"[messages] {key}")
    return messages


def _check_template(text: str, where: str) -> str:
    try:
        text.format(zone="Zone", time="12:00")
    except (KeyError, IndexError, ValueError) as e:
        msg = f"{where} can only use {{zone}} and {{time}} ({type(e).__name__}: {e})"
        raise ConfigError(msg) from None
    return text


def _parse_zone(raw: dict) -> Zone:
    label = repr(raw.get("name", "?"))
    if missing := _ZONE_REQUIRED - set(raw):
        msg = f"Zone {label} is missing: {', '.join(sorted(missing))}"
        raise ConfigError(msg)
    if unknown := set(raw) - _ZONE_REQUIRED - _ZONE_OPTIONAL:
        msg = f"Zone {label} has unknown keys: {', '.join(sorted(unknown))}"
        raise ConfigError(msg)
    zone = Zone(
        name=str(raw["name"]).strip(),
        lat=float(raw["lat"]),
        lon=float(raw["lon"]),
        radius_m=float(raw["radius_m"]),
        arrive=_check_template(str(raw["arrive"]), f"Zone {label} arrive") if "arrive" in raw else None,
        leave=_check_template(str(raw["leave"]), f"Zone {label} leave") if "leave" in raw else None,
    )
    if not zone.name:
        msg = "Zone name can't be empty"
        raise ConfigError(msg)
    if zone.lat == 0 and zone.lon == 0:
        msg = f"Zone {zone.name!r} still has the example's placeholder coordinates (0, 0)"
        raise ConfigError(msg)
    if not (-90 <= zone.lat <= 90 and -180 <= zone.lon <= 180):
        msg = f"Zone {zone.name!r} has out-of-range coordinates"
        raise ConfigError(msg)
    if zone.radius_m <= 0:
        msg = f"Zone {zone.name!r} needs a positive radius_m"
        raise ConfigError(msg)
    return zone
