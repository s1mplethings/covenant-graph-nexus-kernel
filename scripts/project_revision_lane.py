#!/usr/bin/env python3
from __future__ import annotations

# Phase 1 only prepares revision context and manifests.
# Provider-backed revision execution belongs to Phase 2.

import json
import pathlib
import re
import shutil
from datetime import datetime, timezone
from typing import Any

try:
    from . import local_conversation_manager
    from . import local_repo_manager
except ImportError:  # pragma: no cover - script execution path
    import local_conversation_manager  # type: ignore
    import local_repo_manager  # type: ignore


REVISION_HINTS = (
    "上次",
    "之前",
    "刚才",
    "继续改",
    "修改",
    "加一个",
    "加上",
    "修一下",
    "修复",
    "换成",
    "改成",
    "重新生成",
    "再生成",
    "第二版",
    "第三版",
    "在原来基础上",
    "基于之前",
)
NEW_PROJECT_EXCLUSIONS = (
    "新项目",
    "重新做一个不同项目",
    "另做一个",
    "开新项目",
    "不要沿用上次",
    "从零开始",
)
INTERNAL_PUBLIC_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".log", ".yaml", ".yml", ".toml", ".ini"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact(text: str) -> str:
    return re.sub(r"[\s,.!?。！？~～]+", "", str(text or "").lower())


def _write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def has_active_project(conversation: dict[str, Any]) -> bool:
    active = local_conversation_manager.get_active_project(conversation)
    return bool(active.get("project_id")) and str(active.get("status", "none")) not in {"", "none"}


def is_revision_request(text: str, conversation: dict[str, Any]) -> bool:
    compact = _compact(text)
    if any(_compact(term) in compact for term in NEW_PROJECT_EXCLUSIONS):
        return False
    return has_active_project(conversation) and any(_compact(term) in compact for term in REVISION_HINTS)


def create_revision_request(conversation: dict[str, Any], text: str) -> dict[str, Any]:
    if not has_active_project(conversation):
        raise ValueError("active_project_required")
    active = local_conversation_manager.get_active_project(conversation)
    revision_index = int(active.get("revision_index", 0)) + 1
    return {
        "kind": "ProjectRevisionRequest",
        "conversation_id": conversation.get("conversation_id", ""),
        "project_id": active.get("project_id", ""),
        "revision_index": revision_index,
        "created_at": now(),
        "user_revision_request": str(text or "").strip(),
        "previous_manifest_ref": str(active.get("latest_delivery_manifest", "")),
        "previous_package_ref": str(active.get("latest_project_package", "")),
        "previous_project_dir": str(active.get("current_worktree") or active.get("project_dir", "")),
        "previous_revision_index": int(active.get("revision_index", 0)),
    }


def create_revision_plan(conversation: dict[str, Any], revision_request: dict[str, Any]) -> dict[str, Any]:
    request_text = str(revision_request.get("user_revision_request", "")).strip()
    whiteboard = conversation.get("whiteboard", {}) if isinstance(conversation.get("whiteboard"), dict) else {}
    preserve = []
    summary = str(whiteboard.get("project_summary", "")).strip()
    if summary:
        preserve.append(summary)
    return {
        "kind": "ProjectRevisionPlan",
        "revision_mode": "controlled_regenerate",
        "full_regenerate_reason": "patch engine not enabled; controlled regenerate with previous manifest constraints",
        "preserve_requirements": preserve,
        "new_requirements": [request_text] if request_text else [],
        "removed_features": [],
        "delivery_contract": ["local_packager", "public_delivery_gate", "delivery_manifest"],
    }


def prepare_revision_workspace(conversation: dict[str, Any], revision_request: dict[str, Any]) -> dict[str, Any]:
    project_id = str(revision_request.get("project_id", ""))
    revision_index = int(revision_request.get("revision_index", 0))
    local_repo_manager.ensure_project(project_id, str(conversation.get("conversation_id", "")))
    workspace = local_repo_manager.copy_current_to_revision_workspace(project_id, revision_index)
    return {"revision_workspace": str(workspace.resolve()), "revision_index": revision_index}


def build_revision_goal(conversation: dict[str, Any], revision_request: dict[str, Any], revision_plan: dict[str, Any]) -> str:
    active = local_conversation_manager.get_active_project(conversation)
    parts = [
        "Revise the existing project under controlled regenerate mode.",
        f"Project id: {active.get('project_id', '')}",
        f"Previous revision index: {revision_request.get('previous_revision_index', 0)}",
        f"Previous delivery manifest: {revision_request.get('previous_manifest_ref', '')}",
        f"Previous package: {revision_request.get('previous_package_ref', '')}",
        "Preserve existing user-visible behavior unless explicitly changed.",
    ]
    for item in revision_plan.get("preserve_requirements", []) if isinstance(revision_plan.get("preserve_requirements"), list) else []:
        parts.append(f"Preserve: {item}")
    for item in revision_plan.get("new_requirements", []) if isinstance(revision_plan.get("new_requirements"), list) else []:
        parts.append(f"Change request: {item}")
    parts.append("Final delivery must use local_packager, public_delivery_gate, and delivery_manifest.")
    return "\n".join(part for part in parts if str(part).strip())


def revision_manifest_path(manifest: dict[str, Any]) -> pathlib.Path:
    project_id = str(manifest.get("project_id", ""))
    revision_index = int(manifest.get("revision_index", 0))
    return local_repo_manager.project_root(project_id) / "manifests" / f"revision_{revision_index:03d}.json"


def write_revision_manifest(manifest: dict[str, Any]) -> pathlib.Path:
    manifest = dict(manifest)
    manifest.setdefault("kind", "ProjectRevisionManifest")
    manifest.setdefault("schema_version", "1")
    manifest["updated_at"] = now()
    path = revision_manifest_path(manifest)
    manifest["manifest_path"] = str(path.resolve())
    _write_json(path, manifest)
    return path


def run_provider_revision_job(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError(
        "Phase 2: provider-backed revision execution is not implemented in this PR. "
        "Phase 1 only prepares revision request, plan, workspace, and manifest."
    )


def create_revision_manifest(
    conversation: dict[str, Any],
    revision_request: dict[str, Any],
    revision_plan: dict[str, Any],
    workspace: dict[str, Any],
) -> dict[str, Any]:
    created = now()
    return {
        "kind": "ProjectRevisionManifest",
        "schema_version": "1",
        "project_id": revision_request.get("project_id", ""),
        "conversation_id": conversation.get("conversation_id", ""),
        "revision_index": revision_request.get("revision_index", 0),
        "created_at": created,
        "updated_at": created,
        "status": "planned",
        "revision_mode": revision_plan.get("revision_mode", "controlled_regenerate"),
        "full_regenerate_reason": revision_plan.get("full_regenerate_reason", ""),
        "previous_manifest_ref": revision_request.get("previous_manifest_ref", ""),
        "previous_package_ref": revision_request.get("previous_package_ref", ""),
        "previous_project_dir": revision_request.get("previous_project_dir", ""),
        "previous_revision_index": revision_request.get("previous_revision_index", 0),
        "revision_workspace": workspace.get("revision_workspace", ""),
        "user_revision_request": revision_request.get("user_revision_request", ""),
        "preserve_requirements": revision_plan.get("preserve_requirements", []),
        "new_requirements": revision_plan.get("new_requirements", []),
        "removed_features": revision_plan.get("removed_features", []),
        "changed_files": [],
        "test_report": "",
        "package_path": "",
        "delivery_manifest": "",
        "public_delivery_gate": {},
        "user_visible_summary": "",
    }


def mark_revision_success(conversation: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = dict(manifest)
    manifest["status"] = "ready"
    manifest["updated_at"] = now()
    manifest_path = write_revision_manifest(manifest)
    project_id = str(manifest.get("project_id", ""))
    metadata = local_repo_manager.load_project_metadata(project_id)
    metadata["latest_revision_manifest"] = str(manifest_path.resolve())
    metadata["latest_delivery_manifest"] = str(manifest.get("delivery_manifest", ""))
    metadata["latest_package"] = str(manifest.get("package_path", ""))
    local_repo_manager.write_project_metadata(project_id, metadata)
    local_repo_manager.promote_revision_to_current(project_id, int(manifest.get("revision_index", 0)))
    active = local_conversation_manager.get_active_project(conversation)
    active.update(
        {
            "project_id": project_id,
            "project_dir": str(local_repo_manager.project_root(project_id).resolve()),
            "current_worktree": str(local_repo_manager.current_worktree(project_id).resolve()),
            "latest_delivery_manifest": str(manifest.get("delivery_manifest", "")),
            "latest_project_package": str(manifest.get("package_path", "")),
            "revision_index": int(manifest.get("revision_index", 0)),
            "latest_revision_manifest": str(manifest_path.resolve()),
            "status": "revision_ready",
        }
    )
    local_conversation_manager.bind_active_project(conversation, active)
    local_conversation_manager.append_revision_history(conversation, manifest)
    return manifest


def mark_revision_failed(conversation: dict[str, Any], manifest: dict[str, Any], reason: str) -> dict[str, Any]:
    manifest = dict(manifest)
    manifest["status"] = "rework_blocked"
    manifest["failure_reason"] = str(reason or "")
    manifest["updated_at"] = now()
    write_revision_manifest(manifest)
    local_conversation_manager.append_revision_history(conversation, manifest)
    return manifest


def bind_initial_project_delivery(
    conversation: dict[str, Any],
    project_dir: str | pathlib.Path,
    package_path: str = "",
    delivery_manifest: str = "",
) -> dict[str, Any]:
    local_conversation_manager.normalize_conversation(conversation)
    conversation_id = str(conversation.get("conversation_id", ""))
    project_id = local_repo_manager.project_id_for_conversation(conversation_id)
    local_repo_manager.ensure_project(project_id, conversation_id)
    source = pathlib.Path(str(project_dir))
    if source.exists():
        source_resolved = source.resolve()
        current = local_repo_manager.current_worktree(project_id).resolve()
        if source_resolved != current:
            if current.exists():
                shutil.rmtree(current)
            shutil.copytree(source, current)
        else:
            current.mkdir(parents=True, exist_ok=True)
        rev0 = local_repo_manager.revision_dir(project_id, 0)
        if rev0.exists():
            shutil.rmtree(rev0)
        shutil.copytree(current, rev0)
    metadata = local_repo_manager.load_project_metadata(project_id)
    metadata["current_revision"] = 0
    metadata["current_worktree"] = str(local_repo_manager.current_worktree(project_id).resolve())
    metadata["latest_delivery_manifest"] = str(delivery_manifest or "")
    metadata["latest_package"] = str(package_path or "")
    metadata["status"] = "ready"
    if not metadata.get("revisions"):
        metadata["revisions"] = [
            {
                "revision_index": 0,
                "revision_dir": str(local_repo_manager.revision_dir(project_id, 0).resolve()),
                "manifest": "",
                "package": str(package_path or ""),
                "created_at": now(),
                "status": "ready",
            }
        ]
    local_repo_manager.write_project_metadata(project_id, metadata)
    active = {
        "project_id": project_id,
        "project_dir": str(local_repo_manager.project_root(project_id).resolve()),
        "current_worktree": str(local_repo_manager.current_worktree(project_id).resolve()),
        "latest_delivery_manifest": str(delivery_manifest or ""),
        "latest_project_package": str(package_path or ""),
        "revision_index": 0,
        "latest_revision_manifest": "",
        "status": "delivered",
    }
    local_conversation_manager.bind_active_project(conversation, active)
    return active


def public_delivery_is_safe(path: str | pathlib.Path) -> bool:
    return pathlib.Path(str(path)).suffix.lower() not in INTERNAL_PUBLIC_SUFFIXES
