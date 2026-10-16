from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def profile_commands(profile: str) -> list[list[str]]:
    fast = [
        [PYTHON, "-m", "compileall", "-q", "cgkn", "contracts", "scripts"],
        [PYTHON, "scripts/product_direction_gate.py"],
        [PYTHON, "scripts/kernel_architecture_gate.py"],
        [PYTHON, "scripts/test_architecture_gate.py"],
        [PYTHON, "scripts/kernel_completeness_gate.py"],
        [PYTHON, "scripts/verify_kernel_test_receipt.py"],
        [PYTHON, "scripts/receipt_freshness.py"],
        [PYTHON, "scripts/baseline_ledger.py"],
    ]
    for name in ("unit", "boundary", "fault", "security", "local-functional"):
        fast.append([PYTHON, "scripts/run_kernel_profiles.py", "--profile", name])
    fast.extend([
        [PYTHON, "-m", "pytest", "-q", "tests/application/software_project"],
        [PYTHON, "scripts/run_semantic_artifact_experiment.py", "--profile", "schema"],
        [PYTHON, "scripts/run_semantic_artifact_experiment.py", "--profile", "fake"],
    ])
    if profile == "full":
        fast.extend([
            [PYTHON, "scripts/run_kernel_profiles.py", "--profile", "full-core"],
            [PYTHON, "scripts/run_kernel_profiles.py", "--profile", "active-repository"],
            [PYTHON, "scripts/run_semantic_artifact_experiment.py", "--profile", "live-repair"],
        ])
    return fast


def run(profile: str, baseline: str) -> dict[str, Any]:
    started = time.perf_counter()
    records: list[dict[str, Any]] = []
    for command in profile_commands(profile):
        clock = time.perf_counter()
        completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
        records.append({
            "argv": command,
            "returncode": completed.returncode,
            "duration_ms": int((time.perf_counter() - clock) * 1000),
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-2000:],
        })
        if completed.returncode:
            break
    status = "PASS" if len(records) == len(profile_commands(profile)) and all(item["returncode"] == 0 for item in records) else "FAIL"
    return {
        "kind": "CGKNBaselineRegressionReceipt",
        "schema_version": "1.0",
        "baseline": baseline,
        "profile": profile,
        "status": status,
        "commands": records,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="current")
    parser.add_argument("--profile", choices=("fast", "full"), required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    value = run(args.profile, args.baseline)
    rendered = json.dumps(value, indent=2) + "\n"
    if args.output:
        path = ROOT / args.output
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if value["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
