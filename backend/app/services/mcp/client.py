"""Streamable HTTP MCP client built on the official ``mcp`` SDK.

Each operation opens a short-lived MCP session and closes it when the operation
finishes. The SDK session is task-affine (it must be entered and exited in the
same task), so this keeps the client stateless and safe. One connection per
operation is an MVP trade-off; a long-lived session could be introduced later
behind the same interface.

Error messages are deliberately generic so no transport detail or server payload
leaks; the original exception is preserved as ``__cause__``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.services.mcp.base import (
    MCPClient,
    MCPConnectionError,
    MCPError,
    MCPTool,
    MCPToolError,
    MCPToolResult,
)


class MCPSessionProtocol(Protocol):
    """The subset of the SDK session the client relies on."""

    async def list_tools(self) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


SessionFactory = Callable[[], "AbstractAsyncContextManager[MCPSessionProtocol]"]


class StreamableHTTPMCPClient(MCPClient):
    """MCP client over the Streamable HTTP transport."""

    def __init__(
        self,
        url: str,
        *,
        session_factory: SessionFactory | None = None,
    ) -> None:
        parts = urlsplit(url.strip())
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("MCP server url must be an absolute http(s) URL")
        self._url = url
        self._session_factory: SessionFactory = session_factory or self._connect

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[MCPSessionProtocol]:
        async with streamable_http_client(self._url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    async def list_tools(self) -> list[MCPTool]:
        try:
            async with self._session_factory() as session:
                result = await session.list_tools()
        except MCPError:
            raise
        except Exception as exc:
            raise MCPConnectionError(detail="list_tools failed") from exc

        return [self._to_tool(tool) for tool in getattr(result, "tools", None) or []]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        try:
            async with self._session_factory() as session:
                result = await session.call_tool(name, arguments)
        except MCPError:
            raise
        except Exception as exc:
            raise MCPToolError(detail="call_tool failed") from exc

        return MCPToolResult(
            content=self._render_result(result),
            is_error=bool(getattr(result, "is_error", False)),
        )

    @staticmethod
    def _to_tool(tool: Any) -> MCPTool:
        schema = getattr(tool, "input_schema", None)
        description = getattr(tool, "description", None)
        return MCPTool(
            name=str(getattr(tool, "name", "")),
            description=description if isinstance(description, str) else "",
            input_schema=schema if isinstance(schema, dict) else {},
        )

    @staticmethod
    def _render_result(result: Any) -> str:
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            try:
                return json.dumps(structured, default=str, ensure_ascii=False)
            except (TypeError, ValueError):
                return str(structured)
        parts: list[str] = []
        for block in getattr(result, "content", None) or []:
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
