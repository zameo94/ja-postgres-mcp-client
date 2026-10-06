"""Agent orchestration.

The agent drives one user turn:

    messages -> LLM -> (complete) tool calls -> MCP -> tool results -> LLM -> ...

It depends only on the provider-neutral LLM contract and the MCP client
interface; it knows nothing about HTTP, SSE or concrete providers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from app.services.agent.errors import AgentError, AgentErrorCode
from app.services.agent.events import AgentEvent, AgentTextDelta, AgentToolCall, AgentToolResult
from app.services.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMRole,
    TextDelta,
    ToolCall,
    ToolDefinition,
)
from app.services.mcp.base import MCPClient, MCPConnectionError, MCPTool, MCPToolError

DEFAULT_MAX_TOOL_ROUNDS = 8
DEFAULT_MAX_TOOL_FAILURES = 3
MAX_TOOL_RESULT_CHARS = 8000
_TRUNCATION_MARKER = "\n... [tool result truncated]"


class Agent:
    """Orchestrates one conversation turn over an LLM provider and the MCP server."""

    def __init__(
        self,
        provider: LLMProvider,
        mcp: MCPClient,
        *,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        max_tool_failures: int = DEFAULT_MAX_TOOL_FAILURES,
    ) -> None:
        if max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must not be negative")
        if max_tool_failures < 0:
            raise ValueError("max_tool_failures must not be negative")
        self._provider = provider
        self._mcp = mcp
        self._max_tool_rounds = max_tool_rounds
        self._max_tool_failures = max_tool_failures

    async def run(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.0,
    ) -> AsyncIterator[AgentEvent]:
        """Stream the agent events for one turn.

        The caller owns the lifecycle: the agent never closes ``provider`` or
        ``mcp``; they must be closed by whoever built them (e.g. the SSE layer on
        client disconnect).

        Errors may be raised **after** some :class:`AgentTextDelta` events have
        already been yielded, because a turn that uses tools calls the model more
        than once; consumers must therefore treat errors as possibly mid-stream.

        Tool handling:

        * parallel tool calls in one round are executed **sequentially**, in the
          model's order, so events are deterministic;
        * an unknown tool name produces an error result without an MCP round-trip
          (the model can correct itself);
        * an MCP tool-level failure is converted to an error result, up to
          ``max_tool_failures`` per turn, after which the failure is re-raised;
        * an MCP connection failure is fatal and propagates immediately;
        * each tool result is capped at ``MAX_TOOL_RESULT_CHARS`` with an explicit
          truncation marker, to bound the context.
        """
        tool_definitions, known_tools = await self._load_tools()
        conversation: list[LLMMessage] = list(messages)
        tool_rounds = 0
        tool_failures = 0

        while True:
            text_parts: list[str] = []
            tool_calls: list[ToolCall] = []

            async for event in self._provider.stream(
                conversation, tools=tool_definitions, temperature=temperature
            ):
                if isinstance(event, TextDelta):
                    text_parts.append(event.text)
                    yield AgentTextDelta(event.text)
                else:
                    tool_calls.append(event)

            if not tool_calls:
                return

            if tool_rounds >= self._max_tool_rounds:
                raise AgentError(
                    AgentErrorCode.TOOL_LOOP_EXCEEDED,
                    detail=f"max_tool_rounds={self._max_tool_rounds}",
                )
            tool_rounds += 1

            conversation.append(
                LLMMessage(
                    role=LLMRole.ASSISTANT,
                    content="".join(text_parts),
                    tool_calls=tuple(tool_calls),
                )
            )
            for call in tool_calls:
                yield AgentToolCall(id=call.id, name=call.name, arguments=call.arguments)
                if call.name not in known_tools:
                    content = f"Unknown tool: {call.name}"
                    is_error = True
                else:
                    try:
                        result = await self._mcp.call_tool(call.name, call.arguments)
                    except MCPConnectionError:
                        raise
                    except MCPToolError as exc:
                        tool_failures += 1
                        if tool_failures > self._max_tool_failures:
                            raise
                        content = f"Tool error: {exc.message}"
                        is_error = True
                    else:
                        content = self._render_content(result.content, is_error=result.is_error)
                        is_error = result.is_error

                conversation.append(
                    LLMMessage(
                        role=LLMRole.TOOL,
                        content=content,
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )
                yield AgentToolResult(
                    id=call.id, name=call.name, content=content, is_error=is_error
                )

    async def _load_tools(self) -> tuple[list[ToolDefinition], set[str]]:
        tools = await self._mcp.list_tools()
        definitions = [self._to_tool_definition(tool) for tool in tools]
        return definitions, {definition.name for definition in definitions}

    @staticmethod
    def _to_tool_definition(tool: MCPTool) -> ToolDefinition:
        return ToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters=tool.input_schema,
        )

    @staticmethod
    def _render_content(content: str, *, is_error: bool) -> str:
        if len(content) > MAX_TOOL_RESULT_CHARS:
            content = content[:MAX_TOOL_RESULT_CHARS] + _TRUNCATION_MARKER
        if is_error:
            return f"Tool error: {content}"
        return content
