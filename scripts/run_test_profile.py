from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import hashlib
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "generated" / "dynamic_agent_tree_fix_eval" / "test_profiles"


PROFILE_MARKS = {
    "repo_default": "",
    "quick": "not (slow or e2e or live_provider or telegram or benchmark or longrun or long_journey or provider)",
    "regression": "not (longrun or long_journey or provider or live_provider or telegram)",
    "longrun": "longrun or long_journey or benchmark",
    "provider": "provider or live_provider",
    "e2e": "e2e",
    "full_all": "",
}

PROFILE_PATHS = {
    "quick": ["tests", "scripts"],
}


PROFILE_ALIASES = {"all": "full_all", "default": "repo_default"}


def _normalize_profile(profile: str) -> str:
    return PROFILE_ALIASES.get(profile, profile)


def _pytest_counts(stdout: str, stderr: str) -> dict[str, Any]:
    text = f"{stdout}\n{stderr}"
    collected_match = re.search(r"collected\s+(\d+)\s+items?", text)
    summary_match = re.search(r"=+\s*(?P<summary>[^=\n]*(?:passed|failed|skipped|error)[^=\n]*)\s+in\s+[\d.]+s\s*=+", text, re.IGNORECASE)
    counts = {"collected": None, "passed": 0, "failed": 0, "skipped": 0, "skip_reasons": {}}
    if collected_match:
        counts["collected"] = int(collected_match.group(1))
    summary = summary_match.group("summary") if summary_match else text
    for key in ("passed", "failed", "skipped"):
        match = re.search(rf"(\d+)\s+{key}", summary, re.IGNORECASE)
        if match:
            counts[key] = int(match.group(1))
    if counts["collected"] is None:
        counts["collected"] = int(counts["passed"]) + int(counts["failed"]) + int(counts["skipped"])
    skip_reasons: dict[str, int] = {}
    for line in text.splitlines():
        match = re.search(r"SKIPPED\s+\[(\d+)\]\s+[^:]+:\s*(.+)", line)
        if match:
            reason = match.group(2).strip()
            skip_reasons[reason] = skip_reasons.get(reason, 0) + int(match.group(1))
    if counts["skipped"] and not skip_reasons:
        skip_reasons["pytest_skip_summary_unavailable"] = int(counts["skipped"])
    counts["skip_reasons"] = skip_reasons
    return counts


def _sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_profile(profile: str, *, out_dir: str | pathlib.Path = DEFAULT_OUT, timeout: int | None = None) -> dict[str, Any]:
    profile = _normalize_profile(profile)
    if profile not in PROFILE_MARKS:
        raise ValueError(f"unknown profile: {profile}")
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mark = PROFILE_MARKS[profile]
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
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "collected": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "skip_reasons": {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            result_file = _write_profile_result(out, profile, result)
            result["result_file"] = str(result_file)
            result["result_hash"] = _sha256_file(result_file)
            return result
    command = [sys.executable, "-m", "pytest", "-q"]
    command.extend(PROFILE_PATHS.get(profile, []))
    if profile == "full_all":
        command.append("--run-profile-marked")
    if mark:
        command.extend(["-m", mark])
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["CGKN_TEST_PROFILE"] = profile
    if profile != "repo_default":
        env["CGKN_INCLUDE_PROFILE_MARKS"] = "1"
    else:
        env.pop("CGKN_INCLUDE_PROFILE_MARKS", None)
    started = time.time()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout or (900 if profile == "full_all" else 300), env=env)
        status = "PASS" if proc.returncode == 0 else "FAIL"
        counts = _pytest_counts(proc.stdout or "", proc.stderr or "")
        result = {
            "profile": profile,
            "status": status,
            "classification": status.lower(),
            "exit_code": proc.returncode,
            "pytest_run": True,
            "command": " ".join(command),
            "duration_seconds": round(time.time() - started, 3),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            **counts,
            "stdout_tail": (proc.stdout or "")[-4000:],
            "stderr_tail": (proc.stderr or "")[-4000:],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    except subprocess.TimeoutExpired as exc:
        result = {
            "profile": profile,
            "status": "TIMEOUT",
            "classification": "timeout",
            "exit_code": None,
            "pytest_run": True,
            "command": " ".join(command),
            "duration_seconds": round(time.time() - started, 3),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "collected": None,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "skip_reasons": {},
            "stdout_tail": (exc.stdout if isinstance(exc.stdout, str) else "")[-4000:],
            "stderr_tail": (exc.stderr if isinstance(exc.stderr, str) else "")[-4000:],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    result_file = _write_profile_result(out, profile, result)
    result["result_file"] = str(result_file)
    result["result_hash"] = _sha256_file(result_file)
    return result


def _write_profile_result(out: pathlib.Path, profile: str, result: dict[str, Any]) -> pathlib.Path:
    result_file = out / f"{profile}_result.json"
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# {profile} profile", "", *[f"- {key}: {value}" for key, value in result.items() if key not in {"stdout_tail", "stderr_tail"}]]
    (out / f"{profile}_result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=sorted(set(PROFILE_MARKS) | set(PROFILE_ALIASES)))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--timeout", type=int, default=0)
    args = parser.parse_args()
    result = run_profile(args.profile, out_dir=args.out, timeout=args.timeout or None)
    print(json.dumps({k: result.get(k) for k in ("profile", "status", "classification", "exit_code", "pytest_run")}, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
