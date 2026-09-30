"""ntfy push notifications. Alerts carry a zone label and a time, never coordinates."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

from .geofence import Event, Transition

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Alert:
    title: str
    message: str
    # ntfy renders tags that match emoji short codes as emojis in front of the title.
    tags: tuple[str, ...] = ()
    priority: int = 3

    def to_json(self) -> dict[str, Any]:
        return {"title": self.title, "message": self.message, "tags": list(self.tags), "priority": self.priority}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Alert:
        return cls(data["title"], data["message"], tuple(data.get("tags", ())), data.get("priority", 3))


class Notifier:
    """
    Publishes to ntfy via JSON to the server root.

    The topic goes in the body rather than the URL, so it never shows up in HTTP error
    messages or logs.
    """

    def __init__(self, http: aiohttp.ClientSession, server: str, topic: str, token: str | None = None) -> None:
        self._http = http
        self._server = server.rstrip("/")
        self._topic = topic
        self._token = token

    async def send(self, alert: Alert) -> None:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        payload = {"topic": self._topic, **alert.to_json()}
        async with self._http.post(self._server, json=payload, headers=headers) as resp:
            resp.raise_for_status()

    async def flush(self, pending: list[Alert]) -> list[Alert]:
        """Send queued alerts oldest-first. Returns the ones that couldn't be sent yet."""
        for i, alert in enumerate(pending):
            try:
                await self.send(alert)
            except aiohttp.ClientResponseError as e:
                logger.warning("ntfy rejected an alert (HTTP %d); %d alert(s) queued", e.status, len(pending) - i)
                return pending[i:]
            except (aiohttp.ClientError, TimeoutError) as e:
                logger.warning("ntfy unreachable (%s); %d alert(s) queued", type(e).__name__, len(pending) - i)
                return pending[i:]
        return []


def format_time(ts: datetime, now: datetime) -> str:
    local, today = ts.astimezone(), now.astimezone()
    if local.date() == today.date():
        return local.strftime("%H:%M")
    return local.strftime("%a %d %b %H:%M")


def event_alert(event: Event, now: datetime) -> Alert:
    when = format_time(event.timestamp, now)
    if event.transition is Transition.ARRIVE:
        return Alert(f"Chegou em {event.zone}", f"Horário: {when}", ("round_pushpin",))
    return Alert(f"Saiu de {event.zone}", f"Horário: {when}", ("runner",))
