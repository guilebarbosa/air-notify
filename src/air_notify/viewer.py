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

from .config import Settings
from .history import History
from .state import ManualCheck

logger = logging.getLogger(__name__)

# `npm run build` in web/ writes here; the files are committed so deployments don't need Node.
STATIC = Path(__file__).parent / "static"
TILES = "https://tile.openstreetmap.org"

# Required on POSTs. Browsers won't let another website send a custom header here without
# a CORS preflight, which this server never approves, so other sites can't trigger checks.
CHECK_HEADER = "X-Air-Notify"

CSP = "; ".join(
    (
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",  # Leaflet positions elements with inline styles
        f"img-src 'self' data: {TILES}",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)


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
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Built assets have content hashes in their names, so they can be cached for good.
    immutable = request.path.startswith("/assets/")
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-store"
    return response


def create_app(settings: Settings, history: History, controls: Controls | None = None) -> web.Application:
    zones = [{"name": z.name, "lat": z.lat, "lon": z.lon, "radius_m": z.radius_m} for z in settings.zones]

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
        return web.json_response({"date": which.isoformat(), "points": history.points(which), "zones": zones})

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
    app.router.add_get("/", index)
    if (STATIC / "assets").is_dir():
        app.router.add_static("/assets", STATIC / "assets")
    app.router.add_get("/api/days", days)
    app.router.add_get("/api/days/{day}", day)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/poll", poll)
    return app


async def start_viewer(settings: Settings, history: History, controls: Controls | None = None) -> web.AppRunner:
    """Start serving in the running event loop. Raises OSError if the port can't be bound."""
    runner = web.AppRunner(create_app(settings, history, controls), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, settings.viewer.host, settings.viewer.port).start()
    except BaseException:
        await runner.cleanup()
        raise
    logger.info("Viewer: listening on %s:%d", settings.viewer.host, settings.viewer.port)
    return runner
