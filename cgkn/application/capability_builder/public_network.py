from __future__ import annotations

import http.client
import ipaddress
import os
import re
import socket
import ssl
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping
from urllib.parse import urljoin, urlsplit


class PublicNetworkErrorClass(str, Enum):
    NETWORK_POLICY_BLOCK = "NETWORK_POLICY_BLOCK"
    LOCAL_PROXY_UNAVAILABLE = "LOCAL_PROXY_UNAVAILABLE"
    PUBLIC_DNS_FAILURE = "PUBLIC_DNS_FAILURE"
    PUBLIC_TARGET_FAILURE = "PUBLIC_TARGET_FAILURE"
    PUBLIC_RATE_LIMITED = "PUBLIC_RATE_LIMITED"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    REDIRECT_POLICY_BLOCK = "REDIRECT_POLICY_BLOCK"
    UNSUPPORTED_CONTENT_TYPE = "UNSUPPORTED_CONTENT_TYPE"
    CONFIG_ERROR = "CONFIG_ERROR"


class PublicNetworkPolicyError(ValueError):
    """A request violated the deterministic public-network boundary."""

    def __init__(self, message: str, classification: PublicNetworkErrorClass = PublicNetworkErrorClass.NETWORK_POLICY_BLOCK):
        self.classification = classification
        super().__init__(message)


class PublicNetworkMode(str, Enum):
    DIRECT = "DIRECT"
    TRUSTED_LOCAL_PROXY = "TRUSTED_LOCAL_PROXY"


@dataclass(frozen=True)
class PublicNetworkTransport:
    """Explicit transport configuration; it never discovers system proxy state."""

    mode: PublicNetworkMode
    proxy_host: str | None = None
    proxy_port: int | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "PublicNetworkTransport":
        values = os.environ if environment is None else environment
        requested = str(values.get("CGKN_PUBLIC_NETWORK_MODE", "direct")).strip().lower()
        if requested in {"", "direct"}:
            return cls(PublicNetworkMode.DIRECT)
        if requested not in {"proxy", "trusted_local_proxy"}:
            raise PublicNetworkPolicyError("unsupported public network mode", PublicNetworkErrorClass.CONFIG_ERROR)
        raw_proxy = str(values.get("CGKN_PUBLIC_HTTP_PROXY", "")).strip()
        if not raw_proxy:
            raise PublicNetworkPolicyError("proxy mode requires CGKN_PUBLIC_HTTP_PROXY", PublicNetworkErrorClass.CONFIG_ERROR)
        parsed = urlsplit(raw_proxy)
        try:
            port = parsed.port
        except ValueError as exc:
            raise PublicNetworkPolicyError("invalid proxy port", PublicNetworkErrorClass.CONFIG_ERROR) from exc
        if (
            parsed.scheme.lower() != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username
            or parsed.password
            or not port
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise PublicNetworkPolicyError(
                "proxy must be an explicit credential-free HTTP loopback endpoint",
                PublicNetworkErrorClass.CONFIG_ERROR,
            )
        return cls(PublicNetworkMode.TRUSTED_LOCAL_PROXY, parsed.hostname, port)


@dataclass(frozen=True)
class PublicNetworkResponse:
    status_code: int
    final_url: str
    content_type: str
    text: str
    truncated: bool
    bytes_read: int
    redirect_count: int
    transport_mode: str

    def as_dict(self) -> dict[str, object]:
        return {
            "status_code": self.status_code,
            "final_url": self.final_url,
            "content_type": self.content_type,
            "text": self.text,
            "truncated": self.truncated,
            "bytes_read": self.bytes_read,
            "redirect_count": self.redirect_count,
            "transport_mode": self.transport_mode,
        }


@dataclass(frozen=True)
class PublicNetworkEvidence:
    requested_host: str
    transport_mode: str
    status: int
    bytes: int
    redirect_count: int
    policy_decision: str

    def as_dict(self) -> dict[str, object]:
        return {
            "requested_host": self.requested_host,
            "transport_mode": self.transport_mode,
            "status": self.status,
            "bytes": self.bytes,
            "redirect_count": self.redirect_count,
            "policy_decision": self.policy_decision,
        }


@dataclass(frozen=True)
class _TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


Resolver = Callable[[str, int], tuple[str, ...]]
DirectTransport = Callable[[str, str, str, int, str, float, int, Mapping[str, str]], _TransportResponse]
ProxyTransport = Callable[[str, str, int, str, float, int, Mapping[str, str], str, int], _TransportResponse]

_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_BLOCKED_EXACT_HOSTS = {"localhost", "metadata", "metadata.google.internal"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal")
_TEXT_CONTENT_TYPES = {"text/plain", "text/html", "text/markdown", "application/json"}


def _default_resolver(host: str, port: int) -> tuple[str, ...]:
    return tuple(sorted({row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}))


def is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return bool(address.is_global and not address.is_multicast)


def is_fake_ip_address(value: str) -> bool:
    return ipaddress.ip_address(value) in ipaddress.ip_network("198.18.0.0/15")


def _request_bytes(method: str, host: str, target: str, headers: Mapping[str, str]) -> bytes:
    host_header = f"[{host}]" if ":" in host else host
    rows = [f"{method} {target} HTTP/1.1", f"Host: {host_header}"]
    defaults = {"User-Agent": "CGKN-PublicNetwork/2", "Accept": "text/*, application/json"}
    defaults.update(headers)
    rows.extend(f"{key}: {value}" for key, value in defaults.items())
    rows.extend(("Connection: close", "", ""))
    return "\r\n".join(rows).encode("ascii")


def _read_http_response(stream: socket.socket, method: str, limit: int) -> _TransportResponse:
    response = http.client.HTTPResponse(stream)
    response.begin()
    body = b"" if method == "HEAD" else response.read(limit + 1)
    headers = {key.lower(): value for key, value in response.getheaders()}
    return _TransportResponse(response.status, headers, body)


def _default_direct_transport(
    method: str,
    host: str,
    ip: str,
    port: int,
    target: str,
    timeout: float,
    limit: int,
    headers: Mapping[str, str],
) -> _TransportResponse:
    raw = socket.create_connection((ip, port), timeout=timeout)
    try:
        tls = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        try:
            tls.sendall(_request_bytes(method, host, target, headers))
            return _read_http_response(tls, method, limit)
        finally:
            tls.close()
    finally:
        raw.close()


def _default_proxy_transport(
    method: str,
    host: str,
    port: int,
    target: str,
    timeout: float,
    limit: int,
    headers: Mapping[str, str],
    proxy_host: str,
    proxy_port: int,
) -> _TransportResponse:
    raw = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        raw.sendall((f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\nProxy-Connection: close\r\n\r\n").encode("ascii"))
        received = bytearray()
        while b"\r\n\r\n" not in received and len(received) <= 8192:
            chunk = raw.recv(1024)
            if not chunk:
                break
            received.extend(chunk)
        head, separator, remainder = bytes(received).partition(b"\r\n\r\n")
        if not separator or remainder or len(head) > 8192:
            raise OSError("invalid proxy CONNECT response")
        first_line = head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = first_line.split(" ", 2)
        if len(parts) < 2 or parts[1] != "200":
            raise OSError("proxy CONNECT was not accepted")
        tls = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        try:
            tls.sendall(_request_bytes(method, host, target, headers))
            return _read_http_response(tls, method, limit)
        finally:
            tls.close()
    finally:
        raw.close()


def _normalized_host(raw_host: str) -> tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address | None]:
    host = raw_host.rstrip(".").lower()
    try:
        return host, ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PublicNetworkPolicyError("invalid public hostname") from exc
    labels = ascii_host.split(".")
    if len(labels) < 2 or len(ascii_host) > 253 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise PublicNetworkPolicyError("invalid public hostname")
    if ascii_host in _BLOCKED_EXACT_HOSTS or ascii_host.endswith(_BLOCKED_SUFFIXES):
        raise PublicNetworkPolicyError("local or metadata hostname is forbidden")
    return ascii_host, None


class PublicNetworkClient:
    """Credential-free HTTPS GET/HEAD through direct or explicit loopback-proxy transport."""

    FORBIDDEN_HEADERS = {"authorization", "cookie", "set-cookie", "proxy-authorization", "x-api-key", "api-key"}
    ALLOWED_HEADERS = {"accept", "user-agent", "if-none-match", "if-modified-since"}

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1024 * 1024,
        max_redirects: int = 3,
        resolver: Resolver = _default_resolver,
        transport: DirectTransport = _default_direct_transport,
        proxy_transport: ProxyTransport = _default_proxy_transport,
        network_transport: PublicNetworkTransport | None = None,
        environment: Mapping[str, str] | None = None,
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
        self.network_transport = network_transport or PublicNetworkTransport.from_environment(environment)
        self._resolver = resolver
        self._direct_transport = transport
        self._proxy_transport = proxy_transport
        self.last_evidence: PublicNetworkEvidence | None = None

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> dict[str, object]:
        return self.request("GET", url, headers=headers).as_dict()

    def head(self, url: str, *, headers: Mapping[str, str] | None = None) -> dict[str, object]:
        return self.request("HEAD", url, headers=headers).as_dict()

    def _validate_url(self, url: str, *, redirect: bool = False) -> tuple[str, int, str, str | None]:
        classification = PublicNetworkErrorClass.REDIRECT_POLICY_BLOCK if redirect else PublicNetworkErrorClass.NETWORK_POLICY_BLOCK
        try:
            parsed = urlsplit(url)
            if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise PublicNetworkPolicyError("only credential-free HTTPS URLs are allowed", classification)
            host, literal = _normalized_host(parsed.hostname)
            port = parsed.port or 443
        except PublicNetworkPolicyError as exc:
            if redirect and exc.classification is PublicNetworkErrorClass.NETWORK_POLICY_BLOCK:
                raise PublicNetworkPolicyError(str(exc), classification) from exc
            raise
        except (TypeError, ValueError) as exc:
            raise PublicNetworkPolicyError("invalid public URL", classification) from exc
        if literal is not None and not is_public_address(str(literal)):
            raise PublicNetworkPolicyError("non-public literal destination is forbidden", classification)
        if port != 443:
            raise PublicNetworkPolicyError("only HTTPS port 443 is allowed", classification)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        return host, port, target, str(literal) if literal is not None else None

    def _validated_headers(self, headers: Mapping[str, str] | None) -> dict[str, str]:
        supplied = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
        if self.FORBIDDEN_HEADERS.intersection(supplied):
            raise PublicNetworkPolicyError("credentials are forbidden")
        if set(supplied) - self.ALLOWED_HEADERS:
            raise PublicNetworkPolicyError("header is outside the public-network allowlist")
        if any("\r" in value or "\n" in value for value in supplied.values()):
            raise PublicNetworkPolicyError("header injection is forbidden")
        return {"-".join(word.capitalize() for word in key.split("-")): value for key, value in supplied.items()}

    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None) -> PublicNetworkResponse:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD"}:
            raise PublicNetworkPolicyError("only GET and HEAD are allowed")
        supplied_headers = self._validated_headers(headers)
        current = str(url)
        requested_host = ""
        for redirect_index in range(self.max_redirects + 1):
            host, port, target, literal = self._validate_url(current, redirect=redirect_index > 0)
            requested_host = requested_host or host
            try:
                if self.network_transport.mode is PublicNetworkMode.DIRECT:
                    try:
                        addresses = (literal,) if literal else self._resolver(host, port)
                    except (OSError, socket.gaierror) as exc:
                        raise PublicNetworkPolicyError("public hostname resolution failed", PublicNetworkErrorClass.PUBLIC_DNS_FAILURE) from exc
                    if not addresses or any(not is_public_address(address) for address in addresses):
                        raise PublicNetworkPolicyError("destination did not resolve exclusively to public addresses")
                    response = self._direct_transport(normalized_method, host, addresses[0], port, target, self.timeout_seconds, self.max_response_bytes, supplied_headers)
                else:
                    response = self._proxy_transport(
                        normalized_method, host, port, target, self.timeout_seconds,
                        self.max_response_bytes, supplied_headers,
                        str(self.network_transport.proxy_host), int(self.network_transport.proxy_port or 0),
                    )
            except PublicNetworkPolicyError:
                raise
            except OSError as exc:
                error_class = PublicNetworkErrorClass.LOCAL_PROXY_UNAVAILABLE if self.network_transport.mode is PublicNetworkMode.TRUSTED_LOCAL_PROXY else PublicNetworkErrorClass.PUBLIC_TARGET_FAILURE
                raise PublicNetworkPolicyError("public network transport failed", error_class) from exc

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location", "")
                if not location:
                    raise PublicNetworkPolicyError("redirect response omitted Location", PublicNetworkErrorClass.REDIRECT_POLICY_BLOCK)
                if redirect_index >= self.max_redirects:
                    raise PublicNetworkPolicyError("redirect limit exceeded", PublicNetworkErrorClass.REDIRECT_POLICY_BLOCK)
                current = urljoin(current, location)
                continue

            body = response.body
            truncated = len(body) > self.max_response_bytes
            bounded = body[: self.max_response_bytes]
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in _TEXT_CONTENT_TYPES and not (content_type.startswith("application/") and content_type.endswith("+json")):
                raise PublicNetworkPolicyError("response content type is not text-like", PublicNetworkErrorClass.UNSUPPORTED_CONTENT_TYPE)
            text = bounded.decode("utf-8", errors="replace")
            self.last_evidence = PublicNetworkEvidence(requested_host, self.network_transport.mode.value, response.status_code, len(bounded), redirect_index, "ALLOW")
            return PublicNetworkResponse(response.status_code, current, content_type, text, truncated, len(bounded), redirect_index, self.network_transport.mode.value)
        raise PublicNetworkPolicyError("redirect limit exceeded", PublicNetworkErrorClass.REDIRECT_POLICY_BLOCK)
