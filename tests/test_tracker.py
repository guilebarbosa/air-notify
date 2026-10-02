from __future__ import annotations

import os
from datetime import datetime, timedelta, UTC

import aiohttp
import pytest
from findmy import InvalidCredentialsError, UnauthorizedError, UnhandledProtocolError

from air_notify.tracker import ClockBoundAccessory, ErrorKind, classify_error


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


PAIRED = datetime(2026, 9, 28, 19, 39, tzinfo=UTC)
NOW = PAIRED + timedelta(days=3, hours=11, minutes=15)  # 333 15-minute steps after pairing


def accessory(alignment_index: int, alignment_date: datetime) -> dict:
    return {
        "type": "accessory",
        "master_key": os.urandom(28).hex(),
        "skn": os.urandom(32).hex(),
        "sks": os.urandom(32).hex(),
        "paired_at": PAIRED.isoformat(),
        "name": None,
        "model": None,
        "identifier": None,
        "alignment_date": alignment_date.isoformat(),
        "alignment_index": alignment_index,
    }


def test_search_reaches_the_clock_limit_when_alignment_is_too_low():
    # Saved alignment says index 235 at Oct 1 13:43 UTC: FindMy.py alone would stop at 304,
    # while the tag was really at 329 (what happened on 2026-10-02).
    tag = ClockBoundAccessory.from_json(accessory(235, PAIRED + timedelta(days=2, hours=18, minutes=4)))
    assert isinstance(tag, ClockBoundAccessory)
    assert tag.get_max_index(NOW) == 334  # 333 steps since pairing, plus one
    assert tag.get_max_index(NOW) >= 329


def test_a_higher_alignment_ceiling_is_kept():
    tag = ClockBoundAccessory.from_json(accessory(400, NOW))
    assert tag.get_max_index(NOW) == 400
