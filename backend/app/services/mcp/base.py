"""Application-facing MCP client contract.

The agent talks to the existing ``ja-postgres-mcp`` server only through this
interface, so it never sees MCP protocol or transport details. The concrete
implementation lives in :mod:`app.services.mcp.client`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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


class MCPError(Exception):
    """Base class for MCP client failures."""


class MCPConnectionError(MCPError):
    """The MCP server could not be reached or the session could not be used."""


class MCPToolError(MCPError):
    """The MCP server failed to execute a tool at the protocol level."""


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
