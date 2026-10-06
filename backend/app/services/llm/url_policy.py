"""SSRF policy for user-supplied provider base URLs.

The external provider base URL is configured by the end user, so it is treated
as untrusted. Two layers are provided:

* :func:`validate_provider_base_url` -- synchronous: scheme rules plus checks on
  literal addresses and a small denylist of metadata hostnames. Used by the
  provider constructor as a defensive baseline.
* :func:`resolve_and_validate_provider_base_url` -- asynchronous: additionally
  resolves a hostname and rejects it if **any** resolved address is private,
  loopback, link-local, reserved, multicast or unspecified. This is the check the
  request path must use, so an attacker cannot point a public hostname at an
  internal address.

Policy:

* only ``http``/``https``; in production ``https`` is required;
* ``loopback`` and ``private`` addresses are rejected unless insecure mode is
  explicitly enabled (development, e.g. a local OpenAI-compatible server);
* ``link-local`` (including cloud metadata), ``reserved``, ``multicast`` and
  ``unspecified`` addresses are always rejected;
* well-known metadata hostnames are always rejected.

Known limitation: the validated address is not pinned for the actual request, so
a hostile resolver could still change the answer between validation and connect
(a narrow TOCTOU window). Pinning requires a custom transport that connects to
the resolved IP while preserving SNI/Host, and is deferred.

The hostname is resolved on every validation (no cache); a transient resolver
failure is surfaced as ``INVALID_CONFIG``. A short-lived cache is a possible
later optimisation.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.services.llm.errors import LLMErrorCode, LLMProviderError

_BLOCKED_METADATA_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "metadata.goog",
}
_LOOPBACK_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
}


def validate_provider_base_url(url: str, *, allow_insecure: bool) -> str:
    """Validate scheme, port and literal addresses; hostnames are checked later."""
    candidate = url.strip()
    try:
        parts = urlsplit(candidate)
        scheme = parts.scheme
        netloc = parts.netloc
        hostname = parts.hostname or ""
        _ = parts.port  # raises ValueError for a malformed or out-of-range port
    except ValueError as exc:
        raise _malformed_error() from exc

    if scheme not in {"http", "https"} or not netloc:
        raise _malformed_error()
    if scheme == "http" and not allow_insecure:
        raise LLMProviderError(
            LLMErrorCode.INVALID_CONFIG,
            message="The provider base URL must use https.",
        )
    _reject_blocked_host(hostname, allow_insecure=allow_insecure)
    return candidate


async def resolve_and_validate_provider_base_url(url: str, *, allow_insecure: bool) -> str:
    """Validate the URL and reject hostnames resolving to internal addresses."""
    validated = validate_provider_base_url(url, allow_insecure=allow_insecure)
    parts = urlsplit(validated)
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if _parse_ip(host) is not None:
        return validated

    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise LLMProviderError(
            LLMErrorCode.INVALID_CONFIG,
            message="The provider base URL could not be resolved.",
        ) from exc

    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        raise LLMProviderError(
            LLMErrorCode.INVALID_CONFIG,
            message="The provider base URL could not be resolved.",
        )
    for address in addresses:
        _reject_blocked_address(address, allow_insecure=allow_insecure)
    return validated


def _reject_blocked_host(host: str, *, allow_insecure: bool) -> None:
    lowered = host.lower().rstrip(".")
    if not lowered:
        raise LLMProviderError(
            LLMErrorCode.INVALID_CONFIG,
            message="The provider base URL must include a host.",
        )
    if lowered in _BLOCKED_METADATA_HOSTS:
        raise _metadata_error()
    if lowered in _LOOPBACK_HOSTNAMES:
        if not allow_insecure:
            raise _private_error()
        return
    if _parse_ip(lowered) is not None:
        _reject_blocked_address(lowered, allow_insecure=allow_insecure)


def _reject_blocked_address(address: str, *, allow_insecure: bool) -> None:
    parsed = _parse_ip(address)
    if parsed is None:
        # Fail closed: an address we cannot parse is treated as untrusted.
        raise _invalid_address_error()
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    if parsed.is_link_local or parsed.is_reserved or parsed.is_multicast or parsed.is_unspecified:
        raise _metadata_error()
    if not allow_insecure and (parsed.is_loopback or parsed.is_private):
        raise _private_error()


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _malformed_error() -> LLMProviderError:
    return LLMProviderError(
        LLMErrorCode.INVALID_CONFIG,
        message="The provider base URL must be an absolute http(s) URL.",
    )


def _invalid_address_error() -> LLMProviderError:
    return LLMProviderError(
        LLMErrorCode.INVALID_CONFIG,
        message="The provider base URL resolved to an unsupported address.",
    )


def _private_error() -> LLMProviderError:
    return LLMProviderError(
        LLMErrorCode.INVALID_CONFIG,
        message="The provider base URL must not point to a loopback or private address.",
    )


def _metadata_error() -> LLMProviderError:
    return LLMProviderError(
        LLMErrorCode.INVALID_CONFIG,
        message="The provider base URL must not point to a link-local or metadata address.",
    )
