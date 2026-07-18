from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Iterable


HASH_PREFIX = "sha256:"
ROOT_EVIDENCE_OUTPUT_NAMES = {
    "test_execution.json",
    "TEST_REPORT.md",
    "test_stdout.txt",
    "test_stderr.txt",
    "customer_runtime.json",
    "visual_evidence.json",
    "DELIVERY_NOTES.md",
    "generated_image_manifest.json",
    "video_blocked.json",
    "delivery_manifest.json",
    "delivery_receipt.json",
    "packager_run_log.txt",
    "final_project_bundle.zip",
    "user_review.json",
    "user_review_request.json",
    "user_review_replay_ledger.json",
}
EVIDENCE_OUTPUT_SUFFIXES = {".tmp", ".pyc"}
ANY_DEPTH_CACHE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
ROOT_TOOL_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    ".cgnk_test_env",
    ".cgkn_test_env",
    "node_modules",
    ".cgkn_review_history",
}
EVIDENCE_OUTPUT_RELATIVE_PATHS = {
    "screenshots/browser_visual_evidence.png",
}


def sha256_bytes(data: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def sha256_file(path: str | pathlib.Path) -> str:
    return sha256_bytes(pathlib.Path(path).read_bytes())


def canonical_json_payload(document: dict[str, Any], blank_fields: Iterable[str]) -> bytes:
    payload = dict(document)
    for field in blank_fields:
        if field in payload:
            payload[field] = ""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_json_hash(document: dict[str, Any], blank_fields: Iterable[str]) -> str:
    return sha256_bytes(canonical_json_payload(document, blank_fields))


def is_candidate_source_path(path: pathlib.Path, project_dir: str | pathlib.Path) -> bool:
    project = pathlib.Path(project_dir).resolve()
    candidate = pathlib.Path(path)
    try:
        rel = candidate.resolve().relative_to(project).as_posix()
    except ValueError:
        return False
    path_parts = pathlib.PurePosixPath(rel).parts
    parts = set(path_parts)
    if parts & ANY_DEPTH_CACHE_DIRS:
        return False
    if path_parts and path_parts[0] in ROOT_TOOL_DIRS:
        return False
    if rel in ROOT_EVIDENCE_OUTPUT_NAMES:
        return False
    if rel in EVIDENCE_OUTPUT_RELATIVE_PATHS:
        return False
    if candidate.suffix.lower() in EVIDENCE_OUTPUT_SUFFIXES:
        return False
    return True


def iter_candidate_source_files(project_dir: str | pathlib.Path) -> list[pathlib.Path]:
    project = pathlib.Path(project_dir).resolve()
    if not project.exists():
        return []
    return sorted(path for path in project.rglob("*") if path.is_file() and is_candidate_source_path(path, project))


def candidate_source_manifest(project_dir: str | pathlib.Path) -> dict[str, str]:
    project = pathlib.Path(project_dir).resolve()
    return {path.relative_to(project).as_posix(): sha256_file(path) for path in iter_candidate_source_files(project)}


def candidate_source_manifest_diff(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    before_keys = set(before)
    after_keys = set(after)
    common = before_keys & after_keys
    return {
        "added": sorted(after_keys - before_keys),
        "removed": sorted(before_keys - after_keys),
        "changed": sorted(key for key in common if before[key] != after[key]),
    }


def candidate_source_hash(project_dir: str | pathlib.Path) -> str:
    project = pathlib.Path(project_dir).resolve()
    digest = hashlib.sha256()
    for path in iter_candidate_source_files(project):
        rel = path.relative_to(project).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return HASH_PREFIX + digest.hexdigest()
