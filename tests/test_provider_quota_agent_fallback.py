from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import agent_director_loop, agent_state_observer, check_connectivity, run_commercial_readiness


QUOTA_ERROR = 'provider_api_request_failed: HTTP 403: {"error":"Key usage limit exceeded"} [endpoint=https://api.gptsapi.net, retryable=false]'


def write_quota_failure(run_dir: pathlib.Path) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "provider_semantic_review_failure.json").write_text(
        json.dumps({"status": "fail", "issues": [QUOTA_ERROR]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_api_403_key_usage_limit_is_provider_quota() -> None:
    assert check_connectivity._provider_error_type(QUOTA_ERROR) == "PROVIDER_KEY_USAGE_LIMIT"


def test_observer_classifies_provider_quota(tmp_path: pathlib.Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    write_quota_failure(run_dir)
    monkeypatch.setenv("CGNK_TEST_LOCAL_MODEL_AVAILABLE", "1")

    state = agent_state_observer.observe_run_state(run_dir)

    assert state["provider_error_code"] == "403"
    assert state["provider_error_type"] == "PROVIDER_QUOTA_EXCEEDED"
    assert state["provider_quota_exceeded"] is True
    assert state["local_model_available"] is True
    assert state["formal_generation_materialized"] is False
    assert state["writable_project_files_exist"] is False


def test_director_chooses_local_formal_generation_when_quota_and_local_available(monkeypatch) -> None:
    monkeypatch.setenv("CGNK_TEST_LOCAL_MODEL_AVAILABLE", "1")
    state = {
        "has_project_spec": True,
        "candidate_exists": False,
        "writable_project_files_exist": False,
        "formal_generation_materialized": False,
        "provider_quota_exceeded": True,
        "provider_error_type": "PROVIDER_QUOTA_EXCEEDED",
        "local_model_available": True,
        "fallback_reverify_status": "missing",
    }

    decision = agent_director_loop.deterministic_director_decide("ship", state, [])
    validation = agent_director_loop.validate_decision(decision, state)

    assert decision["selected_tool"] == "formal_generation"
    assert decision["provider_strategy"] == "local_only"
    assert validation["status"] == "pass"


def test_director_blocks_waiting_for_provider_quota_when_no_local_model() -> None:
    state = {
        "has_project_spec": True,
        "candidate_exists": False,
        "writable_project_files_exist": False,
        "formal_generation_materialized": False,
        "provider_quota_exceeded": True,
        "provider_error_type": "PROVIDER_QUOTA_EXCEEDED",
        "local_model_available": False,
        "fallback_reverify_status": "missing",
    }

    decision = agent_director_loop.deterministic_director_decide("ship", state, [])
    validation = agent_director_loop.validate_decision(decision, state)

    assert decision["selected_tool"] == "BLOCKED"
    assert decision["reason"] == "WAITING_FOR_PROVIDER_QUOTA"
    assert validation["status"] == "blocked"


def test_quota_without_materialized_project_is_not_product_or_ux_failure(tmp_path: pathlib.Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    write_quota_failure(run_dir)
    report = run_commercial_readiness.assess_commercial_readiness(
        provider_config={"providers": [{"name": "primary", "models": {"large": "large"}, "quota_required": False}]},
        candidate_dir=tmp_path / "missing_candidate",
        run_live=False,
        run_pytest=False,
        formal_project_result={
            "status": "blocked",
            "reason": "provider_fact_blocked",
            "run_dir": str(run_dir),
            "provider_status": {"provider_quota_exceeded": True, "provider_error_type": "PROVIDER_QUOTA_EXCEEDED"},
        },
    )

    assert "provider_quota_exceeded" in report["beta_reasons"]
    assert "no_formal_generation_materialized" in report["beta_reasons"]
    assert report["product_acceptance"]["status"] == "not_evaluated"
    assert report["product_acceptance"]["missing_core_features"] == []
    assert "low_ux_score" not in report["product_acceptance"]["weak_features"]


def test_agent_led_verify_records_director_loop_used_for_quota_block(tmp_path: pathlib.Path, monkeypatch) -> None:
    run_dir = tmp_path / "work" / "run"
    write_quota_failure(run_dir)
    report = tmp_path / "agent_led_verify_report.json"
    monkeypatch.setenv("CGNK_TEST_LOCAL_MODEL_AVAILABLE", "0")

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/run_agent_led_verify.py",
            "--resume-run-dir",
            str(run_dir),
            "--work-root",
            str(tmp_path / "work"),
            "--report",
            str(report),
            "--max-steps",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    doc = json.loads(report.read_text(encoding="utf-8"))

    assert proc.returncode == 0
    assert doc["architecture_direction"] == "agent-led"
    assert doc["director_loop_used"] is True
    assert doc["state"]["provider_quota_exceeded"] is True
    assert doc["loop"]["reason"] == "WAITING_FOR_PROVIDER_QUOTA"
    assert pathlib.Path(doc["agent_decision_ledger"]).exists()
