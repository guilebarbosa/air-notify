from __future__ import annotations

from datetime import timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer
from conftest import SCHOOL, T0, north_of

from air_notify.geofence import Fix
from air_notify.history import History
from air_notify.viewer import LEAFLET_JS_SRI, create_app, host_allowed


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
