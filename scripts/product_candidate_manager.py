from __future__ import annotations

import hashlib
import json
import pathlib
import os
import tempfile
from datetime import datetime, timezone
from typing import Any


FORMAL_STAGES = {"integration", "ui_journey", "screenshot", "review", "repair", "package", "clean_start", "verdict"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def tree_hash(project_dir: str | pathlib.Path) -> str:
    root = pathlib.Path(project_dir).resolve()
    digest = hashlib.sha256()
    if not root.exists():
        return hashlib.sha256(b"missing").hexdigest()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or rel.startswith(".cgkn_execution/") or "__pycache__/" in rel:
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


class ProductCandidateManager:
    def __init__(self, path: str | pathlib.Path, *, run_id: str) -> None:
        self.path = pathlib.Path(path)
        self.events_path = self.path.with_name("candidate_events.jsonl")
        self.run_id = run_id

    def create_candidate(
        self,
        *,
        project_dir: str | pathlib.Path,
        requirement_version: str,
        task_ledger_offset: int = 0,
        evidence_ledger_offset: int = 0,
        interface_version: str = "1",
        accepted_patch_ids: list[str] | None = None,
        database_hash: str = "",
    ) -> dict[str, Any]:
        project_hash = tree_hash(project_dir)
        candidate = {
            "candidate_id": f"cand_{project_hash[:16]}",
            "run_id": self.run_id,
            "project_dir": str(pathlib.Path(project_dir).resolve()),
            "source_commit/hash": project_hash,
            "project_tree_hash": project_hash,
            "database_hash": database_hash or hashlib.sha256(b"no_database").hexdigest(),
            "requirement_version": requirement_version,
            "task_ledger_offset": int(task_ledger_offset),
            "evidence_ledger_offset": int(evidence_ledger_offset),
            "interface_version": interface_version,
            "accepted_patch_ids": list(accepted_patch_ids or []),
            "created_at": utc_now(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.append_stage_event(stage="candidate_created", candidate_id=candidate["candidate_id"], project_tree_hash=project_hash)
        return candidate

    def current(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}

    def update_after_merge(
        self,
        *,
        project_dir: str | pathlib.Path,
        patch_id: str,
        expected_previous_hash: str,
        task_ledger_offset: int,
        evidence_ledger_offset: int,
        interface_version: str | None = None,
    ) -> dict[str, Any]:
        current = self.current()
        if not current:
            return {"status": "NEEDS_REWORK", "reason": "candidate_manifest_missing"}
        if current.get("project_tree_hash") != expected_previous_hash:
            return {"status": "NEEDS_REWORK", "reason": "stale_candidate_manifest", "expected_previous_hash": expected_previous_hash, "actual": current.get("project_tree_hash")}
        new_hash = tree_hash(project_dir)
        updated = dict(current)
        patches = list(updated.get("accepted_patch_ids", []))
        if patch_id not in patches:
            patches.append(patch_id)
        updated.update(
            {
                "source_commit/hash": new_hash,
                "project_tree_hash": new_hash,
                "accepted_patch_ids": patches,
                "task_ledger_offset": int(task_ledger_offset),
                "evidence_ledger_offset": int(evidence_ledger_offset),
                "interface_version": interface_version or str(updated.get("interface_version", "1")),
                "updated_at": utc_now(),
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name, suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            pathlib.Path(tmp_name).replace(self.path)
        except Exception:
            pathlib.Path(tmp_name).unlink(missing_ok=True)
            raise
        self.append_stage_event(stage="candidate_updated", candidate_id=updated["candidate_id"], project_tree_hash=new_hash, artifact_refs=[str(self.path)], result="PASS")
        return {"status": "PASS", "candidate": updated, "previous_hash": expected_previous_hash, "new_hash": new_hash, "patch_id": patch_id}

    def append_stage_event(self, *, stage: str, candidate_id: str, project_tree_hash: str = "", artifact_refs: list[str] | None = None, result: str = "PASS") -> dict[str, Any]:
        event = {
            "created_at": utc_now(),
            "run_id": self.run_id,
            "candidate_id": candidate_id,
            "stage": stage,
            "project_tree_hash": project_tree_hash,
            "artifact_refs": list(artifact_refs or []),
            "result": result,
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def validate_stage_candidate(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        candidate = self.current()
        expected = candidate.get("candidate_id", "")
        wrong = [event for event in events if event.get("stage") in FORMAL_STAGES and event.get("candidate_id") != expected]
        return {"status": "PASS" if not wrong and expected else "NEEDS_REWORK", "expected_candidate_id": expected, "wrong_candidate_events": wrong}

    def invalidated_evidence_after_change(self, events: list[dict[str, Any]], *, old_hash: str, new_hash: str) -> dict[str, Any]:
        if old_hash == new_hash:
            return {"status": "PASS", "invalidated": []}
        invalidated = [event for event in events if event.get("stage") in {"ui_journey", "screenshot", "package", "clean_start", "verdict"} and event.get("project_tree_hash") == old_hash]
        return {"status": "NEEDS_REWORK" if invalidated else "PASS", "invalidated": invalidated}
