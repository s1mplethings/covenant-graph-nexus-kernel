from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_agent_autonomous_diagnosis


def test_diagnosis_report_schema_contains_required_fields(tmp_path: pathlib.Path) -> None:
    observed = {
        "latest_reports": {"agent_led_verify": "verify.json"},
        "latest_report_status": {"agent_led_verify": "pass", "large_project_benchmark": "pass"},
        "quality": {"commercial_status": "COMMERCIAL_READY"},
    }
    diagnosis = {
        "status": "pass",
        "problem_type": "NO_ISSUE_DETECTED",
        "confidence": 0.91,
        "evidence_refs": ["verify.json"],
        "why_this_problem": "all current evidence passes",
        "why_not_other_problems": [],
        "selected_tool": "stability_rerun",
        "rejected_tools": [],
        "remaining_blockers": [],
    }

    report = run_agent_autonomous_diagnosis.build_report(
        run_dir=tmp_path / "run",
        report_path=tmp_path / "agent_autonomous_diagnosis_report.json",
        observed_state=observed,
        diagnosis=diagnosis,
        decision_ledger=tmp_path / "run" / "artifacts" / "agent_decision_ledger.jsonl",
        actions_taken=[],
        tests_run=[],
        test_results=[],
        files_modified=[],
    )

    for key in (
        "status",
        "problem_type",
        "confidence",
        "evidence_refs",
        "observed_state",
        "latest_reports",
        "selected_tool",
        "rejected_tools",
        "decision_ledger",
        "actions_taken",
        "files_modified",
        "tests_run",
        "test_results",
        "post_fix_verify",
        "remaining_blockers",
    ):
        assert key in report
    assert report["post_fix_verify"]["agent_led_verify"] == "pass"
    assert report["post_fix_verify"]["commercial_status"] == "COMMERCIAL_READY"
