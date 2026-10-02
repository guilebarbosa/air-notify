from __future__ import annotations

from datetime import timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer
from conftest import SCHOOL, T0, north_of

from air_notify.geofence import Fix
from air_notify.history import History
from air_notify.state import ManualCheck
from air_notify.viewer import CHECK_HEADER, LEAFLET_JS_SRI, create_app, host_allowed


@pytest.fixture
async def client(settings, paths):
    history = History(paths.history, keep_days=30)
    lat, lon = north_of(SCHOOL, 0)
    history.append([Fix(T0, lat, lon, 20), Fix(T0 + timedelta(minutes=30), lat, lon, 40)], now=T0)
    async with TestClient(TestServer(create_app(settings, history))) as c:
        yield c


async def test_page_pins_leaflet_and_sets_csp(client):
    response = await client.get("/")
    assert response.status == 200
    assert LEAFLET_JS_SRI in await response.text()
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "script-src 'self' https://unpkg.com" in csp


async def test_days_and_day_points(client):
    days = await (await client.get("/api/days")).json()
    assert [d["count"] for d in days] == [2]

    data = await (await client.get(f"/api/days/{days[0]['date']}")).json()
    assert [p["acc"] for p in data["points"]] == [20, 40]
    assert [z["name"] for z in data["zones"]] == ["School", "Home"]


async def test_bad_date_is_rejected(client):
    assert (await client.get("/api/days/yesterday")).status == 400


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("192.168.1.20:8080", True),
        ("[::1]:8080", True),
        ("localhost:8080", True),
        ("pi.local:8080", True),
        ("evil.example.com", False),
        ("192.168.1.20.nip.io:8080", False),
    ],
)
def test_host_allowed(host, allowed):
    assert host_allowed(host) is allowed


async def test_rebinding_host_is_refused(client):
    response = await client.get("/api/days", headers={"Host": "evil.example.com"})
    assert response.status == 421


class FakeControls:
    def __init__(self) -> None:
        self.polls = 0

    async def poll_now(self):
        self.polls += 1
        return ManualCheck(T0, "ok", "Checked just now")

    def snapshot(self):
        return {"last_check": T0.isoformat(), "next_check": None, "latest_report": T0.isoformat(), "stopped": None}


@pytest.fixture
async def daemon_client(settings, paths):
    controls = FakeControls()
    async with TestClient(TestServer(create_app(settings, History(paths.history, 30), controls))) as c:
        c.controls = controls
        yield c


async def test_check_now_needs_the_header(daemon_client):
    assert (await daemon_client.post("/api/poll")).status == 403  # what another website could send
    assert daemon_client.controls.polls == 0

    response = await daemon_client.post("/api/poll", headers={CHECK_HEADER: "1"})
    assert (await response.json()) == {"status": "ok", "detail": "Checked just now"}
    assert daemon_client.controls.polls == 1


async def test_status_with_and_without_the_daemon(daemon_client, client):
    assert (await (await daemon_client.get("/api/status")).json())["available"] is True
    assert (await (await client.get("/api/status")).json()) == {"available": False}


async def test_check_now_without_the_daemon(client):
    response = await client.post("/api/poll", headers={CHECK_HEADER: "1"})
    assert response.status == 503 and (await response.json())["status"] == "unavailable"
