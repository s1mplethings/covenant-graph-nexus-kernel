from __future__ import annotations

from types import SimpleNamespace

import pytest

from cgkn.application.capability_builder import (
    PublicNetworkClient,
    PublicNetworkErrorClass,
    PublicNetworkMode,
    PublicNetworkPolicyError,
    PublicNetworkTransport,
    is_public_address,
)


PUBLIC = ("93.184.216.34",)
DIRECT = PublicNetworkTransport(PublicNetworkMode.DIRECT)
PROXY = PublicNetworkTransport(PublicNetworkMode.TRUSTED_LOCAL_PROXY, "127.0.0.1", 7890)


def response(status=200, body=b"ok", **headers):
    return SimpleNamespace(status_code=status, body=body, headers={key.replace("_", "-"): value for key, value in headers.items()})


def client(*, resolver=lambda host, port: PUBLIC, transport=lambda *args: response(content_type="text/plain"), proxy_transport=lambda *args: response(content_type="text/plain"), limit=1024, redirects=3, mode=DIRECT):
    return PublicNetworkClient(
        resolver=resolver,
        transport=transport,
        proxy_transport=proxy_transport,
        max_response_bytes=limit,
        max_redirects=redirects,
        network_transport=mode,
    )


def test_direct_public_target_is_allowed_and_result_has_transport_evidence():
    value = client().get("https://example.com/path?q=1")
    assert value == {
        "status_code": 200,
        "final_url": "https://example.com/path?q=1",
        "content_type": "text/plain",
        "text": "ok",
        "truncated": False,
        "bytes_read": 2,
        "redirect_count": 0,
        "transport_mode": "DIRECT",
    }


def test_direct_rejects_loopback_and_all_required_non_public_ranges():
    addresses = ("127.0.0.1", "192.168.1.4", "10.0.0.2", "172.16.0.1", "169.254.169.254", "198.18.1.22", "224.0.0.1", "::1", "fc00::1", "fe80::1")
    for address in addresses:
        with pytest.raises(PublicNetworkPolicyError, match="public"):
            client(resolver=lambda host, port, address=address: (address,)).get("https://example.com")
        assert not is_public_address(address)


def test_proxy_rejects_non_public_literal_target_including_fake_ip():
    for url in ("https://127.0.0.1", "https://192.168.1.1", "https://169.254.169.254", "https://198.18.1.22", "https://[::1]"):
        with pytest.raises(PublicNetworkPolicyError, match="literal"):
            client(mode=PROXY).get(url)


def test_proxy_public_hostname_uses_only_explicit_loopback_proxy():
    calls = []
    value = client(mode=PROXY, proxy_transport=lambda *args: calls.append(args) or response(content_type="text/plain")).get("https://example.com")
    assert value["transport_mode"] == "TRUSTED_LOCAL_PROXY"
    assert calls[0][-2:] == ("127.0.0.1", 7890)


def test_proxy_configuration_requires_explicit_credential_free_loopback():
    invalid = (
        {"CGKN_PUBLIC_NETWORK_MODE": "proxy"},
        {"CGKN_PUBLIC_NETWORK_MODE": "proxy", "CGKN_PUBLIC_HTTP_PROXY": "http://192.168.1.2:7890"},
        {"CGKN_PUBLIC_NETWORK_MODE": "proxy", "CGKN_PUBLIC_HTTP_PROXY": "http://203.0.113.1:7890"},
        {"CGKN_PUBLIC_NETWORK_MODE": "proxy", "CGKN_PUBLIC_HTTP_PROXY": "http://user:secret@127.0.0.1:7890"},
        {"CGKN_PUBLIC_NETWORK_MODE": "proxy", "CGKN_PUBLIC_HTTP_PROXY": "http://localhost:7890"},
    )
    for environment in invalid:
        with pytest.raises(PublicNetworkPolicyError) as captured:
            PublicNetworkTransport.from_environment(environment)
        assert captured.value.classification is PublicNetworkErrorClass.CONFIG_ERROR


def test_proxy_configuration_accepts_only_explicit_ipv4_or_ipv6_loopback():
    ipv4 = PublicNetworkTransport.from_environment({"CGKN_PUBLIC_NETWORK_MODE": "proxy", "CGKN_PUBLIC_HTTP_PROXY": "http://127.0.0.1:7890"})
    ipv6 = PublicNetworkTransport.from_environment({"CGKN_PUBLIC_NETWORK_MODE": "proxy", "CGKN_PUBLIC_HTTP_PROXY": "http://[::1]:7890"})
    assert (ipv4.proxy_host, ipv6.proxy_host) == ("127.0.0.1", "::1")


def test_every_redirect_is_revalidated_and_private_targets_are_blocked():
    for destination in ("https://127.0.0.1/private", "https://198.18.1.22/private", "https://metadata.google.internal/"):
        with pytest.raises(PublicNetworkPolicyError) as captured:
            client(mode=PROXY, proxy_transport=lambda *args, destination=destination: response(302, location=destination)).get("https://example.com")
        assert captured.value.classification is PublicNetworkErrorClass.REDIRECT_POLICY_BLOCK


def test_local_and_internal_hostname_forms_are_blocked_without_dns():
    for url in ("https://localhost", "https://x.local", "https://x.internal", "https://metadata", "https://metadata.google.internal"):
        with pytest.raises(PublicNetworkPolicyError):
            client(mode=PROXY).get(url)


def test_credentials_and_non_allowlisted_headers_are_blocked():
    for headers in ({"Authorization": "Bearer secret"}, {"Cookie": "a=b"}, {"Proxy-Authorization": "x"}, {"X-API-Key": "secret"}, {"X-Custom": "value"}):
        with pytest.raises(PublicNetworkPolicyError):
            client().get("https://example.com", headers=headers)


def test_small_safe_header_allowlist_is_forwarded():
    calls = []
    client(transport=lambda *args: calls.append(args) or response(content_type="text/plain")).get("https://example.com", headers={"Accept": "application/json"})
    assert calls[0][-1] == {"Accept": "application/json"}


def test_post_and_user_level_connect_are_blocked():
    for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT"):
        with pytest.raises(PublicNetworkPolicyError, match="GET and HEAD"):
            client().request(method, "https://example.com")


def test_oversized_response_is_bounded_at_configured_limit():
    value = client(transport=lambda *args: response(body=b"abcdef", content_type="text/plain"), limit=4).get("https://example.com")
    assert value["text"] == "abcd" and value["truncated"] is True and value["bytes_read"] == 4


def test_direct_fake_ip_dns_still_blocks_when_proxy_is_disabled():
    with pytest.raises(PublicNetworkPolicyError, match="public"):
        client(resolver=lambda host, port: ("198.18.1.22",)).get("https://example.com")


def test_proxy_public_hostname_does_not_use_fake_ip_resolver_as_authority():
    resolver_calls = []
    value = client(
        mode=PROXY,
        resolver=lambda host, port: resolver_calls.append((host, port)) or ("198.18.1.22",),
        proxy_transport=lambda *args: response(content_type="application/json", body=b"{}"),
    ).get("https://api.github.com/repos/o/r")
    assert resolver_calls == []
    assert value["transport_mode"] == "TRUSTED_LOCAL_PROXY"


def test_redirect_limit_content_type_and_runtime_caps_remain_enforced():
    with pytest.raises(PublicNetworkPolicyError) as redirect_error:
        client(transport=lambda *args: response(302, location="https://example.com/again"), redirects=1).get("https://example.com")
    assert redirect_error.value.classification is PublicNetworkErrorClass.REDIRECT_POLICY_BLOCK
    with pytest.raises(PublicNetworkPolicyError) as content_error:
        client(transport=lambda *args: response(content_type="application/octet-stream")).get("https://example.com")
    assert content_error.value.classification is PublicNetworkErrorClass.UNSUPPORTED_CONTENT_TYPE
    for kwargs in ({"timeout_seconds": 11}, {"max_response_bytes": 1024 * 1024 + 1}, {"max_redirects": 4}):
        with pytest.raises(ValueError):
            PublicNetworkClient(network_transport=DIRECT, **kwargs)
