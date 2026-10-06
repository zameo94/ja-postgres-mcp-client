import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.mcp.base import (
    MCPClient,
    MCPConnectionError,
    MCPTool,
    MCPToolError,
    MCPToolResult,
)
from app.services.mcp.client import StreamableHTTPMCPClient


class FakeSession:
    def __init__(
        self,
        *,
        tools: list[Any] | None = None,
        call_result: Any = None,
        list_error: Exception | None = None,
        call_error: Exception | None = None,
    ) -> None:
        self._tools = tools or []
        self._call_result = call_result
        self._list_error = list_error
        self._call_error = call_error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> Any:
        if self._list_error is not None:
            raise self._list_error
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if self._call_error is not None:
            raise self._call_error
        return self._call_result


def make_client(session: FakeSession) -> StreamableHTTPMCPClient:
    @asynccontextmanager
    async def factory() -> Any:
        yield session

    return StreamableHTTPMCPClient("http://mcp.local/mcp", session_factory=factory)


async def test_list_tools_maps_server_tools() -> None:
    tool = SimpleNamespace(name="db_health", description="ping", input_schema={"type": "object"})
    client = make_client(FakeSession(tools=[tool]))

    tools = await client.list_tools()

    assert tools == [MCPTool(name="db_health", description="ping", input_schema={"type": "object"})]


async def test_list_tools_tolerates_missing_fields() -> None:
    tool = SimpleNamespace(name="db_x", description=None, input_schema=None)
    client = make_client(FakeSession(tools=[tool]))

    tools = await client.list_tools()

    assert tools == [MCPTool(name="db_x", description="", input_schema={})]


async def test_call_tool_renders_structured_content() -> None:
    session = FakeSession(
        call_result=SimpleNamespace(structured_content={"status": "ok"}, content=[], is_error=False)
    )
    client = make_client(session)

    result = await client.call_tool("db_health", {})

    assert result == MCPToolResult(content=json.dumps({"status": "ok"}), is_error=False)
    assert session.calls == [("db_health", {})]


async def test_call_tool_renders_text_blocks() -> None:
    session = FakeSession(
        call_result=SimpleNamespace(
            structured_content=None,
            content=[
                SimpleNamespace(type="text", text="hello"),
                SimpleNamespace(type="image", data="ignored"),
            ],
            is_error=False,
        )
    )
    client = make_client(session)

    result = await client.call_tool("db_x", {"a": 1})

    assert result.content == "hello"
    assert result.is_error is False


async def test_call_tool_preserves_tool_error_flag() -> None:
    session = FakeSession(
        call_result=SimpleNamespace(
            structured_content=None,
            content=[SimpleNamespace(type="text", text="boom")],
            is_error=True,
        )
    )
    client = make_client(session)

    result = await client.call_tool("db_x", {})

    assert result == MCPToolResult(content="boom", is_error=True)


async def test_empty_result_renders_empty_string() -> None:
    session = FakeSession(
        call_result=SimpleNamespace(structured_content=None, content=[], is_error=False)
    )
    client = make_client(session)

    result = await client.call_tool("db_x", {})

    assert result.content == ""


async def test_list_error_is_wrapped_as_connection_error() -> None:
    cause = RuntimeError("socket closed")
    client = make_client(FakeSession(list_error=cause))

    with pytest.raises(MCPConnectionError) as exc:
        await client.list_tools()

    assert exc.value.__cause__ is cause


async def test_call_error_is_wrapped_as_tool_error() -> None:
    cause = RuntimeError("protocol error")
    client = make_client(FakeSession(call_error=cause))

    with pytest.raises(MCPToolError) as exc:
        await client.call_tool("db_x", {})

    assert exc.value.__cause__ is cause


async def test_existing_mcp_error_is_not_double_wrapped() -> None:
    original = MCPConnectionError("already normalized")
    client = make_client(FakeSession(list_error=original))

    with pytest.raises(MCPConnectionError) as exc:
        await client.list_tools()

    assert exc.value is original


@pytest.mark.parametrize("url", ["not-a-url", "ftp://mcp.local/mcp", "http:///mcp"])
def test_rejects_invalid_url(url: str) -> None:
    with pytest.raises(ValueError):
        StreamableHTTPMCPClient(url)


def test_mcp_error_to_dict_is_user_safe() -> None:
    connection = MCPConnectionError()
    tool = MCPToolError()

    assert connection.to_dict() == {
        "code": "mcp_connection_error",
        "message": "The database service could not be reached.",
    }
    assert tool.to_dict() == {
        "code": "mcp_tool_error",
        "message": "The database service failed to run the tool.",
    }


def test_client_is_abstract_and_concrete_is_an_instance() -> None:
    with pytest.raises(TypeError):
        MCPClient()  # type: ignore[abstract]

    assert isinstance(StreamableHTTPMCPClient("http://mcp.local/mcp"), MCPClient)
