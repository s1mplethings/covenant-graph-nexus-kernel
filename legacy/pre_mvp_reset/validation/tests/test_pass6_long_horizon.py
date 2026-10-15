from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from scripts import pass6_blind_evaluator
from scripts import build_pass6_evidence_bundle as evidence_bundle
from scripts import run_pass6_long_horizon as pass6


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_prompt_identity_is_content_bound_not_case_metadata() -> None:
    visible = {
        "case_id": "one",
        "title": "first",
        "visible_user_goal": "Build the requested tool",
        "allowed_assumptions": ["offline"],
        "constraints": ["preserve data"],
    }
    renamed = {**visible, "case_id": "two", "title": "second", "source_path": "changed/path"}
    revised = {**visible, "visible_user_goal": "Build a different requested tool"}
    assert pass6.prompt_hash(visible) == pass6.prompt_hash(renamed)
    assert pass6.prompt_hash(visible) != pass6.prompt_hash(revised)


def test_frozen_cases_are_separated_and_contamination_checks_pass(tmp_path: Path) -> None:
    frozen = pass6.freeze_blind_cases(tmp_path)
    result = pass6.contamination_validation(tmp_path, frozen)
    assert frozen["manifest"]["case_count"] == 25
    assert frozen["manifest"]["difficulty_counts"] == {"L1": 5, "L2": 5, "L3": 6, "L4": 5, "L5": 4}
    assert result["status"] == "PASS"
    workspace_files = [path.relative_to(tmp_path / "contamination_probe" / "generation_workspace").as_posix() for path in (tmp_path / "contamination_probe" / "generation_workspace").rglob("*") if path.is_file()]
    assert workspace_files == ["request.json"]


def test_incomplete_run_cannot_be_promoted_to_soak_pass(tmp_path: Path) -> None:
    started = datetime.now(timezone.utc)
    _write_jsonl(
        tmp_path / "SOAK_EVENTS.jsonl",
        [
            {"at": started.isoformat(), "event": "planned", "task_id": "p1"},
            {"at": (started + timedelta(seconds=1)).isoformat(), "event": "completed", "task_id": "p1", "accepted": True, "latency_seconds": 0.5},
        ],
    )
    _write_jsonl(
        tmp_path / "RESOURCE_EVENTS.jsonl",
        [
            {"at": started.isoformat(), "monotonic": 1.0, "rss_bytes": 10, "handle_count": 2, "disk_bytes": 3, "queue_depth": 0, "retry_count": 0, "recovery_count": 0, "active_workers": 0},
            {"at": (started + timedelta(seconds=2)).isoformat(), "monotonic": 3.0, "rss_bytes": 10, "handle_count": 2, "disk_bytes": 4, "queue_depth": 0, "retry_count": 0, "recovery_count": 0, "active_workers": 0},
        ],
    )
    (tmp_path / "profile_summary.json").write_text(
        json.dumps({"elapsed_seconds": 2, "configuration": {"requested_duration_seconds": 2}, "accounting": {"planned": 1, "rejected": 0, "cancelled": 0, "timed_out": 0, "failed": 0, "completed": 1, "independent_acceptance_passed": 1, "independent_acceptance_failed": 0, "duplicate_delivery_count": 0}, "status": "PASS"}),
        encoding="utf-8",
    )
    result = pass6.analyze_run(tmp_path, 2)
    assert result["status"] == "NOT_EVALUATED"
    assert result["workflow_state"] == "incomplete"
    assert result["gates"]["continuous_24h"] is False


def test_hidden_evaluator_runs_only_against_candidate(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("candidate", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('PASS')\n", encoding="utf-8")
    hidden = {"case_id": "case", "required_files": ["README.md", "main.py"], "probes": [{"argv": [pass6.sys.executable, "main.py"], "stdout_contains": "PASS", "returncode": 0}]}
    assert pass6_blind_evaluator.evaluate(tmp_path, hidden)["status"] == "PASS"
    hidden["required_files"].append("missing.txt")
    assert pass6_blind_evaluator.evaluate(tmp_path, hidden)["status"] == "FAIL"


def test_evidence_redaction_removes_plain_and_json_escaped_user_paths() -> None:
    payload = b'{"plain":"C:\\\\Users\\\\private-user\\\\file", "escaped":"C:\\\\\\\\Users\\\\\\\\private-user\\\\\\\\file"}'
    redacted = evidence_bundle.redact(payload).lower()
    assert b"private-user" not in redacted
    assert b"<user_home>" in redacted
