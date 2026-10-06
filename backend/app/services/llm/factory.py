"""Builds the single LLM provider for a request from the client's selection.

Provider-specific construction is centralized here; the rest of the code only
sees the :class:`LLMProvider` contract. This factory is the choke point for the
external provider: it validates the user-supplied base URL (including DNS) before
the URL can reach ``httpx``.
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
    model: str,
    ollama_base_url: str,
    allow_insecure: bool,
    base_url: str | None = None,
    api_key: str | None = None,
) -> LLMProvider:
    """Return the provider selected for one request.

    ``ollama`` uses the server-side base URL; ``external_api`` requires the
    user-supplied ``base_url`` and ``api_key``, and the base URL is validated
    (scheme, literal ranges and resolved addresses) before construction.
    """
    if provider == OLLAMA_PROVIDER_NAME:
        return OllamaProvider(ollama_base_url, model)
    if provider == EXTERNAL_API_PROVIDER_NAME:
        if not base_url or not api_key:
            raise LLMProviderError(
                LLMErrorCode.INVALID_CONFIG,
                message="A base URL and an API key are required for the external provider.",
            )
        await resolve_and_validate_provider_base_url(base_url, allow_insecure=allow_insecure)
        return OpenAIProvider(base_url, api_key, model, allow_insecure=allow_insecure)
    raise LLMProviderError(
        LLMErrorCode.INVALID_CONFIG,
        message=f"Unknown provider: {provider}.",
    )
