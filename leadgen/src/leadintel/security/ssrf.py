"""Outbound URL validation.

Any URL that originates outside our code (a website found in a SERP, a URL an
analyst typed into "enrich this domain") is checked before we fetch it or spend
scraping credits on it: http(s) only, no embedded credentials, default ports
only, and every resolved address must be public. That blocks the classic SSRF
targets: the instance metadata service (169.254.169.254), VPC-internal hosts,
loopback, and DNS names that resolve to private ranges.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit

from leadintel.core.errors import ValidationFailedError

Resolver = Callable[..., Iterable[tuple[Any, ...]]]

_MAX_URL_LENGTH = 2048
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
# Ranges that ipaddress does not already flag as private/reserved but must be blocked.
_EXTRA_BLOCKED = (
    ipaddress.ip_network("100.64.0.0/10"),  # carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol assignments
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
)


def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False
    return not any(address in net for net in _EXTRA_BLOCKED)


def validate_public_url(url: str, *, resolver: Resolver = socket.getaddrinfo) -> str:
    """Return ``url`` unchanged if it is safe to fetch, else raise ValidationFailedError."""
    if len(url) > _MAX_URL_LENGTH:
        raise ValidationFailedError("url too long")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValidationFailedError("only http and https URLs are allowed")
    if parts.username or parts.password:
        raise ValidationFailedError("credentials in URLs are not allowed")
    host = parts.hostname
    if not host:
        raise ValidationFailedError("url has no host")
    try:
        port = parts.port or _DEFAULT_PORTS[scheme]
    except ValueError as exc:
        raise ValidationFailedError("invalid port") from exc
    if port != _DEFAULT_PORTS[scheme]:
        raise ValidationFailedError("non-default ports are not allowed")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = resolver(host, port, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            raise ValidationFailedError("host does not resolve") from exc
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
        if not addresses:
            raise ValidationFailedError("host does not resolve")
    if not all(_is_public(a) for a in addresses):
        raise ValidationFailedError("url resolves to a non-public address")
    return url
