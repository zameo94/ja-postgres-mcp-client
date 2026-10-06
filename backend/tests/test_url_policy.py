import socket
from collections.abc import Callable
from typing import Any

import pytest

from app.services.llm.errors import LLMErrorCode, LLMProviderError
from app.services.llm.url_policy import (
    resolve_and_validate_provider_base_url,
    validate_provider_base_url,
)


def _resolver(addresses: list[str]) -> Callable[..., list[Any]]:
    def fake(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in addresses
        ]

    return fake


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


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "http:///v1",
        "https://",
        "[bad",
        "https://api.example.com:abc/v1",
        "https://api.example.com:99999/v1",
    ],
)
def test_rejects_malformed_urls(url: str) -> None:
    with pytest.raises(LLMProviderError) as exc:
        validate_provider_base_url(url, allow_insecure=True)

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


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


@pytest.mark.parametrize(
    "url",
    [
        "https://[::ffff:169.254.169.254]/v1",
        "https://[::ffff:127.0.0.1]/v1",
        "https://[64:ff9b::a00:1]/v1",
        "https://[fe80::1]/v1",
    ],
)
def test_ipv6_embedded_and_link_local_are_rejected(url: str) -> None:
    # Pins ipaddress behaviour (Py 3.12): these are reserved/link-local, so they
    # are rejected even in insecure mode.
    with pytest.raises(LLMProviderError):
        validate_provider_base_url(url, allow_insecure=True)


async def test_resolves_public_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _resolver(["93.184.216.34"]))
    url = "https://api.example.com/v1"

    assert await resolve_and_validate_provider_base_url(url, allow_insecure=False) == url


async def test_rejects_hostname_resolving_to_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _resolver(["10.0.0.5"]))

    with pytest.raises(LLMProviderError) as exc:
        await resolve_and_validate_provider_base_url(
            "https://evil.example/v1", allow_insecure=False
        )

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG


async def test_rejects_if_any_resolved_address_is_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _resolver(["93.184.216.34", "169.254.169.254"]))

    with pytest.raises(LLMProviderError):
        await resolve_and_validate_provider_base_url(
            "https://mixed.example/v1", allow_insecure=False
        )


async def test_loopback_resolution_allowed_in_insecure_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _resolver(["127.0.0.1"]))
    url = "http://local.example/v1"

    assert await resolve_and_validate_provider_base_url(url, allow_insecure=True) == url


async def test_unresolvable_hostname_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(*args: Any, **kwargs: Any) -> list[Any]:
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(socket, "getaddrinfo", fake)

    with pytest.raises(LLMProviderError) as exc:
        await resolve_and_validate_provider_base_url(
            "https://nope.example/v1", allow_insecure=False
        )

    assert exc.value.code is LLMErrorCode.INVALID_CONFIG
