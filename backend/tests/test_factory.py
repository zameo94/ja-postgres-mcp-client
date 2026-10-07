from typing import Any

import pytest

from app.services.llm.errors import LLMErrorCode, LLMProviderError
from app.services.llm.factory import build_provider
from app.services.llm.providers.ollama import OllamaProvider
from app.services.llm.providers.openai import OpenAIProvider

OLLAMA_URL = "http://ollama.local"
EXTERNAL_URL = "https://api.example.com/v1"


def _config(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ollama_base_url": OLLAMA_URL,
        "ollama_model": None,
        "external_base_url": None,
        "external_model": None,
        "external_api_key": None,
        "allow_insecure": False,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def passthrough(url: str, *, allow_insecure: bool) -> str:
        return url

    monkeypatch.setattr(
        "app.services.llm.factory.resolve_and_validate_provider_base_url", passthrough
    )


async def test_builds_ollama_provider() -> None:
    provider = await build_provider("ollama", **_config(ollama_model="llama3.1"))

    assert isinstance(provider, OllamaProvider)
    await provider.aclose()


async def test_ollama_requires_a_model() -> None:
    with pytest.raises(LLMProviderError) as exc:
        await build_provider("ollama", **_config(ollama_model="   "))

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_builds_external_provider() -> None:
    provider = await build_provider(
        "external_api",
        **_config(
            external_base_url=EXTERNAL_URL,
            external_model="gpt-4o-mini",
            external_api_key="secret",
        ),
    )

    assert isinstance(provider, OpenAIProvider)
    await provider.aclose()


async def test_external_requires_full_configuration() -> None:
    with pytest.raises(LLMProviderError) as exc:
        await build_provider(
            "external_api",
            **_config(external_base_url=EXTERNAL_URL, external_model="m"),
        )

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_external_provider_runs_ssrf_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    async def spy(url: str, *, allow_insecure: bool) -> str:
        calls.append((url, allow_insecure))
        return url

    monkeypatch.setattr("app.services.llm.factory.resolve_and_validate_provider_base_url", spy)
    provider = await build_provider(
        "external_api",
        **_config(
            external_base_url=EXTERNAL_URL,
            external_model="m",
            external_api_key="k",
        ),
    )

    assert calls == [(EXTERNAL_URL, False)]
    await provider.aclose()


async def test_external_provider_rejects_ssrf_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject(url: str, *, allow_insecure: bool) -> str:
        raise LLMProviderError(LLMErrorCode.INVALID_CONFIG)

    monkeypatch.setattr("app.services.llm.factory.resolve_and_validate_provider_base_url", reject)

    with pytest.raises(LLMProviderError) as exc:
        await build_provider(
            "external_api",
            **_config(
                external_base_url="https://evil.example/v1",
                external_model="m",
                external_api_key="k",
            ),
        )

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(LLMProviderError) as exc:
        await build_provider("nope", **_config(ollama_model="m"))

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_allow_insecure_is_propagated_to_the_external_provider() -> None:
    with pytest.raises(LLMProviderError):
        await build_provider(
            "external_api",
            **_config(
                external_base_url="http://localhost:1234/v1",
                external_model="m",
                external_api_key="k",
                allow_insecure=False,
            ),
        )

    provider = await build_provider(
        "external_api",
        **_config(
            external_base_url="http://localhost:1234/v1",
            external_model="m",
            external_api_key="k",
            allow_insecure=True,
        ),
    )

    assert isinstance(provider, OpenAIProvider)
    await provider.aclose()
