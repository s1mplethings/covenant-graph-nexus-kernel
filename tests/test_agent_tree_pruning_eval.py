from __future__ import annotations

import json
import pathlib
import zipfile

from scripts.run_agent_tree_pruning_eval import run_eval


def test_pruning_eval_covers_all_required_control_cases(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "agent_tree_pruning_eval" / "run_001"
    report = run_eval(out)
    final = json.loads((out / "final_verdict.json").read_text(encoding="utf-8"))

    assert report["verdict"] == "PASS"
    assert final["verdict"] == "PASS"
    assert final["event_count"] == 5
    assert final["replacement_merge_verdict"] == "PASS"
    assert final["delivery_executed"] is False
    assert final["production_mainline"] == "not_connected"
    assert {case["verdict"] for case in report["cases"]} == {"PASS"}


def test_pruning_eval_trace_bundle_is_complete(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "agent_tree_pruning_eval" / "run_001"
    report = run_eval(out)
    bundle = pathlib.Path(report["trace_bundle"]["path"])

    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
    assert {
        "00_INDEX.md",
        "failure_classifications.jsonl",
        "pruning_events.jsonl",
        "upward_signals.jsonl",
        "branch_replans.jsonl",
        "agent_tree_registry_before.json",
        "agent_tree_registry_after.json",
        "final_verdict.json",
    } <= names
    assert any(name.startswith("checkpoints/") for name in names)
    assert any(name.startswith("merge_results/") for name in names)


def test_scope_violation_does_not_write_forbidden_file(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "agent_tree_pruning_eval" / "run_001"
    run_eval(out)

    assert not (out / "scope_project" / "README.md").exists()
