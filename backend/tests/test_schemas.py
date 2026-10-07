import pytest
from pydantic import ValidationError

from app.schemas.chat import (
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    ChatMessage,
    ChatRequest,
)


def _request(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "messages": [{"role": "user", "content": "hi"}],
        "provider": "ollama",
    }
    base.update(overrides)
    return base


def test_rejects_blank_content() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="   ")


def test_rejects_too_long_content() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="x" * (MAX_MESSAGE_CHARS + 1))


def test_rejects_too_many_messages() -> None:
    messages = [{"role": "user", "content": "hi"}] * (MAX_MESSAGES + 1)

    with pytest.raises(ValidationError):
        ChatRequest(**_request(messages=messages))


def test_rejects_assistant_as_last_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            **_request(
                messages=[
                    {"role": "user", "content": "a"},
                    {"role": "assistant", "content": "b"},
                ]
            )
        )


def test_accepts_known_providers() -> None:
    assert ChatRequest(**_request(provider="ollama")).provider == "ollama"
    assert ChatRequest(**_request(provider="external_api")).provider == "external_api"


def test_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(**_request(provider="nope"))


def test_rejects_temperature_out_of_range() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(**_request(temperature=3.0))


def test_accepts_temperature_bounds() -> None:
    assert ChatRequest(**_request(temperature=2.0)).temperature == 2.0
