"""External OpenAI-compatible provider.

Works with any endpoint that speaks the OpenAI Chat Completions protocol
(OpenAI, OpenRouter, vLLM, ...). The base URL, API key and model are supplied by
the user per request, so the base URL is validated against the SSRF policy before
it reaches ``httpx``.

Streaming uses the shared :class:`~app.services.llm.sse.SSEDecoder` (framing),
a JSON step, and a domain step. Tool calls arrive as fragmented deltas and are
correlated deterministically (see :class:`_ToolCallAccumulator`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx

from app.services.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMRole,
    LLMStreamEvent,
    TextDelta,
    ToolCall,
    ToolDefinition,
)
from app.services.llm.errors import (
    LLMErrorCode,
    LLMProviderError,
    error_from_http_status,
    error_from_transport,
)
from app.services.llm.sse import SSEDecoder
from app.services.llm.url_policy import validate_provider_base_url

EXTERNAL_API_PROVIDER_NAME = "external_api"
CHAT_PATH = "/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 120.0
DONE_MARKER = "[DONE]"


@dataclass
class _PendingToolCall:
    index: int | None = None
    id: str | None = None
    name_parts: list[str] = field(default_factory=list)
    argument_parts: list[str] = field(default_factory=list)


class _ToolCallAccumulator:
    """Correlates streaming tool-call deltas deterministically.

    A delta is keyed by its ``index`` when present, otherwise by its ``id``;
    a delta with neither is a protocol error. There is never a silent fallback
    to index 0, so distinct calls cannot be merged.
    """

    def __init__(self) -> None:
        self._calls: dict[object, _PendingToolCall] = {}

    def add(self, deltas: Any) -> None:
        if not isinstance(deltas, list):
            return
        for delta in deltas:
            if not isinstance(delta, dict):
                raise LLMProviderError(
                    LLMErrorCode.TOOL_CALL, detail="tool call delta is not an object"
                )
            index_value = delta.get("index")
            index = (
                index_value
                if isinstance(index_value, int) and not isinstance(index_value, bool)
                else None
            )
            id_value = delta.get("id")
            call_id = id_value if isinstance(id_value, str) and id_value else None
            if index is not None:
                key: object = ("index", index)
            elif call_id is not None:
                key = ("id", call_id)
            else:
                raise LLMProviderError(
                    LLMErrorCode.TOOL_CALL,
                    detail="tool call delta without index or id",
                )

            entry = self._calls.get(key)
            if entry is None:
                entry = _PendingToolCall(index=index, id=call_id)
                self._calls[key] = entry
            if entry.id is None and call_id is not None:
                entry.id = call_id
            if entry.index is None and index is not None:
                entry.index = index

            function = delta.get("function")
            if isinstance(function, dict):
                name = function.get("name")
                if isinstance(name, str):
                    entry.name_parts.append(name)
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    entry.argument_parts.append(arguments)

    def finalize(self) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for entry in self._calls.values():
            name = "".join(entry.name_parts)
            raw_arguments = "".join(entry.argument_parts) or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise LLMProviderError(
                    LLMErrorCode.TOOL_CALL, detail="invalid tool arguments"
                ) from exc
            if not name or not isinstance(arguments, dict):
                raise LLMProviderError(LLMErrorCode.TOOL_CALL, detail="invalid tool call")
            calls.append(ToolCall(id=entry.id or str(uuid4()), name=name, arguments=arguments))
        return calls


class OpenAIProvider(LLMProvider):
    """A single external OpenAI-compatible backend for one request."""

    name = EXTERNAL_API_PROVIDER_NAME

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        allow_insecure: bool = False,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = validate_provider_base_url(base_url, allow_insecure=allow_insecure).rstrip(
            "/"
        )
        if not api_key.strip():
            raise LLMProviderError(
                LLMErrorCode.INVALID_CONFIG,
                message="The API key must not be empty.",
            )
        if not model.strip():
            raise LLMProviderError(
                LLMErrorCode.INVALID_CONFIG,
                message="The model name must not be empty.",
            )
        self._api_key = api_key
        self._model = model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _payload(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition],
        temperature: float,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [self._encode_message(message) for message in messages],
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = [self._encode_tool(tool) for tool in tools]
        return payload

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition] = (),
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMStreamEvent]:
        payload = self._payload(messages, tools, temperature)
        accumulator = _ToolCallAccumulator()
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}{CHAT_PATH}",
                json=payload,
                headers=self._headers(),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise error_from_http_status(
                        response.status_code, detail=f"HTTP {response.status_code}"
                    )
                decoder = SSEDecoder()
                async for line in response.aiter_lines():
                    event = decoder.feed(line)
                    if event is None:
                        continue
                    if event.data == DONE_MARKER:
                        break
                    data = self._parse_event(event.data)
                    if data.get("error"):
                        raise LLMProviderError(
                            LLMErrorCode.PROVIDER_UNAVAILABLE,
                            detail="provider returned an error",
                        )
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield TextDelta(content)
                    accumulator.add(delta.get("tool_calls"))
                if decoder.close() is not None:
                    raise LLMProviderError(
                        LLMErrorCode.STREAMING_PROTOCOL,
                        detail="stream ended mid-event",
                    )
        except httpx.HTTPError as exc:
            raise error_from_transport(exc, detail="provider transport error") from exc

        for call in accumulator.finalize():
            yield call

    @staticmethod
    def _parse_event(data: str) -> dict[str, Any]:
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                LLMErrorCode.MALFORMED_RESPONSE, detail="invalid JSON event"
            ) from exc
        if not isinstance(event, dict):
            raise LLMProviderError(LLMErrorCode.MALFORMED_RESPONSE, detail="event is not an object")
        return event

    @staticmethod
    def _encode_message(message: LLMMessage) -> dict[str, Any]:
        if message.role is LLMRole.TOOL:
            return {
                "role": message.role.value,
                "content": message.content,
                "tool_call_id": message.tool_call_id or "",
            }
        encoded: dict[str, Any] = {"role": message.role.value, "content": message.content}
        if message.tool_calls:
            encoded["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ]
        return encoded

    @staticmethod
    def _encode_tool(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
