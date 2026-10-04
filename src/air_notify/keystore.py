"""
Secret storage: the Apple session, the AirTag keys and the ntfy topic.

- macOS: the Keychain (encrypted at rest, unlocked with your login).
- Linux (Raspberry Pi): one file per secret, encrypted with `systemd-creds --user`
  (AES-256-GCM, keyed by the host key and bound to the user). Without a TPM the host key
  lives on the SD card (root-only), so this protects against other users, copied files and
  leaks, not against someone with root or the SD card.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import keyring

SERVICE = "air-notify"

# Item names (Keychain "account" field / credential file name)
SESSION = "apple-session"  # FindMy.py account state: password, iCloud tokens, device identity
AIRTAG = "airtag"  # FindMy.py accessory: private keys + key-rotation alignment
NTFY = "ntfy"  # {"topic": ..., "token": ...}; whoever knows the topic can read the alerts
MAP_KEY = "map-key"  # {"key": ...}; map tile provider key (e.g. CARTO), sent with tile requests


class SecretStore(Protocol):
    label: str  # for messages, e.g. "the Keychain"

    def get(self, name: str) -> dict[str, Any] | None: ...

    def put(self, name: str, value: Mapping[str, Any]) -> None: ...


def _encode(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class KeychainStore:
    """
    Stores each secret as one JSON-encoded generic password.

    Uses the Security framework via `keyring` (not the `security` CLI), so secrets never
    appear in process arguments. `put` skips the write when the value hasn't changed since
    the last get/put, so polling doesn't rewrite the Keychain every cycle.
    """

    label = "the Keychain"

    def __init__(self, service: str = SERVICE) -> None:
        self._service = service
        self._last: dict[str, str] = {}

    def get(self, name: str) -> dict[str, Any] | None:
        raw = keyring.get_password(self._service, name)
        if raw is None:
            self._last.pop(name, None)
            return None
        self._last[name] = raw
        return json.loads(raw)

    def put(self, name: str, value: Mapping[str, Any]) -> None:
        raw = _encode(value)
        if self._last.get(name) == raw:
            return
        keyring.set_password(self._service, name, raw)
        self._last[name] = raw


class SystemdCredsStore:
    """
    Stores each secret as `<dir>/<name>.cred`, encrypted with `systemd-creds --user`.

    Plaintext only ever travels over the subprocess's stdin/stdout, never in arguments or
    on disk. The credential name is sealed into the ciphertext, so files can't be swapped.
    """

    def __init__(self, directory: Path, executable: str = "systemd-creds") -> None:
        self.label = f"encrypted credentials in {directory}"
        self._dir = directory
        self._exe = executable
        self._last: dict[str, str] = {}

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.cred"

    def _run(self, *args: str, data: bytes) -> bytes:
        result = subprocess.run([self._exe, *args], input=data, capture_output=True, check=False)  # noqa: S603
        if result.returncode != 0:
            # stderr is systemd-creds' own message; it never contains the plaintext.
            msg = f"systemd-creds {args[0]} failed: {result.stderr.decode(errors='replace').strip()}"
            raise RuntimeError(msg)
        return result.stdout

    def get(self, name: str) -> dict[str, Any] | None:
        path = self._path(name)
        if not path.exists():
            self._last.pop(name, None)
            return None
        raw = self._run("decrypt", "--user", f"--name={name}", "-", "-", data=path.read_bytes()).decode()
        self._last[name] = raw
        return json.loads(raw)

    def put(self, name: str, value: Mapping[str, Any]) -> None:
        raw = _encode(value)
        if self._last.get(name) == raw:
            return
        encrypted = self._run("encrypt", "--user", f"--name={name}", "-", "-", data=raw.encode())

        # mkstemp creates the file with mode 0600; os.replace makes the write atomic.
        fd, tmp = tempfile.mkstemp(dir=self._dir, prefix=f".{name}-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(encrypted)
            os.replace(tmp, self._path(name))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._last[name] = raw


def default_store(directory: Path) -> SecretStore:
    """The Keychain on macOS, systemd-creds files on Linux."""
    if sys.platform == "darwin":
        return KeychainStore()
    if shutil.which("systemd-creds"):
        return SystemdCredsStore(directory)
    msg = "No supported secret store: needs the macOS Keychain or systemd-creds (systemd >= 256)"
    raise RuntimeError(msg)
