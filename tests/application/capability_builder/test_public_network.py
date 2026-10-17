from __future__ import annotations

from types import SimpleNamespace

import pytest

from cgkn.application.capability_builder import PublicNetworkClient, PublicNetworkPolicyError, is_public_address


PUBLIC = ("93.184.216.34",)


def response(status=200, body=b"ok", **headers):
    return SimpleNamespace(status_code=status, body=body, headers={key.replace("_", "-"): value for key, value in headers.items()})


def client(*, resolver=lambda host, port: PUBLIC, transport=lambda *args: response(content_type="text/plain"), limit=1024, redirects=3):
    return PublicNetworkClient(resolver=resolver, transport=transport, max_response_bytes=limit, max_redirects=redirects)


def test_public_https_get_is_allowed_and_bounded():
    value = client().get("https://example.com/path?q=1")
    assert value == {"status_code": 200, "final_url": "https://example.com/path?q=1", "content_type": "text/plain", "text": "ok", "truncated": False, "bytes_read": 2}


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.4", "10.0.0.2", "172.16.0.1", "169.254.169.254", "::1", "fc00::1", "fe80::1"])
def test_non_public_addresses_are_blocked(address):
    with pytest.raises(PublicNetworkPolicyError, match="public"):
        client(resolver=lambda host, port: (address,)).get("https://example.com")
    assert not is_public_address(address)


@pytest.mark.parametrize("url", ["https://localhost/x", "https://service.local/x", "http://example.com", "file:///tmp/x", "https://user:secret@example.com"])
def test_non_public_url_forms_are_blocked(url):
    with pytest.raises(PublicNetworkPolicyError):
        client().get(url)


def test_public_to_private_redirect_is_revalidated_and_blocked():
    def resolver(host, port):
        return PUBLIC if host == "example.com" else ("127.0.0.1",)
    def transport(*args):
        return response(302, location="https://127.0.0.1/private")
    with pytest.raises(PublicNetworkPolicyError, match="public"):
        client(resolver=resolver, transport=transport).get("https://example.com")


@pytest.mark.parametrize("headers", [{"Authorization": "Bearer secret"}, {"Cookie": "a=b"}, {"X-API-Key": "secret"}, {"X-Custom": "value"}])
def test_credentials_and_custom_headers_are_blocked(headers):
    with pytest.raises(PublicNetworkPolicyError):
        client().get("https://example.com", headers=headers)


def test_post_is_blocked():
    with pytest.raises(PublicNetworkPolicyError, match="GET and HEAD"):
        client().request("POST", "https://example.com")


def test_oversized_response_is_truncated_at_configured_bound():
    value = client(transport=lambda *args: response(body=b"abcdef", content_type="text/plain"), limit=4).get("https://example.com")
    assert value["text"] == "abcd" and value["truncated"] is True and value["bytes_read"] == 4


def test_redirect_limit_is_enforced():
    with pytest.raises(PublicNetworkPolicyError, match="redirect limit"):
        client(transport=lambda *args: response(302, location="https://example.com/again"), redirects=1).get("https://example.com")


def test_runtime_limits_cannot_exceed_policy_maxima():
    with pytest.raises(ValueError):
        PublicNetworkClient(timeout_seconds=11)
    with pytest.raises(ValueError):
        PublicNetworkClient(max_response_bytes=1024 * 1024 + 1)
    with pytest.raises(ValueError):
        PublicNetworkClient(max_redirects=4)
