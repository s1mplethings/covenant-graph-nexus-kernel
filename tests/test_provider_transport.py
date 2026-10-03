from __future__ import annotations

import io
import http.client
import urllib.error
import json
import pathlib

import pytest

from scripts import provider_transport
from scripts import run_local_pipeline_impl as pipeline


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


def test_retry_policy_stops_two_same_class_pre_header_timeouts() -> None:
    attempts = [
        {"retryable": True, "error_type": "PROVIDER_TRANSPORT_UNSTABLE", "response_headers_received": False},
        {"retryable": True, "error_type": "PROVIDER_TRANSPORT_UNSTABLE", "response_headers_received": False},
    ]
    assert provider_transport.should_retry_provider_attempt(attempts[:1]) is True
    assert provider_transport.should_retry_provider_attempt(attempts) is False


def test_retry_policy_allows_three_response_header_http_attempts() -> None:
    attempts = [
        {"retryable": True, "error_type": "PROVIDER_RETRYABLE_HTTP", "response_headers_received": True},
        {"retryable": True, "error_type": "PROVIDER_RETRYABLE_HTTP", "response_headers_received": True},
    ]
    assert provider_transport.should_retry_provider_attempt(attempts) is True
    assert provider_transport.should_retry_provider_attempt([*attempts, attempts[-1]]) is False


def _planning_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "Return strict planning JSON."},
        {"role": "user", "content": json.dumps({"goal": "中文路径视频帧", "constraints": ["Windows", "local-first"]}, ensure_ascii=False)},
    ]


def test_requirements_preflight_tiny_failure_short_circuits(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(pipeline.check_connectivity, "_resolve_api_credentials", lambda: {"api_key": "secret", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"})
    monkeypatch.setattr(pipeline.check_connectivity, "_openai_compatible_endpoint", lambda *_args, **_kwargs: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    monkeypatch.setattr(pipeline, "choose_provider_model", lambda *_args, **_kwargs: {"selected_model": "qwen3.8-max"})
    monkeypatch.setattr(pipeline.check_connectivity, "_post_json", lambda *_args: (calls.append("tiny") or (None, "TimeoutError: timed out")))
    monkeypatch.setattr(pipeline.check_connectivity, "last_transport_timing", lambda: {"response_headers_received": False, "total_elapsed_ms": 1000})

    with pytest.raises(RuntimeError, match="PROVIDER_BASELINE_UNAVAILABLE"):
        pipeline.requirements_planning_provider_preflight(
            messages=_planning_messages(), requested_model="qwen3.8-max", timeout=60,
            run_dir=tmp_path, routing_policy=None, response_format={"type": "json_object"},
        )
    assert calls == ["tiny"]


def test_requirements_preflight_structured_failure_short_circuits(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        ({"choices": [{"message": {"content": "pong"}}]}, ""),
        (None, "HTTP 503: unavailable [retryable=true]"),
    ]
    monkeypatch.setattr(pipeline.check_connectivity, "_resolve_api_credentials", lambda: {"api_key": "secret", "base_url": "https://api.example.test/v1"})
    monkeypatch.setattr(pipeline.check_connectivity, "_openai_compatible_endpoint", lambda *_args, **_kwargs: "https://api.example.test/v1/chat/completions")
    monkeypatch.setattr(pipeline, "choose_provider_model", lambda *_args, **_kwargs: {"selected_model": "qwen3.8-max"})
    monkeypatch.setattr(pipeline.check_connectivity, "_post_json", lambda *_args: responses.pop(0))
    monkeypatch.setattr(pipeline.check_connectivity, "last_transport_timing", lambda: {"response_headers_received": True, "total_elapsed_ms": 10})

    with pytest.raises(RuntimeError, match="PROVIDER_STRUCTURED_REQUEST_UNAVAILABLE"):
        pipeline.requirements_planning_provider_preflight(
            messages=_planning_messages(), requested_model="qwen3.8-max", timeout=60,
            run_dir=tmp_path, routing_policy=None, response_format={"type": "json_object"},
        )
    assert responses == []


def test_requirements_preflight_writes_secret_free_metrics(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-never-persist-this-value"
    responses = [
        ({"choices": [{"message": {"content": "pong"}}]}, ""),
        ({"choices": [{"message": {"content": '{"cgkn_probe":"ok","goal":"x","capabilities":["y"]}'}}]}, ""),
        ({"choices": [{"message": {"content": '{"cgkn_probe":"ok"}'}}]}, ""),
        ({"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}, ""),
    ]
    monkeypatch.setattr(pipeline.check_connectivity, "_resolve_api_credentials", lambda: {"api_key": secret, "base_url": "https://api.example.test/v1"})
    monkeypatch.setattr(pipeline.check_connectivity, "_openai_compatible_endpoint", lambda *_args, **_kwargs: "https://api.example.test/v1/chat/completions")
    monkeypatch.setattr(pipeline, "choose_provider_model", lambda *_args, **_kwargs: {"selected_model": "qwen3.8-max"})
    monkeypatch.setattr(pipeline.check_connectivity, "_post_json", lambda *_args: responses.pop(0))
    monkeypatch.setattr(pipeline.check_connectivity, "last_transport_timing", lambda: {"response_headers_received": True, "response_headers_elapsed_ms": 8, "response_body_received": True, "response_body_bytes": 20, "total_elapsed_ms": 9})

    result = pipeline.requirements_planning_provider_preflight(
        messages=_planning_messages(), requested_model="qwen3.8-max", timeout=60,
        run_dir=tmp_path, routing_policy=None,
        response_format=pipeline.canonical_goal_spec_compiler.planning_proposal_response_format(),
    )
    metrics_text = (tmp_path / "artifacts" / "requirements_planning_request_metrics.json").read_text(encoding="utf-8")
    assert result["status"] == "PASS"
    assert result["probes"]["tiny"]["max_output_tokens"] == 32
    assert result["probes"]["json_text"]["max_output_tokens"] == 128
    assert result["probes"]["json_schema"]["max_output_tokens"] == 256
    assert result["probes"]["json_schema"]["response_format_type"] == "json_schema"
    assert result["probes"]["real_512"]["max_output_tokens"] == 512
    assert secret not in metrics_text
    assert "中文路径视频帧" not in metrics_text
    metrics = json.loads(metrics_text)
    assert metrics["hashes"]["request_body_sha256"]
    assert metrics["goal_chars"] == len("中文路径视频帧")
    assert metrics["max_output_tokens"] == 12000
    assert metrics["response_format_present"] is True
    assert metrics["schema_sha256"]


def test_requirements_planning_budget_is_deterministic_and_bounded() -> None:
    simple = {"goal": "x"}
    complex_context = {"capabilities": list(range(100)), "workflows": list(range(100)), "constraints": list(range(100))}
    assert pipeline.requirements_planning_output_token_budget(simple) == pipeline.requirements_planning_output_token_budget(simple)
    assert 1200 <= pipeline.requirements_planning_output_token_budget(simple) <= 4096
    assert pipeline.requirements_planning_output_token_budget(complex_context) == 4096


def test_complex_real_requirement_selects_4096_initially() -> None:
    goal = "Local Python video frame extractor with Windows and Chinese-path support"
    context = {"goal": goal, "canonical_evidence_units": pipeline.canonical_goal_spec_compiler.build_canonical_evidence_units(goal)}
    assert pipeline.requirements_planning_output_token_budget(context) == 4096


def test_tiny_requirement_keeps_small_initial_budget() -> None:
    assert pipeline.requirements_planning_output_token_budget({"goal": "x"}) == 1200


def test_requirements_schema_probe_failure_short_circuits_real_request(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        ({"choices": [{"message": {"content": "pong"}}]}, ""),
        ({"choices": [{"message": {"content": '{"cgkn_probe":"ok"}'}}]}, ""),
        (None, 'HTTP 400: response_format json_schema unsupported [retryable=false]'),
    ]
    monkeypatch.setattr(pipeline.check_connectivity, "_resolve_api_credentials", lambda: {"api_key": "secret", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"})
    monkeypatch.setattr(pipeline.check_connectivity, "_openai_compatible_endpoint", lambda *_args, **_kwargs: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    monkeypatch.setattr(pipeline, "choose_provider_model", lambda *_args, **_kwargs: {"selected_model": "qwen3.8-max"})
    monkeypatch.setattr(pipeline.check_connectivity, "_post_json", lambda *_args: responses.pop(0))
    monkeypatch.setattr(pipeline.check_connectivity, "last_transport_timing", lambda: {"response_headers_received": True, "total_elapsed_ms": 10})
    with pytest.raises(RuntimeError, match="PROVIDER_JSON_SCHEMA_UNAVAILABLE"):
        pipeline.requirements_planning_provider_preflight(
            messages=_planning_messages(), requested_model="qwen3.8-max", timeout=60,
            run_dir=tmp_path, routing_policy=None, response_format={"type": "json_object"},
        )
    assert responses == []


def test_provider_text_caps_same_request_pre_header_retries(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload_hashes: list[str] = []
    payloads: list[dict] = []
    monkeypatch.setattr(pipeline, "try_local_provider_text", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline.check_connectivity, "_resolve_api_credentials", lambda: {"api_key": "secret", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"})
    monkeypatch.setattr(pipeline.check_connectivity, "_openai_compatible_endpoint", lambda *_args, **_kwargs: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    monkeypatch.setattr(pipeline, "choose_provider_model", lambda *_args, **_kwargs: {"selected_model": "qwen3.8-max", "requested_model": "qwen3.8-max"})
    monkeypatch.setattr(pipeline, "provider_reasoning_effort", lambda *_args: "none")
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_args: None)

    def fail(_endpoint, payload, _token, _timeout):
        payloads.append(payload)
        payload_hashes.append(pipeline.formal_model_contract.stable_hash(payload))
        pipeline.check_connectivity._set_last_transport_timing({"response_headers_received": False, "failure_phase": "connect_or_response_headers", "total_elapsed_ms": 1})
        return None, "TimeoutError: timed out [retryable=true]"

    monkeypatch.setattr(pipeline.check_connectivity, "_post_json", fail)
    with pytest.raises(RuntimeError, match="response_headers_received=false"):
        pipeline.provider_text(
            _planning_messages(), "qwen3.8-max", 60, max_attempts=5,
            stage="requirements_planning", phase_log_path=tmp_path / "events.jsonl",
            max_tokens=2048,
            response_format=pipeline.canonical_goal_spec_compiler.planning_proposal_response_format(),
        )
    assert len(payload_hashes) == 2
    assert len(set(payload_hashes)) == 1
    assert all(item["max_tokens"] == 2048 and item["response_format"]["type"] == "json_schema" for item in payloads)


def test_requirements_real_512_pre_header_timeout_is_classified(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        ({"choices": [{"message": {"content": "pong"}}]}, ""),
        ({"choices": [{"message": {"content": '{"cgkn_probe":"ok"}'}}]}, ""),
        ({"choices": [{"message": {"content": '{"cgkn_probe":"ok"}'}}]}, ""),
        (None, "TimeoutError: timed out [retryable=true]"),
        (None, "TimeoutError: timed out [retryable=true]"),
    ]
    monkeypatch.setattr(pipeline.check_connectivity, "_resolve_api_credentials", lambda: {"api_key": "secret", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"})
    monkeypatch.setattr(pipeline.check_connectivity, "_openai_compatible_endpoint", lambda *_args, **_kwargs: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    monkeypatch.setattr(pipeline, "choose_provider_model", lambda *_args, **_kwargs: {"selected_model": "qwen3.8-max"})
    monkeypatch.setattr(pipeline.check_connectivity, "_post_json", lambda *_args: responses.pop(0))
    monkeypatch.setattr(pipeline.check_connectivity, "last_transport_timing", lambda: {"response_headers_received": False, "total_elapsed_ms": 60000})
    with pytest.raises(RuntimeError, match="PROVIDER_REAL_PLANNING_TRANSPORT_UNSTABLE"):
        pipeline.requirements_planning_provider_preflight(
            messages=_planning_messages(), requested_model="qwen3.8-max", timeout=60,
            run_dir=tmp_path, routing_policy=None,
            response_format=pipeline.canonical_goal_spec_compiler.planning_proposal_response_format(),
        )
    checkpoint = json.loads((tmp_path / "artifacts" / "provider_preflight_checkpoint.json").read_text(encoding="utf-8"))
    assert len(checkpoint["probes"]["real_512"]["attempts"]) == 2
    assert len({item["request_body_sha256"] for item in checkpoint["probes"]["real_512"]["attempts"]}) == 1
