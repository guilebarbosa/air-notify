"""
Secret storage: the Apple session, the AirTag keys and the ntfy topic.

macOS Keychain for now (encrypted at rest, unlocked with your login). The SecretStore
protocol keeps a Raspberry Pi backend swappable later.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

import keyring

SERVICE = "air-notify"

# Item names (Keychain "account" field)
SESSION = "apple-session"  # FindMy.py account state: password, iCloud tokens, device identity
AIRTAG = "airtag"  # FindMy.py accessory: private keys + key-rotation alignment
NTFY = "ntfy"  # {"topic": ..., "token": ...}; whoever knows the topic can read the alerts


class SecretStore(Protocol):
    def get(self, name: str) -> dict[str, Any] | None: ...

    def put(self, name: str, value: Mapping[str, Any]) -> None: ...


class KeychainStore:
    """
    Stores each secret as one JSON-encoded generic password.

    Uses the Security framework via `keyring` (not the `security` CLI), so secrets never
    appear in process arguments. `put` skips the write when the value hasn't changed since
    the last get/put, so polling doesn't rewrite the Keychain every cycle.
    """

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
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if self._last.get(name) == raw:
            return
        keyring.set_password(self._service, name, raw)
        self._last[name] = raw
