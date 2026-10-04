"""Map styles for the viewer: tile URL templates for Leaflet, their attribution and host."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

from .keystore import MAP_KEY, SecretStore

OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
CARTO_ATTRIBUTION = f'{OSM_ATTRIBUTION} &copy; <a href="https://carto.com/attributions">CARTO</a>'

# The key, if a style needs one, comes from here first: for keys injected from a secrets
# manager at runtime. Otherwise from the secret store (`air-notify set-map-key`).
KEY_ENV = "AIR_NOTIFY_MAP_KEY"


@dataclass(frozen=True)
class MapStyle:
    url: str  # Leaflet template; {key} is filled in by the viewer, never stored in config
    attribution: str
    host: str  # for the viewer's Content-Security-Policy
    max_zoom: int = 19
    needs_key: bool = False

    def tile_url(self, key: str | None) -> str:
        return self.url.replace("{key}", quote(key or "", safe=""))


# CARTO requires a free API key (https://carto.com/basemaps/apikey/); without one its tiles
# come back watermarked.
_CARTO = "https://basemaps.cartocdn.com"


def _carto(path: str) -> MapStyle:
    return MapStyle(f"{_CARTO}/{path}/{{z}}/{{x}}/{{y}}{{r}}.png?key={{key}}", CARTO_ATTRIBUTION, _CARTO, 20, True)


STYLES: dict[str, MapStyle] = {
    "osm": MapStyle(
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png", OSM_ATTRIBUTION, "https://tile.openstreetmap.org"
    ),
    "carto-voyager": _carto("rastertiles/voyager"),
    "carto-positron": _carto("light_all"),
    "carto-dark-matter": _carto("dark_all"),
}
DEFAULT_STYLE = "osm"


def map_key(store: SecretStore) -> str | None:
    """The map provider key: $AIR_NOTIFY_MAP_KEY, else the secret store. Never log it."""
    if key := os.environ.get(KEY_ENV, "").strip():
        return key
    saved = store.get(MAP_KEY)
    return saved.get("key") if saved else None
