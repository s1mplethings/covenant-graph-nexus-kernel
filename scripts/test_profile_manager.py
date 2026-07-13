from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any


TEST_PROFILES = {"unit", "focused", "integration", "browser", "live_provider", "delivery", "recovery", "soak", "default", "full_all"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileLedger:
    def __init__(self, path: str | pathlib.Path, *, run_id: str, candidate_id: str) -> None:
        self.path = pathlib.Path(path)
        self.run_id = run_id
        self.candidate_id = candidate_id

    def append_result(
        self,
        *,
        profile: str,
        command: str,
        result_file: str,
        status: str,
        exit_code: int,
        candidate_id: str | None = None,
        duration_seconds: float = 0.0,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if profile not in TEST_PROFILES:
            raise ValueError(f"unsupported test profile: {profile}")
        row = {
            "created_at": utc_now(),
            "run_id": self.run_id,
            "candidate_id": candidate_id or self.candidate_id,
            "profile": profile,
            "command": command,
            "result_file": result_file,
            "status": status,
            "exit_code": int(exit_code),
            "duration_seconds": float(duration_seconds),
            "data": data or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def profile_boundary_gate(rows: list[dict[str, Any]], *, required_profiles: list[str] | None = None, candidate_id: str = "") -> dict[str, Any]:
    required = set(required_profiles or [])
    by_profile: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_profile.setdefault(str(row.get("profile", "")), []).append(row)
    missing = sorted(profile for profile in required if profile not in by_profile)
    result_files: dict[str, str] = {}
    duplicate_result_files: list[dict[str, str]] = []
    for profile, profile_rows in by_profile.items():
        latest = profile_rows[-1]
        result_file = str(latest.get("result_file", ""))
        if result_file in result_files and result_file:
            duplicate_result_files.append({"first_profile": result_files[result_file], "second_profile": profile, "result_file": result_file})
        result_files[result_file] = profile
    wrong_candidate = [row for row in rows if candidate_id and row.get("candidate_id") != candidate_id]
    failed = [row for row in rows if row.get("status") not in {"PASS", "PASS_WITH_LIMITS"} or int(row.get("exit_code", 1)) != 0]
    ok = not missing and not duplicate_result_files and not wrong_candidate and not failed
    return {
        "status": "PASS" if ok else "NEEDS_REWORK",
        "missing_profiles": missing,
        "duplicate_result_files": duplicate_result_files,
        "wrong_candidate": wrong_candidate,
        "failed_profiles": failed,
    }
