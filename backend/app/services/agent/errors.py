"""Agent-level errors.

Failures raised by the LLM providers (:class:`LLMProviderError`) and the MCP
client (:class:`MCPError`) propagate unchanged; this module only covers failures
that belong to the agent orchestration itself.
"""

from __future__ import annotations

from enum import StrEnum


class AgentErrorCode(StrEnum):
    """Stable error codes. Each member's *value* is the wire code."""

    TOOL_LOOP_EXCEEDED = "tool_loop_exceeded"


DEFAULT_MESSAGES: dict[AgentErrorCode, str] = {
    AgentErrorCode.TOOL_LOOP_EXCEEDED: (
        "The assistant asked to use too many tools in one turn. Please try again."
    ),
}


class AgentError(Exception):
    """A normalized agent failure with a stable, user-safe representation."""

    def __init__(
        self,
        code: AgentErrorCode,
        *,
        message: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.code: AgentErrorCode = code
        self.message: str = message or DEFAULT_MESSAGES[code]
        self.detail: str | None = detail
        super().__init__(self.message)

    def to_dict(self) -> dict[str, str]:
        """Serialize the client-facing part only (no internal ``detail``)."""
        return {"code": self.code.value, "message": self.message}
