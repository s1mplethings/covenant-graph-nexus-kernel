from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "generated" / "dynamic_agent_tree_fix_eval" / "test_profiles"


PROFILE_MARKS = {
    "quick": "not (slow or e2e or live_provider or telegram or benchmark or longrun or long_journey or provider)",
    "regression": "not (longrun or long_journey or provider or live_provider or telegram)",
    "longrun": "longrun or long_journey or benchmark",
    "provider": "provider or live_provider",
    "e2e": "e2e",
    "all": "",
}

PROFILE_PATHS = {
    "quick": ["tests", "scripts"],
}


def run_profile(profile: str, *, out_dir: str | pathlib.Path = DEFAULT_OUT, timeout: int | None = None) -> dict[str, Any]:
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
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _write_profile_result(out, profile, result)
            return result
    command = [sys.executable, "-m", "pytest", "-q"]
    command.extend(PROFILE_PATHS.get(profile, []))
    if mark:
        command.extend(["-m", mark])
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["CGKN_INCLUDE_PROFILE_MARKS"] = "1"
    started = time.time()
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout or (900 if profile == "all" else 300), env=env)
        status = "PASS" if proc.returncode == 0 else "FAIL"
        result = {
            "profile": profile,
            "status": status,
            "classification": status.lower(),
            "exit_code": proc.returncode,
            "pytest_run": True,
            "command": " ".join(command),
            "duration_seconds": round(time.time() - started, 3),
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
            "stdout_tail": (exc.stdout if isinstance(exc.stdout, str) else "")[-4000:],
            "stderr_tail": (exc.stderr if isinstance(exc.stderr, str) else "")[-4000:],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
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
