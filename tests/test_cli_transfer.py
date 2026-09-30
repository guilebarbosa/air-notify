from __future__ import annotations

import io
import json
import os
import plistlib
import sys
import zipfile
from datetime import datetime

import pytest

from air_notify import cli
from air_notify.importer import load_accessories
from air_notify.keystore import AIRTAG


class DictStore:
    label = "a test store"

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def get(self, name):
        return self.items.get(name)

    def put(self, name, value):
        self.items[name] = dict(value)


@pytest.fixture
def accessory_json(tmp_path):
    beacon = {
        "privateKey": {"key": {"data": os.urandom(32)}},
        "sharedSecret": {"key": {"data": os.urandom(32)}},
        "secondarySharedSecret": {"key": {"data": os.urandom(32)}},
        "pairingDate": datetime(2025, 1, 1),
        "model": "AirTag1,1",
        "identifier": "B1",
    }
    path = tmp_path / "tags.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("OwnedBeacons/B1.plist", plistlib.dumps(beacon))
    (acc,) = load_accessories(path).values()
    return acc.to_json()


def import_from_stdin(monkeypatch, paths, store, data: str, *, yes: bool) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(data))
    return cli.cmd_import_airtag(paths, store, cli.Path("-"), alignment=None, beacon=None, delete_source=False, yes=yes)


def test_import_from_pipe(monkeypatch, paths, accessory_json):
    store = DictStore()
    assert import_from_stdin(monkeypatch, paths, store, json.dumps(accessory_json), yes=False) == 0
    assert store.items[AIRTAG] == accessory_json
    assert paths.resume_flag.exists()


def test_import_from_pipe_needs_yes_to_replace(monkeypatch, paths, accessory_json, capsys):
    store = DictStore()
    store.put(AIRTAG, {"old": True})
    assert import_from_stdin(monkeypatch, paths, store, json.dumps(accessory_json), yes=False) == 1
    assert store.items[AIRTAG] == {"old": True}
    assert "--yes" in capsys.readouterr().out


def test_import_from_pipe_hides_parse_errors(monkeypatch, paths, capsys):
    assert import_from_stdin(monkeypatch, paths, DictStore(), '{"master_key": "abc123secret"', yes=True) == 1
    out = capsys.readouterr().out
    assert "abc123secret" not in out and "JSONDecodeError" in out


def test_export_refuses_terminal_or_file(capsys):
    store = DictStore()
    store.put(AIRTAG, {"master_key": "secret"})
    assert cli.cmd_export_airtag(store) == 1  # pytest's captured stdout is not a pipe
    captured = capsys.readouterr()
    assert "secret" not in captured.out and "Refusing" in captured.err


def test_export_writes_to_pipe(monkeypatch, accessory_json):
    store = DictStore()
    store.put(AIRTAG, accessory_json)
    r, w = os.pipe()
    with os.fdopen(w, "w") as writer:
        monkeypatch.setattr(sys, "stdout", writer)
        assert cli.cmd_export_airtag(store) == 0
    with os.fdopen(r) as reader:
        assert json.loads(reader.read()) == accessory_json
