#!/usr/bin/env python3
"""Read-only, hash-bound source identity captured at production-run start."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any


SOURCE_SUFFIXES = {".py", ".json", ".md", ".toml", ".yaml", ".yml", ".ps1"}
EXCLUDED_PARTS = {".git", ".pytest_cache", "__pycache__", "node_modules", "generated", "workspaces"}
EXCLUDED_PREFIXES = (".cgkn/publish/",)
RELEVANT_SOURCE_ROOTS = {
    ".github", "cgkn", "config", "contracts", "docs", "governance", "legacy",
    "plugins", "project_management", "schemas", "scripts", "skills", "specs",
    "src", "tests", "tools",
}
RELEVANT_SOURCE_FILES = {
    ".gitattributes", ".gitignore", "AGENTS.md", "COVENANT_GRAPH_NEXUS_KERNEL_DESIGN.md",
    "EDITION.md", "PRODUCT_GOAL.md", "README.md", "VERSION", "demo_auto_generation.py",
    "pytest.ini", "test_e2e_service.py",
}
DEFAULT_GIT_TIMEOUT_SECONDS = 15
GIT_TIMEOUT_SECONDS = {"rev-parse HEAD": 15, "status": 15, "diff HEAD": 20, "ls-files": 15}
SOURCE_IDENTITY_TOTAL_BUDGET_SECONDS = 45
MAX_GIT_DIAGNOSTIC_CHARS = 8192
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


def _sha_bytes(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha_file(path: pathlib.Path) -> str:
    return _sha_bytes(path.read_bytes()) if path.is_file() else "MISSING"


def _bounded_output(value: Any) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    return text[-MAX_GIT_DIAGNOSTIC_CHARS:]


def _git_failure_payload(
    *, operation: str, classification: str, command: list[str], timeout_seconds: int,
    returncode: int | None, stdout: Any = "", stderr: Any = "",
) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "classification": classification,
        "command": command,
        "returncode": returncode,
        "timeout_seconds": timeout_seconds,
        "stdout": _bounded_output(stdout),
        "stderr": _bounded_output(stderr),
    }


def _git_executable() -> str:
    discovered = pathlib.Path(shutil.which("git") or "git")
    if os.name == "nt" and discovered.name.lower() == "git.exe" and discovered.parent.name.lower() in {"bin", "cmd"}:
        native = discovered.parent.parent / "mingw64" / "bin" / "git.exe"
        if native.is_file():
            return str(native)
    return str(discovered)


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_CONFIG",
        "GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
    ):
        environment.pop(name, None)
    environment.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
        "GIT_OPTIONAL_LOCKS": "0",
    })
    return environment


def _git(
    root: pathlib.Path,
    *args: str,
    timeout: int = DEFAULT_GIT_TIMEOUT_SECONDS,
    operation: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [_git_executable(), *args]
    diagnostic_command = ["git", *args]
    label = operation or " ".join(args[:2]) or "git"
    try:
        return subprocess.run(
            command, cwd=root, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False, timeout=timeout,
            stdin=subprocess.DEVNULL, env=_git_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(json.dumps(_git_failure_payload(
            operation=label,
            classification="GIT_COMMAND_TIMEOUT",
            command=diagnostic_command,
            timeout_seconds=timeout,
            returncode=None,
            stdout=exc.stdout,
            stderr=exc.stderr,
        ), ensure_ascii=False, sort_keys=True)) from exc


def _require_git(
    result: subprocess.CompletedProcess[Any], operation: str, *, timeout_seconds: int = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[Any]:
    if result.returncode == 0:
        return result
    result_args = [str(item) for item in result.args] if isinstance(result.args, (list, tuple)) else [str(result.args)]
    if result_args:
        result_args[0] = "git"
    failure = _git_failure_payload(
        operation=operation,
        classification="GIT_COMMAND_FAILED",
        command=result_args,
        timeout_seconds=timeout_seconds,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    raise RuntimeError(json.dumps(failure, ensure_ascii=False, sort_keys=True))


def _excluded_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def _identity_status(porcelain: str) -> str:
    rows = []
    for line in porcelain.splitlines():
        path_value = line[3:] if len(line) > 3 else ""
        if " -> " in path_value:
            path_value = path_value.rsplit(" -> ", 1)[-1]
        if not _excluded_path(path_value):
            rows.append(line)
    return "\n".join(rows) + ("\n" if rows else "")


def _tree_hash(root: pathlib.Path, relative_root: str) -> tuple[str, list[dict[str, Any]]]:
    base = root / relative_root
    rows: list[dict[str, Any]] = []
    if base.is_dir():
        for current, directories, filenames in os.walk(base):
            directories[:] = sorted(item for item in directories if item not in EXCLUDED_PARTS)
            for filename in sorted(filenames):
                path = pathlib.Path(current) / filename
                rows.append({
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha_file(path),
                    "size": path.stat().st_size,
                })
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha_bytes(encoded), rows


def capture(root: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    started = time.perf_counter()
    timings: dict[str, float] = {}
    included_pathspec = tuple(sorted((*RELEVANT_SOURCE_ROOTS, *RELEVANT_SOURCE_FILES)))
    excluded_pathspec = tuple(f":(exclude)**/{part}/**" for part in sorted(EXCLUDED_PARTS))
    pathspec = (*included_pathspec, *excluded_pathspec)

    def run(operation: str, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        elapsed = time.perf_counter() - started
        remaining = SOURCE_IDENTITY_TOTAL_BUDGET_SECONDS - elapsed
        if remaining <= 0:
            raise RuntimeError(json.dumps(_git_failure_payload(
                operation=operation,
                classification="GIT_COMMAND_TIMEOUT",
                command=["git", *args],
                timeout_seconds=SOURCE_IDENTITY_TOTAL_BUDGET_SECONDS,
                returncode=None,
                stderr="source identity total budget exhausted",
            ), ensure_ascii=False, sort_keys=True))
        timeout = max(1, min(GIT_TIMEOUT_SECONDS[operation], int(remaining + 0.999)))
        phase_started = time.perf_counter()
        result = _require_git(
            _git(root, *args, timeout=timeout, operation=operation),
            operation,
            timeout_seconds=timeout,
        )
        timings[operation] = round(time.perf_counter() - phase_started, 6)
        return result

    head = run("rev-parse HEAD", ("rev-parse", "HEAD"))
    status = run("status", ("status", "--porcelain=v1", "--untracked-files=no", "--", *pathspec))
    untracked = run("ls-files", ("ls-files", "--others", "--exclude-standard", "--", *pathspec))
    relevant_untracked: list[dict[str, Any]] = []
    for value in sorted(line.strip() for line in untracked.stdout.splitlines() if line.strip()):
        if _excluded_path(value):
            continue
        path = root / value
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if EXCLUDED_PARTS.intersection(path.relative_to(root).parts):
            continue
        relevant_untracked.append({"path": path.relative_to(root).as_posix(), "sha256": _sha_file(path)})
    identity_status = _identity_status(status.stdout)
    if relevant_untracked:
        identity_status += "".join(f"?? {item['path']}\n" for item in relevant_untracked)
    diff = run("diff HEAD", ("diff", "--no-ext-diff", "--no-textconv", "HEAD", "--", *pathspec))
    tree_started = time.perf_counter()
    agent_kit_hash, agent_kit_files = _tree_hash(root, "tools/cgkn-agent-kit")
    plugin_hash, plugin_files = _tree_hash(root, "plugins/cgkn")
    timings["tree_hash"] = round(time.perf_counter() - tree_started, 6)
    if time.perf_counter() - started > SOURCE_IDENTITY_TOTAL_BUDGET_SECONDS:
        raise RuntimeError(json.dumps(_git_failure_payload(
            operation="source_identity_total",
            classification="GIT_COMMAND_TIMEOUT",
            command=["source_identity", "capture"],
            timeout_seconds=SOURCE_IDENTITY_TOTAL_BUDGET_SECONDS,
            returncode=None,
            stderr="source identity total budget exhausted",
        ), ensure_ascii=False, sort_keys=True))
    manifest_path = root / "plugins" / "cgkn" / ".codex-plugin" / "plugin.json"
    plugin_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    report: dict[str, Any] = {
        "kind": "CGKNSourceIdentityReport",
        "schema_version": "1.0",
        "formal_evidence_status": "NOT_EVALUATED",
        "authority": "support_identity_only",
        "repository_root": str(root),
        "head_sha": head.stdout.strip(),
        "working_tree_clean": not bool(identity_status.strip()),
        "git_status_sha256": _sha_bytes(identity_status.encode("utf-8")),
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
        "timing": {
            "head_seconds": timings.get("rev-parse HEAD", 0.0),
            "status_seconds": timings.get("status", 0.0),
            "untracked_seconds": timings.get("ls-files", 0.0),
            "diff_seconds": timings.get("diff HEAD", 0.0),
            "tree_hash_seconds": timings.get("tree_hash", 0.0),
            "total_seconds": round(time.perf_counter() - started, 6),
        },
    }
    # Identity must be repeatable for unchanged bytes. Capture time is metadata,
    # not part of the identity used to bind test and publish receipts.
    identity_projection = {
        key: value for key, value in report.items()
        if key not in {"source_identity_hash", "captured_at", "timing"}
    }
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
