import pytest

from app.services.llm.errors import LLMErrorCode, LLMProviderError
from app.services.llm.factory import build_provider
from app.services.llm.providers.ollama import OllamaProvider
from app.services.llm.providers.openai import OpenAIProvider

OLLAMA_URL = "http://ollama.local"
EXTERNAL_URL = "https://api.example.com/v1"


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def passthrough(url: str, *, allow_insecure: bool) -> str:
        return url

    monkeypatch.setattr(
        "app.services.llm.factory.resolve_and_validate_provider_base_url", passthrough
    )


async def test_builds_ollama_provider() -> None:
    provider = await build_provider(
        "ollama", model="llama3.1", ollama_base_url=OLLAMA_URL, allow_insecure=False
    )

    assert isinstance(provider, OllamaProvider)
    await provider.aclose()


async def test_builds_external_provider() -> None:
    provider = await build_provider(
        "external_api",
        model="gpt-4o-mini",
        ollama_base_url=OLLAMA_URL,
        allow_insecure=False,
        base_url=EXTERNAL_URL,
        api_key="secret",
    )

    assert isinstance(provider, OpenAIProvider)
    await provider.aclose()


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
        model="m",
        ollama_base_url=OLLAMA_URL,
        allow_insecure=False,
        base_url=EXTERNAL_URL,
        api_key="k",
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
            model="m",
            ollama_base_url=OLLAMA_URL,
            allow_insecure=False,
            base_url="https://evil.example/v1",
            api_key="k",
        )

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_external_provider_requires_credentials() -> None:
    with pytest.raises(LLMProviderError) as exc:
        await build_provider(
            "external_api", model="m", ollama_base_url=OLLAMA_URL, allow_insecure=False
        )

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(LLMProviderError) as exc:
        await build_provider("nope", model="m", ollama_base_url=OLLAMA_URL, allow_insecure=False)

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_allow_insecure_is_propagated_to_the_external_provider() -> None:
    with pytest.raises(LLMProviderError):
        await build_provider(
            "external_api",
            model="m",
            ollama_base_url=OLLAMA_URL,
            allow_insecure=False,
            base_url="http://localhost:1234/v1",
            api_key="k",
        )

    provider = await build_provider(
        "external_api",
        model="m",
        ollama_base_url=OLLAMA_URL,
        allow_insecure=True,
        base_url="http://localhost:1234/v1",
        api_key="k",
    )

    assert isinstance(provider, OpenAIProvider)
    await provider.aclose()
