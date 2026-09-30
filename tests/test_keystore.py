from __future__ import annotations

import stat
import sys

import pytest

from air_notify import keystore
from air_notify.keystore import KeychainStore, SystemdCredsStore, default_store

# Stands in for `systemd-creds`: "encrypts" by reversing the bytes behind a name header,
# checks the name on decrypt, and logs each call's argv so tests can inspect it.
FAKE = """#!{python}
import sys
cmd, *args = sys.argv[1:]
with open({log!r}, "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
assert "--user" in args and args[-2:] == ["-", "-"], args
name = next(a.split("=", 1)[1] for a in args if a.startswith("--name="))
header = b"ENC:" + name.encode() + b":"
data = sys.stdin.buffer.read()
if cmd == "encrypt":
    sys.stdout.buffer.write(header + data[::-1])
elif not data.startswith(header):
    sys.stderr.write("credential name mismatch")
    sys.exit(1)
else:
    sys.stdout.buffer.write(data[len(header):][::-1])
"""


@pytest.fixture
def creds(tmp_path):
    log = tmp_path / "calls.log"
    exe = tmp_path / "systemd-creds"
    exe.write_text(FAKE.format(python=sys.executable, log=str(log)))
    exe.chmod(0o755)
    store_dir = tmp_path / "home"
    store_dir.mkdir()
    return SystemdCredsStore(store_dir, executable=str(exe)), store_dir, log


SECRET = {"account": {"password": "hunter2-very-secret"}}


def test_round_trip_encrypted_at_rest(creds):
    store, store_dir, log = creds
    store.put("apple-session", SECRET)

    path = store_dir / "apple-session.cred"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert b"hunter2" not in path.read_bytes()
    assert "hunter2" not in log.read_text()  # never in command-line arguments
    assert [p.name for p in store_dir.iterdir()] == ["apple-session.cred"]  # no temp files left

    fresh = SystemdCredsStore(store_dir, executable=store._exe)
    assert fresh.get("apple-session") == SECRET


def test_missing_item_is_none(creds):
    store, _, _ = creds
    assert store.get("airtag") is None


def test_unchanged_put_skips_encryption(creds):
    store, _, log = creds
    store.put("airtag", {"k": 1})
    store.put("airtag", {"k": 1})
    store.put("airtag", {"k": 2})
    assert [line.split()[0] for line in log.read_text().splitlines()] == ["encrypt", "encrypt"]


def test_swapped_file_is_rejected(creds):
    store, store_dir, _ = creds
    store.put("ntfy", {"topic": "t"})
    (store_dir / "ntfy.cred").rename(store_dir / "airtag.cred")
    with pytest.raises(RuntimeError, match="decrypt failed: credential name mismatch"):
        store.get("airtag")


def test_default_store_by_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(keystore.sys, "platform", "darwin")
    assert isinstance(default_store(tmp_path), KeychainStore)

    monkeypatch.setattr(keystore.sys, "platform", "linux")
    monkeypatch.setattr(keystore.shutil, "which", lambda _: "/usr/bin/systemd-creds")
    assert isinstance(default_store(tmp_path), SystemdCredsStore)

    monkeypatch.setattr(keystore.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="No supported secret store"):
        default_store(tmp_path)
