"""
Map viewer for the location history: the JSON API, plus the web UI built from web/ (Svelte).

The UI bundles Leaflet; the only outside host the page loads from is the OpenStreetMap tile
server. The coordinates themselves only travel between this server and your browser.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Protocol

from aiohttp import web

from .config import Circle, Settings, Zone
from .history import History
from .maps import DEFAULT_STYLE, STYLES
from .timeline import day_events
from .state import ManualCheck

logger = logging.getLogger(__name__)

# `npm run build` in web/ writes here; the files are committed so deployments don't need Node.
STATIC = Path(__file__).parent / "static"

# Required on POSTs. Browsers won't let another website send a custom header here without
# a CORS preflight, which this server never approves, so other sites can't trigger checks.
CHECK_HEADER = "X-Air-Notify"


def content_security_policy(*tile_hosts: str) -> str:
    return "; ".join(
        (
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",  # Leaflet positions elements with inline styles
            f"img-src 'self' data: {' '.join(sorted(set(tile_hosts)))}",
            "font-src 'self'",  # the bundled Lexend (wordmark)
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        )
    )


CSP_KEY = web.AppKey("csp", str)


class Controls(Protocol):
    """What the daemon offers the viewer when it serves it (absent with `air-notify view`)."""

    async def poll_now(self) -> ManualCheck: ...

    def snapshot(self) -> dict[str, str | None]: ...


def host_allowed(host: str) -> bool:
    """
    Only answer requests addressed to an IP, localhost, a .local name or this machine's name.

    Blocks DNS rebinding: a website you visit pointing its own domain at this machine to
    read your history. Such requests carry that domain in the Host header.
    """
    name = host.split("]")[0].lstrip("[") if host.startswith("[") else host.rsplit(":", 1)[0]
    name = name.lower().rstrip(".")
    if name in ("localhost", socket.gethostname().lower()) or name.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


@web.middleware
async def _guard(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    if not host_allowed(request.host):
        logger.warning("Viewer: refused a request for host %r", request.host)
        return web.Response(status=421, text="Misdirected request")
    if request.method == "POST" and request.headers.get(CHECK_HEADER) != "1":
        return web.Response(status=403, text="Forbidden")
    response = await handler(request)
    response.headers["Content-Security-Policy"] = request.app[CSP_KEY]
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Built assets have content hashes in their names, so they can be cached for good.
    immutable = request.path.startswith("/assets/")
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-store"
    return response


def _zone_json(zone: Zone) -> dict:
    """A circle has lat, lon and radius_m; a custom shape has an outline of [lat, lon] corners."""
    if isinstance(zone.shape, Circle):
        return {"name": zone.name, "lat": zone.shape.lat, "lon": zone.shape.lon, "radius_m": zone.shape.radius_m}
    return {"name": zone.name, "outline": [list(corner) for corner in zone.shape.corners]}


def create_app(
    settings: Settings,
    history: History,
    controls: Controls | None = None,
    map_key: Callable[[], str | None] = lambda: None,
) -> web.Application:
    """`map_key` is called per request, so a key saved with `air-notify set-map-key` works without a restart."""
    zones = [_zone_json(z) for z in settings.zones]
    style = STYLES[settings.viewer.map]
    fallback = STYLES[DEFAULT_STYLE]

    async def index(_: web.Request) -> web.StreamResponse:
        page = STATIC / "index.html"
        if not page.is_file():
            return web.Response(status=503, text="The viewer UI isn't built: run `npm ci && npm run build` in web/.")
        return web.FileResponse(page)

    async def days(_: web.Request) -> web.Response:
        return web.json_response([{"date": d.isoformat(), "count": n} for d, n in history.days()])

    async def day(request: web.Request) -> web.Response:
        try:
            which = date.fromisoformat(request.match_info["day"])
        except ValueError:
            raise web.HTTPBadRequest(text="Expected a date like 2026-09-30") from None
        return web.json_response(
            {
                "date": which.isoformat(),
                "points": history.points(which),
                "zones": zones,
                "events": day_events(history, which, settings),
                # The map hides reports less accurate than this, like the alerts do.
                "max_accuracy_m": settings.max_accuracy_m,
            }
        )

    async def map_tiles(_: web.Request) -> web.Response:
        # The key necessarily reaches the browser (it's part of every tile URL); never log it.
        chosen, warning = style, None
        key = map_key() if style.needs_key else None
        if style.needs_key and not key:
            chosen = fallback
            warning = (
                f"No map key saved for {settings.viewer.map}; showing OpenStreetMap. Run `air-notify set-map-key`."
            )
        return web.json_response(
            {
                "url": chosen.tile_url(key),
                "attribution": chosen.attribution,
                "maxZoom": chosen.max_zoom,
                "warning": warning,
            }
        )

    async def status(_: web.Request) -> web.Response:
        if controls is None:
            return web.json_response({"available": False})
        return web.json_response({"available": True, **controls.snapshot()})

    async def poll(_: web.Request) -> web.Response:
        if controls is None:
            return web.json_response(
                {"status": "unavailable", "detail": "Checks need the daemon; this viewer runs on its own."},
                status=503,
            )
        outcome = await controls.poll_now()
        return web.json_response({"status": outcome.status, "detail": outcome.detail})

    app = web.Application(middlewares=[_guard])
    app[CSP_KEY] = content_security_policy(style.host, fallback.host)
    app.router.add_get("/", index)
    if (STATIC / "assets").is_dir():
        app.router.add_static("/assets", STATIC / "assets")
    if (STATIC / "icons").is_dir():
        app.router.add_static("/icons", STATIC / "icons")
    app.router.add_get("/api/days", days)
    app.router.add_get("/api/days/{day}", day)
    app.router.add_get("/api/map", map_tiles)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/poll", poll)
    return app


async def start_viewer(
    settings: Settings,
    history: History,
    controls: Controls | None = None,
    map_key: Callable[[], str | None] = lambda: None,
) -> web.AppRunner:
    """Start serving in the running event loop. Raises OSError if the port can't be bound."""
    runner = web.AppRunner(create_app(settings, history, controls, map_key), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, settings.viewer.host, settings.viewer.port).start()
    except BaseException:
        await runner.cleanup()
        raise
    logger.info("Viewer: listening on %s:%d", settings.viewer.host, settings.viewer.port)
    return runner
