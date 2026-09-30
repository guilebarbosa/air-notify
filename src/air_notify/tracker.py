"""FindMy.py wrapper: restores the saved session, fetches reports, writes secrets back to the store."""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

import aiohttp
from findmy import (
    AsyncAppleAccount,
    FindMyAccessory,
    InvalidCredentialsError,
    LoginState,
    UnauthorizedError,
)

from .geofence import Fix
from .keystore import AIRTAG, SESSION, SecretStore

logger = logging.getLogger(__name__)


class SetupError(RuntimeError):
    """Something must be set up by hand first (login, AirTag import)."""


class ErrorKind(StrEnum):
    AUTH = "auth"  # Apple rejected the session: needs `air-notify login`
    APPLE = "apple"  # Apple answered with an error: rate limit, outage, protocol change, bug
    NETWORK = "network"  # Apple couldn't be reached at all


class FetchError(Exception):
    """A classified fetch failure. `detail` is safe to send in an alert: no secrets, no coordinates."""

    def __init__(self, kind: ErrorKind, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def describe_status(status: int) -> str:
    if status == 429:
        return "Apple rate limit (HTTP 429)"
    if status == 503:
        return "Apple unavailable, possibly rate limiting (HTTP 503)"
    return f"Apple error (HTTP {status})"


def classify_error(exc: BaseException, last_status: int | None) -> FetchError:
    """
    Map an exception from a fetch onto the daemon's safeguards.

    Anything that isn't clearly an auth failure or a connection failure counts as an Apple
    error, which stops polling: the safe default for the account.
    """
    if isinstance(exc, UnauthorizedError | InvalidCredentialsError):
        return FetchError(ErrorKind.AUTH, "Apple login needed")
    if isinstance(exc, aiohttp.ClientResponseError):
        return FetchError(ErrorKind.APPLE, describe_status(exc.status))
    if isinstance(exc, aiohttp.ClientConnectionError | TimeoutError):
        return FetchError(ErrorKind.NETWORK, f"Can't reach Apple ({type(exc).__name__})")
    # FindMy.py raises UnhandledProtocolError for non-2xx replies and drops the status code;
    # the recorder in Tracker keeps it so the alert can say e.g. "HTTP 429".
    if last_status is not None and not 200 <= last_status < 300:
        return FetchError(ErrorKind.APPLE, describe_status(last_status))
    return FetchError(ErrorKind.APPLE, f"Unexpected error ({type(exc).__name__})")


class Tracker:
    """Owns the FindMy.py account and accessory. Never starts a fresh login by itself."""

    def __init__(self, store: SecretStore, anisette_libs: Path) -> None:
        self._store = store
        self._anisette_libs = anisette_libs
        self._account: AsyncAppleAccount | None = None
        self._accessory: FindMyAccessory | None = None
        self._last_status: int | None = None

    async def open(self) -> None:
        session = self._store.get(SESSION)
        if session is None:
            msg = "No Apple session saved. Run `air-notify login`."
            raise SetupError(msg)
        airtag = self._store.get(AIRTAG)
        if airtag is None:
            msg = "No AirTag keys saved. Run `air-notify import-airtag`."
            raise SetupError(msg)

        self._account = AsyncAppleAccount.from_json(session, anisette_libs_path=self._anisette_libs)
        self._accessory = FindMyAccessory.from_json(airtag)
        self._record_http_status(self._account)

    async def reload(self) -> None:
        """Pick up a session written by `air-notify login` while the daemon was running."""
        await self.close()
        await self.open()

    async def close(self) -> None:
        if self._account is not None:
            await self._account.close()
            self._account = None

    async def fetch(self) -> list[Fix]:
        """Fetch the newest batch of reports (about 20). Raises FetchError on any failure."""
        if self._account is None or self._accessory is None:
            msg = "Tracker is not open"
            raise RuntimeError(msg)
        if self._account.login_state != LoginState.LOGGED_IN:
            raise FetchError(ErrorKind.AUTH, "Apple login needed")

        self._last_status = None
        try:
            reports = await self._account.fetch_location_history(self._accessory)
        except Exception as exc:
            raise classify_error(exc, self._last_status) from exc
        finally:
            # Tokens (after an automatic re-auth) and key alignment may have changed even if
            # the fetch failed later on.
            self._persist()

        return [Fix(r.timestamp, r.latitude, r.longitude, r.horizontal_accuracy) for r in reports]

    def _persist(self) -> None:
        assert self._account is not None and self._accessory is not None
        try:
            self._store.put(SESSION, self._account.to_json())
            self._store.put(AIRTAG, self._accessory.to_json())
        except Exception:
            logger.exception("Couldn't save the session/AirTag state to the secret store")

    def _record_http_status(self, account: AsyncAppleAccount) -> None:
        # Private FindMy.py API (pinned <0.11). If it moves, alerts just lose the HTTP status.
        http = getattr(account, "_http", None)
        request = getattr(http, "request", None)
        if request is None:
            logger.warning("Can't observe HTTP status codes; alerts will name error types only")
            return

        async def recording_request(*args: Any, **kwargs: Any) -> Any:
            response = await request(*args, **kwargs)
            self._last_status = response.status_code
            return response

        http.request = recording_request
