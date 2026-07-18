from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

import hashlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "generated" / "dynamic_agent_tree_fix_eval" / "test_profiles"


PROFILE_MARKS = {
    "quick": "not (slow or e2e or live_provider or telegram or benchmark or longrun or long_journey or provider)",
    "regression": "not (longrun or long_journey or provider or live_provider or telegram)",
    "longrun": "longrun or long_journey or benchmark",
    "provider": "provider or live_provider",
    "e2e": "e2e",
    "all": "",
    "full_all": "",
}

PROFILE_PATHS = {
    "quick": ["tests", "scripts"],
}


def _parse_counts(output: str) -> dict[str, int]:
    counts = {key: 0 for key in ("collected", "executed", "passed", "failed", "skipped", "deselected")}
    collected = re.search(r"collected\s+(\d+)\s+items?", output)
    if collected:
        counts["collected"] = int(collected.group(1))
    for key in ("passed", "failed", "skipped", "deselected"):
        matches = re.findall(rf"(\d+)\s+{key}", output)
        if matches:
            counts[key] = int(matches[-1])
    counts["executed"] = counts["passed"] + counts["failed"] + counts["skipped"]
    if not counts["collected"]:
        counts["collected"] = counts["executed"] + counts["deselected"]
    return counts


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _finalize_result(
    result: dict[str, Any], *, run_id: str, candidate_id: str, candidate_hash: str, commit_sha: str
) -> dict[str, Any]:
    result.update(
        {
            "kind": "CGKNTestProfileResult",
            "schema_version": "1.0",
            "run_id": run_id,
            "candidate_id": candidate_id,
            "candidate_hash": candidate_hash,
            "commit_sha": commit_sha,
            "producer": "scripts/run_test_profile.py",
        }
    )
    result["artifact_hash"] = ""
    result["artifact_hash"] = _sha256_text(
        json.dumps({**result, "artifact_hash": ""}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    return result


def run_profile(
    profile: str,
    *,
    out_dir: str | pathlib.Path = DEFAULT_OUT,
    timeout: int | None = None,
    run_id: str = "",
    candidate_id: str = "CGKN",
    candidate_hash: str = "",
    commit_sha: str = "",
) -> dict[str, Any]:
    if profile not in PROFILE_MARKS:
        raise ValueError(f"unknown profile: {profile}")
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mark = PROFILE_MARKS[profile]
    if not commit_sha:
        commit_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if not candidate_hash:
        candidate_hash = _sha256_text(commit_sha)
    run_id = run_id or f"test-profile-{profile}-{int(time.time())}"
    if profile == "provider":
        # Provider profile is allowed to be BLOCKED when readiness is unavailable.
        sys.path.insert(0, str(ROOT / "scripts"))
        from agent_leaf_provider_guard import provider_readiness

        readiness = provider_readiness(out_dir=out / "provider_readiness", smoke=True, timeout=45)
        if not readiness.get("provider_ready"):
            result = {
                "profile": profile,
                "status": "BLOCKED",
                "classification": "provider_unavailable",
                "exit_code": 0,
                "pytest_run": False,
                "reason": readiness.get("public_safe_error", "provider unavailable"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _finalize_result(result, run_id=run_id, candidate_id=candidate_id, candidate_hash=candidate_hash, commit_sha=commit_sha)
            _write_profile_result(out, profile, result)
            return result
    command = [sys.executable, "-m", "pytest", "-q", "-ra"]
    command.extend(PROFILE_PATHS.get(profile, []))
    if mark:
        command.extend(["-m", mark])
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["CGKN_INCLUDE_PROFILE_MARKS"] = "1"
    started = time.time()
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout or (900 if profile == "all" else 300), env=env)
        counts = _parse_counts((proc.stdout or "") + "\n" + (proc.stderr or ""))
        unexplained_incomplete = profile == "full_all" and (
            counts["skipped"] or counts["deselected"] or not counts["collected"] or counts["executed"] != counts["collected"]
        )
        status = "PASS" if proc.returncode == 0 and not unexplained_incomplete else "FAIL"
        stdout_path = out / f"{profile}_stdout.txt"
        stderr_path = out / f"{profile}_stderr.txt"
        stdout_path.write_text(proc.stdout or "", encoding="utf-8")
        stderr_path.write_text(proc.stderr or "", encoding="utf-8")
        result = {
            "kind": "CGKNTestProfileResult",
            "schema_version": "1.0",
            "run_id": run_id,
            "candidate_id": candidate_id,
            "candidate_hash": candidate_hash,
            "commit_sha": commit_sha,
            "producer": "scripts/run_test_profile.py",
            "profile": profile,
            "status": status,
            "classification": status.lower(),
            "exit_code": proc.returncode,
            "pytest_run": True,
            "command": " ".join(command),
            "duration_seconds": round(time.time() - started, 3),
            **counts,
            "timeout": False,
            "stdout_ref": str(stdout_path.resolve()),
            "stdout_hash": _sha256_text(proc.stdout or ""),
            "stderr_ref": str(stderr_path.resolve()),
            "stderr_hash": _sha256_text(proc.stderr or ""),
            "stdout_tail": (proc.stdout or "")[-4000:],
            "stderr_tail": (proc.stderr or "")[-4000:],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    except subprocess.TimeoutExpired as exc:
        result = {
            "kind": "CGKNTestProfileResult",
            "schema_version": "1.0",
            "run_id": run_id,
            "candidate_id": candidate_id,
            "candidate_hash": candidate_hash,
            "commit_sha": commit_sha,
            "producer": "scripts/run_test_profile.py",
            "profile": profile,
            "status": "TIMEOUT",
            "classification": "timeout",
            "exit_code": None,
            "pytest_run": True,
            "command": " ".join(command),
            "duration_seconds": round(time.time() - started, 3),
            "collected": 0,
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "deselected": 0,
            "timeout": True,
            "stdout_tail": (exc.stdout if isinstance(exc.stdout, str) else "")[-4000:],
            "stderr_tail": (exc.stderr if isinstance(exc.stderr, str) else "")[-4000:],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    _finalize_result(result, run_id=run_id, candidate_id=candidate_id, candidate_hash=candidate_hash, commit_sha=commit_sha)
    _write_profile_result(out, profile, result)
    return result


def _write_profile_result(out: pathlib.Path, profile: str, result: dict[str, Any]) -> None:
    (out / f"{profile}_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# {profile} profile", "", *[f"- {key}: {value}" for key, value in result.items() if key not in {"stdout_tail", "stderr_tail"}]]
    (out / f"{profile}_result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=sorted(PROFILE_MARKS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--timeout", type=int, default=0)
    args = parser.parse_args()
    result = run_profile(args.profile, out_dir=args.out, timeout=args.timeout or None)
    print(json.dumps({k: result.get(k) for k in ("profile", "status", "classification", "exit_code", "pytest_run")}, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
