"""Builds the single LLM provider for a request from server configuration.

Provider connection details come from the environment (not the request), so the
browser never holds a provider secret. This factory is also the choke point for
the external provider: it validates the configured base URL (including DNS)
before the URL can reach ``httpx``.
"""

from __future__ import annotations

from app.services.llm.base import LLMProvider
from app.services.llm.errors import LLMErrorCode, LLMProviderError
from app.services.llm.providers.ollama import OLLAMA_PROVIDER_NAME, OllamaProvider
from app.services.llm.providers.openai import EXTERNAL_API_PROVIDER_NAME, OpenAIProvider
from app.services.llm.url_policy import resolve_and_validate_provider_base_url


async def build_provider(
    provider: str,
    *,
    ollama_base_url: str,
    ollama_model: str | None,
    external_base_url: str | None,
    external_model: str | None,
    external_api_key: str | None,
    allow_insecure: bool,
) -> LLMProvider:
    """Return the provider selected for one request, built from configuration."""
    if provider == OLLAMA_PROVIDER_NAME:
        model = (ollama_model or "").strip()
        if not model:
            raise LLMProviderError(
                LLMErrorCode.INVALID_CONFIG,
                message="No Ollama model is configured.",
            )
        return OllamaProvider(ollama_base_url, model)

    if provider == EXTERNAL_API_PROVIDER_NAME:
        base_url = (external_base_url or "").strip()
        model = (external_model or "").strip()
        api_key = external_api_key or ""
        if not base_url or not model or not api_key:
            raise LLMProviderError(
                LLMErrorCode.INVALID_CONFIG,
                message="The external provider is not configured.",
            )
        await resolve_and_validate_provider_base_url(base_url, allow_insecure=allow_insecure)
        return OpenAIProvider(base_url, api_key, model, allow_insecure=allow_insecure)

    raise LLMProviderError(
        LLMErrorCode.INVALID_CONFIG,
        message=f"Unknown provider: {provider}.",
    )
