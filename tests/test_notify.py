from __future__ import annotations

from contextlib import asynccontextmanager

import aiohttp
from conftest import at

from air_notify.geofence import Event, Transition
from air_notify.notify import Alert, Notifier, event_alert


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(None, (), status=self.status)  # type: ignore[arg-type]


class FakeSession:
    def __init__(self, fail_after: int | None = None, error: Exception | None = None) -> None:
        self.posts: list[dict] = []
        self._fail_after = fail_after
        self._error = error

    @asynccontextmanager
    async def post(self, url, *, json, headers):
        if self._fail_after is not None and len(self.posts) >= self._fail_after:
            raise self._error or aiohttp.ClientConnectionError()
        self.posts.append({"url": url, "json": json, "headers": headers})
        yield FakeResponse(200)


async def test_send_puts_topic_in_body_not_url():
    session = FakeSession()
    await Notifier(session, "https://ntfy.sh/", "secret-topic", token="tk").send(  # noqa: S106
        Alert("T", "M", ("warning",), 4)
    )

    (post,) = session.posts
    assert post["url"] == "https://ntfy.sh"
    assert post["json"] == {"topic": "secret-topic", "title": "T", "message": "M", "tags": ["warning"], "priority": 4}
    assert post["headers"] == {"Authorization": "Bearer tk"}


async def test_flush_keeps_unsent_alerts_in_order():
    alerts = [Alert("a", "1"), Alert("b", "2"), Alert("c", "3")]
    session = FakeSession(fail_after=1)
    remaining = await Notifier(session, "https://ntfy.sh", "t").flush(alerts)
    assert remaining == alerts[1:]
    assert [p["json"]["title"] for p in session.posts] == ["a"]


async def test_flush_keeps_alerts_when_server_rejects():
    session = FakeSession(fail_after=0, error=aiohttp.ClientResponseError(None, (), status=429))  # type: ignore[arg-type]
    alerts = [Alert("a", "1")]
    assert await Notifier(session, "https://ntfy.sh", "t").flush(alerts) == alerts


def test_event_alert_has_zone_and_time_only():
    arrive = event_alert(Event("School", Transition.ARRIVE, at(12)), now=at(30))
    leave = event_alert(Event("School", Transition.LEAVE, at(-24 * 60)), now=at(30))

    assert arrive.title == "Chegou em School"
    assert arrive.message == f"Horário: {at(12).astimezone():%H:%M}"
    assert leave.title == "Saiu de School"
    assert leave.message.startswith("Horário: ")
    assert len(leave.message) > len("Horário: 00:00")  # includes the day when not today
