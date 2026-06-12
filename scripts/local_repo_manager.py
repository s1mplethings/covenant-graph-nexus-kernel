#!/usr/bin/env python3
from __future__ import annotations

import filecmp
import json
import os
import pathlib
import re
import shutil
import zipfile
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = ROOT / "generated" / "managed_projects"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_id(raw: Any) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "")).strip("-")
    return value[:120] or "project"


def managed_projects_root() -> pathlib.Path:
    override = str(os.environ.get("CGNK_MANAGED_PROJECT_ROOT", "")).strip()
    return pathlib.Path(override) if override else DEFAULT_PROJECT_ROOT


def project_id_for_conversation(conversation_id: str) -> str:
    return f"project-{safe_id(conversation_id)}"


def project_root(project_id: str) -> pathlib.Path:
    return managed_projects_root() / safe_id(project_id)


def metadata_path(project_id: str) -> pathlib.Path:
    return project_root(project_id) / "project.json"


def current_worktree(project_id: str) -> pathlib.Path:
    return project_root(project_id) / "current"


def revision_dir(project_id: str, revision_index: int) -> pathlib.Path:
    return project_root(project_id) / "revisions" / f"rev{revision_index:03d}"


def _write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_tree(src: pathlib.Path, dst: pathlib.Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copytree(src, dst)
    else:
        dst.mkdir(parents=True, exist_ok=True)


def _default_metadata(project_id: str, conversation_id: str) -> dict[str, Any]:
    created = now()
    root = project_root(project_id)
    return {
        "kind": "CGNKManagedProject",
        "schema_version": "1",
        "project_id": safe_id(project_id),
        "created_at": created,
        "updated_at": created,
        "source_conversation_id": str(conversation_id),
        "current_revision": 0,
        "current_worktree": str((root / "current").resolve()),
        "latest_delivery_manifest": "",
        "latest_package": "",
        "latest_revision_manifest": "",
        "status": "ready",
        "revisions": [],
    }


def ensure_project(project_id: str, conversation_id: str) -> dict[str, Any]:
    root = project_root(project_id)
    for name in ("current", "revisions", "snapshots", "manifests", "reports"):
        (root / name).mkdir(parents=True, exist_ok=True)
    if metadata_path(project_id).exists():
        return load_project_metadata(project_id)
    metadata = _default_metadata(project_id, conversation_id)
    write_project_metadata(project_id, metadata)
    return metadata


def load_project_metadata(project_id: str) -> dict[str, Any]:
    path = metadata_path(project_id)
    if not path.exists():
        return _default_metadata(project_id, "")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_metadata(project_id, "")
    return doc if isinstance(doc, dict) else _default_metadata(project_id, "")


def write_project_metadata(project_id: str, metadata: dict[str, Any]) -> None:
    metadata["updated_at"] = now()
    metadata["project_id"] = safe_id(metadata.get("project_id") or project_id)
    _write_json(metadata_path(project_id), metadata)


def create_revision_workspace(project_id: str, revision_index: int) -> pathlib.Path:
    ensure_project(project_id, "")
    path = revision_dir(project_id, revision_index)
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_current_to_revision_workspace(project_id: str, revision_index: int) -> pathlib.Path:
    ensure_project(project_id, "")
    workspace = revision_dir(project_id, revision_index)
    _copy_tree(current_worktree(project_id), workspace)
    return workspace


def promote_revision_to_current(project_id: str, revision_index: int) -> dict[str, Any]:
    metadata = ensure_project(project_id, "")
    source = revision_dir(project_id, revision_index)
    if not source.exists():
        raise FileNotFoundError(f"revision workspace not found: {source}")
    _copy_tree(source, current_worktree(project_id))
    metadata["current_revision"] = int(revision_index)
    metadata["current_worktree"] = str(current_worktree(project_id).resolve())
    metadata["status"] = "ready"
    revision_entry = {
        "revision_index": int(revision_index),
        "revision_dir": str(source.resolve()),
        "manifest": metadata.get("latest_revision_manifest", ""),
        "package": metadata.get("latest_package", ""),
        "created_at": now(),
        "status": "ready",
    }
    revisions = metadata.get("revisions", [])
    if not isinstance(revisions, list):
        revisions = []
    revisions = [item for item in revisions if not (isinstance(item, dict) and item.get("revision_index") == revision_index)]
    revisions.append(revision_entry)
    metadata["revisions"] = sorted(revisions, key=lambda item: int(item.get("revision_index", 0)) if isinstance(item, dict) else 0)
    write_project_metadata(project_id, metadata)
    return metadata


def _files_under(root: pathlib.Path) -> dict[str, pathlib.Path]:
    if not root.exists():
        return {}
    out: dict[str, pathlib.Path] = {}
    for path in root.rglob("*"):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = path
    return out


def compute_changed_files(before_dir: pathlib.Path, after_dir: pathlib.Path) -> list[str]:
    before = _files_under(pathlib.Path(before_dir))
    after = _files_under(pathlib.Path(after_dir))
    changed: list[str] = []
    for rel in sorted(set(before) | set(after)):
        if rel not in before:
            changed.append(f"added:{rel}")
        elif rel not in after:
            changed.append(f"deleted:{rel}")
        elif not filecmp.cmp(before[rel], after[rel], shallow=False):
            changed.append(f"modified:{rel}")
    return changed


def create_snapshot(project_id: str, revision_index: int) -> pathlib.Path:
    ensure_project(project_id, "")
    source = current_worktree(project_id)
    snapshot = project_root(project_id) / "snapshots" / f"snapshot_{revision_index:03d}.zip"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(snapshot, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in source.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(source).as_posix())
    return snapshot


def rollback_to_revision(project_id: str, revision_index: int) -> dict[str, Any]:
    metadata = ensure_project(project_id, "")
    source = revision_dir(project_id, revision_index)
    if not source.exists():
        raise FileNotFoundError(f"revision workspace not found: {source}")
    _copy_tree(source, current_worktree(project_id))
    metadata["current_revision"] = int(revision_index)
    metadata["status"] = "rolled_back"
    write_project_metadata(project_id, metadata)
    return metadata
