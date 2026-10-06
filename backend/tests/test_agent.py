from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from app.services.agent.agent import MAX_TOOL_RESULT_CHARS, Agent
from app.services.agent.errors import AgentError, AgentErrorCode
from app.services.agent.events import AgentTextDelta, AgentToolCall, AgentToolResult
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
    MCPToolError,
    MCPToolResult,
)


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, scripts: list[list[LLMStreamEvent]]) -> None:
        self._scripts = scripts
        self.calls: list[tuple[list[LLMMessage], list[ToolDefinition], float]] = []

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition] = (),
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMStreamEvent]:
        self.calls.append((list(messages), list(tools), temperature))
        for event in self._scripts.pop(0):
            yield event


class FailingProvider(LLMProvider):
    name = "failing"

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition] = (),
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMStreamEvent]:
        raise self._error
        yield TextDelta("")  # pragma: no cover


class FakeMCP(MCPClient):
    def __init__(
        self,
        tools: list[MCPTool] | None = None,
        results: dict[str, MCPToolResult] | None = None,
        *,
        list_error: Exception | None = None,
        call_error: Exception | None = None,
    ) -> None:
        self._tools = tools or []
        self._results = results or {}
        self._list_error = list_error
        self._call_error = call_error
        self.list_tools_calls = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[MCPTool]:
        self.list_tools_calls += 1
        if self._list_error is not None:
            raise self._list_error
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        self.calls.append((name, arguments))
        if self._call_error is not None:
            raise self._call_error
        return self._results[name]


def _user(text: str = "hi") -> LLMMessage:
    return LLMMessage(role=LLMRole.USER, content=text)


def _tool(name: str = "db_health") -> MCPTool:
    return MCPTool(
        name=name, description="health", input_schema={"type": "object", "properties": {}}
    )


def _call(name: str = "db_health", *, call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={})


async def _run(agent: Agent, messages: list[LLMMessage]) -> list[Any]:
    return [event async for event in agent.run(messages)]


async def test_returns_text_without_tools() -> None:
    provider = ScriptedProvider([[TextDelta("Hel"), TextDelta("lo")]])
    mcp = FakeMCP()
    agent = Agent(provider, mcp)

    events = await _run(agent, [_user()])

    assert events == [AgentTextDelta("Hel"), AgentTextDelta("lo")]
    assert mcp.calls == []


async def test_passes_mcp_tools_as_definitions_and_lists_once() -> None:
    provider = ScriptedProvider([[TextDelta("ok")]])
    mcp = FakeMCP(tools=[_tool()])
    agent = Agent(provider, mcp)

    await _run(agent, [_user()])

    _messages, tools, temperature = provider.calls[0]
    assert tools == [
        ToolDefinition(
            name="db_health",
            description="health",
            parameters={"type": "object", "properties": {}},
        )
    ]
    assert temperature == 0.0
    assert mcp.list_tools_calls == 1


async def test_temperature_is_forwarded_to_provider() -> None:
    provider = ScriptedProvider([[TextDelta("ok")]])
    agent = Agent(provider, FakeMCP())

    _ = [event async for event in agent.run([_user()], temperature=0.7)]

    assert provider.calls[0][2] == 0.7


async def test_executes_tool_and_continues() -> None:
    call = _call()
    provider = ScriptedProvider([[call], [TextDelta("done")]])
    mcp = FakeMCP(results={"db_health": MCPToolResult(content='{"status":"ok"}')})
    agent = Agent(provider, mcp)

    events = await _run(agent, [_user("health?")])

    assert events == [
        AgentToolCall(id="c1", name="db_health", arguments={}),
        AgentToolResult(id="c1", name="db_health", content='{"status":"ok"}', is_error=False),
        AgentTextDelta("done"),
    ]
    assert mcp.calls == [("db_health", {})]


async def test_second_call_includes_tool_history() -> None:
    call = _call()
    provider = ScriptedProvider([[call], [TextDelta("done")]])
    mcp = FakeMCP(results={"db_health": MCPToolResult(content="ok")})
    agent = Agent(provider, mcp)

    await _run(agent, [_user("q")])

    messages, _tools, _temperature = provider.calls[1]
    assert messages[0] == _user("q")
    assert messages[1] == LLMMessage(role=LLMRole.ASSISTANT, content="", tool_calls=(call,))
    assert messages[2] == LLMMessage(
        role=LLMRole.TOOL, content="ok", tool_call_id="c1", name="db_health"
    )


async def test_does_not_mutate_input_messages() -> None:
    original = [_user("q")]
    provider = ScriptedProvider([[_call()], [TextDelta("done")]])
    mcp = FakeMCP(results={"db_health": MCPToolResult(content="ok")})
    agent = Agent(provider, mcp)

    await _run(agent, original)

    assert original == [_user("q")]


async def test_multi_turn_history_is_passed_through() -> None:
    history = [
        _user("first"),
        LLMMessage(role=LLMRole.ASSISTANT, content="first answer"),
        _user("second"),
    ]
    provider = ScriptedProvider([[TextDelta("ok")]])
    agent = Agent(provider, FakeMCP())

    await _run(agent, history)

    assert provider.calls[0][0] == history


async def test_executes_parallel_tool_calls_in_order() -> None:
    first = ToolCall(id="c1", name="a", arguments={"x": 1})
    second = ToolCall(id="c2", name="b", arguments={"y": 2})
    provider = ScriptedProvider([[first, second], [TextDelta("ok")]])
    mcp = FakeMCP(results={"a": MCPToolResult(content="A"), "b": MCPToolResult(content="B")})
    agent = Agent(provider, mcp)

    await _run(agent, [_user()])

    assert mcp.calls == [("a", {"x": 1}), ("b", {"y": 2})]


async def test_forwards_tool_error_result_with_marker() -> None:
    call = _call()
    provider = ScriptedProvider([[call], [TextDelta("recovered")]])
    mcp = FakeMCP(results={"db_health": MCPToolResult(content="boom", is_error=True)})
    agent = Agent(provider, mcp)

    events = await _run(agent, [_user()])

    result = next(event for event in events if isinstance(event, AgentToolResult))
    assert result.is_error is True
    assert result.content == "Tool error: boom"


async def test_unknown_tool_returns_error_without_mcp_call() -> None:
    provider = ScriptedProvider([[_call("ghost")], [TextDelta("fixed")]])
    mcp = FakeMCP(results={})
    agent = Agent(provider, mcp)

    events = await _run(agent, [_user()])

    assert events == [
        AgentToolCall(id="c1", name="ghost", arguments={}),
        AgentToolResult(id="c1", name="ghost", content="Unknown tool: ghost", is_error=True),
        AgentTextDelta("fixed"),
    ]
    assert mcp.calls == []


async def test_mcp_tool_error_becomes_error_result() -> None:
    call = _call()
    provider = ScriptedProvider([[call], [TextDelta("ok")]])
    mcp = FakeMCP(call_error=MCPToolError("protocol error"))
    agent = Agent(provider, mcp)

    events = await _run(agent, [_user()])

    result = next(event for event in events if isinstance(event, AgentToolResult))
    assert result.is_error is True
    assert result.content == "Tool execution failed: protocol error"


async def test_mcp_tool_errors_are_tolerated_up_to_the_limit_then_raised() -> None:
    call = _call()
    provider = ScriptedProvider([[call], [call]])
    mcp = FakeMCP(call_error=MCPToolError("dead"))
    agent = Agent(provider, mcp, max_tool_failures=1)

    with pytest.raises(MCPToolError):
        await _run(agent, [_user()])


async def test_mcp_connection_error_from_call_is_fatal() -> None:
    call = _call()
    provider = ScriptedProvider([[call], [TextDelta("x")]])
    mcp = FakeMCP(call_error=MCPConnectionError("down"))
    agent = Agent(provider, mcp)

    with pytest.raises(MCPConnectionError):
        await _run(agent, [_user()])


async def test_long_tool_result_is_truncated() -> None:
    call = _call()
    big = "x" * (MAX_TOOL_RESULT_CHARS + 500)
    provider = ScriptedProvider([[call], [TextDelta("done")]])
    mcp = FakeMCP(results={"db_health": MCPToolResult(content=big)})
    agent = Agent(provider, mcp)

    events = await _run(agent, [_user()])

    result = next(event for event in events if isinstance(event, AgentToolResult))
    assert result.content.endswith("[tool result truncated]")
    assert len(result.content) < len(big)


async def test_exactly_max_tool_rounds_then_final_answer_succeeds() -> None:
    call = _call()
    provider = ScriptedProvider([[call], [TextDelta("final")]])
    mcp = FakeMCP(results={"db_health": MCPToolResult(content="ok")})
    agent = Agent(provider, mcp, max_tool_rounds=1)

    events = await _run(agent, [_user()])

    assert events[-1] == AgentTextDelta("final")


async def test_error_is_raised_after_partial_deltas() -> None:
    call = _call()
    provider = ScriptedProvider([[TextDelta("preamble"), call], [TextDelta("more"), call]])
    mcp = FakeMCP(results={"db_health": MCPToolResult(content="ok")})
    agent = Agent(provider, mcp, max_tool_rounds=1)

    emitted: list[Any] = []
    with pytest.raises(AgentError):
        async for event in agent.run([_user()]):
            emitted.append(event)

    assert AgentTextDelta("preamble") in emitted
    assert AgentTextDelta("more") in emitted


async def test_provider_error_propagates() -> None:
    agent = Agent(
        FailingProvider(LLMProviderError(LLMErrorCode.AUTHENTICATION)),
        FakeMCP(),
    )

    with pytest.raises(LLMProviderError):
        await _run(agent, [_user()])


async def test_mcp_connection_error_from_list_tools_propagates() -> None:
    agent = Agent(
        ScriptedProvider([[TextDelta("x")]]),
        FakeMCP(list_error=MCPConnectionError("down")),
    )

    with pytest.raises(MCPConnectionError):
        await _run(agent, [_user()])


def test_rejects_negative_limits() -> None:
    with pytest.raises(ValueError):
        Agent(ScriptedProvider([]), FakeMCP(), max_tool_rounds=-1)
    with pytest.raises(ValueError):
        Agent(ScriptedProvider([]), FakeMCP(), max_tool_failures=-1)


def test_agent_error_serializes_without_detail() -> None:
    error = AgentError(AgentErrorCode.TOOL_LOOP_EXCEEDED, detail="internal debug")

    assert error.to_dict() == {
        "code": "tool_loop_exceeded",
        "message": "The assistant asked to use too many tools in one turn. Please try again.",
    }
    assert "internal debug" not in str(error.to_dict())


def test_agent_error_default_message_when_omitted() -> None:
    error = AgentError(AgentErrorCode.TOOL_LOOP_EXCEEDED)

    assert error.message == (
        "The assistant asked to use too many tools in one turn. Please try again."
    )
