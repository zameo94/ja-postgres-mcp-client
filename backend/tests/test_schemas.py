import pytest
from pydantic import ValidationError

from app.schemas.chat import (
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    ChatMessage,
    ChatRequest,
    ProviderConfig,
)


def _provider(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"provider": "ollama", "model": "m"}
    base.update(overrides)
    return base


def _request(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "messages": [{"role": "user", "content": "hi"}],
        "provider": _provider(),
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
        ChatRequest(messages=messages, provider=_provider())


def test_rejects_assistant_as_last_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            ],
            provider=_provider(),
        )


def test_external_provider_requires_credentials() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[{"role": "user", "content": "hi"}],
            provider={"provider": "external_api", "model": "m"},
        )


def test_external_provider_with_credentials_is_valid() -> None:
    request = ChatRequest(
        messages=[{"role": "user", "content": "hi"}],
        provider={
            "provider": "external_api",
            "model": "m",
            "base_url": "https://api.example.com/v1",
            "api_key": "k",
        },
    )

    assert request.provider.base_url == "https://api.example.com/v1"


def test_rejects_control_characters_in_model() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(provider="ollama", model="bad\nmodel")


def test_rejects_temperature_out_of_range() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(**_request(temperature=3.0))


def test_accepts_temperature_bounds() -> None:
    request = ChatRequest(**_request(temperature=2.0))

    assert request.temperature == 2.0
