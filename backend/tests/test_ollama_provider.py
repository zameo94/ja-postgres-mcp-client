import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.services.llm.base import (
    LLMMessage,
    LLMRole,
    TextDelta,
    ToolCall,
    ToolDefinition,
)
from app.services.llm.errors import LLMErrorCode, LLMProviderError
from app.services.llm.providers.ollama import OllamaProvider

Handler = Callable[[httpx.Request], httpx.Response]


def _ndjson(*chunks: dict[str, Any]) -> bytes:
    return ("\n".join(json.dumps(chunk) for chunk in chunks) + "\n").encode()


def _provider(handler: Handler) -> OllamaProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.local",
    )
    return OllamaProvider("http://ollama.local", "llama3.1", client=client)


async def _collect(provider: OllamaProvider, **kwargs: Any) -> list[Any]:
    messages = kwargs.pop("messages", [LLMMessage(role=LLMRole.USER, content="hi")])
    return [event async for event in provider.stream(messages, **kwargs)]


async def test_streams_text_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            content=_ndjson(
                {"message": {"content": "Hel"}},
                {"message": {"content": "lo"}},
                {"done": True},
            ),
        )

    events = await _collect(_provider(handler))

    assert events == [TextDelta("Hel"), TextDelta("lo")]


async def test_payload_carries_model_temperature_and_tools() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=_ndjson({"message": {"content": "ok"}, "done": True}))

    tool = ToolDefinition(
        name="db_health",
        description="health check",
        parameters={"type": "object", "properties": {}},
    )

    await _collect(_provider(handler), tools=[tool], temperature=0.1)

    assert captured["model"] == "llama3.1"
    assert captured["options"] == {"temperature": 0.1}
    assert captured["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "db_health",
                "description": "health check",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


async def test_omits_tools_when_none_are_given() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=_ndjson({"message": {"content": "ok"}, "done": True}))

    await _collect(_provider(handler))

    assert "tools" not in captured


async def test_emits_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_ndjson(
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "db_list_tables",
                                    "arguments": {"schema": "public"},
                                }
                            }
                        ],
                    }
                },
                {"done": True},
            ),
        )

    events = await _collect(
        _provider(handler), messages=[LLMMessage(role=LLMRole.USER, content="t")]
    )

    assert len(events) == 1
    call = events[0]
    assert isinstance(call, ToolCall)
    assert call.name == "db_list_tables"
    assert call.arguments == {"schema": "public"}
    assert isinstance(call.id, str) and call.id


async def test_parses_string_tool_arguments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_ndjson(
                {
                    "message": {
                        "tool_calls": [{"function": {"name": "db_health", "arguments": "{}"}}]
                    }
                },
                {"done": True},
            ),
        )

    events = await _collect(_provider(handler))

    assert isinstance(events[0], ToolCall)
    assert events[0].arguments == {}


async def test_encodes_tool_result_message() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=_ndjson({"message": {"content": "ok"}, "done": True}))

    messages = [
        LLMMessage(
            role=LLMRole.TOOL,
            content='{"status":"ok"}',
            tool_call_id="call-1",
            name="db_health",
        )
    ]

    await _collect(_provider(handler), messages=messages)

    assert captured["messages"] == [
        {"role": "tool", "content": '{"status":"ok"}', "tool_name": "db_health"}
    ]


async def test_malformed_stream_raises_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not-json}\n")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.MALFORMED_RESPONSE


async def test_http_error_raises_provider_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.PROVIDER_UNAVAILABLE


async def test_transport_error_raises_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.TRANSPORT


async def test_error_field_raises_provider_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_ndjson({"error": "model not found"}))

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.PROVIDER_UNAVAILABLE


def test_empty_model_is_rejected() -> None:
    with pytest.raises(LLMProviderError) as exc:
        OllamaProvider("http://ollama.local", "   ")

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_aclose_leaves_injected_client_open() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"")),
        base_url="http://ollama.local",
    )
    provider = OllamaProvider("http://ollama.local", "llama3.1", client=client)

    await provider.aclose()

    assert client.is_closed is False
    await client.aclose()
