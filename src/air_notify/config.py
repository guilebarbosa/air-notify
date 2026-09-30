"""Paths and settings (zones, polling) loaded from a TOML file."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Zone:
    name: str
    lat: float
    lon: float
    radius_m: float


@dataclass(frozen=True)
class Messages:
    """Alert text for zone events; `{zone}` and `{time}` are filled in."""

    arrive: str = "Arrived at {zone}"
    leave: str = "Left {zone}"
    time: str = "Seen at {time}"


@dataclass(frozen=True)
class Settings:
    zones: tuple[Zone, ...]
    poll_interval_minutes: float = MIN_POLL_MINUTES
    max_accuracy_m: float = 100
    exit_buffer_m: float = 50
    ntfy_server: str = "https://ntfy.sh"
    messages: Messages = Messages()


_SETTINGS_KEYS = {"poll_interval_minutes", "max_accuracy_m", "exit_buffer_m", "ntfy_server", "messages", "zones"}
_ZONE_KEYS = {"name", "lat", "lon", "radius_m"}
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
    return settings


def _parse_messages(raw: dict) -> Messages:
    if unknown := set(raw) - _MESSAGE_KEYS:
        msg = f"Unknown [messages] keys: {', '.join(sorted(unknown))}"
        raise ConfigError(msg)
    messages = Messages(**{key: str(value) for key, value in raw.items()})
    for key in _MESSAGE_KEYS:
        try:
            getattr(messages, key).format(zone="Zone", time="12:00")
        except (KeyError, IndexError, ValueError) as e:
            msg = f"[messages] {key} can only use {{zone}} and {{time}} ({type(e).__name__}: {e})"
            raise ConfigError(msg) from None
    return messages


def _parse_zone(raw: dict) -> Zone:
    if set(raw) != _ZONE_KEYS:
        msg = f"Each zone needs exactly these keys: {', '.join(sorted(_ZONE_KEYS))}"
        raise ConfigError(msg)
    zone = Zone(
        name=str(raw["name"]).strip(),
        lat=float(raw["lat"]),
        lon=float(raw["lon"]),
        radius_m=float(raw["radius_m"]),
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
