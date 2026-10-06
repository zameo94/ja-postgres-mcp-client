import pytest

from app.services.llm.errors import LLMErrorCode, LLMProviderError
from app.services.llm.url_policy import validate_provider_base_url


def test_accepts_public_https() -> None:
    url = "https://api.example.com/v1"

    assert validate_provider_base_url(url, allow_insecure=False) == url


def test_accepts_public_http_in_insecure_mode() -> None:
    url = "http://api.example.com/v1"

    assert validate_provider_base_url(url, allow_insecure=True) == url


def test_rejects_http_in_production() -> None:
    with pytest.raises(LLMProviderError) as exc:
        validate_provider_base_url("http://api.example.com/v1", allow_insecure=False)

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(LLMProviderError) as exc:
        validate_provider_base_url("ftp://api.example.com", allow_insecure=True)

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


@pytest.mark.parametrize("url", ["not-a-url", "http:///v1", "https://"])
def test_rejects_malformed_urls(url: str) -> None:
    with pytest.raises(LLMProviderError):
        validate_provider_base_url(url, allow_insecure=True)


@pytest.mark.parametrize("url", ["http://localhost:1234/v1", "http://127.0.0.1:1234/v1"])
def test_loopback_allowed_only_in_insecure_mode(url: str) -> None:
    with pytest.raises(LLMProviderError):
        validate_provider_base_url(url, allow_insecure=False)

    assert validate_provider_base_url(url, allow_insecure=True) == url


@pytest.mark.parametrize("url", ["https://10.0.0.5/v1", "https://192.168.1.10/v1"])
def test_private_addresses_rejected_in_production(url: str) -> None:
    with pytest.raises(LLMProviderError):
        validate_provider_base_url(url, allow_insecure=False)

    assert validate_provider_base_url(url, allow_insecure=True) == url


@pytest.mark.parametrize("url", ["https://169.254.169.254/latest", "http://169.254.169.254/"])
def test_link_local_metadata_rejected_even_in_insecure_mode(url: str) -> None:
    with pytest.raises(LLMProviderError):
        validate_provider_base_url(url, allow_insecure=True)


def test_metadata_hostname_rejected() -> None:
    with pytest.raises(LLMProviderError):
        validate_provider_base_url("http://metadata.google.internal/", allow_insecure=True)
