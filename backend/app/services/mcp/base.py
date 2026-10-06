"""Application-facing MCP client contract.

The agent talks to the existing ``ja-postgres-mcp`` server only through this
interface, so it never sees MCP protocol or transport details. The concrete
implementation lives in :mod:`app.services.mcp.client`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class MCPTool:
    """A tool advertised by the MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class MCPToolResult:
    """The outcome of a tool call.

    ``is_error`` mirrors the MCP server's ``isError`` flag: a **tool-level**
    error the model is allowed to see and recover from. This is distinct from a
    protocol/connection failure, which is raised as an :class:`MCPError`.
    """

    content: str
    is_error: bool = False


class MCPErrorCode(StrEnum):
    """Stable error codes. Each member's *value* is the wire code."""

    CONNECTION = "mcp_connection_error"
    TOOL = "mcp_tool_error"


_MESSAGES: dict[MCPErrorCode, str] = {
    MCPErrorCode.CONNECTION: "The database service could not be reached.",
    MCPErrorCode.TOOL: "The database service failed to run the tool.",
}


class MCPError(Exception):
    """Base class for MCP client failures.

    ``message`` is user-safe; internal diagnostics go in ``detail`` and are never
    serialized. ``to_dict`` exposes the client-facing representation.
    """

    code: MCPErrorCode

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        self.message: str = message or _MESSAGES[self.code]
        self.detail: str | None = detail
        super().__init__(self.message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


class MCPConnectionError(MCPError):
    """The MCP server could not be reached or the session could not be used."""

    code = MCPErrorCode.CONNECTION


class MCPToolError(MCPError):
    """The MCP server failed to execute a tool at the protocol level."""

    code = MCPErrorCode.TOOL


class MCPClient(ABC):
    """Read-only interface to the MCP server used by the agent."""

    @abstractmethod
    async def list_tools(self) -> list[MCPTool]:
        """Return the tools advertised by the MCP server."""
        raise NotImplementedError

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        """Execute one tool and return its rendered result."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release client resources; stateless clients need not override."""
        return None
