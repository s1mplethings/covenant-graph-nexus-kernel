from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import agent_decision_ledger, agent_director_loop, agent_tool_registry


def test_agent_director_selects_candidate_repair_before_final_promotion() -> None:
    state = {
        "candidate_exists": True,
        "semantic_review_status": "needs_rework",
        "final_project_exists": False,
        "delivery_manifest_exists": False,
        "final_bundle_exists": False,
        "fallback_reverify_status": "missing",
    }

    decision = agent_director_loop.deterministic_director_decide("ship final", state, agent_tool_registry.get_tool_registry())
    validation = agent_director_loop.validate_decision(decision, state)

    assert decision["selected_tool"] == "candidate_repair"
    assert "final_promotion" in decision["rejected_tools"]
    assert validation["status"] == "pass"


def test_agent_director_selects_final_promotion_after_semantic_pass() -> None:
    state = {
        "candidate_exists": True,
        "semantic_review_status": "pass",
        "final_project_exists": False,
        "delivery_manifest_exists": False,
        "final_bundle_exists": False,
        "fallback_reverify_status": "missing",
    }

    decision = agent_director_loop.deterministic_director_decide("ship final", state, agent_tool_registry.get_tool_registry())
    validation = agent_director_loop.validate_decision(decision, state)

    assert decision["selected_tool"] == "final_promotion"
    assert validation["status"] == "pass"


def test_agent_director_cannot_bypass_evidence_gate_for_commercial_readiness() -> None:
    state = {
        "candidate_exists": True,
        "semantic_review_status": "pass",
        "final_project_exists": True,
        "delivery_manifest_exists": False,
        "final_bundle_exists": False,
        "public_gate_status": "missing",
        "fallback_reverify_status": "missing",
    }
    decision = {
        "selected_tool": "commercial_readiness",
        "reason": "fake director tried to skip delivery evidence",
        "rejected_tools": [],
    }

    validation = agent_director_loop.validate_decision(decision, state)

    assert validation["status"] == "fail"
    assert validation["reason"] in {"tool_not_allowed_for_state", "evidence_gate_missing"}
    assert "delivery_manifest_exists" in validation["missing_conditions"]
    assert "final_bundle_exists" in validation["missing_conditions"]


def test_agent_director_rejects_promotion_package_screenshot_without_writable_files() -> None:
    state = {
        "candidate_exists": True,
        "semantic_review_status": "pass",
        "final_project_exists": True,
        "delivery_manifest_exists": True,
        "final_bundle_exists": True,
        "public_gate_status": "READY",
        "fallback_reverify_status": "missing",
        "writable_project_files_exist": False,
        "screenshot_evidence_exists": True,
    }

    for selected in ("final_promotion", "delivery_manifest_build", "screenshot_capture"):
        validation = agent_director_loop.validate_decision({"selected_tool": selected}, state)
        assert validation["status"] == "fail"
        assert validation["reason"] == "writable_project_files_missing"


def test_agent_director_loop_writes_failed_decision_ledger(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "candidate_project").mkdir(parents=True)
    (run_dir / "artifacts").mkdir()
    (run_dir / "artifacts" / "semantic_review_result.json").write_text('{"status":"pass"}\n', encoding="utf-8")

    def fake_director(goal, state, registry):
        return {
            "agent_role": "Project Director",
            "observed_state_hash": agent_decision_ledger.observed_state_hash(state),
            "observed_state_summary": agent_director_loop.state_summary(state),
            "goal": goal,
            "decision": "run_commercial_readiness",
            "selected_tool": "commercial_readiness",
            "rejected_tools": ["final_promotion"],
            "reason": "fake director tried to skip final delivery evidence",
            "expected_outputs": ["commercial_readiness_report"],
            "status": "planned",
            "result_refs": [],
        }

    result = agent_director_loop.run_director_loop(run_dir, goal="ship final", director=fake_director, max_steps=1)
    rows = agent_decision_ledger.read_decision_ledger(run_dir)

    assert result["status"] == "blocked"
    assert rows[0]["selected_tool"] == "commercial_readiness"
    assert rows[0]["status"] == "failed"
    assert rows[0]["reason"]
