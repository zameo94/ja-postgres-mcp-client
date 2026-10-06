"""Chat application service.

Turns a chat request into a provider + agent run and maps the agent's events and
failures into transport-agnostic :class:`ChatEvent` values. The HTTP/SSE layer
only serializes these; it contains no orchestration logic.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.core.config import Settings
from app.schemas.chat import ChatMessage, ChatRequest
from app.services.agent.agent import Agent
from app.services.agent.errors import AgentError
from app.services.agent.events import (
    AgentEvent,
    AgentTextDelta,
    AgentToolCall,
    AgentToolResult,
)
from app.services.llm.base import LLMMessage, LLMRole
from app.services.llm.errors import LLMProviderError
from app.services.llm.factory import build_provider
from app.services.mcp.base import MCPClient, MCPError

logger = logging.getLogger(__name__)

INTERNAL_ERROR: dict[str, str] = {
    "code": "internal_error",
    "message": "An unexpected error occurred.",
}


class ChatEventType(StrEnum):
    """Stable SSE event names. Each member's *value* is the wire event name."""

    MESSAGE_START = "message_start"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    MESSAGE_END = "message_end"
    ERROR = "error"


@dataclass(frozen=True)
class ChatEvent:
    """A transport-agnostic event ready to be serialized (e.g. as SSE)."""

    name: ChatEventType
    data: dict[str, Any]


class ChatService:
    def __init__(self, settings: Settings, mcp: MCPClient) -> None:
        self._settings = settings
        self._mcp = mcp

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        try:
            provider = await build_provider(
                request.provider.provider,
                model=request.provider.model,
                ollama_base_url=self._settings.ollama_base_url,
                allow_insecure=self._settings.is_development,
                base_url=request.provider.base_url,
                api_key=request.provider.api_key,
            )
        except LLMProviderError as exc:
            logger.warning("provider configuration rejected: code=%s", exc.code.value)
            yield ChatEvent(ChatEventType.ERROR, exc.to_dict())
            return
        except Exception:
            logger.exception("unexpected error building the provider")
            yield ChatEvent(ChatEventType.ERROR, dict(INTERNAL_ERROR))
            return

        try:
            yield ChatEvent(
                ChatEventType.MESSAGE_START,
                {"provider": request.provider.provider, "model": request.provider.model},
            )
            agent = Agent(provider, self._mcp)
            async for event in agent.run(
                self._build_messages(request), temperature=request.temperature
            ):
                yield _to_chat_event(event)
        except (LLMProviderError, AgentError) as exc:
            logger.warning("agent turn failed: code=%s detail=%s", exc.code.value, exc.detail)
            yield ChatEvent(ChatEventType.ERROR, exc.to_dict())
        except MCPError as exc:
            logger.warning("mcp failure: code=%s detail=%s", exc.code.value, exc.detail)
            yield ChatEvent(ChatEventType.ERROR, exc.to_dict())
        except Exception:
            logger.exception("unexpected error while streaming chat")
            yield ChatEvent(ChatEventType.ERROR, dict(INTERNAL_ERROR))
        else:
            yield ChatEvent(ChatEventType.MESSAGE_END, {})
        finally:
            await provider.aclose()

    def _build_messages(self, request: ChatRequest) -> list[LLMMessage]:
        messages = [_to_message(message) for message in request.messages]
        prompt = self._settings.system_prompt.strip()
        if prompt:
            messages.insert(0, LLMMessage(role=LLMRole.SYSTEM, content=prompt))
        return messages


def _to_message(message: ChatMessage) -> LLMMessage:
    role = LLMRole.USER if message.role == "user" else LLMRole.ASSISTANT
    return LLMMessage(role=role, content=message.content)


def _to_chat_event(event: AgentEvent) -> ChatEvent:
    if isinstance(event, AgentTextDelta):
        return ChatEvent(ChatEventType.TOKEN, {"text": event.text})
    if isinstance(event, AgentToolCall):
        return ChatEvent(
            ChatEventType.TOOL_CALL,
            {"id": event.id, "name": event.name, "arguments": event.arguments},
        )
    if isinstance(event, AgentToolResult):
        return ChatEvent(
            ChatEventType.TOOL_RESULT,
            {
                "id": event.id,
                "name": event.name,
                "content": event.content,
                "is_error": event.is_error,
            },
        )
    raise TypeError(f"Unsupported agent event: {type(event).__name__}")
