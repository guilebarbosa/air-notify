"""
Map viewer for the location history: a list of recorded days and a Leaflet map.

The page loads Leaflet from unpkg (pinned, integrity-checked) and map tiles from
OpenStreetMap; the coordinates themselves only travel between this server and your browser.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Protocol

from aiohttp import web

from .config import Settings
from .history import History
from .state import ManualCheck

logger = logging.getLogger(__name__)

LEAFLET = "https://unpkg.com/leaflet@1.9.4/dist"
LEAFLET_JS_SRI = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
LEAFLET_CSS_SRI = "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
TILES = "https://tile.openstreetmap.org"

# Required on POSTs. Browsers won't let another website send a custom header here without
# a CORS preflight, which this server never approves, so other sites can't trigger checks.
CHECK_HEADER = "X-Air-Notify"

CSP = "; ".join(
    (
        "default-src 'none'",
        "script-src 'self' https://unpkg.com",
        "style-src 'self' 'unsafe-inline' https://unpkg.com",  # Leaflet positions elements with inline styles
        f"img-src 'self' data: https://unpkg.com {TILES}",
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
    response.headers["Cache-Control"] = "no-store"
    return response


def create_app(settings: Settings, history: History, controls: Controls | None = None) -> web.Application:
    zones = [{"name": z.name, "lat": z.lat, "lon": z.lon, "radius_m": z.radius_m} for z in settings.zones]

    async def index(_: web.Request) -> web.Response:
        return web.Response(text=INDEX_HTML, content_type="text/html")

    async def app_js(_: web.Request) -> web.Response:
        return web.Response(text=APP_JS, content_type="application/javascript")

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
    app.router.add_get("/app.js", app_js)
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


INDEX_HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>air-notify</title>
<link rel="stylesheet" href="{LEAFLET}/leaflet.css" integrity="{LEAFLET_CSS_SRI}" crossorigin="">
<style>
  html, body {{ margin: 0; height: 100%; font: 14px system-ui, sans-serif; }}
  body {{ display: flex; }}
  nav {{ width: 13rem; overflow-y: auto; border-right: 1px solid #ddd; }}
  nav h1 {{ font-size: 1rem; margin: .75rem; }}
  nav p {{ margin: .75rem; color: #666; }}
  #check {{ margin: 0 .75rem; padding: .4rem .7rem; font: inherit; cursor: pointer; }}
  #check[hidden] {{ display: none; }}
  #status {{ font-size: 12px; }}
  #days button {{ display: flex; justify-content: space-between; width: 100%; padding: .5rem .75rem;
    border: 0; background: none; font: inherit; text-align: left; cursor: pointer; }}
  #days button:hover, #days button[aria-current="true"] {{ background: #e8f0fe; }}
  #days .count {{ color: #888; }}
  #map {{ flex: 1; }}
  @media (max-width: 40rem) {{
    body {{ flex-direction: column; }}
    nav {{ width: auto; height: 40%; border-right: 0; border-bottom: 1px solid #ddd; }}
  }}
</style>
</head>
<body>
<nav>
  <h1>air-notify</h1>
  <button id="check" type="button" hidden>Check now</button>
  <p id="status"></p>
  <div id="days"></div>
</nav>
<div id="map"></div>
<script src="{LEAFLET}/leaflet.js" integrity="{LEAFLET_JS_SRI}" crossorigin=""></script>
<script src="/app.js"></script>
</body>
</html>
"""

# Text goes in via textContent / DOM nodes, never as HTML, so a zone name can't inject markup.
APP_JS = f""""use strict";
const map = L.map("map").setView([20, 0], 2);
L.tileLayer("{TILES}/{{z}}/{{x}}/{{y}}.png", {{
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}}).addTo(map);
const layer = L.layerGroup().addTo(map);
const daysEl = document.getElementById("days");
const statusEl = document.getElementById("status");
const checkButton = document.getElementById("check");
let selected = null;

async function getJSON(url, options) {{
  const response = await fetch(url, options);
  if (!response.ok && response.status !== 503) throw new Error(`${{url}}: HTTP ${{response.status}}`);
  return response.json();
}}

function text(value) {{
  const span = document.createElement("span");
  span.textContent = value;
  return span;
}}

const clock = (t) => new Date(t).toLocaleTimeString([], {{ hour: "2-digit", minute: "2-digit" }});

async function showDay(day) {{
  selected = day;
  for (const b of daysEl.querySelectorAll("button")) {{
    if (b.dataset.date === day) b.setAttribute("aria-current", "true");
    else b.removeAttribute("aria-current");
  }}
  const data = await getJSON(`/api/days/${{day}}`);

  layer.clearLayers();
  for (const z of data.zones) {{
    L.circle([z.lat, z.lon], {{ radius: z.radius_m, color: "#2e7d32", weight: 1, fillOpacity: 0.1 }})
      .bindTooltip(text(z.name)).addTo(layer);
  }}
  const path = data.points.map((p) => [p.lat, p.lon]);
  if (path.length > 1) L.polyline(path, {{ color: "#1565c0", weight: 2, opacity: 0.6 }}).addTo(layer);
  data.points.forEach((p, i) => {{
    L.circle([p.lat, p.lon], {{ radius: p.acc, stroke: false, fillOpacity: 0.08 }}).addTo(layer);
    const last = i === data.points.length - 1;
    L.circleMarker([p.lat, p.lon], {{
      radius: last ? 7 : 5, weight: 1, color: "#fff", fillColor: last ? "#c62828" : "#1565c0", fillOpacity: 1,
    }}).bindPopup(text(`${{clock(p.t)}} · ±${{p.acc}} m`)).addTo(layer);
  }});
  if (path.length) map.fitBounds(path, {{ padding: [30, 30], maxZoom: 17 }});
}}

async function loadDays() {{
  const days = await getJSON("/api/days");
  if (!days.length) {{
    const p = document.createElement("p");
    p.textContent = "No locations recorded yet.";
    daysEl.replaceChildren(p);
    return;
  }}
  const buttons = days.map((d) => {{
    const button = document.createElement("button");
    button.dataset.date = d.date;
    const label = new Date(`${{d.date}}T12:00`)
      .toLocaleDateString([], {{ weekday: "short", day: "numeric", month: "short" }});
    const count = text(d.count);
    count.className = "count";
    button.append(text(label), count);
    button.addEventListener("click", () => showDay(d.date).catch(showError));
    return button;
  }});
  daysEl.replaceChildren(...buttons);
  const keep = days.some((d) => d.date === selected) ? selected : days[0].date;
  await showDay(keep);
}}

async function loadStatus() {{
  const s = await getJSON("/api/status");
  checkButton.hidden = !s.available;
  if (!s.available) return;
  const parts = [];
  if (s.stopped) parts.push(`Stopped: ${{s.stopped}}`);
  if (s.last_check) parts.push(`Last check ${{clock(s.last_check)}}`);
  if (s.latest_report) parts.push(`latest report ${{clock(s.latest_report)}}`);
  statusEl.textContent = parts.join(" · ");
}}

checkButton.addEventListener("click", async () => {{
  checkButton.disabled = true;
  checkButton.textContent = "Checking…";
  try {{
    const result = await getJSON("/api/poll", {{ method: "POST", headers: {{ "{CHECK_HEADER}": "1" }} }});
    await Promise.all([loadStatus(), loadDays()]);
    if (result.status !== "ok") statusEl.textContent = result.detail;
  }} catch (error) {{
    showError(error);
  }} finally {{
    checkButton.disabled = false;
    checkButton.textContent = "Check now";
  }}
}});

function showError(error) {{
  console.error(error);
  statusEl.textContent = `Error: ${{error.message}}`;
}}

Promise.all([loadStatus(), loadDays()]).catch(showError);
"""
