from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import formal_model_contract
import run_local_pipeline_impl


def test_api_504_triggers_local_model_fallback_and_ledger(monkeypatch, tmp_path: pathlib.Path) -> None:
    def fake_call_text_task(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        assert task == "pipeline_planner"
        return {
            "ok": True,
            "provider": "ollama",
            "model": "qwen2.5:7b-instruct",
            "text": '{"repair":"continue formal chain"}',
        }

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_call_text_task)
    error = (
        "component runtime_execution provider_api_request_failed after transport attempts: 3: "
        'provider_api_request_failed: HTTP 504: {"status":504} '
        '[endpoint=https://api.gptsapi.net, retryable=true, provider_headers={"cf-ray":"abc-HKG","date":"Fri, 26 Jun 2026 13:31:45 GMT","server":"cloudflare"}]'
    )

    diagnostics = run_local_pipeline_impl.write_provider_transport_blocked_failure(
        tmp_path,
        tmp_path / "requested_project",
        error,
        {"status": "pending", "selected_model": "gpt-5.5", "stage": "provider_semantic_repair"},
        [],
        None,
        failed_component="runtime_execution",
    )

    fallback = diagnostics["provider_fallback_evidence"]
    assert fallback["primary_provider"] == "api_agent"
    assert fallback["primary_status"] == "failed_504"
    assert fallback["fallback_provider"] == "local_model_router"
    assert fallback["fallback_status"] == "ok"
    assert fallback["formal_chain_continued"] is True
    assert fallback["requires_reverify"] is True

    records = formal_model_contract.read_ledger(tmp_path)
    assert any(row["provider"] == "api_agent" and row["status"] == "timeout" for row in records)
    assert any(row["provider"] == "local_model_router" and row["status"] == "ok" for row in records)
    assert formal_model_contract.evaluate_model_participation(
        context="repair",
        run_dir=tmp_path,
        usage_plan={"requires_model": True, "uses_model": True},
    )["status"] == "pass"
