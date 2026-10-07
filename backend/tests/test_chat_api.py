from collections.abc import AsyncIterator, Sequence
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from app.services.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMStreamEvent,
    TextDelta,
    ToolDefinition,
)
from app.services.mcp.base import MCPClient, MCPTool, MCPToolResult
from app.services.mcp.client import StreamableHTTPMCPClient


class FakeMCP(MCPClient):
    async def list_tools(self) -> list[MCPTool]:
        return []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        return MCPToolResult(content="ok")


class FakeProvider(LLMProvider):
    name = "fake"

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition] = (),
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMStreamEvent]:
        yield TextDelta("hi")


async def _fake_build_provider(*args: Any, **kwargs: Any) -> FakeProvider:
    return FakeProvider()


def _app(monkeypatch: Any) -> Any:
    monkeypatch.setenv("JA_CLIENT_MCP_SERVER_URL", "http://mcp.local/mcp")
    monkeypatch.setattr("app.services.chat.build_provider", _fake_build_provider)
    app = create_app()
    app.state.settings = Settings(_env_file=None)
    app.state.mcp = FakeMCP()
    return app


def test_chat_streams_sse(monkeypatch: Any) -> None:
    client = TestClient(_app(monkeypatch))

    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "provider": "ollama"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: message_start" in response.text
    assert "event: token" in response.text
    assert "event: message_end" in response.text


def test_chat_rejects_empty_messages() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/chat",
        json={"messages": [], "provider": "ollama"},
    )

    assert response.status_code == 422


def test_chat_rejects_unknown_provider() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "provider": "nope"},
    )

    assert response.status_code == 422


def test_chat_rejects_assistant_as_last_message() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/chat",
        json={
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            "provider": "ollama",
        },
    )

    assert response.status_code == 422


def test_chat_endpoint_wires_the_real_lifespan(monkeypatch: Any) -> None:
    monkeypatch.setenv("JA_CLIENT_MCP_SERVER_URL", "http://mcp.local/mcp")
    monkeypatch.setattr("app.services.chat.build_provider", _fake_build_provider)
    monkeypatch.setattr("app.main.configure_logging", lambda level: None)
    get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            assert isinstance(app.state.mcp, StreamableHTTPMCPClient)
            app.state.mcp = FakeMCP()

            response = client.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "hi"}], "provider": "ollama"},
            )

            assert response.status_code == 200
            assert "event: message_end" in response.text
    finally:
        get_settings.cache_clear()
