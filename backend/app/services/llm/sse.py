"""Incremental Server-Sent Events decoder.

Implements the event-stream framing only (no JSON, no provider payload): an event
is terminated by a blank line, and multiple ``data:`` lines belonging to the same
event are joined with ``\\n``. Comment lines (``:`` keep-alives) and unknown
fields are ignored.

Callers feed one line at a time and receive a :class:`ServerSentEvent` only when
an event terminates. :meth:`SSEDecoder.close` flushes the pending buffer at end
of stream and returns ``None`` for a clean end; a non-``None`` value means the
stream ended in the middle of an event.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServerSentEvent:
    """One fully-framed SSE event."""

    data: str
    event: str | None = None
    id: str | None = None


class SSEDecoder:
    def __init__(self) -> None:
        self._data: list[str] = []
        self._event: str | None = None
        self._id: str | None = None

    def feed(self, line: str) -> ServerSentEvent | None:
        """Consume one line; return an event when the current one terminates."""
        if line == "":
            return self._dispatch()
        if line.startswith(":"):
            return None

        field, separator, value = line.partition(":")
        if not separator:
            field, value = line, ""
        if value.startswith(" "):
            value = value[1:]

        if field == "data":
            self._data.append(value)
        elif field == "event":
            self._event = value
        elif field == "id":
            self._id = value
        return None

    def close(self) -> ServerSentEvent | None:
        """Flush at end of stream; non-``None`` means a truncated event."""
        return self._dispatch()

    def _dispatch(self) -> ServerSentEvent | None:
        if not self._data:
            self._event = None
            return None
        event = ServerSentEvent(data="\n".join(self._data), event=self._event, id=self._id)
        self._data = []
        self._event = None
        return event
