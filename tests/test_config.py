from __future__ import annotations

import stat

import pytest

from air_notify import config
from air_notify.config import Circle, ConfigError, Outline, Paths, find_config, load_settings, parse_settings

ZONE = {"name": "School", "lat": 52.0, "lon": 5.0, "radius_m": 150}
PARK = {"name": "Park", "outline": [[52.0, 5.0], [52.0, 5.01], [52.01, 5.01], [52.01, 5]]}


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
        {"zones": [ZONE], "messages": {"arrive": "Hi {name}"}},
        {"zones": [ZONE], "messages": {"greeting": "Hi"}},
        {"zones": [{**ZONE, "arrive": "Hi {name}"}]},
        {"zones": [{**ZONE, "greeting": "Hi"}]},
        {"zones": [ZONE], "history_days": -1},
        {"zones": [ZONE], "viewer": {"enabled": True}},  # the viewer needs history
        {"zones": [ZONE], "history_days": 30, "viewer": {"port": 0}},
        {"zones": [ZONE], "viewer": {"bind": "0.0.0.0"}},
        {"zones": [{"lat": 52.0, "lon": 5.0, "radius_m": 150}]},  # no name
        {"zones": [{**PARK, "outline": PARK["outline"][:2]}]},  # fewer than 3 corners
        {"zones": [{**PARK, "outline": [*PARK["outline"], [52.0]]}]},  # a corner that isn't a pair
        {"zones": [{**PARK, "outline": [*PARK["outline"], [52.0, True]]}]},
        {"zones": [{**PARK, "outline": [*PARK["outline"], [95.0, 5.0]]}]},  # out of range
        {"zones": [{**PARK, "outline": "52.0, 5.0"}]},
        {"zones": [{**PARK, "radius_m": 100}]},  # an outline and a circle key
    ],
)
def test_invalid_configs(raw):
    with pytest.raises(ConfigError):
        parse_settings(raw)


def test_circle_and_outline_zones():
    school, park = parse_settings({"zones": [ZONE, {**PARK, "arrive": "Chegou no parque"}]}).zones
    assert school.shape == Circle(52.0, 5.0, 150)
    assert park.shape == Outline(((52.0, 5.0), (52.0, 5.01), (52.01, 5.01), (52.01, 5.0)))
    assert park.arrive == "Chegou no parque"


def test_custom_messages():
    s = parse_settings({"zones": [ZONE], "messages": {"arrive": "Chegou em {zone}"}})
    assert s.messages.arrive == "Chegou em {zone}"
    assert s.messages.leave == "Left {zone}"  # unset keys keep the defaults


def test_zone_messages_override_the_global_ones():
    s = parse_settings(
        {
            "messages": {"arrive": "Chegou em {zone}", "leave": "Saiu de {zone}", "time": "Horário: {time}"},
            "zones": [{**ZONE, "arrive": "Chegou na escola"}, {**ZONE, "name": "Casa", "lat": 52.1}],
        }
    )
    school, casa = s.messages_for("School"), s.messages_for("Casa")
    assert (school.arrive, school.leave, school.time) == ("Chegou na escola", "Saiu de {zone}", "Horário: {time}")
    assert (casa.arrive, casa.leave) == ("Chegou em {zone}", "Saiu de {zone}")
    assert s.messages_for("Removed zone") == s.messages


def test_history_and_viewer():
    s = parse_settings({"zones": [ZONE], "history_days": 30, "viewer": {"enabled": True, "host": "0.0.0.0"}})
    assert s.history_days == 30
    assert (s.viewer.enabled, s.viewer.host, s.viewer.port) == (True, "0.0.0.0", 8080)
    assert parse_settings({"zones": [ZONE]}).viewer.host == "127.0.0.1"  # safe default


def test_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.delenv("AIR_NOTIFY_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert Paths.default().root == tmp_path / "air-notify"


def test_load_tightens_permissions(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[[zones]]\nname = "School"\nlat = 52.0\nlon = 5.0\nradius_m = 150\n')
    path.chmod(0o644)
    load_settings(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_config_lookup_order(monkeypatch, tmp_path):
    data_dir, clone = tmp_path / "data", tmp_path / "clone"
    data_dir.mkdir()
    clone.mkdir()
    monkeypatch.delenv("AIR_NOTIFY_CONFIG", raising=False)
    monkeypatch.setattr(config, "checkout_root", lambda: clone)

    assert find_config(data_dir) == data_dir / "config.toml"  # nothing in the clone: the data dir

    (clone / "config.toml").write_text("")
    assert find_config(data_dir) == clone / "config.toml"  # the clone's wins

    monkeypatch.setenv("AIR_NOTIFY_CONFIG", str(tmp_path / "elsewhere.toml"))
    assert find_config(data_dir) == tmp_path / "elsewhere.toml"  # the env var wins over both


def test_plain_install_uses_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("AIR_NOTIFY_CONFIG", raising=False)
    monkeypatch.setattr(config, "checkout_root", lambda: None)
    assert find_config(tmp_path) == tmp_path / "config.toml"


def test_paths_without_a_config_file_default_to_the_data_dir(tmp_path):
    assert Paths(tmp_path).config == tmp_path / "config.toml"


def test_checkout_root_finds_this_clone():
    root = config.checkout_root()
    assert root is not None and (root / "pyproject.toml").is_file()
