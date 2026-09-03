#!/usr/bin/env python3
"""Isolated execution path for a Codex-requested CGKN kernel repair."""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Callable

import cgkn_supervision_protocol as protocol


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def build_repair_request(
    audit_result: dict[str, Any],
    checkpoint: dict[str, Any],
    *,
    reproduction_checks: list[str],
) -> dict[str, Any]:
    if audit_result.get("action") != "repair_kernel" or audit_result.get("scope") != "kernel":
        raise ValueError("governed repair requires action=repair_kernel and scope=kernel")
    targets = [protocol._safe_repair_target(item) for item in audit_result.get("repair_targets", [])]
    if not targets or any(not item for item in targets):
        raise ValueError("governed repair has unsafe or empty targets")
    if not any(target.startswith("tests/") for target in targets):
        raise ValueError("governed repair must declare a regression test target")
    checks = [str(item).strip() for item in reproduction_checks if str(item).strip()]
    if not checks:
        raise ValueError("governed repair requires a failing reproduction check")
    return {
        "kind": "CGKNGovernedKernelRepairRequest",
        "schema_version": "1.0",
        "created_at": _now(),
        "checkpoint_id": str(checkpoint.get("checkpoint_id", "")),
        "checkpoint_sha256": str(checkpoint.get("checkpoint_sha256", "")),
        "audit_result_sha256": str(audit_result.get("result_sha256", "")),
        "repair_targets": targets,
        "reproduction_checks": checks,
        "acceptance_checks": list(audit_result.get("acceptance_checks", [])),
        "workflow": [
            "reproduce_false_pass",
            "add_regression_test",
            "repair_kernel_implementation",
            "run_regression_checks",
            "reemit_original_checkpoint",
        ],
        "forbidden_roots": list(protocol.FORBIDDEN_REPAIR_PREFIXES),
    }


def _copy_allowed_repository(source: pathlib.Path, destination: pathlib.Path) -> None:
    for prefix in protocol.ALLOWED_REPAIR_PREFIXES:
        relative = pathlib.PurePosixPath(prefix.rstrip("/"))
        origin = source.joinpath(*relative.parts)
        target = destination.joinpath(*relative.parts)
        if origin.is_dir():
            shutil.copytree(origin, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in protocol.ALLOWED_REPAIR_FILES:
        origin = source / name
        if origin.is_file():
            (destination / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination / name)


def execute_repair(
    request: dict[str, Any],
    repository_root: str | pathlib.Path,
    *,
    codex_command: str = "codex",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    test_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: int = 900,
    metrics_state_dir: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """Run Codex in an allowlisted mirror, verify, then copy declared files back."""
    root = pathlib.Path(repository_root).resolve()
    targets = [str(item) for item in request.get("repair_targets", [])]
    if any(protocol._safe_repair_target(item) != item for item in targets):
        raise ValueError("repair request escaped CGKN-owned allowlist")
    original_hashes = {target: _sha(root / pathlib.PurePosixPath(target)) for target in targets}
    with tempfile.TemporaryDirectory(prefix="cgkn-kernel-repair-") as raw_temp:
        isolated = pathlib.Path(raw_temp).resolve()
        _copy_allowed_repository(root, isolated)
        prompt = (
            "Repair only the declared CGKN-owned targets in this isolated mirror. "
            "First preserve or add the declared regression test, then fix the kernel and run the checks. "
            "Do not weaken tests, invent evidence, touch customer candidates, package, or deliver.\n\n"
            + json.dumps(request, ensure_ascii=False, indent=2)
        )
        completed = runner(
            [codex_command, "exec", "--sandbox", "workspace-write", "--cd", str(isolated), "-"],
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=max(60, min(int(timeout), 1800)),
            check=False,
            cwd=isolated,
        )
        if int(completed.returncode) != 0:
            raise RuntimeError(f"governed Codex repair failed: {(completed.stderr or completed.stdout)[-1600:]}")
        changed: list[str] = []
        for target in targets:
            isolated_path = isolated / pathlib.PurePosixPath(target)
            if isolated_path.is_file() and _sha(isolated_path) != original_hashes[target]:
                changed.append(target)
        if not changed:
            raise RuntimeError("governed Codex repair produced no declared change")
        for check in request.get("reproduction_checks", []):
            command = str(check).strip().split()
            verified = test_runner(
                command,
                cwd=isolated,
                capture_output=True,
                text=True,
                timeout=max(30, min(int(timeout), 900)),
                check=False,
            )
            if int(verified.returncode) != 0:
                raise RuntimeError(f"kernel repair regression check failed: {check}: {(verified.stdout + verified.stderr)[-1200:]}")
        for target in changed:
            actual = root / pathlib.PurePosixPath(target)
            if _sha(actual) != original_hashes[target]:
                raise RuntimeError(f"repair target changed concurrently: {target}")
        for target in changed:
            source = isolated / pathlib.PurePosixPath(target)
            destination = root / pathlib.PurePosixPath(target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    if metrics_state_dir is not None:
        metrics_path = pathlib.Path(metrics_state_dir).resolve() / "supervision_metrics.json"
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            metrics = {}
        metrics.setdefault("kind", "CGKNSupervisionMetrics")
        metrics.setdefault("codex_supervisor_invocation_count", 0)
        metrics["codex_kernel_repair_invocation_count"] = int(
            metrics.get("codex_kernel_repair_invocation_count", 0) or 0
        ) + 1
        metrics["updated_at"] = _now()
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = metrics_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(metrics_path)
    return {
        "kind": "CGKNGovernedKernelRepairReceipt",
        "status": "PASS",
        "created_at": _now(),
        "checkpoint_id": str(request.get("checkpoint_id", "")),
        "changed_targets": changed,
        "regression_checks": list(request.get("reproduction_checks", [])),
        "original_checkpoint_must_be_reemitted": True,
    }
