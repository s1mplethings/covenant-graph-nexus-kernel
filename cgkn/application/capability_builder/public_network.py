from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import urljoin, urlsplit


class PublicNetworkPolicyError(ValueError):
    """A request violated the deterministic public-network boundary."""


@dataclass(frozen=True)
class PublicNetworkResponse:
    status_code: int
    final_url: str
    content_type: str
    text: str
    truncated: bool
    bytes_read: int

    def as_dict(self) -> dict[str, object]:
        return {
            "status_code": self.status_code,
            "final_url": self.final_url,
            "content_type": self.content_type,
            "text": self.text,
            "truncated": self.truncated,
            "bytes_read": self.bytes_read,
        }


@dataclass(frozen=True)
class _TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


Resolver = Callable[[str, int], tuple[str, ...]]
Transport = Callable[[str, str, str, int, str, float, int], _TransportResponse]


def _default_resolver(host: str, port: int) -> tuple[str, ...]:
    return tuple(sorted({row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}))


def is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return bool(address.is_global and not address.is_multicast)


def _default_transport(method: str, host: str, ip: str, port: int, target: str, timeout: float, limit: int) -> _TransportResponse:
    raw = socket.create_connection((ip, port), timeout=timeout)
    try:
        tls = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        try:
            request = (
                f"{method} {target} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "User-Agent: CGKN-PublicNetwork/1\r\n"
                "Accept: text/*, application/json\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            tls.sendall(request)
            response = http.client.HTTPResponse(tls)
            response.begin()
            body = b"" if method == "HEAD" else response.read(limit + 1)
            headers = {key.lower(): value for key, value in response.getheaders()}
            return _TransportResponse(response.status, headers, body)
        finally:
            tls.close()
    finally:
        raw.close()


class PublicNetworkClient:
    """Credential-free HTTPS GET/HEAD with DNS, redirect, and size enforcement."""

    FORBIDDEN_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key", "api-key"}

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1024 * 1024,
        max_redirects: int = 3,
        resolver: Resolver = _default_resolver,
        transport: Transport = _default_transport,
    ) -> None:
        if not 0 < timeout_seconds <= 10:
            raise ValueError("timeout must be in (0, 10]")
        if not 0 < max_response_bytes <= 1024 * 1024:
            raise ValueError("max response bytes must be in (0, 1 MiB]")
        if not 0 <= max_redirects <= 3:
            raise ValueError("max redirects must be in [0, 3]")
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        self._resolver = resolver
        self._transport = transport

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> dict[str, object]:
        return self.request("GET", url, headers=headers).as_dict()

    def head(self, url: str, *, headers: Mapping[str, str] | None = None) -> dict[str, object]:
        return self.request("HEAD", url, headers=headers).as_dict()

    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None) -> PublicNetworkResponse:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD"}:
            raise PublicNetworkPolicyError("only GET and HEAD are allowed")
        supplied_headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
        if self.FORBIDDEN_HEADERS.intersection(supplied_headers):
            raise PublicNetworkPolicyError("credentials are forbidden")
        if supplied_headers:
            raise PublicNetworkPolicyError("custom headers are not allowed")

        current = str(url)
        for redirect_index in range(self.max_redirects + 1):
            parsed = urlsplit(current)
            if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise PublicNetworkPolicyError("only credential-free HTTPS URLs are allowed")
            host = parsed.hostname.rstrip(".").lower()
            if host == "localhost" or host.endswith(".local"):
                raise PublicNetworkPolicyError("local destinations are forbidden")
            port = parsed.port or 443
            if port != 443:
                raise PublicNetworkPolicyError("only HTTPS port 443 is allowed")
            addresses = self._resolver(host, port)
            if not addresses or any(not is_public_address(address) for address in addresses):
                raise PublicNetworkPolicyError("destination did not resolve exclusively to public addresses")
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            response = self._transport(normalized_method, host, addresses[0], port, target, self.timeout_seconds, self.max_response_bytes)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location", "")
                if not location:
                    raise PublicNetworkPolicyError("redirect response omitted Location")
                if redirect_index >= self.max_redirects:
                    raise PublicNetworkPolicyError("redirect limit exceeded")
                current = urljoin(current, location)
                continue
            body = response.body
            truncated = len(body) > self.max_response_bytes
            bounded = body[: self.max_response_bytes]
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            text = bounded.decode("utf-8", errors="replace")
            return PublicNetworkResponse(response.status_code, current, content_type, text, truncated, len(bounded))
        raise PublicNetworkPolicyError("redirect limit exceeded")
