"""SSRF policy for user-supplied provider base URLs.

The external provider base URL will eventually be configured by the end user, so
it is treated as untrusted. This module is the single choke point that validates
it before it is handed to ``httpx``; the future endpoint must construct the
provider through this validation and never pass an arbitrary URL to ``httpx``.

Policy (MVP):

* only ``http``/``https``; in production ``https`` is required;
* ``loopback`` and ``private`` addresses are rejected unless insecure mode is
  explicitly enabled (development, e.g. a local OpenAI-compatible server);
* ``link-local`` (including cloud metadata), ``reserved``, ``multicast`` and
  ``unspecified`` addresses are always rejected;
* a small denylist of well-known metadata hostnames is rejected.

Known limitation: a hostname that resolves (via DNS) to a private address is not
detected here (DNS rebinding). Fully addressing it requires resolving and pinning
the address at request time; that is deferred until the endpoint that consumes
user URLs exists.
"""

from __future__ import annotations

import ipaddress
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
    """Return ``url`` if it is allowed by the SSRF policy, else raise."""
    candidate = url.strip()
    parts = urlsplit(candidate)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise LLMProviderError(
            LLMErrorCode.INVALID_CONFIG,
            message="The provider base URL must be an absolute http(s) URL.",
        )
    if parts.scheme == "http" and not allow_insecure:
        raise LLMProviderError(
            LLMErrorCode.INVALID_CONFIG,
            message="The provider base URL must use https.",
        )
    _reject_blocked_host(parts.hostname or "", allow_insecure=allow_insecure)
    return candidate


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

    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return  # regular hostname; DNS-rebinding check is deferred

    if (
        address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise _metadata_error()
    if not allow_insecure and (address.is_loopback or address.is_private):
        raise _private_error()


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
