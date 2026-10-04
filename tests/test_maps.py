from __future__ import annotations

from dataclasses import replace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from air_notify.config import ConfigError, Viewer, parse_settings
from air_notify.history import History
from air_notify.keystore import MAP_KEY
from air_notify.maps import KEY_ENV, STYLES, map_key
from air_notify.viewer import create_app


class DictStore:
    label = "a test store"

    def __init__(self, items=None) -> None:
        self.items = dict(items or {})

    def get(self, name):
        return self.items.get(name)

    def put(self, name, value):
        self.items[name] = dict(value)


async def tiles(settings, paths, style: str, key: str | None):
    settings = replace(settings, viewer=Viewer(map=style))
    app = create_app(settings, History(paths.history, 30), map_key=lambda: key)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/map")
        return await response.json(), response.headers["Content-Security-Policy"]


async def test_default_is_openstreetmap_without_a_key(settings, paths):
    data, csp = await tiles(settings, paths, "osm", None)
    assert data["url"].startswith("https://tile.openstreetmap.org/")
    assert data["warning"] is None
    assert "cartocdn" not in csp


async def test_carto_with_a_key(settings, paths):
    data, csp = await tiles(settings, paths, "carto-voyager", "k3y")
    assert data["url"] == "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png?key=k3y"
    assert "CARTO" in data["attribution"] and data["warning"] is None
    assert "https://basemaps.cartocdn.com" in csp and "https://tile.openstreetmap.org" in csp


async def test_carto_without_a_key_falls_back_with_a_warning(settings, paths):
    data, _ = await tiles(settings, paths, "carto-positron", None)
    assert data["url"].startswith("https://tile.openstreetmap.org/")
    assert "set-map-key" in data["warning"]


def test_key_is_url_encoded():
    assert STYLES["carto-dark-matter"].tile_url("a b&c").endswith("?key=a%20b%26c")


def test_env_var_wins_over_the_store(monkeypatch):
    store = DictStore({MAP_KEY: {"key": "saved"}})
    monkeypatch.delenv(KEY_ENV, raising=False)
    assert map_key(store) == "saved"
    monkeypatch.setenv(KEY_ENV, "from-env")
    assert map_key(store) == "from-env"
    assert map_key(DictStore()) == "from-env"
    monkeypatch.delenv(KEY_ENV)
    assert map_key(DictStore()) is None


def test_unknown_style_is_rejected():
    zone = {"name": "A", "lat": 1.0, "lon": 1.0, "radius_m": 10}
    with pytest.raises(ConfigError, match="map must be one of"):
        parse_settings({"zones": [zone], "viewer": {"map": "google"}})


def test_label_free_variants():
    assert STYLES["carto-positron-nolabels"].tile_url("k").startswith("https://basemaps.cartocdn.com/light_nolabels/")
    assert all(STYLES[name].needs_key for name in STYLES if name.startswith("carto-"))
