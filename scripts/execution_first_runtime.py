from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from typing import Any


TASK_STATUSES = {
    "proposed",
    "planned",
    "dependency_blocked",
    "ready",
    "assigned",
    "running",
    "result_submitted",
    "testing",
    "test_failed",
    "review_pending",
    "review_failed",
    "repair_created",
    "repair_running",
    "reverify_pending",
    "completed",
    "externally_blocked",
    "cancelled",
}

ALLOWED_TRANSITIONS = {
    "proposed": {"planned", "cancelled"},
    "planned": {"dependency_blocked", "ready", "cancelled"},
    "dependency_blocked": {"ready", "cancelled"},
    "ready": {"assigned", "cancelled"},
    "assigned": {"running", "externally_blocked", "cancelled"},
    "running": {"result_submitted", "externally_blocked", "cancelled"},
    "result_submitted": {"testing", "review_pending"},
    "testing": {"test_failed", "review_pending"},
    "test_failed": {"repair_created", "externally_blocked", "cancelled"},
    "review_pending": {"review_failed", "completed"},
    "review_failed": {"repair_created", "cancelled"},
    "repair_created": {"repair_running", "cancelled"},
    "repair_running": {"reverify_pending", "externally_blocked", "cancelled"},
    "reverify_pending": {"testing", "review_pending"},
    "completed": set(),
    "externally_blocked": {"ready", "cancelled"},
    "cancelled": set(),
}

EVIDENCE_TYPES = {
    "execution_started",
    "file_changed",
    "command_run",
    "test_result",
    "provider_request",
    "provider_response",
    "local_model_request",
    "local_model_response",
    "review_finding",
    "finding_confirmed",
    "repair_result",
    "screenshot_captured",
    "user_action",
    "state_before",
    "state_after",
    "checkpoint_saved",
    "process_stopped",
    "process_restored",
    "package_created",
    "clean_start_result",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def append_jsonl(path: pathlib.Path, doc: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
    return doc


def read_jsonl(path: str | pathlib.Path) -> list[dict[str, Any]]:
    p = pathlib.Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class EvidenceLedger:
    def __init__(self, path: str | pathlib.Path, *, root: str | pathlib.Path | None = None, run_id: str = "run", project_id: str = "project") -> None:
        self.path = pathlib.Path(path)
        self.root = pathlib.Path(root).resolve() if root else self.path.parent.resolve()
        self.run_id = run_id
        self.project_id = project_id

    def append(
        self,
        *,
        task_id: str,
        event_type: str,
        source: str,
        artifact_refs: list[str] | None = None,
        hashes: dict[str, str] | None = None,
        result_classification: str = "PASS",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if event_type not in EVIDENCE_TYPES:
            raise ValueError(f"unsupported evidence event_type: {event_type}")
        refs = list(artifact_refs or [])
        event = {
            "evidence_id": stable_id(
                "evidence",
                {
                    "run_id": self.run_id,
                    "task_id": task_id,
                    "event_type": event_type,
                    "source": source,
                    "timestamp": time.time_ns(),
                },
            ),
            "run_id": self.run_id,
            "project_id": self.project_id,
            "task_id": task_id,
            "event_type": event_type,
            "source": source,
            "timestamp": utc_now(),
            "artifact_refs": refs,
            "hashes": hashes or {},
            "result_classification": result_classification,
            "data": data or {},
        }
        return append_jsonl(self.path, event)

    def rows(self) -> list[dict[str, Any]]:
        return read_jsonl(self.path)

    def validate_refs(self) -> dict[str, Any]:
        missing: list[dict[str, str]] = []
        for row in self.rows():
            for ref in row.get("artifact_refs", []):
                path = pathlib.Path(str(ref))
                resolved = path if path.is_absolute() else self.root / path
                if not resolved.exists():
                    missing.append({"evidence_id": str(row.get("evidence_id", "")), "ref": str(ref)})
        return {"status": "PASS" if not missing else "NEEDS_REWORK", "missing": missing, "missing_count": len(missing)}


class TaskLedger:
    def __init__(self, path: str | pathlib.Path, *, run_id: str = "run", project_id: str = "project") -> None:
        self.path = pathlib.Path(path)
        self.run_id = run_id
        self.project_id = project_id

    def append_event(
        self,
        *,
        task_id: str,
        previous_status: str,
        new_status: str,
        agent_id: str,
        branch_id: str,
        reason_code: str,
        evidence_refs: list[str] | None = None,
        provider_request_ids: list[str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        previous = str(previous_status)
        new = str(new_status)
        if previous not in TASK_STATUSES:
            raise ValueError(f"invalid previous_status: {previous}")
        if new not in TASK_STATUSES:
            raise ValueError(f"invalid new_status: {new}")
        if new not in ALLOWED_TRANSITIONS[previous]:
            raise ValueError(f"illegal task transition: {previous}->{new}")
        event = {
            "event_id": stable_id("task_event", {"run_id": self.run_id, "task_id": task_id, "previous": previous, "new": new, "timestamp": time.time_ns()}),
            "run_id": self.run_id,
            "project_id": self.project_id,
            "task_id": task_id,
            "previous_status": previous,
            "new_status": new,
            "agent_id": agent_id,
            "branch_id": branch_id,
            "reason_code": reason_code,
            "evidence_refs": list(evidence_refs or []),
            "provider_request_ids": list(provider_request_ids or []),
            "timestamp": utc_now(),
            "data": data or {},
        }
        return append_jsonl(self.path, event)

    def create_task(self, *, task_id: str, agent_id: str, branch_id: str, reason_code: str = "task_created") -> dict[str, Any]:
        return self.append_event(task_id=task_id, previous_status="proposed", new_status="planned", agent_id=agent_id, branch_id=branch_id, reason_code=reason_code)

    def complete_task(
        self,
        *,
        task_id: str,
        current_status: str,
        agent_id: str,
        branch_id: str,
        test_evidence: str,
        review_evidence: str,
        provider_request_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if current_status != "review_pending":
            raise ValueError("tasks can complete only from review_pending")
        return self.append_event(
            task_id=task_id,
            previous_status=current_status,
            new_status="completed",
            agent_id=agent_id,
            branch_id=branch_id,
            reason_code="test_and_review_passed",
            evidence_refs=[test_evidence, review_evidence],
            provider_request_ids=provider_request_ids,
        )

    def rows(self) -> list[dict[str, Any]]:
        return read_jsonl(self.path)

    def replay(self) -> dict[str, Any]:
        rows = self.rows()
        status_by_task: dict[str, str] = {}
        events_by_task: dict[str, list[dict[str, Any]]] = {}
        illegal: list[dict[str, Any]] = []
        duplicate_running = 0
        completion_without_test_review = 0
        for row in rows:
            task_id = str(row.get("task_id", ""))
            previous = str(row.get("previous_status", ""))
            new = str(row.get("new_status", ""))
            if previous not in TASK_STATUSES or new not in TASK_STATUSES or new not in ALLOWED_TRANSITIONS[previous]:
                illegal.append(row)
            if task_id in status_by_task and status_by_task[task_id] != previous:
                illegal.append({**row, "reason": f"ledger_replay_expected_{status_by_task[task_id]}"})
            if new == "running" and any(event.get("new_status") == "running" for event in events_by_task.get(task_id, [])):
                duplicate_running += 1
            if new == "completed":
                refs = [str(ref) for ref in row.get("evidence_refs", [])]
                if len(refs) < 2:
                    completion_without_test_review += 1
            status_by_task[task_id] = new
            events_by_task.setdefault(task_id, []).append(row)
        distribution: dict[str, int] = {}
        for status in status_by_task.values():
            distribution[status] = distribution.get(status, 0) + 1
        return {
            "status_by_task": status_by_task,
            "status_distribution": distribution,
            "completed": distribution.get("completed", 0),
            "failed": distribution.get("test_failed", 0) + distribution.get("review_failed", 0),
            "blocked": distribution.get("dependency_blocked", 0) + distribution.get("externally_blocked", 0),
            "retried": len([row for row in rows if str(row.get("new_status")) in {"repair_created", "repair_running", "reverify_pending"}]),
            "dependency_violations": len([row for row in illegal if row.get("reason_code") == "dependency_violation"]),
            "ownership_conflicts": len([row for row in illegal if row.get("reason_code") == "ownership_conflict"]),
            "duplicate_executions": duplicate_running,
            "illegal_transition_count": len(illegal),
            "completion_without_test_review": completion_without_test_review,
            "illegal_events": illegal,
        }


def screenshot_integrity(rows: list[dict[str, Any]], *, require_same_run: str | None = None) -> dict[str, Any]:
    screenshot_rows = [row for row in rows if row.get("event_type") == "screenshot_captured"]
    hashes: dict[str, int] = {}
    empty = 0
    wrong_run = 0
    for row in screenshot_rows:
        if require_same_run and row.get("run_id") != require_same_run:
            wrong_run += 1
        h = str((row.get("hashes") or {}).get("sha256", ""))
        if h:
            hashes[h] = hashes.get(h, 0) + 1
        if row.get("result_classification") in {"EMPTY", "BLANK", "DUPLICATE"}:
            empty += 1
    duplicates = sum(count - 1 for count in hashes.values() if count > 1)
    status = "PASS" if screenshot_rows and duplicates == 0 and empty == 0 and wrong_run == 0 else "NEEDS_REWORK"
    return {"status": status, "unique_screenshots": len(hashes), "duplicate_screenshots": duplicates, "empty_screenshots": empty, "wrong_run_screenshots": wrong_run}


def public_ui_journey_gate(rows: list[dict[str, Any]], *, project_type: str) -> dict[str, Any]:
    is_gui = project_type.lower() in {"gui", "web", "desktop", "browser"}
    user_actions = [row for row in rows if row.get("event_type") == "user_action"]
    api_only = is_gui and user_actions and all((row.get("data") or {}).get("channel") == "api" for row in user_actions)
    state_changes = [row for row in rows if row.get("event_type") == "state_after" and (row.get("data") or {}).get("changed") is True]
    screenshot = [row for row in rows if row.get("event_type") == "screenshot_captured"]
    status = "PASS"
    reasons: list[str] = []
    if is_gui and api_only:
        status = "NEEDS_REWORK"
        reasons.append("api_only_journey_for_gui")
    if is_gui and not screenshot:
        status = "NEEDS_REWORK"
        reasons.append("missing_screenshot")
    if user_actions and not state_changes:
        status = "NEEDS_REWORK"
        reasons.append("no_state_change")
    return {"status": status, "api_only": api_only, "user_actions": len(user_actions), "state_changes": len(state_changes), "screenshots": len(screenshot), "reasons": reasons}


def package_order_gate(rows: list[dict[str, Any]], bundle: str | pathlib.Path | None = None) -> dict[str, Any]:
    index = {row.get("event_type"): i for i, row in enumerate(rows)}
    package_index = index.get("package_created")
    required_before = ["test_result", "screenshot_captured", "review_finding"]
    missing = [item for item in required_before if item not in index]
    out_of_order = [item for item in required_before if package_index is not None and item in index and index[item] > package_index]
    nested_zip: list[str] = []
    if bundle:
        bundle_path = pathlib.Path(bundle)
        if bundle_path.exists() and bundle_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(bundle_path) as zf:
                nested_zip = [name for name in zf.namelist() if name.lower().endswith(".zip")]
    status = "PASS" if package_index is not None and not missing and not out_of_order and not nested_zip else "NEEDS_REWORK"
    return {"status": status, "missing_before_package": missing, "out_of_order": out_of_order, "nested_zip": nested_zip}


def apply_replan(task_ledger: TaskLedger, *, blocked_task_id: str, new_task_ids: list[str], agent_id: str, branch_id: str, evidence_ref: str) -> dict[str, Any]:
    task_ledger.append_event(task_id=blocked_task_id, previous_status="review_failed", new_status="repair_created", agent_id=agent_id, branch_id=branch_id, reason_code="double_loop_replan_trigger", evidence_refs=[evidence_ref])
    created = []
    for task_id in new_task_ids:
        task_ledger.create_task(task_id=task_id, agent_id=agent_id, branch_id=branch_id, reason_code="double_loop_replan_new_task")
        created.append(task_id)
    return {"status": "PASS", "new_task_count": len(created), "new_tasks": created, "cancelled_or_replaced": [blocked_task_id]}


def save_checkpoint(path: str | pathlib.Path, task_ledger: TaskLedger, evidence_ledger: EvidenceLedger, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    checkpoint = {
        "created_at": utc_now(),
        "task_ledger": str(task_ledger.path),
        "evidence_ledger": str(evidence_ledger.path),
        "task_offset": len(task_ledger.rows()),
        "evidence_offset": len(evidence_ledger.rows()),
        "replay": task_ledger.replay(),
        "extra": extra or {},
    }
    write_json(pathlib.Path(path), checkpoint)
    return checkpoint


def restore_checkpoint(path: str | pathlib.Path) -> dict[str, Any]:
    checkpoint = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    task = TaskLedger(checkpoint["task_ledger"])
    evidence = EvidenceLedger(checkpoint["evidence_ledger"])
    return {
        "status": "PASS",
        "checkpoint": checkpoint,
        "replay": task.replay(),
        "evidence_refs": evidence.validate_refs(),
    }


def verify_recovery_new_process(checkpoint_path: str | pathlib.Path) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, __file__, "restore", str(checkpoint_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        restored = json.loads(proc.stdout)
    except Exception:
        restored = {}
    return {
        "status": "PASS" if proc.returncode == 0 and restored.get("status") == "PASS" else "NEEDS_REWORK",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
        "restored": restored,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["restore"])
    parser.add_argument("checkpoint")
    args = parser.parse_args()
    if args.command == "restore":
        print(json.dumps(restore_checkpoint(args.checkpoint), ensure_ascii=False, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
