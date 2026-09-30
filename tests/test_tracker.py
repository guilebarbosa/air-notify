from __future__ import annotations

import aiohttp
import pytest
from findmy import InvalidCredentialsError, UnauthorizedError, UnhandledProtocolError

from air_notify.tracker import ErrorKind, classify_error


@pytest.mark.parametrize(
    ("exc", "status", "kind", "detail"),
    [
        (UnauthorizedError("x"), None, ErrorKind.AUTH, "Apple login needed"),
        (InvalidCredentialsError("x"), 401, ErrorKind.AUTH, "Apple login needed"),
        (UnhandledProtocolError("Failed to fetch reports: None"), 429, ErrorKind.APPLE, "Apple rate limit (HTTP 429)"),
        (UnhandledProtocolError("x"), 503, ErrorKind.APPLE, "Apple unavailable, possibly rate limiting (HTTP 503)"),
        (UnhandledProtocolError("x"), 500, ErrorKind.APPLE, "Apple error (HTTP 500)"),
        (UnhandledProtocolError("x"), 200, ErrorKind.APPLE, "Unexpected error (UnhandledProtocolError)"),
        (KeyError("searchPartyToken"), None, ErrorKind.APPLE, "Unexpected error (KeyError)"),
        (aiohttp.ClientConnectionError(), None, ErrorKind.NETWORK, "Can't reach Apple (ClientConnectionError)"),
        (TimeoutError(), None, ErrorKind.NETWORK, "Can't reach Apple (TimeoutError)"),
    ],
)
def test_classify_error(exc, status, kind, detail):
    error = classify_error(exc, status)
    assert (error.kind, error.detail) == (kind, detail)


def test_response_error_status_wins():
    exc = aiohttp.ClientResponseError(None, (), status=429)  # type: ignore[arg-type]
    assert classify_error(exc, None).detail == "Apple rate limit (HTTP 429)"


def test_detail_never_includes_exception_message():
    # Exception messages could carry anything; alerts only name the type or status.
    error = classify_error(RuntimeError("user@example.com 52.1234,5.6789"), None)
    assert "example" not in error.detail and "52." not in error.detail
