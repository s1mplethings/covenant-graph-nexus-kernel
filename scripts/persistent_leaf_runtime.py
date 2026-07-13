from __future__ import annotations

import json
import pathlib
import subprocess
import hashlib
from datetime import datetime, timezone
from typing import Any, Callable

try:
    import leaf_workspace_manager
    import patch_merge_manager
    import product_candidate_manager
except Exception:  # pragma: no cover
    from scripts import leaf_workspace_manager, patch_merge_manager, product_candidate_manager  # type: ignore


LEAF_SESSION_STATUSES = {
    "created",
    "workspace_ready",
    "context_loaded",
    "inspecting",
    "short_plan_created",
    "implementation_started",
    "implementing",
    "file_changed",
    "nearest_test_started",
    "testing",
    "nearest_test_result",
    "test_failed",
    "repairing",
    "peer_waiting",
    "peer_response_received",
    "result_ready",
    "review_pending",
    "accepted",
    "rejected",
    "checkpoint_saved",
    "timed_out",
    "externally_blocked",
    "cancelled",
}

LEAF_PROFILES = {
    "micro": {"max_files": 2, "api_budget": 2, "minutes": 10, "checkpoint_required": False},
    "standard": {"max_files": 5, "api_budget": 6, "minutes": 30, "checkpoint_required": False},
    "branch": {"max_files": 12, "api_budget": 10, "minutes": 90, "checkpoint_required": True},
    "recovery": {"max_files": 5, "api_budget": 8, "minutes": 30, "checkpoint_required": True},
}


LeafAction = Callable[[pathlib.Path, dict[str, Any]], dict[str, Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: pathlib.Path, doc: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
    return doc


def file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class PersistentLeafRuntime:
    def __init__(self, run_dir: str | pathlib.Path, *, run_id: str) -> None:
        self.run_dir = pathlib.Path(run_dir).resolve()
        self.run_id = run_id
        self.workspace_manager = leaf_workspace_manager.LeafWorkspaceManager(self.run_dir / "leaf_runs", run_id=run_id)
        self.merge_manager = patch_merge_manager.PatchMergeManager(self.run_dir / "merge_events.jsonl")
        self.session_events = self.run_dir / "leaf_session_events.jsonl"
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def record(self, *, leaf_id: str, task_id: str, previous_status: str, new_status: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        if previous_status not in LEAF_SESSION_STATUSES or new_status not in LEAF_SESSION_STATUSES:
            raise ValueError("invalid leaf session status")
        return append_jsonl(
            self.session_events,
            {
                "created_at": utc_now(),
                "run_id": self.run_id,
                "leaf_id": leaf_id,
                "task_id": task_id,
                "previous_status": previous_status,
                "new_status": new_status,
                "data": data or {},
            },
        )

    def run_leaf(
        self,
        *,
        leaf_id: str,
        task_id: str,
        candidate_dir: str | pathlib.Path,
        task_contract: dict[str, Any],
        context_packet: dict[str, Any] | None,
        allowed_files: list[str],
        action: LeafAction,
        nearest_test_command: str = "",
        profile: str = "standard",
        merge: bool = True,
    ) -> dict[str, Any]:
        profile_doc = LEAF_PROFILES.get(profile, LEAF_PROFILES["standard"])
        if len(allowed_files) > int(profile_doc["max_files"]):
            return {"status": "NEEDS_REWORK", "reason": "leaf_scope_too_large", "profile": profile, "max_files": profile_doc["max_files"]}
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="created", new_status="workspace_ready")
        workspace = self.workspace_manager.create_workspace(
            leaf_id=leaf_id,
            task_id=task_id,
            candidate_dir=candidate_dir,
            task_contract={**task_contract, "allowed_files": allowed_files, "profile": profile, "api_budget": profile_doc["api_budget"]},
            context_packet=context_packet or {},
        )
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="workspace_ready", new_status="context_loaded", data={"workspace": workspace})
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="context_loaded", new_status="inspecting")
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="inspecting", new_status="short_plan_created", data={"allowed_files": allowed_files, "nearest_test": nearest_test_command})
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="short_plan_created", new_status="implementation_started")
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="implementation_started", new_status="implementing")
        workspace_path = pathlib.Path(str(workspace["workspace"]))
        try:
            action_result = action(workspace_path, {"task_contract": task_contract, "context_packet": context_packet or {}, "workspace": workspace})
        except Exception as exc:
            self.record(leaf_id=leaf_id, task_id=task_id, previous_status="implementing", new_status="externally_blocked", data={"error": str(exc)})
            return {"status": "externally_blocked", "workspace": workspace, "error": str(exc)}
        changed_files = patch_merge_manager.changed_files_between(candidate_dir, workspace_path)
        if changed_files:
            self.record(leaf_id=leaf_id, task_id=task_id, previous_status="implementing", new_status="file_changed", data={"changed_files": changed_files})
            previous_for_test = "file_changed"
        else:
            previous_for_test = "implementing"
        test_result = {"status": "NOT_EVALUATED", "command": nearest_test_command}
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status=previous_for_test, new_status="nearest_test_started", data={"command": nearest_test_command})
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="nearest_test_started", new_status="testing")
        if nearest_test_command:
            proc = subprocess.run(nearest_test_command, cwd=str(workspace_path), shell=True, capture_output=True, text=True, timeout=120)
            leaf_dir = pathlib.Path(str(workspace["leaf_dir"]))
            test_path = leaf_dir / "test_results.json"
            stdout_path = leaf_dir / "stdout.log"
            stderr_path = leaf_dir / "stderr.log"
            stdout_path.write_text(proc.stdout, encoding="utf-8", errors="replace")
            stderr_path.write_text(proc.stderr, encoding="utf-8", errors="replace")
            test_result = {
                "status": "PASS" if proc.returncode == 0 else "NEEDS_REWORK",
                "command": nearest_test_command,
                "returncode": proc.returncode,
                "exit_code": proc.returncode,
                "stdout_tail": proc.stdout[-4000:],
                "stderr_tail": proc.stderr[-4000:],
                "provenance_status": "observed",
                "artifact_refs": ["stdout.log", "stderr.log"],
                "hashes": {"stdout.log": file_hash(stdout_path), "stderr.log": file_hash(stderr_path)},
            }
            test_path.write_text(json.dumps(test_result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="testing", new_status="nearest_test_result", data={"test_result": test_result})
        if test_result["status"] not in {"PASS", "NOT_EVALUATED"}:
            self.record(leaf_id=leaf_id, task_id=task_id, previous_status="nearest_test_result", new_status="test_failed", data={"test_result": test_result})
            return {"status": "test_failed", "workspace": workspace, "test_result": test_result}
        result_manifest = self.merge_manager.build_leaf_result(
            base_candidate_dir=candidate_dir,
            leaf_workspace_dir=workspace_path,
            leaf_dir=workspace["leaf_dir"],
            allowed_files=allowed_files,
            interface_impact=action_result.get("interface_impact", {}) if isinstance(action_result, dict) else {},
            nearest_test_result=test_result,
            peer_dependencies=action_result.get("peer_dependencies", []) if isinstance(action_result, dict) else [],
            unresolved_findings=action_result.get("unresolved_findings", []) if isinstance(action_result, dict) else [],
        )
        checkpoint_path = pathlib.Path(str(workspace["leaf_dir"])) / "checkpoint.json"
        checkpoint_path.write_text(
            json.dumps({"run_id": self.run_id, "leaf_id": leaf_id, "task_id": task_id, "changed_files": changed_files, "test_result": test_result, "created_at": utc_now()}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="nearest_test_result", new_status="checkpoint_saved", data={"checkpoint": str(checkpoint_path)})
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="checkpoint_saved", new_status="result_ready", data={"result_manifest": result_manifest})
        if result_manifest["result_classification"] != "PASS":
            self.record(leaf_id=leaf_id, task_id=task_id, previous_status="result_ready", new_status="rejected", data={"result_manifest": result_manifest})
            return {"status": "rejected", "workspace": workspace, "result_manifest": result_manifest}
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="result_ready", new_status="review_pending")
        merge_result = {"status": "NOT_EVALUATED"}
        if merge:
            merge_result = self.merge_manager.merge_leaf_result(
                candidate_dir=candidate_dir,
                leaf_workspace_dir=workspace_path,
                result_manifest=result_manifest,
                nearest_test_command=nearest_test_command,
            )
        final_status = "accepted" if merge_result.get("status") in {"PASS", "NOT_EVALUATED"} else "rejected"
        self.record(leaf_id=leaf_id, task_id=task_id, previous_status="review_pending", new_status=final_status, data={"merge_result": merge_result})
        return {
            "status": "PASS" if final_status == "accepted" else "NEEDS_REWORK",
            "workspace": workspace,
            "result_manifest": result_manifest,
            "merge_result": merge_result,
            "candidate_hash": product_candidate_manager.tree_hash(candidate_dir),
        }
