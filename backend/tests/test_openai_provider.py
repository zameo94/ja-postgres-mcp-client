import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.services.llm.base import (
    LLMErrorCode,
    LLMMessage,
    LLMProviderError,
    LLMRole,
    TextDelta,
    ToolCall,
    ToolDefinition,
)
from app.services.llm.providers.openai import OpenAIProvider

Handler = Callable[[httpx.Request], httpx.Response]
BASE_URL = "https://api.example.com/v1"


def _sse(*events: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(event)}" for event in events]
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def _provider(handler: Handler) -> OpenAIProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAIProvider(BASE_URL, "secret-key", "gpt-4o-mini", client=client)


async def _collect(provider: OpenAIProvider, **kwargs: Any) -> list[Any]:
    messages = kwargs.pop("messages", [LLMMessage(role=LLMRole.USER, content="hi")])
    return [event async for event in provider.stream(messages, **kwargs)]


async def test_streams_text_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                {"choices": [{"delta": {"role": "assistant", "content": ""}}]},
                {"choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ),
        )

    events = await _collect(_provider(handler))

    assert events == [TextDelta("Hel"), TextDelta("lo")]


async def test_reassembles_fragmented_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {
                                            "name": "db_list_tables",
                                            "arguments": '{"schema":',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [{"index": 0, "function": {"arguments": '"public"}'}}]
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ),
        )

    events = await _collect(_provider(handler))

    assert events == [ToolCall(id="call_1", name="db_list_tables", arguments={"schema": "public"})]


async def test_payload_carries_model_temperature_tools_and_auth() -> None:
    captured: dict[str, Any] = {}
    auth: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        auth["value"] = request.headers.get("authorization")
        return httpx.Response(200, content=_sse({"choices": [{"delta": {"content": "ok"}}]}))

    tool = ToolDefinition(
        name="db_health",
        description="health check",
        parameters={"type": "object", "properties": {}},
    )

    await _collect(_provider(handler), tools=[tool], temperature=0.3)

    assert captured["model"] == "gpt-4o-mini"
    assert captured["temperature"] == 0.3
    assert captured["stream"] is True
    assert captured["tools"][0]["function"]["name"] == "db_health"
    assert auth["value"] == "Bearer secret-key"


async def test_omits_tools_when_none_are_given() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=_sse({"choices": [{"delta": {"content": "ok"}}]}))

    await _collect(_provider(handler))

    assert "tools" not in captured


async def test_encodes_assistant_tool_calls_and_tool_results() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=_sse({"choices": [{"delta": {"content": "ok"}}]}))

    messages = [
        LLMMessage(
            role=LLMRole.ASSISTANT,
            tool_calls=(ToolCall(id="call_1", name="db_health", arguments={"a": 1}),),
        ),
        LLMMessage(
            role=LLMRole.TOOL,
            content='{"status":"ok"}',
            tool_call_id="call_1",
            name="db_health",
        ),
    ]

    await _collect(_provider(handler), messages=messages)

    assert captured["messages"][0] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "db_health", "arguments": json.dumps({"a": 1})},
            }
        ],
    }
    assert captured["messages"][1] == {
        "role": "tool",
        "content": '{"status":"ok"}',
        "tool_call_id": "call_1",
    }


async def test_ignores_non_data_lines() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b": keep-alive\n\n" + _sse({"choices": [{"delta": {"content": "x"}}]}),
        )

    events = await _collect(_provider(handler))

    assert events == [TextDelta("x")]


async def test_malformed_event_raises_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data: {not-json}\n\n")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.BAD_RESPONSE


async def test_http_error_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"unauthorized")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.UNAVAILABLE


async def test_transport_error_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.UNAVAILABLE


async def test_error_field_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse({"error": {"message": "bad key"}}))

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.UNAVAILABLE


@pytest.mark.parametrize(
    ("base_url", "api_key", "model"),
    [
        ("not-a-url", "key", "model"),
        ("ftp://api.example.com", "key", "model"),
        (BASE_URL, "   ", "model"),
        (BASE_URL, "key", "   "),
    ],
)
def test_rejects_invalid_configuration(base_url: str, api_key: str, model: str) -> None:
    with pytest.raises(LLMProviderError) as exc:
        OpenAIProvider(base_url, api_key, model)

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_aclose_leaves_injected_client_open() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b""))
    )
    provider = OpenAIProvider(BASE_URL, "secret-key", "gpt-4o-mini", client=client)

    await provider.aclose()

    assert client.is_closed is False
    await client.aclose()
