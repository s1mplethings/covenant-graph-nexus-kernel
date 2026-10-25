#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "research" / "release-056" / "benchmark_manifest.json"
SECRET_ARGUMENT = re.compile(r"(?i)(api[-_]?key|authorization|bearer|password|secret|token)")
SECRET_VALUE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]{12,}|(?:sk|ghp|github_pat|xai)-[A-Za-z0-9_-]{12,}|"
    r"(?:api[-_]?key|authorization|password|secret)\s*[:=]\s*\S+)"
)


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _git(checkout: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=checkout, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def verify_checkout(checkout: pathlib.Path, expected_commit: str) -> dict[str, Any]:
    resolved = checkout.resolve(strict=True)
    actual = _git(resolved, "rev-parse", "HEAD")
    try:
        expected = _git(resolved, "rev-parse", f"{expected_commit}^{{commit}}")
    except RuntimeError as exc:
        raise ValueError(f"benchmark checkout commit mismatch: expected {expected_commit}, got {actual}") from exc
    dirty = _git(resolved, "status", "--porcelain=v1")
    if actual != expected:
        raise ValueError(f"benchmark checkout commit mismatch: expected {expected}, got {actual}")
    if dirty:
        raise ValueError("official benchmark checkout must be clean")
    return {"commit": actual, "tree": _git(resolved, "show", "-s", "--format=%T", "HEAD"), "clean": True}


def sanitize_output(value: str, *, checkout: pathlib.Path) -> str:
    sanitized = SECRET_VALUE.sub("[REDACTED]", value)
    candidates = {str(checkout.resolve()), str(ROOT.resolve()), str(pathlib.Path.home().resolve())}
    for candidate in sorted(candidates, key=len, reverse=True):
        sanitized = sanitized.replace(candidate, "[LOCAL_PATH]").replace(candidate.replace("\\", "/"), "[LOCAL_PATH]")
    return sanitized[:20_000]


def validate_command(command: Sequence[str]) -> None:
    if not command:
        raise ValueError("official command is required after --")
    for index, value in enumerate(command):
        if SECRET_ARGUMENT.search(value):
            raise ValueError(f"secret-bearing command argument is prohibited at position {index}")


def _lookup_metric(value: Any, dotted_key: str) -> Any:
    current = value
    for part in dotted_key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise KeyError(dotted_key)
        current = current[part]
    if not isinstance(current, (str, int, float, bool)) and current is not None:
        raise TypeError(f"metric {dotted_key} must resolve to a scalar")
    return current


def run_adapter(
    *, benchmark: Mapping[str, Any], checkout: pathlib.Path, command: Sequence[str],
    output: pathlib.Path, timeout_seconds: int, task_ids: Sequence[str],
    official_result: pathlib.Path | None = None, metrics: Sequence[str] = (),
) -> dict[str, Any]:
    validate_command(command)
    expected = str(benchmark.get("official_evaluation_commit") or benchmark["commit"])
    identity_before = verify_checkout(checkout, expected)
    output = output.resolve()
    checkout_resolved = checkout.resolve()
    root_resolved = ROOT.resolve()
    if output == root_resolved or root_resolved in output.parents or output == checkout_resolved or checkout_resolved in output.parents:
        raise ValueError("benchmark receipt output must be external to CGNK and the official checkout")
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(command), cwd=checkout_resolved, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
            check=False, env=os.environ.copy(),
        )
        return_code: int | None = completed.returncode
        stdout = sanitize_output(completed.stdout, checkout=checkout_resolved)
        stderr = sanitize_output(completed.stderr, checkout=checkout_resolved)
        combined = f"{stdout}\n{stderr}".casefold()
        environment_blocked = any(marker in combined for marker in (
            "docker daemon", "cannot connect to the docker", "no space left on device",
            "cuda is not available", "connection timed out", "temporary failure in name resolution",
        ))
        status = "ENVIRONMENT_BLOCKED" if environment_blocked else ("PASS" if completed.returncode == 0 else "FAIL")
    except subprocess.TimeoutExpired as exc:
        return_code = None
        stdout = sanitize_output(str(exc.stdout or ""), checkout=checkout_resolved)
        stderr = sanitize_output(str(exc.stderr or ""), checkout=checkout_resolved)
        status = "ENVIRONMENT_BLOCKED"
    identity_after = verify_checkout(checkout, expected)
    if identity_after != identity_before:
        raise RuntimeError("official benchmark checkout identity changed during evaluation")
    official: dict[str, Any] | None = None
    if official_result is not None:
        resolved_result = official_result.resolve(strict=True)
        parsed = json.loads(resolved_result.read_text(encoding="utf-8"))
        official = {
            "result_hash": file_hash(resolved_result),
            "metrics": {key: _lookup_metric(parsed, key) for key in metrics},
        }
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "kind": "CGKNRelease056PublicBenchmarkReceipt",
        "benchmark_id": benchmark["id"],
        "repository": benchmark["repository"],
        "official_commit": expected,
        "official_tree": identity_before["tree"],
        "official_checkout_clean_before_after": True,
        "license": benchmark["license"],
        "redistribution": benchmark["redistribution"],
        "task_ids": list(task_ids),
        "task_count": len(task_ids),
        "command": [pathlib.Path(command[0]).name, *command[1:]],
        "timeout_seconds": timeout_seconds,
        "return_code": return_code,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "official_result": official,
        "dataset_copied_into_cgnk": False,
        "official_evaluator_modified": False,
        "credentials_recorded": False,
        "leaderboard_submission": False,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    output.mkdir(parents=True, exist_ok=False)
    (output / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an unmodified pinned public benchmark harness externally")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--checkout", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--official-result", type=pathlib.Path)
    parser.add_argument("--metric", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_id = {str(item["id"]): item for item in manifest["public_benchmarks"]}
    if args.benchmark not in by_id:
        parser.error(f"unknown benchmark: {args.benchmark}")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        receipt = run_adapter(
            benchmark=by_id[args.benchmark], checkout=args.checkout, command=command,
            output=args.output, timeout_seconds=args.timeout_seconds,
            task_ids=args.task_id, official_result=args.official_result, metrics=args.metric,
        )
    except (OSError, ValueError, KeyError, RuntimeError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{args.benchmark}: {receipt['status']}")
    return 0 if receipt["status"] in {"PASS", "ENVIRONMENT_BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
