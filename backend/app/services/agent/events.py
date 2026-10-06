"""Agent-level streaming events.

These are the application events the agent produces for the transport layer (SSE
in the next task). They are deliberately decoupled from provider-specific
streaming events and from HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentTextDelta:
    """Incremental assistant text to forward to the client."""

    text: str


@dataclass(frozen=True)
class AgentToolCall:
    """The agent is about to execute a tool."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentToolResult:
    """The result of a tool execution."""

    id: str
    name: str
    content: str
    is_error: bool


AgentEvent = AgentTextDelta | AgentToolCall | AgentToolResult
