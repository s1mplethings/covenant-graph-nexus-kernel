from __future__ import annotations

import argparse

from scripts import run_provider_failure_boundary as boundary


def test_boundary_case_sizes_are_deterministic() -> None:
    cases = boundary._case_definitions()

    assert len(cases["input_32763_short"]["prompt"]) == 32_763
    assert len(cases["input_39k_short"]["prompt"]) == 39_000
    assert cases["complex_32763_4k"]["max_tokens"] == 4_000
    assert cases["complex_32763_8k"]["max_tokens"] == 8_000


def test_run_records_hashes_and_metrics_but_not_generated_content(monkeypatch) -> None:
    monkeypatch.setattr(
        boundary.check_connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "sk-test-secret-value", "base_url": "https://api.gptsapi.net/v1"},
    )
    monkeypatch.setattr(
        boundary.provider_transport,
        "post_json_once",
        lambda endpoint, payload, token, timeout: (
            {
                "id": "request-1",
                "choices": [{"message": {"content": "PONG"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
            "",
        ),
    )

    report = boundary.run(
        argparse.Namespace(
            model="gpt-5.4-nano",
            timeout=90,
            cases="control_1k_short",
            repeats=1,
            concurrency=0,
        )
    )

    result = report["results"][0]
    assert result["ok"] is True
    assert result["response_chars"] == 4
    assert len(result["response_sha256"]) == 64
    assert result["finish_reason"] == "stop"
    assert "PONG" not in str(report)
    assert "sk-test-secret-value" not in str(report)
    assert report["secrets_recorded"] is False


def test_failure_is_classified_without_response_content(monkeypatch) -> None:
    monkeypatch.setattr(
        boundary.check_connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "sk-test-secret-value", "base_url": "https://api.gptsapi.net/v1"},
    )
    monkeypatch.setattr(
        boundary.provider_transport,
        "post_json_once",
        lambda endpoint, payload, token, timeout: (
            None,
            "HTTP 520: origin failed [retryable=true]",
        ),
    )

    report = boundary.run(
        argparse.Namespace(
            model="gpt-5.4-nano",
            timeout=90,
            cases="complex_32763_8k",
            repeats=1,
            concurrency=0,
        )
    )

    result = report["results"][0]
    assert result["ok"] is False
    assert result["error_type"] == "PROVIDER_TRANSPORT_UNSTABLE"
    assert result["response_chars"] == 0
    assert report["summary"]["failure_count"] == 1
