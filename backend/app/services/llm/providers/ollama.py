"""Local Ollama provider over its HTTP chat API.

Ollama streams newline-delimited JSON chunks from ``POST /api/chat``. This
adapter normalizes them into :data:`~app.services.llm.base.LLMStreamEvent`
values and maps tool definitions/arguments between our schema and Ollama's.
Error messages are deliberately generic so no provider payload or credential can
leak; the original exception is preserved as ``__cause__``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any
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

OLLAMA_PROVIDER_NAME = "ollama"
CHAT_PATH = "/api/chat"
DEFAULT_TIMEOUT_SECONDS = 120.0


class OllamaProvider(LLMProvider):
    """A single local Ollama backend, bound to one model for one request."""

    name = OLLAMA_PROVIDER_NAME

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not model.strip():
            raise LLMProviderError(LLMErrorCode.INVALID_CONFIG, "model must not be empty")
        self._model = model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _payload(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition],
        temperature: float,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [self._encode_message(message) for message in messages],
            "stream": True,
            "options": {"temperature": temperature},
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
        try:
            async with self._client.stream("POST", CHAT_PATH, json=payload) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise LLMProviderError(
                        LLMErrorCode.UNAVAILABLE,
                        f"Ollama returned status {response.status_code}",
                    )
                async for line in response.aiter_lines():
                    chunk = line.strip()
                    if not chunk:
                        continue
                    data = self._parse_chunk(chunk)
                    if data.get("error"):
                        raise LLMProviderError(LLMErrorCode.UNAVAILABLE, "Ollama reported an error")
                    message = data.get("message") or {}
                    content = message.get("content")
                    if content:
                        yield TextDelta(content)
                    for raw_call in message.get("tool_calls") or ():
                        yield self._parse_tool_call(raw_call)
                    if data.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise LLMProviderError(LLMErrorCode.UNAVAILABLE, "Could not reach Ollama") from exc

    @staticmethod
    def _parse_chunk(chunk: str) -> dict[str, Any]:
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                LLMErrorCode.BAD_RESPONSE, "Ollama streamed invalid data"
            ) from exc
        if not isinstance(data, dict):
            raise LLMProviderError(LLMErrorCode.BAD_RESPONSE, "Ollama streamed invalid data")
        return data

    @staticmethod
    def _parse_tool_call(raw: Any) -> ToolCall:
        function = raw.get("function") if isinstance(raw, dict) else None
        if not isinstance(function, dict):
            raise LLMProviderError(
                LLMErrorCode.BAD_RESPONSE, "Ollama returned an invalid tool call"
            )
        name = function.get("name")
        arguments: Any = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise LLMProviderError(
                    LLMErrorCode.BAD_RESPONSE, "Ollama returned invalid tool arguments"
                ) from exc
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            raise LLMProviderError(
                LLMErrorCode.BAD_RESPONSE, "Ollama returned an invalid tool call"
            )
        return ToolCall(id=str(uuid4()), name=name, arguments=arguments)

    @staticmethod
    def _encode_message(message: LLMMessage) -> dict[str, Any]:
        encoded: dict[str, Any] = {"role": message.role.value, "content": message.content}
        if message.tool_calls:
            encoded["tool_calls"] = [
                {"function": {"name": call.name, "arguments": call.arguments}}
                for call in message.tool_calls
            ]
        if message.role is LLMRole.TOOL and message.name:
            encoded["tool_name"] = message.name
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
