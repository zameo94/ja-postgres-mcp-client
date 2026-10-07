"""Chat application service.

Turns a chat request into a provider + agent run and maps the agent's events and
failures into transport-agnostic :class:`ChatEvent` values. The HTTP/SSE layer
only serializes these; it contains no orchestration logic.
"""

from __future__ import annotations

import itertools
import json
import logging
import time
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
from app.services.llm.errors import DEFAULT_MESSAGES, LLMErrorCode, LLMProviderError
from app.services.llm.factory import build_provider
from app.services.mcp.base import MCPClient, MCPError

logger = logging.getLogger(__name__)

_TURN_IDS = itertools.count(1)
# Schema context budget: columns are injected only for small schemas, to bound
# the prompt size and the number of extra MCP calls per turn.
_MAX_DESCRIBED_RELATIONS = 20
_MAX_COLUMNS_PER_RELATION = 30
_MAX_SCHEMA_CONTEXT_CHARS = 4000

INTERNAL_ERROR: dict[str, str] = {
    "code": LLMErrorCode.INTERNAL.value,
    "message": DEFAULT_MESSAGES[LLMErrorCode.INTERNAL],
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

        turn = next(_TURN_IDS)
        started = time.perf_counter()
        logger.info(
            "chat turn started: turn=%d provider=%s model=%s",
            turn,
            request.provider.provider,
            request.provider.model,
        )
        try:
            yield ChatEvent(
                ChatEventType.MESSAGE_START,
                {"provider": request.provider.provider, "model": request.provider.model},
            )
            agent = Agent(provider, self._mcp)
            async for event in agent.run(
                await self._build_messages(request), temperature=request.temperature
            ):
                yield _to_chat_event(event)
        except (LLMProviderError, AgentError) as exc:
            logger.warning(
                "agent turn failed: turn=%d code=%s detail=%s",
                turn,
                exc.code.value,
                exc.detail,
            )
            yield ChatEvent(ChatEventType.ERROR, exc.to_dict())
        except MCPError as exc:
            logger.warning(
                "mcp failure: turn=%d code=%s detail=%s", turn, exc.code.value, exc.detail
            )
            yield ChatEvent(ChatEventType.ERROR, exc.to_dict())
        except Exception:
            logger.exception("unexpected error while streaming chat: turn=%d", turn)
            yield ChatEvent(ChatEventType.ERROR, dict(INTERNAL_ERROR))
        else:
            yield ChatEvent(ChatEventType.MESSAGE_END, {})
        finally:
            await provider.aclose()
            logger.info(
                "chat turn finished: turn=%d duration_ms=%d",
                turn,
                int((time.perf_counter() - started) * 1000),
            )

    async def _build_messages(self, request: ChatRequest) -> list[LLMMessage]:
        messages = [_to_message(message) for message in request.messages]
        prompt = self._settings.system_prompt.strip()
        context = await self._schema_context()
        if context:
            prompt = f"{prompt}\n{context}".strip()
        if prompt:
            messages.insert(0, LLMMessage(role=LLMRole.SYSTEM, content=prompt))
        return messages

    async def _schema_context(self) -> str:
        """Best-effort schema summary injected into the system prompt.

        Weak local models often skip discovery and guess column names, so we give
        them the real relations and columns up front. If the database is small we
        describe every relation; if it is large we list only the schemas and let
        the model drill down, to keep the prompt bounded.
        """
        listing = await self._list_tables()
        if listing is None:
            return ""
        tables, truncated = listing
        if truncated:
            schemas = await self._list_schemas()
            if not schemas:
                return ""
            return (
                "The database has many tables; available schemas: "
                + ", ".join(schemas)
                + ". Use db_list_tables and db_describe_table to inspect them before querying."
            )
        if not tables:
            return ""
        if len(tables) <= _MAX_DESCRIBED_RELATIONS:
            described = await self._describe_tables(tables)
            if described:
                context = (
                    "Available relations (always use schema-qualified names and only "
                    "these columns): " + "; ".join(described) + "."
                )
                if len(context) <= _MAX_SCHEMA_CONTEXT_CHARS:
                    return context
        return (
            "Available tables (always use schema-qualified names): "
            + ", ".join(f"{schema}.{name}" for schema, name in tables)
            + ". Use db_describe_table to see their columns."
        )

    async def _list_tables(self) -> tuple[list[tuple[str, str]], bool] | None:
        payload = await self._call_json("db_list_tables", {"page_size": 200})
        if payload is None:
            return None
        tables = payload.get("tables")
        if not isinstance(tables, list):
            return None
        pairs = [
            (table["schema_name"], table["name"])
            for table in tables
            if isinstance(table, dict)
            and isinstance(table.get("schema_name"), str)
            and isinstance(table.get("name"), str)
        ]
        return pairs, payload.get("next_cursor") is not None

    async def _describe_tables(self, tables: list[tuple[str, str]]) -> list[str]:
        described: list[str] = []
        for schema, name in tables:
            payload = await self._call_json("db_describe_table", {"schema": schema, "table": name})
            if payload is None:
                continue
            columns = payload.get("columns")
            if not isinstance(columns, list):
                continue
            column_names = [
                column["name"]
                for column in columns
                if isinstance(column, dict) and isinstance(column.get("name"), str)
            ][:_MAX_COLUMNS_PER_RELATION]
            if column_names:
                described.append(f"{schema}.{name}({', '.join(column_names)})")
        return described

    async def _list_schemas(self) -> list[str]:
        payload = await self._call_json("db_list_schemas", {})
        if payload is None:
            return []
        schemas = payload.get("schemas")
        if not isinstance(schemas, list):
            return []
        return [
            schema["name"]
            for schema in schemas
            if isinstance(schema, dict) and isinstance(schema.get("name"), str)
        ]

    async def _call_json(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        try:
            result = await self._mcp.call_tool(name, arguments)
        except MCPError:
            return None
        if result.is_error:
            return None
        try:
            payload = json.loads(result.content)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None


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
