from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import agent_decision_ledger


def test_agent_decision_ledger_writes_decision(tmp_path: pathlib.Path) -> None:
    state = {"candidate_exists": True, "semantic_review_status": "needs_rework", "final_project_exists": False}
    decision = {
        "agent_role": "Project Director",
        "observed_state_hash": agent_decision_ledger.observed_state_hash(state),
        "observed_state_summary": state,
        "goal": "produce commercially acceptable final project",
        "decision": "run_candidate_repair",
        "selected_tool": "candidate_repair",
        "rejected_tools": ["final_promotion", "package_builder"],
        "reason": "candidate exists but semantic review is needs_rework, so promotion is not allowed",
        "expected_outputs": ["repair_report", "updated_candidate_project_dir"],
    }

    path = agent_decision_ledger.append_decision(
        tmp_path / "run",
        decision,
        {"status": "executed", "artifacts": ["repair_report.json"]},
    )
    rows = agent_decision_ledger.read_decision_ledger(tmp_path / "run")

    assert path.exists()
    assert rows[0]["selected_tool"] == "candidate_repair"
    assert rows[0]["reason"]
    assert rows[0]["rejected_tools"]
    assert rows[0]["result_refs"] == ["repair_report.json"]
