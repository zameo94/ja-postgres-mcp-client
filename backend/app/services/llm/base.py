"""Canonical, provider-neutral LLM streaming contract used by the agent.

The agent depends only on the types in this module and on :class:`LLMProvider`.
Concrete providers (local Ollama, external OpenAI-compatible API) live in their
own adapters and are built per request by a factory.

Canonical events
----------------

A provider's :meth:`LLMProvider.stream` is an async iterator yielding exactly two
kinds of canonical events:

* :class:`TextDelta` -- incremental assistant text, emitted as soon as it is
  available;
* :class:`ToolCall` -- a **complete** tool call (id, name, fully parsed
  arguments), never a partial fragment.

Completion and errors
---------------------

* **Stream completion** is the normal termination of the async iterator. There is
  no completion event.
* **Errors** are raised as :class:`~app.services.llm.errors.LLMProviderError`
  (never yielded), carrying a stable code and a user-safe message. The agent
  must not depend on provider-specific exception types.

Ordering guarantees
-------------------

Only these are guaranteed:

* every emitted :class:`ToolCall` is complete;
* all events are emitted before the iterator terminates.

The **relative order of text and tool calls is not guaranteed** and differs
between providers (an adapter may emit tool calls inline as they arrive, or
buffer them and emit them after the text). Consumers must accumulate the stream,
collect tool calls, and act only once the iterator is exhausted.

Conversely, an adapter must not assume text and tool calls arrive in any
particular order from its provider, nor with any particular chunking strategy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar


class LLMRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ToolDefinition:
    """A tool the model may call, described as a JSON Schema parameter object."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A complete tool call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMMessage:
    """One message in the conversation sent to the model.

    ``tool_calls`` is set on assistant messages that request tools;
    ``tool_call_id`` (and ``name``) are set on tool-result messages.
    """

    role: LLMRole
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class TextDelta:
    """Incremental assistant text."""

    text: str


LLMStreamEvent = TextDelta | ToolCall


class LLMProvider(ABC):
    """A single LLM backend bound to one configuration for one request.

    Implementations translate the provider's native streaming protocol into the
    canonical events documented at module level, and must never expose
    credentials in errors or logs.
    """

    name: ClassVar[str] = ""

    @abstractmethod
    def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition] = (),
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Stream the model's reply for ``messages``.

        Yields :class:`TextDelta` and complete :class:`ToolCall` events; raises
        :class:`~app.services.llm.errors.LLMProviderError` on failure.
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release provider resources; stateless providers need not override."""
        return None
