#!/usr/bin/env python3
"""Read-only, hash-bound source identity captured at production-run start."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone
from typing import Any


SOURCE_SUFFIXES = {".py", ".json", ".md", ".toml", ".yaml", ".yml", ".ps1"}
EXCLUDED_PARTS = {".git", ".pytest_cache", "__pycache__", "node_modules", "generated", "workspaces"}
RELEVANT_SOURCE_ROOTS = {"scripts", "contracts", "tests", "plugins", "tools", "docs", "project_management"}
IDENTITY_MODULES = (
    "scripts/canonical_goal_spec_compiler.py",
    "scripts/requirement_decision_lane.py",
    "scripts/run_local_pipeline.py",
    "scripts/run_local_pipeline_impl.py",
    "scripts/codex_conversation.py",
    "scripts/surrogate_provider_adapter.py",
    "plugins/cgkn/scripts/cgkn_mcp_server.py",
)
IDENTITY_CONTRACTS = (
    "contracts/requirements_planning_proposal_v1.schema.json",
    "contracts/canonical_goal_spec_v2.schema.json",
    "docs/00_kernel_contract.md",
    "docs/01_contract_registry.md",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha_file(path: pathlib.Path) -> str:
    return _sha_bytes(path.read_bytes()) if path.is_file() else "MISSING"


def _git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )


def _tree_hash(root: pathlib.Path, relative_root: str) -> tuple[str, list[dict[str, Any]]]:
    base = root / relative_root
    rows: list[dict[str, Any]] = []
    if base.is_dir():
        for path in sorted(item for item in base.rglob("*") if item.is_file()):
            if EXCLUDED_PARTS.intersection(path.relative_to(root).parts):
                continue
            rows.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha_file(path),
                "size": path.stat().st_size,
            })
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha_bytes(encoded), rows


def capture(root: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise RuntimeError("SOURCE_IDENTITY_GIT_HEAD_UNAVAILABLE")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"], cwd=root, capture_output=True, check=False,
    )
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    relevant_untracked: list[dict[str, Any]] = []
    for value in sorted(line.strip() for line in untracked.stdout.splitlines() if line.strip()):
        path = root / value
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if pathlib.PurePosixPath(value.replace("\\", "/")).parts[0] not in RELEVANT_SOURCE_ROOTS:
            continue
        if EXCLUDED_PARTS.intersection(path.relative_to(root).parts):
            continue
        relevant_untracked.append({"path": path.relative_to(root).as_posix(), "sha256": _sha_file(path)})
    agent_kit_hash, agent_kit_files = _tree_hash(root, "tools/cgkn-agent-kit")
    plugin_hash, plugin_files = _tree_hash(root, "plugins/cgkn")
    manifest_path = root / "plugins" / "cgkn" / ".codex-plugin" / "plugin.json"
    plugin_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    report: dict[str, Any] = {
        "kind": "CGKNSourceIdentityReport",
        "schema_version": "1.0",
        "formal_evidence_status": "NOT_EVALUATED",
        "authority": "support_identity_only",
        "repository_root": str(root),
        "head_sha": head.stdout.strip(),
        "working_tree_clean": not bool(status.stdout.strip()),
        "git_status_sha256": _sha_bytes(status.stdout.encode("utf-8")),
        "git_diff_sha256": _sha_bytes(diff.stdout),
        "relevant_untracked_manifest": relevant_untracked,
        "relevant_untracked_manifest_sha256": _sha_bytes(json.dumps(relevant_untracked, sort_keys=True).encode("utf-8")),
        "agent_kit_package_sha256": agent_kit_hash,
        "agent_kit_file_count": len(agent_kit_files),
        "plugin_version": str(plugin_manifest.get("version", "")),
        "plugin_source_sha256": plugin_hash,
        "plugin_file_count": len(plugin_files),
        "modified_canonical_module_hashes": {name: _sha_file(root / name) for name in IDENTITY_MODULES},
        "contract_hashes": {name: _sha_file(root / name) for name in IDENTITY_CONTRACTS},
        "captured_at": _now(),
    }
    identity_projection = {key: value for key, value in report.items() if key != "source_identity_hash"}
    report["source_identity_hash"] = _sha_bytes(
        json.dumps(identity_projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return report


def capture_once(root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    output = pathlib.Path(output)
    if output.is_file():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and existing.get("kind") == "CGKNSourceIdentityReport":
            return existing
        raise RuntimeError("SOURCE_IDENTITY_EXISTING_ARTIFACT_INVALID")
    report = capture(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
