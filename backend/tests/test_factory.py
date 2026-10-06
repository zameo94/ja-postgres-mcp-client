import pytest

from app.services.llm.errors import LLMErrorCode, LLMProviderError
from app.services.llm.factory import build_provider
from app.services.llm.providers.ollama import OllamaProvider
from app.services.llm.providers.openai import OpenAIProvider

OLLAMA_URL = "http://ollama.local"


async def test_builds_ollama_provider() -> None:
    provider = build_provider(
        "ollama", model="llama3.1", ollama_base_url=OLLAMA_URL, allow_insecure=False
    )

    assert isinstance(provider, OllamaProvider)
    await provider.aclose()


async def test_builds_external_provider() -> None:
    provider = build_provider(
        "external_api",
        model="gpt-4o-mini",
        ollama_base_url=OLLAMA_URL,
        allow_insecure=False,
        base_url="https://api.example.com/v1",
        api_key="secret",
    )

    assert isinstance(provider, OpenAIProvider)
    await provider.aclose()


def test_external_provider_requires_credentials() -> None:
    with pytest.raises(LLMProviderError) as exc:
        build_provider("external_api", model="m", ollama_base_url=OLLAMA_URL, allow_insecure=False)

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(LLMProviderError) as exc:
        build_provider("nope", model="m", ollama_base_url=OLLAMA_URL, allow_insecure=False)

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_allow_insecure_is_propagated_to_the_external_provider() -> None:
    with pytest.raises(LLMProviderError):
        build_provider(
            "external_api",
            model="m",
            ollama_base_url=OLLAMA_URL,
            allow_insecure=False,
            base_url="http://localhost:1234/v1",
            api_key="k",
        )

    provider = build_provider(
        "external_api",
        model="m",
        ollama_base_url=OLLAMA_URL,
        allow_insecure=True,
        base_url="http://localhost:1234/v1",
        api_key="k",
    )

    assert isinstance(provider, OpenAIProvider)
    await provider.aclose()
