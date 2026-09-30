from __future__ import annotations

import stat

import pytest

from air_notify.config import ConfigError, load_settings, parse_settings

ZONE = {"name": "School", "lat": 52.0, "lon": 5.0, "radius_m": 150}


def test_defaults():
    s = parse_settings({"zones": [ZONE]})
    assert s.poll_interval_minutes == 15
    assert s.zones[0].name == "School"


@pytest.mark.parametrize(
    "raw",
    [
        {"zones": []},
        {"zones": [ZONE], "poll_interval_minutes": 10},
        {"zones": [ZONE, ZONE]},
        {"zones": [{**ZONE, "lat": 95}]},
        {"zones": [{**ZONE, "radius_m": 0}]},
        {"zones": [{**ZONE, "radius": 150}]},
        {"zones": [ZONE], "pol_interval_minutes": 20},
        {"zones": [ZONE], "ntfy_server": "http://ntfy.sh"},
        {"zones": [{**ZONE, "lat": 0, "lon": 0}]},
    ],
)
def test_invalid_configs(raw):
    with pytest.raises(ConfigError):
        parse_settings(raw)


def test_load_tightens_permissions(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[[zones]]\nname = "School"\nlat = 52.0\nlon = 5.0\nradius_m = 150\n')
    path.chmod(0o644)
    load_settings(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
