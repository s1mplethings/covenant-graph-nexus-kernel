#!/usr/bin/env python3
"""Post-generation evaluator for frozen Pass 6 blind cases.

This module is never imported by the generation path.  It consumes a hidden
case only after the candidate workspace has been sealed by the caller.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


def _contained(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes candidate root: {relative}")
    return candidate


def evaluate(candidate_root: Path, hidden_case: dict[str, Any], timeout_seconds: float = 30.0) -> dict[str, Any]:
    candidate_root = candidate_root.resolve()
    checks: list[dict[str, Any]] = []
    for relative in hidden_case.get("required_files", []):
        path = _contained(candidate_root, str(relative))
        checks.append({"kind": "required_file", "path": str(relative), "passed": path.is_file()})

    safe_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_PROXY": "*",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
    }
    for probe in hidden_case.get("probes", []):
        argv = probe.get("argv", [])
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            checks.append({"kind": "runtime_probe", "passed": False, "reason": "invalid_argv"})
            continue
        try:
            completed = subprocess.run(
                argv,
                cwd=candidate_root,
                env=safe_env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=min(float(probe.get("timeout_seconds", timeout_seconds)), timeout_seconds),
                check=False,
            )
            stdout = completed.stdout or ""
            expected = str(probe.get("stdout_contains", ""))
            passed = completed.returncode == int(probe.get("returncode", 0)) and (not expected or expected in stdout)
            checks.append(
                {
                    "kind": "runtime_probe",
                    "argv": argv,
                    "returncode": completed.returncode,
                    "stdout_sha256": __import__("hashlib").sha256(stdout.encode("utf-8")).hexdigest(),
                    "passed": passed,
                }
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks.append({"kind": "runtime_probe", "argv": argv, "passed": False, "reason": type(exc).__name__})

    passed = bool(checks) and all(check.get("passed") is True for check in checks)
    return {
        "kind": "CGKNPass6BlindCaseEvaluation",
        "case_id": hidden_case.get("case_id"),
        "formal_evidence_status": "NOT_EVALUATED",
        "checks": checks,
        "status": "PASS" if passed else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--hidden-case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    hidden = json.loads(args.hidden_case.read_text(encoding="utf-8"))
    result = evaluate(args.candidate_root, hidden)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
