from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import provider_transport
from scripts.run_quick_large_sync_tree_benchmark import run_benchmark, run_provider_readiness_only


def _transport_result(*, ok: bool = True, error: str = "", error_type: str = "") -> provider_transport.ProviderTransportResult:
    attempt = provider_transport.ProviderTransportAttempt(
        attempt=1,
        ok=ok,
        error=error,
        error_type=error_type,
        retryable=False,
        elapsed_ms=1,
    )
    return provider_transport.ProviderTransportResult(
        ok=ok,
        doc={"choices": [{"message": {"content": "ok"}}]} if ok else None,
        error=error,
        error_type=error_type,
        attempts=[attempt],
        recovered=False,
    )


def _patch_credentials(monkeypatch, *, key: str = "test-token", base_url: str = "https://api.gptsapi.net/v1") -> None:
    monkeypatch.setattr(
        "scripts.run_quick_large_sync_tree_benchmark.check_connectivity._resolve_api_credentials",
        lambda: {"api_key": key, "api_key_source": "test", "base_url": base_url, "base_url_source": "test"},
    )


def test_guarded_provider_readiness_only_does_not_start_generation(tmp_path: pathlib.Path, monkeypatch) -> None:
    _patch_credentials(monkeypatch)
    monkeypatch.setattr(
        "scripts.run_quick_large_sync_tree_benchmark.check_connectivity._post_json_with_retry",
        lambda *args, **kwargs: _transport_result(),
    )

    summary = run_benchmark(
        goal="Multi-Environment Studio Operations Platform",
        mode="guarded_provider",
        max_rounds=1,
        max_branches=1,
        max_leaves=1,
        require_multi_env=True,
        require_sync_growth=True,
        output_root=tmp_path / "generated" / "quick_large_sync_tree",
        model="gpt-4.1-mini",
        provider_readiness_only=True,
    )
    readiness = json.loads((pathlib.Path(summary["run_dir"]) / "provider_readiness.json").read_text(encoding="utf-8"))

    assert readiness["leaf_generation_started"] is False
    assert readiness["project_generation_started"] is False
    assert not (pathlib.Path(summary["run_dir"]) / "project").exists()
    assert not (pathlib.Path(summary["run_dir"]) / "sync_growth_ledger.jsonl").exists()


def test_gptsapi_gpt41mini_selects_chat_completions(tmp_path: pathlib.Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    _patch_credentials(monkeypatch, base_url="https://api.gptsapi.net/v1")

    def fake_post(endpoint, payload, token, timeout, **kwargs):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return _transport_result()

    summary = run_provider_readiness_only(
        goal="goal",
        mode="guarded_provider",
        model="gpt-4.1-mini",
        output_root=tmp_path / "generated" / "quick_large_sync_tree",
        post_json_with_retry_fn=fake_post,
    )
    readiness = json.loads((pathlib.Path(summary["run_dir"]) / "provider_readiness.json").read_text(encoding="utf-8"))

    assert readiness["selected_method"] == "chat_completions"
    assert readiness["base_url_domain"] == "gptsapi.net"
    assert captured["endpoint"] == "https://api.gptsapi.net/v1/chat/completions"
    assert "messages" in captured["payload"]
    assert "input" not in captured["payload"]


def test_readiness_report_does_not_contain_api_key(tmp_path: pathlib.Path, monkeypatch) -> None:
    fake_key = "sk-" + "a" * 32
    _patch_credentials(monkeypatch, key=fake_key)
    monkeypatch.setattr(
        "scripts.run_quick_large_sync_tree_benchmark.check_connectivity._post_json_with_retry",
        lambda *args, **kwargs: _transport_result(ok=False, error=f"HTTP 400: {fake_key} unsupported", error_type="PROVIDER_METHOD_UNSUPPORTED"),
    )

    summary = run_provider_readiness_only(
        goal="goal",
        mode="guarded_provider",
        model="gpt-4.1-mini",
        output_root=tmp_path / "generated" / "quick_large_sync_tree",
    )
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in pathlib.Path(summary["run_dir"]).glob("*") if path.is_file())

    assert fake_key not in text
    assert not re.search(r"sk-[A-Za-z0-9]{20,}", text)
    assert "Authorization" not in text


def test_method_unsupported_classifies_as_provider_method_unsupported(tmp_path: pathlib.Path, monkeypatch) -> None:
    _patch_credentials(monkeypatch)
    monkeypatch.setattr(
        "scripts.run_quick_large_sync_tree_benchmark.check_connectivity._post_json_with_retry",
        lambda *args, **kwargs: _transport_result(
            ok=False,
            error='HTTP 400: {"error":"model does not support this API"} [retryable=false]',
            error_type="PROVIDER_METHOD_UNSUPPORTED",
        ),
    )

    summary = run_provider_readiness_only(goal="goal", mode="guarded_provider", model="gpt-4.1-mini", output_root=tmp_path)
    readiness = json.loads((pathlib.Path(summary["run_dir"]) / "provider_readiness.json").read_text(encoding="utf-8"))

    assert readiness["status"] == "blocked"
    assert readiness["classification"] == "PROVIDER_METHOD_UNSUPPORTED"
    assert summary["verdict"] == "BLOCKED_PROVIDER"


def test_quota_key_and_transport_classification_reuses_provider_transport(tmp_path: pathlib.Path, monkeypatch) -> None:
    _patch_credentials(monkeypatch)
    cases = [
        ("HTTP 403: Key usage limit exceeded [retryable=false]", "PROVIDER_QUOTA_EXCEEDED"),
        ("request failed: SSLError: SSLV3_ALERT_BAD_RECORD_MAC", "PROVIDER_TRANSPORT_UNSTABLE"),
    ]
    for index, (error, expected) in enumerate(cases):
        monkeypatch.setattr(
            "scripts.run_quick_large_sync_tree_benchmark.check_connectivity._post_json_with_retry",
            lambda *args, error=error, **kwargs: _transport_result(ok=False, error=error, error_type=provider_transport.classify_provider_error(error)),
        )
        summary = run_provider_readiness_only(goal="goal", mode="guarded_provider", model="gpt-4.1-mini", output_root=tmp_path / str(index))
        readiness = json.loads((pathlib.Path(summary["run_dir"]) / "provider_readiness.json").read_text(encoding="utf-8"))
        assert readiness["classification"] == expected


def test_acceptance_report_says_not_product_pass(tmp_path: pathlib.Path, monkeypatch) -> None:
    _patch_credentials(monkeypatch)
    monkeypatch.setattr(
        "scripts.run_quick_large_sync_tree_benchmark.check_connectivity._post_json_with_retry",
        lambda *args, **kwargs: _transport_result(),
    )

    summary = run_provider_readiness_only(goal="goal", mode="guarded_provider", model="gpt-4.1-mini", output_root=tmp_path)
    report = (pathlib.Path(summary["run_dir"]) / "acceptance_report.md").read_text(encoding="utf-8")

    assert "This is provider readiness only." in report
    assert "No leaf generation was started." in report
    assert "No product generation was started." in report
    assert "This is not a product PASS." in report


def test_output_path_can_be_under_generated(tmp_path: pathlib.Path, monkeypatch) -> None:
    _patch_credentials(monkeypatch)
    monkeypatch.setattr(
        "scripts.run_quick_large_sync_tree_benchmark.check_connectivity._post_json_with_retry",
        lambda *args, **kwargs: _transport_result(),
    )
    output_root = tmp_path / "generated" / "quick_large_sync_tree"

    summary = run_provider_readiness_only(goal="goal", mode="guarded_provider", model="gpt-4.1-mini", output_root=output_root)

    assert pathlib.Path(summary["run_dir"]).is_relative_to(output_root)


def test_missing_credentials_are_skipped_not_ready(tmp_path: pathlib.Path, monkeypatch) -> None:
    _patch_credentials(monkeypatch, key="", base_url="")

    summary = run_provider_readiness_only(goal="goal", mode="guarded_provider", model="gpt-4.1-mini", output_root=tmp_path)
    readiness = json.loads((pathlib.Path(summary["run_dir"]) / "provider_readiness.json").read_text(encoding="utf-8"))

    assert readiness["status"] == "skipped"
    assert readiness["classification"] == "PROVIDER_UNAVAILABLE"
    assert summary["verdict"] == "SKIPPED_PROVIDER"
