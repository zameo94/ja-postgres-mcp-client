import httpx
import pytest

from app.services.llm.errors import (
    DEFAULT_MESSAGES,
    LLMErrorCode,
    LLMProviderError,
    classify_http_status,
    error_from_http_status,
    error_from_transport,
)


def test_wire_codes_are_stable() -> None:
    assert LLMErrorCode.INVALID_CONFIG.value == "invalid_config"
    assert LLMErrorCode.AUTHENTICATION.value == "authentication_failed"
    assert LLMErrorCode.REJECTED_REQUEST.value == "request_rejected"
    assert LLMErrorCode.RATE_LIMITED.value == "rate_limited"
    assert LLMErrorCode.PROVIDER_UNAVAILABLE.value == "provider_unavailable"
    assert LLMErrorCode.TIMEOUT.value == "provider_timeout"
    assert LLMErrorCode.TRANSPORT.value == "transport_error"
    assert LLMErrorCode.MALFORMED_RESPONSE.value == "malformed_response"
    assert LLMErrorCode.TOOL_CALL.value == "tool_call_error"
    assert LLMErrorCode.STREAMING_PROTOCOL.value == "streaming_protocol_error"
    assert LLMErrorCode.INTERNAL.value == "internal_error"


def test_every_code_has_a_default_message() -> None:
    for code in LLMErrorCode:
        assert DEFAULT_MESSAGES[code]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, LLMErrorCode.REJECTED_REQUEST),
        (401, LLMErrorCode.AUTHENTICATION),
        (403, LLMErrorCode.AUTHENTICATION),
        (404, LLMErrorCode.REJECTED_REQUEST),
        (408, LLMErrorCode.TIMEOUT),
        (429, LLMErrorCode.RATE_LIMITED),
        (500, LLMErrorCode.PROVIDER_UNAVAILABLE),
        (503, LLMErrorCode.PROVIDER_UNAVAILABLE),
        (302, LLMErrorCode.INTERNAL),
    ],
)
def test_classify_http_status(status: int, expected: LLMErrorCode) -> None:
    assert classify_http_status(status) is expected


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (401, LLMErrorCode.AUTHENTICATION, "The API key was rejected by the provider."),
        (403, LLMErrorCode.AUTHENTICATION, "The API key does not have access to this model."),
        (404, LLMErrorCode.REJECTED_REQUEST, "The configured model or endpoint was not found."),
        (408, LLMErrorCode.TIMEOUT, "The provider did not respond in time."),
        (
            429,
            LLMErrorCode.RATE_LIMITED,
            "The provider is rate limiting requests. Please try again later.",
        ),
        (500, LLMErrorCode.PROVIDER_UNAVAILABLE, "The provider is currently unavailable."),
    ],
)
def test_error_from_http_status(status: int, code: LLMErrorCode, message: str) -> None:
    error = error_from_http_status(status, detail=f"HTTP {status}")

    assert error.code is code
    assert error.message == message
    assert error.detail == f"HTTP {status}"


def test_error_from_transport_timeout() -> None:
    error = error_from_transport(httpx.ConnectTimeout("slow"))

    assert error.code is LLMErrorCode.TIMEOUT
    assert error.message == "The provider did not respond in time."


def test_error_from_transport_connection() -> None:
    error = error_from_transport(httpx.ConnectError("no route"))

    assert error.code is LLMErrorCode.TRANSPORT
    assert error.message == "The provider could not be reached."


def test_default_message_used_when_omitted() -> None:
    error = LLMProviderError(LLMErrorCode.MALFORMED_RESPONSE)

    assert error.message == "The provider returned an invalid response."


def test_to_dict_never_exposes_internal_detail() -> None:
    error = LLMProviderError(
        LLMErrorCode.AUTHENTICATION,
        detail="upstream said: bearer sk-secret-key",
    )

    payload = error.to_dict()

    assert payload == {
        "code": "authentication_failed",
        "message": "The API key was rejected by the provider.",
    }
    assert "sk-secret-key" not in str(payload)
