"""Provider-agnostic LLM contract used by the agent.

The agent depends only on the types in this module and on :class:`LLMProvider`.
Concrete providers (local Ollama, external OpenAI-compatible API) live in their
own adapters and are built per request by a factory.

A provider turns its native streaming protocol into a flat sequence of
:data:`LLMStreamEvent` values: incremental text and/or complete tool calls. The
agent accumulates those events to decide whether to execute tools and call the
model again.
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
    """Incremental text produced by the model."""

    text: str


LLMStreamEvent = TextDelta | ToolCall


class LLMErrorCode(StrEnum):
    """Stable, provider-agnostic error codes surfaced to the agent."""

    INVALID_CONFIG = "INVALID_PROVIDER_CONFIG"
    UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    BAD_RESPONSE = "PROVIDER_BAD_RESPONSE"


class LLMProviderError(Exception):
    """Provider-agnostic failure with a stable, machine-readable code.

    ``message`` must be safe to surface: adapters never include credentials,
    request bodies or raw provider payloads in it.
    """

    def __init__(self, code: LLMErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LLMProvider(ABC):
    """A single LLM backend bound to one configuration for one request.

    Implementations translate the provider's native streaming protocol into
    :data:`LLMStreamEvent` values and must never expose credentials in errors or
    logs.
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

        Yields :class:`TextDelta` for incremental text and :class:`ToolCall` for
        each complete tool call the model requests. Raises
        :class:`LLMProviderError` on a normalized failure.
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release provider resources; stateless providers need not override."""
        return None
