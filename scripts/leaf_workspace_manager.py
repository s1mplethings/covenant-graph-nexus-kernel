from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Any


LEAF_REQUIRED_FILES = (
    "task_contract.json",
    "context_packet.json",
    "peer_inbox.jsonl",
    "peer_outbox.jsonl",
    "execution_ledger.jsonl",
    "evidence_ledger.jsonl",
    "patch.diff",
    "result_manifest.json",
    "test_results.json",
    "stdout.log",
    "stderr.log",
    "checkpoint.json",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inside(base: pathlib.Path, target: pathlib.Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _copy_tree(src: pathlib.Path, dst: pathlib.Path) -> None:
    if not src.exists():
        dst.mkdir(parents=True, exist_ok=True)
        return
    ignore = shutil.ignore_patterns(".git", ".cgkn_execution", "__pycache__", ".pytest_cache")
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)


class LeafWorkspaceManager:
    def __init__(self, run_dir: str | pathlib.Path, *, run_id: str) -> None:
        self.run_dir = pathlib.Path(run_dir).resolve()
        self.run_id = run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def create_workspace(
        self,
        *,
        leaf_id: str,
        task_id: str,
        candidate_dir: str | pathlib.Path,
        task_contract: dict[str, Any],
        context_packet: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_leaf = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in leaf_id)[:80] or "leaf"
        clean_task = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in task_id)[:80] or "task"
        leaf_dir = self.run_dir / f"leaf_{clean_leaf}_{clean_task}"
        workspace = leaf_dir / "workspace"
        input_dir = leaf_dir / "input"
        data_dir = leaf_dir / "data"
        temp_dir = pathlib.Path(tempfile.mkdtemp(prefix=f"{clean_leaf}_{clean_task}_", dir=str(self.run_dir)))
        leaf_dir.mkdir(parents=True, exist_ok=True)
        input_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        _copy_tree(pathlib.Path(candidate_dir).resolve(), workspace)
        files = {
            "task_contract.json": task_contract,
            "context_packet.json": context_packet or {},
            "result_manifest.json": {},
            "test_results.json": {},
            "checkpoint.json": {"created_at": utc_now(), "run_id": self.run_id, "leaf_id": leaf_id, "task_id": task_id},
        }
        for name, doc in files.items():
            (leaf_dir / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for name in ("peer_inbox.jsonl", "peer_outbox.jsonl", "execution_ledger.jsonl", "evidence_ledger.jsonl", "stdout.log", "stderr.log", "patch.diff"):
            (leaf_dir / name).write_text("", encoding="utf-8")
        return {
            "run_id": self.run_id,
            "leaf_id": leaf_id,
            "task_id": task_id,
            "leaf_dir": str(leaf_dir),
            "workspace": str(workspace),
            "input_dir": str(input_dir),
            "data_dir": str(data_dir),
            "temp_dir": str(temp_dir),
            "workspace_id": f"{self.run_id}:{leaf_id}:{task_id}",
            "created_at": utc_now(),
        }

    def resolve_workspace_path(self, leaf_workspace: dict[str, Any], raw_path: str) -> pathlib.Path:
        workspace = pathlib.Path(str(leaf_workspace["workspace"])).resolve()
        target = (workspace / raw_path).resolve()
        if not _inside(workspace, target):
            raise PermissionError(f"leaf path outside workspace is not allowed: {raw_path}")
        return target

    def authorize_peer_artifact(
        self,
        *,
        source_leaf_workspace: dict[str, Any],
        target_leaf_workspace: dict[str, Any],
        artifact_relpath: str,
        reason: str,
    ) -> dict[str, Any]:
        source = self.resolve_workspace_path(source_leaf_workspace, artifact_relpath)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(artifact_relpath)
        target_input = pathlib.Path(str(target_leaf_workspace["input_dir"])).resolve()
        target_input.mkdir(parents=True, exist_ok=True)
        dest = target_input / pathlib.Path(artifact_relpath).name
        shutil.copy2(source, dest)
        provenance = {
            "created_at": utc_now(),
            "source_leaf": source_leaf_workspace["leaf_id"],
            "target_leaf": target_leaf_workspace["leaf_id"],
            "artifact": str(dest),
            "artifact_relpath": artifact_relpath,
            "reason": reason,
            "mode": "read_only_peer_input_copy",
        }
        with (pathlib.Path(str(target_leaf_workspace["leaf_dir"])) / "peer_inbox.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(provenance, ensure_ascii=False, sort_keys=True) + "\n")
        return provenance


def validate_leaf_workspace_layout(leaf_dir: str | pathlib.Path) -> dict[str, Any]:
    base = pathlib.Path(leaf_dir)
    missing = [name for name in LEAF_REQUIRED_FILES if not (base / name).exists()]
    missing_dirs = [name for name in ("workspace", "input") if not (base / name).is_dir()]
    return {
        "status": "PASS" if not missing and not missing_dirs else "NEEDS_REWORK",
        "missing_files": missing,
        "missing_dirs": missing_dirs,
    }


def summarize_leaf_workspaces(workspaces: list[dict[str, Any]]) -> dict[str, Any]:
    by_workspace_id: dict[str, dict[str, str]] = {}
    duplicate_workspace_ids: list[str] = []
    missing_identity: list[dict[str, Any]] = []
    non_workspace_dirs: list[str] = []
    for item in workspaces:
        workspace_id = str(item.get("workspace_id", "")).strip()
        workspace_root = str(item.get("workspace", "") or item.get("workspace_root", "")).strip()
        if not workspace_id or not workspace_root:
            missing_identity.append(item)
            continue
        if workspace_id in by_workspace_id:
            duplicate_workspace_ids.append(workspace_id)
            continue
        by_workspace_id[workspace_id] = {
            "workspace_id": workspace_id,
            "workspace_root": str(pathlib.Path(workspace_root).resolve()),
            "leaf_id": str(item.get("leaf_id", "")),
            "task_id": str(item.get("task_id", "")),
        }
        for key in ("leaf_dir", "input_dir", "data_dir", "temp_dir"):
            value = str(item.get(key, "")).strip()
            if value:
                non_workspace_dirs.append(str(pathlib.Path(value).resolve()))
    real_roots = {row["workspace_root"] for row in by_workspace_id.values()}
    counted_non_workspace_dirs = sorted(path for path in set(non_workspace_dirs) if path in real_roots)
    ok = not duplicate_workspace_ids and not missing_identity and not counted_non_workspace_dirs
    return {
        "status": "PASS" if ok else "NEEDS_REWORK",
        "leaf_workspace_count": len(by_workspace_id),
        "workspace_ids": sorted(by_workspace_id),
        "workspace_roots": sorted(real_roots),
        "duplicate_workspace_ids": sorted(set(duplicate_workspace_ids)),
        "missing_identity": missing_identity,
        "ignored_container_dirs": sorted(set(non_workspace_dirs) - real_roots),
        "counted_non_workspace_dirs": counted_non_workspace_dirs,
    }
