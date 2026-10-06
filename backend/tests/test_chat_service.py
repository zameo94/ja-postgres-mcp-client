from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from app.core.config import Settings
from app.schemas.chat import ChatMessage, ChatRequest, ProviderConfig
from app.services.agent.errors import AgentError, AgentErrorCode
from app.services.chat import ChatService
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
from app.services.mcp.base import (
    MCPClient,
    MCPConnectionError,
    MCPTool,
    MCPToolResult,
)


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(
        self,
        scripts: list[list[LLMStreamEvent]] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._scripts = scripts or []
        self._error = error
        self.closed = False
        self.calls: list[list[LLMMessage]] = []

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition] = (),
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMStreamEvent]:
        self.calls.append(list(messages))
        if self._error is not None:
            raise self._error
        for event in self._scripts.pop(0):
            yield event

    async def aclose(self) -> None:
        self.closed = True


class RaisingAgent:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def run(
        self, messages: Sequence[LLMMessage], *, temperature: float = 0.0
    ) -> AsyncIterator[object]:
        raise AgentError(AgentErrorCode.TOOL_LOOP_EXCEEDED)
        yield  # pragma: no cover


class FakeMCP(MCPClient):
    def __init__(
        self,
        tools: list[MCPTool] | None = None,
        results: dict[str, MCPToolResult] | None = None,
        *,
        list_error: Exception | None = None,
    ) -> None:
        self._tools = tools or []
        self._results = results or {}
        self._list_error = list_error

    async def list_tools(self) -> list[MCPTool]:
        if self._list_error is not None:
            raise self._list_error
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        return self._results[name]


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("JA_CLIENT_MCP_SERVER_URL", "http://mcp.local/mcp")
    return Settings(_env_file=None)


def _request(**provider_kwargs: Any) -> ChatRequest:
    provider = ProviderConfig(provider="ollama", model="test-model", **provider_kwargs)
    return ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        provider=provider,
    )


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: LLMProvider) -> None:
    monkeypatch.setattr("app.services.chat.build_provider", lambda *args, **kwargs: provider)


async def test_streams_text_then_message_end(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ScriptedProvider([[TextDelta("Hel"), TextDelta("lo")]])
    _use_provider(monkeypatch, provider)
    service = ChatService(_settings(monkeypatch), FakeMCP())

    events = [event async for event in service.stream(_request())]

    assert [event.name for event in events] == ["message_start", "token", "token", "message_end"]
    assert events[1].data == {"text": "Hel"}
    assert provider.closed is True


async def test_system_prompt_is_prepended(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ScriptedProvider([[TextDelta("ok")]])
    _use_provider(monkeypatch, provider)
    settings = _settings(monkeypatch)
    service = ChatService(settings, FakeMCP())

    _ = [event async for event in service.stream(_request())]

    messages = provider.calls[0]
    assert messages[0].role is LLMRole.SYSTEM
    assert messages[0].content == settings.system_prompt
    assert messages[1].role is LLMRole.USER


async def test_maps_tool_events(monkeypatch: pytest.MonkeyPatch) -> None:
    call = ToolCall(id="c1", name="db_health", arguments={})
    provider = ScriptedProvider([[call], [TextDelta("done")]])
    _use_provider(monkeypatch, provider)
    mcp = FakeMCP(
        tools=[MCPTool(name="db_health", description="h", input_schema={})],
        results={"db_health": MCPToolResult(content="ok")},
    )
    service = ChatService(_settings(monkeypatch), mcp)

    events = [event async for event in service.stream(_request())]

    assert [event.name for event in events] == [
        "message_start",
        "tool_call",
        "tool_result",
        "token",
        "message_end",
    ]
    assert events[1].data == {"id": "c1", "name": "db_health", "arguments": {}}


async def test_provider_construction_error_emits_only_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> LLMProvider:
        raise LLMProviderError(LLMErrorCode.INVALID_CONFIG)

    monkeypatch.setattr("app.services.chat.build_provider", boom)
    service = ChatService(_settings(monkeypatch), FakeMCP())

    events = [event async for event in service.stream(_request())]

    assert [event.name for event in events] == ["error"]
    assert events[0].data["code"] == "invalid_config"


async def test_unexpected_provider_construction_error_is_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> LLMProvider:
        raise RuntimeError("bug")

    monkeypatch.setattr("app.services.chat.build_provider", boom)
    service = ChatService(_settings(monkeypatch), FakeMCP())

    events = [event async for event in service.stream(_request())]

    assert [event.name for event in events] == ["error"]
    assert events[0].data["code"] == "internal_error"


async def test_provider_stream_error_after_start(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ScriptedProvider(error=LLMProviderError(LLMErrorCode.AUTHENTICATION))
    _use_provider(monkeypatch, provider)
    service = ChatService(_settings(monkeypatch), FakeMCP())

    events = [event async for event in service.stream(_request())]

    assert [event.name for event in events] == ["message_start", "error"]
    assert events[1].data["code"] == "authentication_failed"
    assert provider.closed is True


async def test_agent_error_is_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_provider(monkeypatch, ScriptedProvider([[TextDelta("x")]]))
    monkeypatch.setattr("app.services.chat.Agent", RaisingAgent)
    service = ChatService(_settings(monkeypatch), FakeMCP())

    events = [event async for event in service.stream(_request())]

    assert [event.name for event in events] == ["message_start", "error"]
    assert events[1].data["code"] == "tool_loop_exceeded"


async def test_mcp_connection_error_is_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ScriptedProvider([[TextDelta("x")]])
    _use_provider(monkeypatch, provider)
    service = ChatService(_settings(monkeypatch), FakeMCP(list_error=MCPConnectionError()))

    events = [event async for event in service.stream(_request())]

    assert [event.name for event in events] == ["message_start", "error"]
    assert events[1].data["code"] == "mcp_connection_error"
    assert provider.closed is True


async def test_unexpected_runtime_error_is_mapped_to_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ScriptedProvider(error=RuntimeError("boom"))
    _use_provider(monkeypatch, provider)
    service = ChatService(_settings(monkeypatch), FakeMCP())

    events = [event async for event in service.stream(_request())]

    assert [event.name for event in events] == ["message_start", "error"]
    assert events[1].data == {"code": "internal_error", "message": "An unexpected error occurred."}
