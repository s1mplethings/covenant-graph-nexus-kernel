#!/usr/bin/env python3
from __future__ import annotations

import ast
import pathlib
import json
import hashlib
import re
import shutil
from datetime import datetime, timezone
from typing import Any

try:
    from pipeline_contracts import CandidateMaterializationResult, base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import CandidateMaterializationResult, base_result


LIFECYCLE_FILES = {
    "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json",
    "candidate_record.json",
    "candidate_review_summary.json",
    "known_limits.json",
    "repair_plan.json",
    "TEST_REPORT.md",
    "screenshot_blocked.json",
    "video_blocked.json",
    "final_project_bundle.zip",
    "delivery_manifest.json",
}


def _ignored_candidate_relative(relative: pathlib.PurePath) -> bool:
    return bool(
        relative.name in LIFECYCLE_FILES
        or relative.suffix.lower() in {".pyc", ".pyo"}
        or any(part in {"__pycache__", ".pytest_cache"} for part in relative.parts)
        or relative.as_posix().startswith("artifacts/")
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_relative(value: Any) -> pathlib.PurePosixPath:
    relative = pathlib.PurePosixPath(str(value or "").replace("\\", "/"))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe candidate path: {relative}")
    return relative


def _normalized_path(value: Any) -> str:
    return _safe_relative(value).as_posix()


def _file_map(files: list[dict[str, str]]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for item in files:
        path = _normalized_path(item.get("path", ""))
        if path in mapped:
            raise ValueError(f"duplicate candidate path: {path}")
        content = item.get("content")
        if not isinstance(content, str):
            raise ValueError(f"candidate content must be text: {path}")
        mapped[path] = content
    return mapped


def _files_from_tree(root: pathlib.Path) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    if not root.exists():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = pathlib.PurePosixPath(path.relative_to(root).as_posix())
        if _ignored_candidate_relative(relative):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        files.append({"path": relative.as_posix(), "content": content})
    return files


def _resolve_local_reference(source_path: str, reference: str) -> str:
    source = pathlib.PurePosixPath(source_path)
    raw = str(reference or "").strip().replace("\\", "/")
    if raw.startswith("/"):
        raw = raw.lstrip("/")
        target = pathlib.PurePosixPath(raw)
    else:
        target = source.parent / pathlib.PurePosixPath(raw)
    parts: list[str] = []
    for part in target.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return pathlib.PurePosixPath(*parts).as_posix()


def _reference_candidates(path: str, *, suffixes: tuple[str, ...]) -> list[str]:
    pure = pathlib.PurePosixPath(path)
    candidates = [pure.as_posix()]
    if not pure.suffix:
        candidates.extend(pure.as_posix() + suffix for suffix in suffixes)
        candidates.extend((pure / ("index" + suffix)).as_posix() for suffix in suffixes)
    return list(dict.fromkeys(candidates))


def _python_local_references(path: str, content: str, present: set[str]) -> list[dict[str, str]]:
    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError:
        return []
    top_level_roots = {item.split("/", 1)[0].removesuffix(".py") for item in present}
    references: list[dict[str, str]] = []
    source = pathlib.PurePosixPath(path)
    for node in ast.walk(tree):
        modules: list[tuple[str, int]] = []
        if isinstance(node, ast.Import):
            modules.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append((node.module or "", int(node.level or 0)))
        for module, level in modules:
            if not module and level <= 0:
                continue
            module_parts = [part for part in module.split(".") if part]
            if level:
                base = list(source.parent.parts)
                for _ in range(max(0, level - 1)):
                    if base:
                        base.pop()
                target = pathlib.PurePosixPath(*base, *module_parts).as_posix()
            else:
                top = module_parts[0] if module_parts else ""
                if top not in top_level_roots:
                    continue
                target = pathlib.PurePosixPath(*module_parts).as_posix()
            references.append(
                {
                    "source_path": path,
                    "reference": "." * level + module,
                    "kind": "python_import",
                    "candidate_paths": _reference_candidates(
                        target, suffixes=(".py", "/__init__.py")
                    ),
                }
            )
    return references


def _test_entry_references(path: str, content: str) -> list[dict[str, str]]:
    if not path.endswith(".py") or not pathlib.PurePosixPath(path).name.startswith("test"):
        return []
    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError:
        return []
    references: list[dict[str, str]] = []
    entry_names = {"SUITE_PARTS", "TEST_MODULES", "PYTEST_FILES"}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None or not any(isinstance(target, ast.Name) and target.id in entry_names for target in targets):
            continue
        for child in ast.walk(value):
            if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
                continue
            reference = child.value.strip().replace("\\", "/")
            if not reference.endswith(".py"):
                continue
            expected = (
                pathlib.PurePosixPath(reference).as_posix()
                if "/" in reference
                else _resolve_local_reference(path, reference)
            )
            references.append(
                {
                    "source_path": path,
                    "reference": reference,
                    "kind": "test_entry_reference",
                    "candidate_paths": [expected],
                }
            )
    return references


def _html_local_references(path: str, content: str) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    tag_pattern = re.compile(r"<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*(['\"])(.*?)\1", re.I | re.S)
    for match in tag_pattern.finditer(content):
        reference = match.group(2).strip()
        if not reference or reference.startswith(("http://", "https://", "//", "data:", "#")):
            continue
        reference = reference.split("?", 1)[0].split("#", 1)[0]
        expected = _resolve_local_reference(path, reference)
        references.append(
            {
                "source_path": path,
                "reference": reference,
                "kind": "html_asset_reference",
                "candidate_paths": [expected],
            }
        )
    return references


def _javascript_local_references(path: str, content: str) -> list[dict[str, str]]:
    patterns = (
        re.compile(r"(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]", re.M),
        re.compile(r"(?:require|import)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.M),
    )
    references: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(content):
            reference = match.group(1).strip()
            if not reference.startswith((".", "/")) or reference in seen:
                continue
            seen.add(reference)
            expected = _resolve_local_reference(path, reference)
            references.append(
                {
                    "source_path": path,
                    "reference": reference,
                    "kind": "javascript_module_reference",
                    "candidate_paths": _reference_candidates(
                        expected, suffixes=(".js", ".mjs", ".cjs", ".json")
                    ),
                }
            )
    return references


def assess_candidate_closure(
    files: list[dict[str, str]] | None = None,
    *,
    candidate_dir: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Check obvious local executable references without acting as a linker."""
    source_files = files if files is not None else _files_from_tree(pathlib.Path(candidate_dir or "."))
    mapped = _file_map(source_files)
    present = set(mapped)
    references: list[dict[str, Any]] = []
    for path, content in mapped.items():
        suffix = pathlib.PurePosixPath(path).suffix.lower()
        if suffix == ".py":
            references.extend(_python_local_references(path, content, present))
            references.extend(_test_entry_references(path, content))
        elif suffix in {".html", ".htm"}:
            references.extend(_html_local_references(path, content))
        elif suffix in {".js", ".mjs", ".cjs"}:
            references.extend(_javascript_local_references(path, content))
    missing: list[dict[str, str]] = []
    checked: list[dict[str, str]] = []
    for item in references:
        candidates = [str(value) for value in item.pop("candidate_paths", [])]
        resolved = next((candidate for candidate in candidates if candidate in present), "")
        record = {**item, "resolved_path": resolved or (candidates[0] if candidates else "")}
        checked.append(record)
        if not resolved:
            missing.append(record)
    return {
        "kind": "CGKNCandidateClosureCheck",
        "schema_version": "1.0",
        "status": "PASS" if not missing else "FAIL",
        "checked_reference_count": len(checked),
        "checked_references": checked,
        "missing_paths": missing,
        "present_paths": sorted(present),
        "authority": {"can_assert_formal_evidence": False, "can_package": False},
    }


def build_authorized_candidate_file_set(
    base_files: list[dict[str, str]],
    emission_files: list[dict[str, str]],
    *,
    owned_paths: list[str],
    validated_paths: list[str],
) -> dict[str, Any]:
    """Promote only Provider files authorized by both ownership and validation."""
    merged = _file_map(base_files)
    emission = _file_map(emission_files)
    owned = {_normalized_path(path) for path in owned_paths}
    validated = {_normalized_path(path) for path in validated_paths}
    authorized = owned & validated
    promoted: list[str] = []
    excluded: list[dict[str, str]] = []
    for path, content in emission.items():
        if path not in owned:
            excluded.append({"path": path, "reason": "UNOWNED"})
            continue
        if path not in validated:
            excluded.append({"path": path, "reason": "NOT_VALIDATED"})
            continue
        if merged.get(path) != content:
            merged[path] = content
            promoted.append(path)
    files = [{"path": path, "content": merged[path]} for path in sorted(merged)]
    closure = assess_candidate_closure(files)
    return {
        "kind": "CGKNCandidateAuthorizedPromotion",
        "schema_version": "1.0",
        "status": "PASS" if closure["status"] == "PASS" else "FAIL",
        "authorized_paths": sorted(authorized),
        "promoted_paths": sorted(promoted),
        "excluded_paths": excluded,
        "files": files,
        "closure": closure,
        "authority": {"can_assert_formal_evidence": False, "can_package": False},
    }


def candidate_source_manifest(root: pathlib.Path) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    if not root.exists():
        return manifest
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _ignored_candidate_relative(pathlib.PurePosixPath(relative)):
            continue
        payload = path.read_bytes()
        manifest.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
        )
    return manifest


def candidate_source_hash(root: pathlib.Path) -> str:
    payload = json.dumps(
        candidate_source_manifest(root),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assess_build_complete(
    files: list[dict[str, str]],
    *,
    required_paths: list[str] | None = None,
    ownership_violations: list[Any] | None = None,
    safety_blockers: list[Any] | None = None,
) -> dict[str, Any]:
    """Authorize only saveable, complete project sets; never release readiness."""
    present: set[str] = set()
    blockers: list[dict[str, Any]] = []
    for item in files:
        try:
            relative = _safe_relative(item.get("path", ""))
        except ValueError as exc:
            blockers.append({"rule_id": "UNSAFE_PATH", "detail": str(exc)})
            continue
        rel = relative.as_posix()
        if rel in present:
            blockers.append({"rule_id": "OWNERSHIP_COLLISION", "path": rel})
        present.add(rel)
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            blockers.append({"rule_id": "CORRUPT_OUTPUT", "path": rel})
    missing = sorted(
        {
            str(path).replace("\\", "/").strip()
            for path in (required_paths or [])
            if str(path).strip()
        }
        - present
    )
    blockers.extend({"rule_id": "REQUIRED_PATH_MISSING", "path": path} for path in missing)
    blockers.extend(
        {"rule_id": "OWNERSHIP_VIOLATION", "detail": str(item)}
        for item in (ownership_violations or [])
    )
    blockers.extend(
        {"rule_id": "SECURITY_BLOCKER", "detail": str(item)}
        for item in (safety_blockers or [])
    )
    closure = assess_candidate_closure(files)
    blockers.extend(
        {
            "rule_id": "CANDIDATE_CLOSURE_MISSING",
            "path": str(item.get("resolved_path", "")),
            "source_path": str(item.get("source_path", "")),
            "reference_kind": str(item.get("kind", "")),
        }
        for item in closure["missing_paths"]
    )
    return {
        "status": "BUILD_COMPLETE" if not blockers else "BUILD_BLOCKED",
        "build_complete": not blockers,
        "required_paths": sorted(required_paths or []),
        "present_paths": sorted(present),
        "blockers": blockers,
        "closure": closure,
        "release_ready": False,
    }


def _copy_candidate_source(source: pathlib.Path, destination: pathlib.Path) -> None:
    if destination.exists():
        raise RuntimeError(f"immutable candidate version already exists: {destination}")
    destination.mkdir(parents=True)
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if _ignored_candidate_relative(relative):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def snapshot_version(
    *,
    candidate_dir: pathlib.Path,
    store_dir: pathlib.Path,
    parent_candidate_id: str = "",
    repair_issue_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one immutable candidate version and append its lifecycle receipt."""
    candidate = pathlib.Path(candidate_dir).resolve()
    store = pathlib.Path(store_dir).resolve()
    closure = assess_candidate_closure(candidate_dir=candidate)
    if closure["status"] != "PASS":
        missing = ", ".join(
            str(item.get("resolved_path", ""))
            for item in closure["missing_paths"]
        )
        raise RuntimeError(f"candidate closure failed: {missing}")
    versions = store / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    candidate_hash = candidate_source_hash(candidate)
    index_path = store / "candidate_versions.json"
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            index = {}
    else:
        index = {}
    candidates = index.get("candidates", []) if isinstance(index.get("candidates", []), list) else []
    parent = next(
        (
            item
            for item in candidates
            if isinstance(item, dict)
            and str(item.get("candidate_id", "")) == str(parent_candidate_id or "")
        ),
        None,
    )
    if parent_candidate_id and parent is None:
        raise RuntimeError(f"candidate parent not found: {parent_candidate_id}")
    if parent is None and candidates and isinstance(candidates[-1], dict):
        parent = candidates[-1]
    if parent is not None and str(parent.get("candidate_hash", "")) == candidate_hash:
        return {
            **parent,
            "version_created": False,
            "version_skip_reason": "NO_TREE_DELTA",
            "attempted_parent_candidate_id": str(parent.get("candidate_id", "")),
        }

    version_number = len(candidates)
    candidate_id = f"candidate-v{version_number}-{candidate_hash[:12]}"
    version_name = f"v{version_number:03d}__{candidate_hash[:12]}"
    version_dir = versions / version_name
    _copy_candidate_source(candidate, version_dir)
    supplied = dict(metadata or {})
    record = {
        "kind": "CGKNProvisionalCandidate",
        "schema_version": "1.0",
        "workflow_state": "BUILD_COMPLETE",
        "evidence_status": "NOT_EVALUATED",
        "release_ready": False,
        "candidate_version": version_number,
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "candidate_path": str(version_dir),
        "parent_candidate_id": str(parent_candidate_id or ""),
        "repair_issue_ids": sorted({str(item) for item in (repair_issue_ids or []) if str(item)}),
        "commit_sha": str(supplied.get("commit_sha", "")),
        "project_spec_hash": str(supplied.get("project_spec_hash", "")),
        "known_issues": list(supplied.get("known_issues", [])) if isinstance(supplied.get("known_issues", []), list) else [],
        "provider_provenance": supplied.get("provider_provenance", {}),
        "provider_calls": int(supplied.get("provider_calls", 0) or 0),
        "created_at": _now(),
        "not_final_delivery": True,
        "version_created": True,
    }
    (version_dir / "candidate_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    candidates.append(record)
    index = {
        "kind": "CGKNCandidateStoreIndex",
        "schema_version": "1.0",
        "latest_candidate_id": candidate_id,
        "candidate_versions_total": len(candidates),
        "release_authority": False,
        "candidates": candidates,
    }
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def run(
    *,
    candidate_dir: pathlib.Path,
    files: list[dict[str, str]],
    semantic_classes: dict[str, Any] | None = None,
    sanitize_result: dict[str, Any] | None = None,
    store_dir: pathlib.Path | None = None,
    version_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    closure = assess_candidate_closure(files)
    if closure["status"] != "PASS":
        missing = ", ".join(
            str(item.get("resolved_path", ""))
            for item in closure["missing_paths"]
        )
        raise RuntimeError(f"candidate closure failed: {missing}")
    root = pathlib.Path(candidate_dir).resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    generated_files: list[str] = []
    for item in files:
        relative = _safe_relative(item.get("path", ""))
        target = (root / pathlib.Path(*relative.parts)).resolve()
        target.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item.get("content", "")), encoding="utf-8")
        generated_files.append(relative.as_posix())
    marker = {
        "kind": "CGKNCandidateOnlyMarker",
        "status": "needs_rework",
        "semantic_classes": semantic_classes or {},
        "sanitize_result": sanitize_result or {},
    }
    (root / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result = CandidateMaterializationResult(
        status="pass",
        verdict="candidate_materialized",
        candidate_dir=str(candidate_dir),
        artifacts=[str(candidate_dir / rel) for rel in generated_files],
        metadata={"generated_files": generated_files, "candidate_only": True},
    )
    data = result.to_dict()
    data["candidate_dir"] = result.candidate_dir
    data["build_state"] = "BUILD_COMPLETE"
    data["release_ready"] = False
    data["candidate_closure"] = closure
    if store_dir is not None:
        record = snapshot_version(
            candidate_dir=root,
            store_dir=pathlib.Path(store_dir),
            metadata=version_metadata,
        )
        data["candidate_record"] = record
        data["metadata"].update(
            {
                "candidate_id": record["candidate_id"],
                "candidate_hash": record["candidate_hash"],
                "candidate_version": record["candidate_version"],
            }
        )
    return data


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="module_contract",
        metadata={
            "responsibilities": ["write candidate_project_dir", "candidate marker", "immutable candidate versions", "candidate snapshot manifest", "runnable candidate validation"],
            "forbidden": ["final_project_bundle.zip", "delivery_manifest.json"],
        },
    )
