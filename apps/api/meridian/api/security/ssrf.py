"""Outbound URL validation: HTTPS only, and no private, loopback, link-local, or otherwise internal address."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

Resolver = Callable[..., list[Any]]


class UnsafeUrl(ValueError):
    pass


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def _lookup(host: str, port: int, **kwargs: Any) -> list[Any]:
    return socket.getaddrinfo(host, port, **kwargs)


def validate_url(url: str, resolver: Resolver | None = None) -> tuple[str, int, list[str]]:
    """The host, port, and public addresses for the URL. Raises UnsafeUrl otherwise."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise UnsafeUrl("Only https URLs are accepted.")
    if not parts.hostname or parts.username or parts.password:
        raise UnsafeUrl("The URL must have a host and no embedded credentials.")
    port = parts.port or 443
    try:
        records = (resolver or _lookup)(parts.hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrl("The host name could not be resolved.") from exc
    addresses = sorted({r[4][0] for r in records})
    if not addresses:
        raise UnsafeUrl("The host name could not be resolved.")
    if not all(is_public(a) for a in addresses):
        raise UnsafeUrl("The URL resolves to a non-public address.")
    return parts.hostname, port, addresses
