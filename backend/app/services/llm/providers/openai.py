"""External OpenAI-compatible provider.

Works with any endpoint that speaks the OpenAI Chat Completions protocol
(OpenAI, OpenRouter, vLLM, ...). The base URL, API key and model are supplied by
the user per request.

The provider streams Server-Sent Events and reassembles tool calls, which OpenAI
sends as fragmented deltas keyed by ``index``. Error messages are deliberately
generic: the API key and provider payloads never appear in them, and the
original exception is preserved as ``__cause__``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.services.llm.base import (
    LLMErrorCode,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMRole,
    LLMStreamEvent,
    TextDelta,
    ToolCall,
    ToolDefinition,
)

EXTERNAL_API_PROVIDER_NAME = "external_api"
CHAT_PATH = "/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 120.0
DONE_MARKER = "[DONE]"


class OpenAIProvider(LLMProvider):
    """A single external OpenAI-compatible backend for one request."""

    name = EXTERNAL_API_PROVIDER_NAME

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        parts = urlsplit(base_url.strip())
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise LLMProviderError(
                LLMErrorCode.INVALID_CONFIG, "base_url must be an absolute http(s) URL"
            )
        if not api_key.strip():
            raise LLMProviderError(LLMErrorCode.INVALID_CONFIG, "api_key must not be empty")
        if not model.strip():
            raise LLMProviderError(LLMErrorCode.INVALID_CONFIG, "model must not be empty")
        self._base_url = base_url.rstrip("/")
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
        pending: dict[int, dict[str, str]] = {}
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}{CHAT_PATH}",
                json=payload,
                headers=self._headers(),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise LLMProviderError(
                        LLMErrorCode.UNAVAILABLE,
                        f"Provider returned status {response.status_code}",
                    )
                async for line in response.aiter_lines():
                    chunk = line.strip()
                    if not chunk or not chunk.startswith("data:"):
                        continue
                    data = chunk[len("data:") :].strip()
                    if data == DONE_MARKER:
                        break
                    event = self._parse_event(data)
                    if event.get("error"):
                        raise LLMProviderError(
                            LLMErrorCode.UNAVAILABLE, "Provider reported an error"
                        )
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield TextDelta(content)
                    self._accumulate_tool_calls(delta.get("tool_calls"), pending)
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                LLMErrorCode.UNAVAILABLE, "Could not reach the provider"
            ) from exc

        for call in self._finalize_tool_calls(pending):
            yield call

    @staticmethod
    def _parse_event(data: str) -> dict[str, Any]:
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                LLMErrorCode.BAD_RESPONSE, "Provider streamed invalid data"
            ) from exc
        if not isinstance(event, dict):
            raise LLMProviderError(LLMErrorCode.BAD_RESPONSE, "Provider streamed invalid data")
        return event

    @staticmethod
    def _accumulate_tool_calls(deltas: Any, pending: dict[int, dict[str, str]]) -> None:
        if not isinstance(deltas, list):
            return
        for delta in deltas:
            if not isinstance(delta, dict):
                continue
            raw_index = delta.get("index", 0)
            index = raw_index if isinstance(raw_index, int) else 0
            entry = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
            call_id = delta.get("id")
            if isinstance(call_id, str) and call_id:
                entry["id"] = call_id
            function = delta.get("function")
            if isinstance(function, dict):
                name = function.get("name")
                if isinstance(name, str):
                    entry["name"] += name
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    entry["arguments"] += arguments

    @staticmethod
    def _finalize_tool_calls(pending: dict[int, dict[str, str]]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for index in sorted(pending):
            entry = pending[index]
            name = entry["name"]
            raw_arguments = entry["arguments"] or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise LLMProviderError(
                    LLMErrorCode.BAD_RESPONSE, "Provider returned invalid tool arguments"
                ) from exc
            if not name or not isinstance(arguments, dict):
                raise LLMProviderError(
                    LLMErrorCode.BAD_RESPONSE, "Provider returned an invalid tool call"
                )
            calls.append(ToolCall(id=entry["id"] or str(uuid4()), name=name, arguments=arguments))
        return calls

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
