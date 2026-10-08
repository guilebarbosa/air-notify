"""Command-line entry point. Interactive commands never echo secrets or raw coordinates."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import os
import re
import signal
import stat
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
from aiohttp import web
from findmy import (
    AsyncAppleAccount,
    FindMyAccessory,
    InvalidCredentialsError,
    LocalAnisetteProvider,
    LoginState,
    SmsSecondFactorMethod,
    TrustedDeviceSecondFactorMethod,
)

from .config import Circle, ConfigError, Paths, Settings, load_settings
from .daemon import acquire_lock, daemon_pid, run_daemon
from .geofence import Presence, classify, distance_m, outside_by_m
from .history import History
from .importer import ExportFormatError, load_accessories
from .keystore import AIRTAG, MAP_KEY, NTFY, SESSION, SecretStore, default_store
from .maps import STYLES, map_key
from .notify import Alert, Notifier
from .state import load_state
from .tracker import FetchError, SetupError, Tracker
from .viewer import create_app

DEFAULT_NTFY_SERVER = Settings(zones=()).ntfy_server


def setup_logging(level: int) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # findmy logs the Apple ID at INFO; anisette logs device secrets at DEBUG.
    for noisy in ("findmy", "anisette"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# --- login -----------------------------------------------------------------------------------


async def cmd_login(paths: Paths, store: SecretStore) -> int:
    previous = store.get(SESSION)
    if previous:
        # Reuse the device identity (ids + anisette provisioning): every brand-new identity
        # adds a device to the Apple account, and too many break login.
        logged_out = {**previous, "login": {"state": LoginState.LOGGED_OUT.value, "data": {}}}
        account = AsyncAppleAccount.from_json(logged_out, anisette_libs_path=paths.anisette_libs)
        default_user = previous["account"].get("username") or ""
    else:
        account = AsyncAppleAccount(LocalAnisetteProvider(libs_path=paths.anisette_libs))
        default_user = ""

    try:
        prompt = f"Apple ID [{default_user}]: " if default_user else "Apple ID: "
        username = (await asyncio.to_thread(input, prompt)).strip() or default_user
        password = await asyncio.to_thread(getpass.getpass, "Apple ID password (hidden): ")
        if not username or not password:
            print("Apple ID and password are required.")
            return 1

        print("Signing in…")
        state = await account.login(username, password)
        if state == LoginState.REQUIRE_2FA:
            state = await _two_factor(account)
        if state != LoginState.LOGGED_IN:
            print(f"Login didn't complete (state: {state.name}). Nothing was saved.")
            return 1

        store.put(SESSION, account.to_json())
        paths.resume_flag.touch(mode=0o600)
        print(f"Logged in. Session saved to {store.label}.")
        return 0
    except InvalidCredentialsError:
        print("Apple rejected the Apple ID or password. Nothing was saved.")
        return 1
    finally:
        await account.close()


async def _two_factor(account: AsyncAppleAccount) -> LoginState:
    methods = await account.get_2fa_methods()
    if not methods:
        print("No supported 2FA method. (Passkeys and security keys aren't supported by FindMy.py.)")
        return account.login_state

    for i, method in enumerate(methods, 1):
        if isinstance(method, TrustedDeviceSecondFactorMethod):
            print(f"  {i}. Code on a trusted Apple device")
        elif isinstance(method, SmsSecondFactorMethod):
            print(f"  {i}. SMS to {method.phone_number}")
    choice = (await asyncio.to_thread(input, "Choose a 2FA method [1]: ")).strip() or "1"
    if not choice.isdigit() or not 1 <= int(choice) <= len(methods):
        print("Invalid choice.")
        return account.login_state

    method = methods[int(choice) - 1]
    await method.request()
    code = (await asyncio.to_thread(input, "Enter the code: ")).strip()
    return await method.submit(code)


# --- import-airtag / set-ntfy ----------------------------------------------------------------


def cmd_import_airtag(
    paths: Paths,
    store: SecretStore,
    path: Path,
    *,
    alignment: Path | None,
    beacon: str | None,
    delete_source: bool,
    yes: bool,
) -> int:
    from_pipe = str(path) == "-"
    try:
        if from_pipe:
            accessories = {"stdin": FindMyAccessory.from_json(json.load(sys.stdin))}
        else:
            accessories = load_accessories(path, alignment)
    except (ExportFormatError, OSError, ValueError, KeyError, TypeError) as e:
        # Only the type for piped input: the error text could quote the key material.
        print(f"Can't read {'the piped AirTag keys' if from_pipe else path}: {type(e).__name__ if from_pipe else e}")
        return 1

    if beacon is None and len(accessories) > 1:
        print("The export has several items; choose one with --beacon:")
        for beacon_id, acc in accessories.items():
            print(f"  {beacon_id}  {acc.name or '?'} ({acc.model or '?'})")
        return 1
    if beacon is not None and beacon not in accessories:
        print(f"No item {beacon!r} in the export.")
        return 1
    accessory = accessories[beacon] if beacon else next(iter(accessories.values()))

    if store.get(AIRTAG) is not None and not yes:
        if from_pipe:  # stdin is the keys, so we can't ask
            print("AirTag keys are already saved; add --yes to replace them.")
            return 1
        if input("Replace the saved AirTag keys? [y/N] ").strip().lower() != "y":
            return 1

    store.put(AIRTAG, accessory.to_json())
    paths.resume_flag.touch(mode=0o600)
    print(f"Imported {accessory.name or 'the AirTag'} ({accessory.model or 'unknown model'}) into {store.label}.")

    if from_pipe:
        return 0
    if delete_source:
        for p in (path, alignment):
            if p is not None:
                p.unlink()
        print("Deleted the export file(s).")
    else:
        print(f"Now delete {path} (keep a copy in 1Password first if you want a backup).")
    return 0


def _stdout_is_pipe() -> bool:
    try:
        return stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode)
    except OSError, ValueError:  # e.g. stdout replaced by an in-memory buffer
        return False


def cmd_export_airtag(store: SecretStore) -> int:
    """Write the saved AirTag keys to a pipe, to move them to another machine over SSH."""
    if not _stdout_is_pipe():
        print(
            "Refusing to write the AirTag's private keys to a terminal or file. Pipe them instead:\n"
            "  air-notify export-airtag | ssh <user>@<pi> '~/.local/bin/air-notify import-airtag - --yes'",
            file=sys.stderr,
        )
        return 1
    data = store.get(AIRTAG)
    if data is None:
        print("No AirTag keys saved.", file=sys.stderr)
        return 1
    json.dump(data, sys.stdout)
    sys.stdout.flush()
    print("AirTag keys written to the pipe.", file=sys.stderr)
    return 0


async def cmd_set_ntfy(store: SecretStore, server: str) -> int:
    print("Subscribe to a long, random topic in the ntfy app first, then enter it here.")
    topic = (await asyncio.to_thread(getpass.getpass, "ntfy topic (hidden): ")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
        print("Topics may only contain letters, digits, '-' and '_' (max 64).")
        return 1
    if len(topic) < 20:
        print("Warning: short topics are guessable, and anyone who guesses it can read the alerts.")
    token_prompt = "ntfy access token if your server needs one (hidden, Enter for none): "  # noqa: S105
    token = (await asyncio.to_thread(getpass.getpass, token_prompt)).strip() or None

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        try:
            await Notifier(http, server, topic, token).send(
                Alert("air-notify connected", "Test message: AirTag alerts will arrive here.", ("white_check_mark",))
            )
        except aiohttp.ClientResponseError as e:
            print(f"ntfy rejected the test message (HTTP {e.status}). Nothing was saved.")
            return 1
        except (aiohttp.ClientError, TimeoutError) as e:
            print(f"Couldn't reach {server} ({type(e).__name__}). Nothing was saved.")
            return 1

    store.put(NTFY, {"topic": topic, "token": token})
    print(f"Test message sent and topic saved to {store.label}. Check your phone.")
    return 0


async def cmd_set_map_key(store: SecretStore, style_name: str) -> int:
    """Save the map tile key after checking the provider accepts it. Never prints the key or tile URLs."""
    style = STYLES[style_name if STYLES[style_name].needs_key else "carto-voyager"]
    key = (await asyncio.to_thread(getpass.getpass, "Map key (hidden): ")).strip()
    if not key or any(ch.isspace() for ch in key):
        print("That doesn't look like a key. Nothing was saved.")
        return 1

    async def tile(url: str) -> bytes:
        async with http.get(url.replace("{z}/{x}/{y}{r}", "3/4/2")) as response:
            response.raise_for_status()
            return await response.read()

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        try:
            # Without a valid key the provider answers with a watermark image, so compare the two.
            with_key, without_key = await tile(style.tile_url(key)), await tile(style.tile_url(None))
        except aiohttp.ClientResponseError as e:
            print(f"The map provider rejected the key (HTTP {e.status}). Nothing was saved.")
            return 1
        except (aiohttp.ClientError, TimeoutError) as e:
            print(f"Couldn't reach the map provider ({type(e).__name__}). Nothing was saved.")
            return 1
    if with_key == without_key:
        print("The map provider didn't accept the key (its tiles are still watermarked). Nothing was saved.")
        return 1

    store.put(MAP_KEY, {"key": key})
    print(f"Map key saved to {store.label}. Reload the viewer; no restart needed.")
    return 0


# --- check / status / resume -----------------------------------------------------------------


def _ago(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h {minutes % 60} min"
    return f"{minutes // (24 * 60)} days"


def _distance(meters: float) -> str:
    return f"{round(meters, -1):.0f} m" if meters < 1000 else f"{meters / 1000:.1f} km"


async def cmd_check(settings: Settings, paths: Paths, store: SecretStore, *, force: bool) -> int:
    state = load_state(paths.state)
    if state.paused is not None and not force:
        print(f"The daemon is stopped: {state.paused.detail}. Use --force to fetch anyway.")
        return 1

    tracker = Tracker(store, paths.anisette_libs)
    try:
        await tracker.open()
        fixes = await tracker.fetch()
    except SetupError as e:
        print(e)
        return 1
    except FetchError as e:
        print(f"Fetch failed: {e.detail}")
        return 1
    finally:
        await tracker.close()

    if not fixes:
        print("No reports in the last 7 days. (None arrive while the AirTag is near one of your own devices.)")
        return 0

    latest = max(fixes, key=lambda f: f.timestamp)
    age = datetime.now().astimezone() - latest.timestamp
    print(f"{len(fixes)} report(s). Latest: {_ago(age)} ago, accuracy ±{latest.accuracy_m:.0f} m")
    for zone in settings.zones:
        where = {Presence.INSIDE: "inside", Presence.OUTSIDE: "outside", None: "at the edge (hysteresis band)"}[
            classify(zone, latest, settings.exit_buffer_m)
        ]
        if isinstance(zone.shape, Circle):
            d = distance_m(zone.shape.lat, zone.shape.lon, latest.lat, latest.lon)
            print(f"  {zone.name}: {where}, {_distance(d)} from the centre (radius {zone.shape.radius_m:.0f} m)")
        elif (outside := outside_by_m(zone.shape, latest.lat, latest.lon)) > 0:
            print(f"  {zone.name}: {where}, {_distance(outside)} from its outline")
        else:
            print(f"  {zone.name}: {where} its outline")
    return 0


def cmd_status(paths: Paths) -> int:
    state = load_state(paths.state)
    lock = acquire_lock(paths)
    if lock is not None:
        lock.close()
    print(f"Daemon: {'running' if lock is None else 'not running'}")

    def fmt(ts: datetime | None) -> str:
        return ts.astimezone().strftime("%a %d %b %H:%M") if ts else "never"

    if state.paused is not None:
        print(f"Polling: STOPPED since {fmt(state.paused.since)}: {state.paused.detail}")
    else:
        print(f"Polling: active, next poll {fmt(state.next_poll_at) if state.next_poll_at else 'now'}")
        with contextlib.suppress(ConfigError):
            print(f"Interval now: {load_settings(paths.config).interval_at(datetime.now()):g} min")
    if state.network_failures:
        print(f"Network: {state.network_failures} failed poll(s) in a row")
    print(f"Latest report: {fmt(state.last_report_ts)}")
    for name, presence in state.presence.items():
        print(f"  {name}: {presence}")
    if state.pending_alerts:
        print(f"{len(state.pending_alerts)} alert(s) waiting to be sent")
    return 0


def cmd_poll(paths: Paths, *, timeout_s: float = 120) -> int:
    """Ask the running daemon for a check right now, and print the outcome."""
    pid = daemon_pid(paths)
    if pid is None:
        print("The daemon isn't running. (`air-notify check` does a one-off fetch without it.)")
        return 1
    asked_at = datetime.now().astimezone()
    os.kill(pid, signal.SIGUSR1)
    print("Checking…")

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = load_state(paths.state)
        if state.last_manual is not None and state.last_manual.at >= asked_at:
            print(state.last_manual.detail)
            if state.last_report_ts is not None:
                print(f"Latest report: {state.last_report_ts.astimezone():%H:%M}")
            for name, presence in state.presence.items():
                print(f"  {name}: {presence}")
            return 0 if state.last_manual.status == "ok" else 1
        time.sleep(1)
    print("No answer from the daemon within 2 minutes; check its log.")
    return 1


def cmd_resume(paths: Paths) -> int:
    paths.resume_flag.touch(mode=0o600)
    if load_state(paths.state).paused is not None:
        print("Resume requested; the daemon picks it up within a minute (polls keep their 15-min spacing).")
    else:
        print("Polling isn't stopped; the daemon will just reload its saved secrets.")
    return 0


# --- run -------------------------------------------------------------------------------------


async def _alert_best_effort(store: SecretStore, alert: Alert) -> None:
    """For failures before the config is loaded: try the default server, never raise."""
    try:
        ntfy = store.get(NTFY)
        if ntfy is None:
            return
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
            await Notifier(http, DEFAULT_NTFY_SERVER, ntfy["topic"], ntfy.get("token")).send(alert)
    except Exception:
        logging.getLogger(__name__).warning("Couldn't send the startup-failure alert")


def cmd_run(paths: Paths, store: SecretStore) -> int:
    try:
        settings = load_settings(paths.config)
    except ConfigError as e:
        logging.getLogger(__name__).error("%s", e)
        asyncio.run(_alert_best_effort(store, Alert("air-notify can't start", f"Config error: {e}", ("warning",), 4)))
        return 0  # a restart won't fix the config; don't let launchd loop
    return asyncio.run(run_daemon(settings, paths, store))


def cmd_view(settings: Settings, paths: Paths, store: SecretStore) -> int:
    """Serve the map viewer on its own (the daemon also serves it when [viewer] is enabled)."""
    if not settings.history_days:
        print("Location history is off: set history_days in config.toml (see config.example.toml).")
        return 1
    host, port = settings.viewer.host, settings.viewer.port
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host  # noqa: S104
    print(f"Map viewer on http://{shown}:{port} (Ctrl+C to stop)")
    web.run_app(
        create_app(settings, History(paths.history, settings.history_days), map_key=lambda: map_key(store)),
        host=host,
        port=port,
        access_log=None,
        print=None,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="air-notify", description="AirTag arrive/leave notifications.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="log in to Apple (interactive, with 2FA) and save the session")

    p = sub.add_parser("import-airtag", help="import AirTag keys from an export")
    p.add_argument("path", type=Path, help="OpenTagViewer export .zip, beacon .plist, FindMy.py .json, or - (stdin)")
    p.add_argument("--alignment", type=Path, help="KeyAlignmentRecord .plist (only with a single .plist)")
    p.add_argument("--beacon", help="which item to import when the export has several")
    p.add_argument("--delete-source", action="store_true", help="delete the export file(s) after importing")
    p.add_argument("--yes", action="store_true", help="replace existing keys without asking")

    sub.add_parser("export-airtag", help="write the saved AirTag keys to a pipe (to move them over SSH)")
    sub.add_parser("set-ntfy", help="save the ntfy topic and send a test message")
    sub.add_parser("set-map-key", help="save the map tile key (e.g. CARTO) for the viewer, after checking it works")

    p = sub.add_parser("check", help="fetch once and show where the AirTag is relative to each zone")
    p.add_argument("--force", action="store_true", help="fetch even if the daemon has stopped polling")

    sub.add_parser("status", help="show the daemon's state")
    sub.add_parser("resume", help="resume polling after a safeguard stopped it")
    sub.add_parser("view", help="serve the location-history map viewer on its own")
    sub.add_parser("poll", help="ask the running daemon to check right now")
    sub.add_parser("run", help="run the daemon (used by the LaunchAgent)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(logging.INFO if args.command == "run" else logging.WARNING)
    paths = Paths.default()
    store = default_store(paths.root)

    try:
        match args.command:
            case "login":
                return asyncio.run(cmd_login(paths, store))
            case "import-airtag":
                return cmd_import_airtag(
                    paths,
                    store,
                    args.path,
                    alignment=args.alignment,
                    beacon=args.beacon,
                    delete_source=args.delete_source,
                    yes=args.yes,
                )
            case "export-airtag":
                return cmd_export_airtag(store)
            case "set-ntfy":
                try:
                    server = load_settings(paths.config).ntfy_server
                except ConfigError:
                    server = DEFAULT_NTFY_SERVER
                return asyncio.run(cmd_set_ntfy(store, server))
            case "set-map-key":
                try:
                    style_name = load_settings(paths.config).viewer.map
                except ConfigError:
                    style_name = "carto-voyager"
                return asyncio.run(cmd_set_map_key(store, style_name))
            case "check":
                return asyncio.run(cmd_check(load_settings(paths.config), paths, store, force=args.force))
            case "status":
                return cmd_status(paths)
            case "resume":
                return cmd_resume(paths)
            case "view":
                return cmd_view(load_settings(paths.config), paths, store)
            case "poll":
                return cmd_poll(paths)
            case "run":
                return cmd_run(paths, store)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 2
