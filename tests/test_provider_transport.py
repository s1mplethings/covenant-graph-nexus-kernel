from __future__ import annotations

import io
import http.client
import urllib.error

import pytest

from scripts import provider_transport


def test_key_usage_limit_is_non_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fail(_request, _timeout):
        calls.append(1)
        raise urllib.error.HTTPError(
            "https://api.example.test/v1/responses",
            403,
            "forbidden",
            {},
            io.BytesIO(b'{"error":"Key usage limit exceeded"}'),
        )

    monkeypatch.setattr(provider_transport, "_urlopen", fail)
    result = provider_transport.post_json_with_retry(
        "https://api.example.test/v1/responses",
        {"model": "test"},
        "secret-token",
        5,
        sleep_fn=lambda _delay: None,
    )

    assert result.ok is False
    assert result.error_type == "PROVIDER_KEY_USAGE_LIMIT"
    assert len(result.attempts) == 1
    assert calls == [1]


def test_429_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_once(*_args):
        calls.append(1)
        return None, "HTTP 429: rate limited [retryable=true]"

    monkeypatch.setattr(provider_transport, "post_json_once", fake_once)
    result = provider_transport.post_json_with_retry(
        "https://api.example.test/v1/responses",
        {},
        "token",
        5,
        max_attempts=3,
        sleep_fn=lambda _delay: None,
        jitter_fn=lambda: 0,
    )

    assert result.ok is False
    assert len(result.attempts) == 3
    assert all(item.retryable for item in result.attempts)


def test_remote_disconnected_exception_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def disconnect(_request, _timeout):
        calls.append(1)
        raise http.client.RemoteDisconnected("Remote end closed connection without response")

    monkeypatch.setattr(provider_transport, "_urlopen", disconnect)
    result = provider_transport.post_json_with_retry(
        "https://api.example.test/v1/responses",
        {},
        "token",
        5,
        max_attempts=2,
        sleep_fn=lambda _delay: None,
        jitter_fn=lambda: 0,
    )

    assert result.error_type == "PROVIDER_TRANSPORT_UNSTABLE"
    assert len(result.attempts) == 2
    assert calls == [1, 1]


@pytest.mark.parametrize(
    "error",
    [
        "SSLError: SSLV3_ALERT_BAD_RECORD_MAC",
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol",
        "ConnectionResetError: connection reset",
        "TimeoutError: timed out",
        "URLError: connection aborted",
        "HTTP 520: upstream unavailable [retryable=true]",
    ],
)
def test_transport_failures_are_classified_unstable(error: str) -> None:
    assert provider_transport.is_retryable_error(error) is True
    assert provider_transport.classify_provider_error(error) == "PROVIDER_TRANSPORT_UNSTABLE"


def test_third_attempt_success_sets_recovered(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        (None, "TimeoutError: timed out"),
        (None, "HTTP 503: unavailable [retryable=true]"),
        ({"status": "completed"}, ""),
    ]
    monkeypatch.setattr(provider_transport, "post_json_once", lambda *_args: responses.pop(0))

    result = provider_transport.post_json_with_retry(
        "https://api.example.test/v1/responses",
        {},
        "token",
        5,
        sleep_fn=lambda _delay: None,
        jitter_fn=lambda: 0,
    )

    assert result.ok is True
    assert result.recovered is True
    assert len(result.attempts) == 3


def test_non_json_response_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"<html>not json</html>"

    monkeypatch.setattr(provider_transport, "_urlopen", lambda _request, _timeout: Response())
    doc, error = provider_transport.post_json_once("https://api.example.test", {}, "token", 5)

    assert doc is None
    assert "non-json response" in error


def test_api_key_is_redacted_from_result_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "sk-sensitive-value-123456"
    monkeypatch.setattr(
        provider_transport,
        "post_json_once",
        lambda *_args: (None, f"connection reset while using Bearer {token}"),
    )

    result = provider_transport.post_json_with_retry(
        "https://api.example.test",
        {},
        token,
        5,
        max_attempts=1,
    )

    assert token not in repr(result)
    assert "<redacted>" in result.error
