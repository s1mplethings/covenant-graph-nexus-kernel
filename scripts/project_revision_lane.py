#!/usr/bin/env python3
from __future__ import annotations

# Phase 2 executes revisions through injected provider/finalize/package/gate adapters.
# The lane still preserves the single formal delivery contract: provider route,
# local_packager, public_delivery_gate, then delivery_manifest.

import json
import pathlib
import re
import shutil
import inspect
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


def _load_json_object(path: str | pathlib.Path) -> dict[str, Any]:
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else {}


def _call_adapter(adapter: Any, **kwargs: Any) -> Any:
    signature = inspect.signature(adapter)
    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
    if accepts_kwargs:
        return adapter(**kwargs)
    filtered = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return adapter(**filtered)


def _result_path(value: Any, key: str) -> str:
    if isinstance(value, dict):
        return str(value.get(key, "") or "")
    return ""


def _artifact_missing(package_path: str, delivery_manifest: str) -> list[str]:
    missing: list[str] = []
    if not package_path or not pathlib.Path(package_path).exists():
        missing.append("final_project_bundle.zip")
    if not delivery_manifest or not pathlib.Path(delivery_manifest).exists():
        missing.append("delivery_manifest")
    return missing


def _revision_result(manifest: dict[str, Any], status: str, error: str = "") -> dict[str, Any]:
    return {
        "kind": "ProjectRevisionExecutionResult",
        "status": status,
        "project_id": str(manifest.get("project_id", "")),
        "revision_index": int(manifest.get("revision_index", 0)),
        "revision_manifest": str(manifest.get("manifest_path", "")),
        "revision_workspace": str(manifest.get("revision_workspace", "")),
        "package_path": str(manifest.get("package_path", "")),
        "delivery_manifest": str(manifest.get("delivery_manifest", "")),
        "public_delivery_gate": manifest.get("public_delivery_gate", {}) if isinstance(manifest.get("public_delivery_gate"), dict) else {},
        "error": error,
    }


def _changed_files_for_revision(manifest: dict[str, Any], workspace: pathlib.Path) -> tuple[list[str], str]:
    previous_dir = pathlib.Path(str(manifest.get("previous_project_dir", "")))
    if not previous_dir.exists():
        return [], f"previous project dir not found: {previous_dir}"
    try:
        return local_repo_manager.compute_changed_files(previous_dir, workspace), ""
    except Exception as exc:
        return [], str(exc)


def _changed_file_path(item: str) -> str:
    value = str(item or "").replace("\\", "/")
    prefix, separator, path = value.partition(":")
    if separator and prefix in {"added", "modified", "deleted"}:
        return path.lstrip("/")
    return value.lstrip("/")


def _is_revision_changed_file_noise(item: str) -> bool:
    rel = _changed_file_path(item)
    parts = [part for part in rel.split("/") if part]
    if not parts:
        return True
    noise_dirs = {
        ".cgnk",
        ".cgnk_test_env",
        ".cgnk_tmp",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
    }
    if any(part in noise_dirs for part in parts):
        return True
    if pathlib.PurePosixPath(rel).suffix.lower() in {".pyc", ".pyo"}:
        return True
    return parts[-1] in {
        "delivery_manifest.json",
        "final_project_bundle.zip",
        "packager_run_log.txt",
    }


def _filter_revision_changed_files(changed_files: list[str]) -> tuple[list[str], int]:
    filtered = [item for item in changed_files if not _is_revision_changed_file_noise(item)]
    return filtered, len(changed_files) - len(filtered)


def _merge_changed_files_warning(existing: str, extra: str) -> str:
    if not existing:
        return extra
    if not extra:
        return existing
    return f"{existing}; {extra}"


def run_provider_revision_job(
    *,
    conversation: dict[str, Any],
    revision_manifest: dict[str, Any] | str | pathlib.Path,
    provider_execute: Any,
    post_build_finalize: Any,
    package_project: Any,
    evaluate_public_delivery_gate: Any,
    model: str,
    timeout: int = 420,
) -> dict[str, Any]:
    """Execute a prepared revision through provider -> finalize -> package -> public gate."""
    if not all(callable(item) for item in (provider_execute, post_build_finalize, package_project, evaluate_public_delivery_gate)):
        raise ValueError("provider_execute, post_build_finalize, package_project, and evaluate_public_delivery_gate are required")

    manifest = _load_json_object(revision_manifest) if isinstance(revision_manifest, (str, pathlib.Path)) else dict(revision_manifest)
    project_id = str(manifest.get("project_id", ""))
    revision_index = int(manifest.get("revision_index", 0))
    workspace = pathlib.Path(str(manifest.get("revision_workspace", ""))).resolve()
    revision_goal = str(manifest.get("revision_goal", "")).strip()
    if not project_id or revision_index < 1 or not revision_goal:
        raise ValueError("revision_manifest must include project_id, revision_index, and revision_goal")
    workspace.mkdir(parents=True, exist_ok=True)

    manifest.update(
        {
            "status": "generating",
            "started_at": now(),
            "model": str(model or ""),
            "provider_route": "api_provider_project_generation",
            "delivery_contract": ["provider_route", "local_packager", "public_delivery_gate", "delivery_manifest"],
            "current_promoted": False,
        }
    )
    write_revision_manifest(manifest)

    try:
        provider_result = _call_adapter(
            provider_execute,
            goal=revision_goal,
            out_dir=str(workspace),
            model=model,
            timeout=timeout,
            revision_context=manifest,
            conversation=conversation,
        )
        manifest["provider_result"] = provider_result if isinstance(provider_result, dict) else {"result": str(provider_result)}

        finalize_result = _call_adapter(
            post_build_finalize,
            project_dir=workspace,
            provider_result=provider_result,
            conversation=conversation,
            revision_manifest=manifest,
        )
        manifest["post_build_finalize"] = finalize_result if isinstance(finalize_result, dict) else {"result": str(finalize_result)}

        # The concrete adapter is expected to be local_packager.package_project.
        package_manifest = _call_adapter(
            package_project,
            project_dir=workspace,
            output_dir=workspace,
            revision_manifest=manifest,
        )
        if not isinstance(package_manifest, dict):
            raise RuntimeError("package_project returned non-object manifest")
        package_path = _result_path(package_manifest, "package_path")
        delivery_manifest = _result_path(package_manifest, "manifest_path")
        manifest["package_path"] = package_path
        manifest["delivery_manifest"] = delivery_manifest
        artifact_missing = _artifact_missing(package_path, delivery_manifest)
        if artifact_missing:
            gate = {
                "delivery_allowed": False,
                "status": "REWORK",
                "missing": artifact_missing,
            }
            manifest["public_delivery_gate"] = gate
            manifest["current_promoted"] = False
            failed = mark_revision_failed(conversation, manifest, "delivery_artifact_missing")
            return _revision_result(failed, "rework_blocked", "delivery_artifact_missing")

        # The concrete adapter is expected to be public_delivery_gate evaluation.
        gate = _call_adapter(
            evaluate_public_delivery_gate,
            project_dir=workspace,
            manifest=package_manifest,
            conversation=conversation,
            revision_manifest=manifest,
            phase="final",
        )
        if not isinstance(gate, dict):
            raise RuntimeError("evaluate_public_delivery_gate returned non-object result")
        if package_path and not public_delivery_is_safe(package_path):
            gate = dict(gate)
            gate["delivery_allowed"] = False
            gate["status"] = "REWORK"
            gate["missing"] = sorted(set(list(gate.get("missing", [])) + ["public_package_suffix"]))
        manifest["public_delivery_gate"] = gate

        # _changed_files_for_revision wraps local_repo_manager.compute_changed_files.
        raw_changed_files, warning = _changed_files_for_revision(manifest, workspace)
        changed_files, excluded_count = _filter_revision_changed_files(raw_changed_files)
        manifest["changed_files"] = changed_files
        if excluded_count:
            manifest["changed_files_excluded_count"] = excluded_count
        if raw_changed_files and not changed_files:
            warning = _merge_changed_files_warning(warning, "all changed files were internal/generated artifacts")
        if warning:
            manifest["changed_files_warning"] = warning

        if gate.get("delivery_allowed") is not True:
            manifest["current_promoted"] = False
            failed = mark_revision_failed(conversation, manifest, "public_delivery_gate_rejected")
            return _revision_result(failed, "rework_blocked", "public_delivery_gate_rejected")

        manifest["completed_at"] = now()
        manifest["current_promoted"] = True
        success = mark_revision_success(conversation, manifest)
        return _revision_result(success, "ready")
    except Exception as exc:
        manifest["current_promoted"] = False
        manifest["failed_at"] = now()
        failed = mark_revision_failed(conversation, manifest, str(exc))
        return _revision_result(failed, "rework_blocked", str(exc))


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
    manifest["current_promoted"] = False
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
