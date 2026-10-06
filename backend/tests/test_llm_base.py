from collections.abc import AsyncIterator, Sequence

import pytest

from app.services.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMRole,
    LLMStreamEvent,
    TextDelta,
    ToolCall,
    ToolDefinition,
)
from app.services.llm.errors import LLMErrorCode, LLMProviderError


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        self.received: tuple[Sequence[LLMMessage], Sequence[ToolDefinition], float] | None = None

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition] = (),
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMStreamEvent]:
        self.received = (messages, tools, temperature)
        yield TextDelta("hello")
        yield ToolCall(id="c1", name="db_health", arguments={})
        yield TextDelta(" world")


async def test_stream_yields_text_and_tool_call_events() -> None:
    provider = FakeProvider()
    tools = [
        ToolDefinition(name="db_health", description="health check", parameters={"type": "object"})
    ]
    messages = [LLMMessage(role=LLMRole.USER, content="hi")]

    events = [event async for event in provider.stream(messages, tools=tools, temperature=0.2)]

    assert events == [
        TextDelta("hello"),
        ToolCall(id="c1", name="db_health", arguments={}),
        TextDelta(" world"),
    ]
    assert provider.received is not None
    received_messages, received_tools, received_temperature = provider.received
    assert received_messages == messages
    assert received_tools == tools
    assert received_temperature == 0.2


def test_message_defaults() -> None:
    message = LLMMessage(role=LLMRole.USER, content="hi")

    assert message.tool_calls == ()
    assert message.tool_call_id is None
    assert message.name is None


def test_provider_error_carries_code_and_message() -> None:
    error = LLMProviderError(LLMErrorCode.PROVIDER_UNAVAILABLE, message="provider is down")

    assert error.code is LLMErrorCode.PROVIDER_UNAVAILABLE
    assert error.message == "provider is down"
    assert str(error) == "provider is down"


def test_provider_cannot_be_instantiated_without_stream() -> None:
    class Incomplete(LLMProvider):
        name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


async def test_aclose_is_a_noop_by_default() -> None:
    assert await FakeProvider().aclose() is None
