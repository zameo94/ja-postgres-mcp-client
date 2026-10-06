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
from app.services.llm.providers.openai import OpenAIProvider

Handler = Callable[[httpx.Request], httpx.Response]
BASE_URL = "https://api.example.com/v1"


def _sse(*events: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(event)}" for event in events]
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def _provider(handler: Handler, *, allow_insecure: bool = False) -> OpenAIProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAIProvider(
        BASE_URL, "secret-key", "gpt-4o-mini", allow_insecure=allow_insecure, client=client
    )


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


async def test_joins_json_split_across_data_lines() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = b'data: {"choices":\ndata: [{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, content=content)

    events = await _collect(_provider(handler))

    assert events == [TextDelta("hi")]


async def test_reassembles_fragmented_tool_calls_by_index() -> None:
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


async def test_keeps_parallel_tool_calls_separate_and_ordered() -> None:
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
                                "tool_calls": [
                                    {
                                        "index": 1,
                                        "id": "call_2",
                                        "function": {"name": "db_health", "arguments": "{}"},
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
            ),
        )

    events = await _collect(_provider(handler))

    assert events == [
        ToolCall(id="call_1", name="db_list_tables", arguments={"schema": "public"}),
        ToolCall(id="call_2", name="db_health", arguments={}),
    ]


async def test_correlates_by_id_when_index_is_absent() -> None:
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
                                        "id": "call_x",
                                        "function": {"name": "db_health", "arguments": "{"},
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
                                "tool_calls": [{"id": "call_x", "function": {"arguments": "}"}}]
                            }
                        }
                    ]
                },
            ),
        )

    events = await _collect(_provider(handler))

    assert events == [ToolCall(id="call_x", name="db_health", arguments={})]


async def test_tool_call_without_index_or_id_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                {"choices": [{"delta": {"tool_calls": [{"function": {"arguments": "{}"}}]}}]},
            ),
        )

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.TOOL_CALL


async def test_empty_arguments_default_to_empty_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "id": "call_1", "function": {"name": "db_health"}}
                                ]
                            }
                        }
                    ]
                },
            ),
        )

    events = await _collect(_provider(handler))

    assert events == [ToolCall(id="call_1", name="db_health", arguments={})]


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


async def test_ignores_comments_and_non_data_lines() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b": keep-alive\n\n" + _sse({"choices": [{"delta": {"content": "x"}}]}),
        )

    events = await _collect(_provider(handler))

    assert events == [TextDelta("x")]


async def test_malformed_event_raises_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data: {not-json}\n\n")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.MALFORMED_RESPONSE


async def test_truncated_stream_raises_streaming_protocol() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"x"}}]}\n')

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.STREAMING_PROTOCOL


async def test_auth_error_raises_authentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"unauthorized")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.AUTHENTICATION


async def test_rate_limit_raises_rate_limited() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b"slow down")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.RATE_LIMITED


async def test_transport_error_raises_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.TRANSPORT


async def test_error_field_raises_provider_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse({"error": {"message": "bad key"}}))

    with pytest.raises(LLMProviderError) as exc:
        await _collect(_provider(handler))

    assert exc.value.code is LLMErrorCode.PROVIDER_UNAVAILABLE


@pytest.mark.parametrize(
    ("base_url", "api_key", "model"),
    [
        ("not-a-url", "key", "model"),
        ("ftp://api.example.com", "key", "model"),
        ("http://api.example.com", "key", "model"),
        (BASE_URL, "   ", "model"),
        (BASE_URL, "key", "   "),
    ],
)
def test_rejects_invalid_configuration(base_url: str, api_key: str, model: str) -> None:
    with pytest.raises(LLMProviderError) as exc:
        OpenAIProvider(base_url, api_key, model)

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_insecure_mode_allows_local_http_endpoint() -> None:
    provider = OpenAIProvider("http://localhost:1234/v1", "key", "model", allow_insecure=True)

    assert provider.name == "external_api"
    await provider.aclose()


async def test_aclose_leaves_injected_client_open() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b""))
    )
    provider = OpenAIProvider(BASE_URL, "secret-key", "gpt-4o-mini", client=client)

    await provider.aclose()

    assert client.is_closed is False
    await client.aclose()
