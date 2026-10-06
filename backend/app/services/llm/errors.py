"""Provider-agnostic LLM error model.

Every failure crossing the LLM boundary is an :class:`LLMProviderError` carrying:

* a stable machine-readable ``code`` (:class:`LLMErrorCode`), whose enum *value*
  is the wire code sent to clients;
* a user-facing ``message`` that explains what happened and, when possible, what
  the user can do about it;
* an optional internal ``detail`` for server-side diagnostics. It must never
  contain secrets and is never serialized to the client.

:meth:`LLMProviderError.to_dict` exposes only ``code`` and ``message``.
"""

from __future__ import annotations

from enum import StrEnum

import httpx


class LLMErrorCode(StrEnum):
    """Stable error taxonomy. Each member's *value* is the wire code."""

    INVALID_CONFIG = "invalid_config"
    AUTHENTICATION = "authentication_failed"
    REJECTED_REQUEST = "request_rejected"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "provider_timeout"
    TRANSPORT = "transport_error"
    MALFORMED_RESPONSE = "malformed_response"
    TOOL_CALL = "tool_call_error"
    STREAMING_PROTOCOL = "streaming_protocol_error"
    INTERNAL = "internal_error"


DEFAULT_MESSAGES: dict[LLMErrorCode, str] = {
    LLMErrorCode.INVALID_CONFIG: "The provider configuration is invalid.",
    LLMErrorCode.AUTHENTICATION: "The API key was rejected by the provider.",
    LLMErrorCode.REJECTED_REQUEST: "The provider rejected the request.",
    LLMErrorCode.RATE_LIMITED: ("The provider is rate limiting requests. Please try again later."),
    LLMErrorCode.PROVIDER_UNAVAILABLE: "The provider is currently unavailable.",
    LLMErrorCode.TIMEOUT: "The provider did not respond in time.",
    LLMErrorCode.TRANSPORT: "The provider could not be reached.",
    LLMErrorCode.MALFORMED_RESPONSE: "The provider returned an invalid response.",
    LLMErrorCode.TOOL_CALL: "The provider returned an invalid tool call.",
    LLMErrorCode.STREAMING_PROTOCOL: ("The provider stream sent an invalid or incomplete message."),
    LLMErrorCode.INTERNAL: "An unexpected error occurred.",
}

_STATUS_MESSAGES: dict[int, str] = {
    400: "The provider rejected the request.",
    401: "The API key was rejected by the provider.",
    403: "The API key does not have access to this model.",
    404: "The configured model or endpoint was not found.",
    408: "The provider did not respond in time.",
    429: "The provider is rate limiting requests. Please try again later.",
}


def classify_http_status(status: int) -> LLMErrorCode:
    """Map an HTTP status from a provider to a stable error code."""
    if status in (401, 403):
        return LLMErrorCode.AUTHENTICATION
    if status == 408:
        return LLMErrorCode.TIMEOUT
    if status == 429:
        return LLMErrorCode.RATE_LIMITED
    if status >= 500:
        return LLMErrorCode.PROVIDER_UNAVAILABLE
    if 400 <= status < 500:
        return LLMErrorCode.REJECTED_REQUEST
    return LLMErrorCode.INTERNAL


class LLMProviderError(Exception):
    """A normalized provider failure with a stable, user-safe representation."""

    def __init__(
        self,
        code: LLMErrorCode,
        *,
        message: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.code: LLMErrorCode = code
        self.message: str = message or DEFAULT_MESSAGES[code]
        self.detail: str | None = detail
        super().__init__(self.message)

    def to_dict(self) -> dict[str, str]:
        """Serialize the client-facing part only (no internal ``detail``)."""
        return {"code": self.code.value, "message": self.message}


def error_from_http_status(status: int, *, detail: str | None = None) -> LLMProviderError:
    code = classify_http_status(status)
    message = _STATUS_MESSAGES.get(status) or DEFAULT_MESSAGES[code]
    return LLMProviderError(code, message=message, detail=detail)


def error_from_transport(exc: httpx.HTTPError, *, detail: str | None = None) -> LLMProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return LLMProviderError(LLMErrorCode.TIMEOUT, detail=detail)
    return LLMProviderError(LLMErrorCode.TRANSPORT, detail=detail)
