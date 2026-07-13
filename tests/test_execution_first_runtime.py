from __future__ import annotations

import hashlib
import json
import pathlib
import zipfile

import pytest

from scripts.execution_first_runtime import (
    EvidenceLedger,
    TaskLedger,
    apply_replan,
    package_order_gate,
    public_ui_journey_gate,
    save_checkpoint,
    screenshot_integrity,
    verify_recovery_new_process,
)


def _full_task_lifecycle(task: TaskLedger, task_id: str, evidence_ref: str) -> None:
    task.create_task(task_id=task_id, agent_id="agent", branch_id="branch")
    transitions = [
        ("planned", "ready"),
        ("ready", "assigned"),
        ("assigned", "running"),
        ("running", "result_submitted"),
        ("result_submitted", "testing"),
        ("testing", "review_pending"),
    ]
    for previous, new in transitions:
        task.append_event(task_id=task_id, previous_status=previous, new_status=new, agent_id="agent", branch_id="branch", reason_code="progress", evidence_refs=[evidence_ref])
    task.complete_task(task_id=task_id, current_status="review_pending", agent_id="agent", branch_id="branch", test_evidence=evidence_ref, review_evidence=evidence_ref)


def test_planned_cannot_jump_to_completed(tmp_path: pathlib.Path) -> None:
    ledger = TaskLedger(tmp_path / "task_ledger.jsonl")
    ledger.create_task(task_id="task_a", agent_id="agent", branch_id="branch")

    with pytest.raises(ValueError):
        ledger.append_event(task_id="task_a", previous_status="planned", new_status="completed", agent_id="agent", branch_id="branch", reason_code="bad")


def test_completed_metrics_are_replayed_from_ledger(tmp_path: pathlib.Path) -> None:
    evidence_file = tmp_path / "evidence.txt"
    evidence_file.write_text("ok", encoding="utf-8")
    ledger = TaskLedger(tmp_path / "task_ledger.jsonl")

    _full_task_lifecycle(ledger, "task_a", str(evidence_file))
    replay = ledger.replay()

    assert replay["completed"] == 1
    assert replay["status_distribution"]["completed"] == 1
    assert replay["illegal_transition_count"] == 0
    assert replay["completion_without_test_review"] == 0


def test_test_failure_requires_repair_before_completion(tmp_path: pathlib.Path) -> None:
    ledger = TaskLedger(tmp_path / "task_ledger.jsonl")
    ledger.create_task(task_id="task_a", agent_id="agent", branch_id="branch")
    for previous, new in [
        ("planned", "ready"),
        ("ready", "assigned"),
        ("assigned", "running"),
        ("running", "result_submitted"),
        ("result_submitted", "testing"),
        ("testing", "test_failed"),
    ]:
        ledger.append_event(task_id="task_a", previous_status=previous, new_status=new, agent_id="agent", branch_id="branch", reason_code="progress")

    with pytest.raises(ValueError):
        ledger.complete_task(task_id="task_a", current_status="test_failed", agent_id="agent", branch_id="branch", test_evidence="test", review_evidence="review")

    ledger.append_event(task_id="task_a", previous_status="test_failed", new_status="repair_created", agent_id="agent", branch_id="branch", reason_code="nearest_test_failed")
    ledger.append_event(task_id="task_a", previous_status="repair_created", new_status="repair_running", agent_id="repair", branch_id="branch", reason_code="repair")
    ledger.append_event(task_id="task_a", previous_status="repair_running", new_status="reverify_pending", agent_id="repair", branch_id="branch", reason_code="repair")
    ledger.append_event(task_id="task_a", previous_status="reverify_pending", new_status="testing", agent_id="repair", branch_id="branch", reason_code="reverify")
    ledger.append_event(task_id="task_a", previous_status="testing", new_status="review_pending", agent_id="repair", branch_id="branch", reason_code="reverify_passed")
    ledger.complete_task(task_id="task_a", current_status="review_pending", agent_id="repair", branch_id="branch", test_evidence="test", review_evidence="review")

    assert ledger.replay()["retried"] == 3


def test_evidence_refs_must_exist(tmp_path: pathlib.Path) -> None:
    evidence = EvidenceLedger(tmp_path / "evidence_ledger.jsonl", root=tmp_path)
    ok_file = tmp_path / "ok.txt"
    ok_file.write_text("ok", encoding="utf-8")
    evidence.append(task_id="task_a", event_type="test_result", source="pytest", artifact_refs=["ok.txt"])
    evidence.append(task_id="task_a", event_type="review_finding", source="reviewer", artifact_refs=["missing.txt"])

    report = evidence.validate_refs()

    assert report["status"] == "NEEDS_REWORK"
    assert report["missing_count"] == 1


def test_gui_project_cannot_pass_api_only_journey(tmp_path: pathlib.Path) -> None:
    evidence = EvidenceLedger(tmp_path / "evidence_ledger.jsonl", root=tmp_path, run_id="run_gui")
    evidence.append(task_id="journey", event_type="user_action", source="journey", data={"channel": "api", "action": "create"})
    evidence.append(task_id="journey", event_type="state_after", source="journey", data={"changed": True})

    report = public_ui_journey_gate(evidence.rows(), project_type="web")

    assert report["status"] == "NEEDS_REWORK"
    assert "api_only_journey_for_gui" in report["reasons"]


def test_screenshot_integrity_requires_same_run_and_unique_hashes(tmp_path: pathlib.Path) -> None:
    evidence = EvidenceLedger(tmp_path / "evidence_ledger.jsonl", root=tmp_path, run_id="run_a")
    digest = hashlib.sha256(b"same").hexdigest()
    evidence.append(task_id="ui", event_type="screenshot_captured", source="browser", hashes={"sha256": digest})
    evidence.append(task_id="ui", event_type="screenshot_captured", source="browser", hashes={"sha256": digest})

    report = screenshot_integrity(evidence.rows(), require_same_run="run_a")

    assert report["status"] == "NEEDS_REWORK"
    assert report["duplicate_screenshots"] == 1


def test_package_order_requires_acceptance_before_package_and_no_nested_zip(tmp_path: pathlib.Path) -> None:
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("old/final_project_bundle.zip", b"nested")
    evidence = EvidenceLedger(tmp_path / "evidence_ledger.jsonl", root=tmp_path)
    evidence.append(task_id="delivery", event_type="package_created", source="packager", artifact_refs=[str(bundle)])
    evidence.append(task_id="delivery", event_type="test_result", source="pytest")

    report = package_order_gate(evidence.rows(), bundle)

    assert report["status"] == "NEEDS_REWORK"
    assert "screenshot_captured" in report["missing_before_package"]
    assert report["nested_zip"] == ["old/final_project_bundle.zip"]


def test_replan_creates_real_new_tasks_in_ledger(tmp_path: pathlib.Path) -> None:
    evidence_file = tmp_path / "stall.json"
    evidence_file.write_text(json.dumps({"same_failure": 2}), encoding="utf-8")
    task = TaskLedger(tmp_path / "task_ledger.jsonl")
    _full_task_lifecycle(task, "blocked", str(evidence_file))
    # Replace final completed state with a realistic failed-review task in a fresh ledger.
    task = TaskLedger(tmp_path / "replan_task_ledger.jsonl")
    task.create_task(task_id="blocked", agent_id="agent", branch_id="branch")
    for previous, new in [
        ("planned", "ready"),
        ("ready", "assigned"),
        ("assigned", "running"),
        ("running", "result_submitted"),
        ("result_submitted", "testing"),
        ("testing", "review_pending"),
        ("review_pending", "review_failed"),
    ]:
        task.append_event(task_id="blocked", previous_status=previous, new_status=new, agent_id="agent", branch_id="branch", reason_code="progress")

    result = apply_replan(task, blocked_task_id="blocked", new_task_ids=["split_a", "split_b"], agent_id="pm", branch_id="branch", evidence_ref=str(evidence_file))

    replay = task.replay()
    assert result["new_task_count"] == 2
    assert replay["status_by_task"]["split_a"] == "planned"
    assert replay["status_by_task"]["split_b"] == "planned"


def test_recovery_uses_new_process_and_replays_ledger(tmp_path: pathlib.Path) -> None:
    evidence_file = tmp_path / "test.txt"
    evidence_file.write_text("ok", encoding="utf-8")
    task = TaskLedger(tmp_path / "task_ledger.jsonl")
    evidence = EvidenceLedger(tmp_path / "evidence_ledger.jsonl", root=tmp_path)
    evidence.append(task_id="task_a", event_type="test_result", source="pytest", artifact_refs=["test.txt"])
    _full_task_lifecycle(task, "task_a", str(evidence_file))
    checkpoint = tmp_path / "checkpoint.json"
    save_checkpoint(checkpoint, task, evidence)

    report = verify_recovery_new_process(checkpoint)

    assert report["status"] == "PASS"
    assert report["restored"]["replay"]["completed"] == 1
