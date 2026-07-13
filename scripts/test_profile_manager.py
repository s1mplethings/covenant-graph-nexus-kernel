from __future__ import annotations

import json
import pathlib
import re
import hashlib
from datetime import datetime, timezone
from typing import Any


TEST_PROFILES = {
    "unit",
    "focused",
    "integration",
    "browser",
    "live_provider",
    "delivery",
    "recovery",
    "soak",
    "repo_default",
    "full_all",
    "e2e",
}

PROFILE_COMMAND_CONTRACTS: dict[str, re.Pattern[str]] = {
    "repo_default": re.compile(r"(^|\s)(python|py|python\.exe|[^ ]*python[^ ]*)\s+-m\s+pytest\s+-q(\s|$)", re.IGNORECASE),
    "full_all": re.compile(r"(--profile\s+full_all|--profile\s+all|--run-profile-marked|CGKN_TEST_PROFILE=full_all)", re.IGNORECASE),
    "e2e": re.compile(r"(\be2e\b|--profile\s+e2e)", re.IGNORECASE),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | pathlib.Path) -> str:
    target = pathlib.Path(path)
    return hashlib.sha256(target.read_bytes()).hexdigest()


class ProfileLedger:
    def __init__(self, path: str | pathlib.Path, *, run_id: str, candidate_id: str, commit_sha: str = "") -> None:
        self.path = pathlib.Path(path)
        self.run_id = run_id
        self.candidate_id = candidate_id
        self.commit_sha = commit_sha

    def append_result(
        self,
        *,
        profile: str,
        command: str,
        result_file: str,
        status: str,
        exit_code: int,
        candidate_id: str | None = None,
        run_id: str | None = None,
        commit_sha: str | None = None,
        duration_seconds: float = 0.0,
        started_at: str = "",
        finished_at: str = "",
        collected: int | None = None,
        passed: int | None = None,
        failed: int | None = None,
        skipped: int | None = None,
        skip_reasons: dict[str, int] | None = None,
        result_hash: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if profile not in TEST_PROFILES:
            raise ValueError(f"unsupported test profile: {profile}")
        resolved_result_hash = result_hash
        result_path = pathlib.Path(result_file)
        if not resolved_result_hash and result_path.exists() and result_path.is_file():
            resolved_result_hash = sha256_file(result_path)
        now = utc_now()
        row = {
            "created_at": now,
            "run_id": run_id or self.run_id,
            "candidate_id": candidate_id or self.candidate_id,
            "commit_sha": commit_sha if commit_sha is not None else self.commit_sha,
            "profile": profile,
            "command": command,
            "result_file": result_file,
            "result_hash": resolved_result_hash,
            "status": status,
            "exit_code": int(exit_code),
            "duration_seconds": float(duration_seconds),
            "started_at": started_at or now,
            "finished_at": finished_at or now,
            "collected": collected,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "skip_reasons": skip_reasons or {},
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


def _command_contract_failure(row: dict[str, Any]) -> str:
    profile = str(row.get("profile", ""))
    command = str(row.get("command", ""))
    pattern = PROFILE_COMMAND_CONTRACTS.get(profile)
    if pattern and not pattern.search(command):
        return f"{profile} command does not satisfy profile contract"
    if profile == "full_all" and re.fullmatch(r"[^ ]*python[^ ]*\s+-m\s+pytest\s+-q", command.strip(), re.IGNORECASE):
        return "full_all cannot reuse repo_default pytest command"
    if profile == "repo_default" and ("--run-profile-marked" in command or "--profile" in command):
        return "repo_default cannot include explicit profile markers"
    return ""


def _missing_count_fields(row: dict[str, Any]) -> list[str]:
    missing = []
    for key in ("collected", "passed", "failed", "skipped"):
        if row.get(key) is None:
            missing.append(key)
    return missing


def profile_boundary_gate(
    rows: list[dict[str, Any]],
    *,
    required_profiles: list[str] | None = None,
    candidate_id: str = "",
    run_id: str = "",
    commit_sha: str = "",
) -> dict[str, Any]:
    required = set(required_profiles or [])
    by_profile: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_profile.setdefault(str(row.get("profile", "")), []).append(row)
    missing = sorted(profile for profile in required if profile not in by_profile)
    result_files: dict[str, str] = {}
    result_hashes: dict[str, str] = {}
    duplicate_result_files: list[dict[str, str]] = []
    duplicate_result_hashes: list[dict[str, str]] = []
    invalid_commands: list[dict[str, str]] = []
    missing_result_hash: list[dict[str, Any]] = []
    missing_times: list[dict[str, Any]] = []
    missing_counts: list[dict[str, Any]] = []
    uncategorized_skips: list[dict[str, Any]] = []
    for profile, profile_rows in by_profile.items():
        latest = profile_rows[-1]
        result_file = str(latest.get("result_file", ""))
        if result_file in result_files and result_file:
            duplicate_result_files.append({"first_profile": result_files[result_file], "second_profile": profile, "result_file": result_file})
        result_files[result_file] = profile
        result_hash = str(latest.get("result_hash", ""))
        if result_hash in result_hashes and result_hash:
            duplicate_result_hashes.append({"first_profile": result_hashes[result_hash], "second_profile": profile, "result_hash": result_hash})
        if result_hash:
            result_hashes[result_hash] = profile
        else:
            missing_result_hash.append(latest)
        if not latest.get("started_at") or not latest.get("finished_at"):
            missing_times.append(latest)
        missing_fields = _missing_count_fields(latest)
        if missing_fields:
            missing_counts.append({"profile": profile, "missing": missing_fields})
        skipped = int(latest.get("skipped") or 0)
        skip_reasons = latest.get("skip_reasons", {})
        if skipped and (not isinstance(skip_reasons, dict) or sum(int(value or 0) for value in skip_reasons.values()) != skipped):
            uncategorized_skips.append({"profile": profile, "skipped": skipped, "skip_reasons": skip_reasons if isinstance(skip_reasons, dict) else {}})
        command_failure = _command_contract_failure(latest)
        if command_failure:
            invalid_commands.append({"profile": profile, "reason": command_failure, "command": str(latest.get("command", ""))})
    wrong_candidate = [row for row in rows if candidate_id and row.get("candidate_id") != candidate_id]
    wrong_run = [row for row in rows if run_id and row.get("run_id") != run_id]
    wrong_commit = [row for row in rows if commit_sha and row.get("commit_sha") != commit_sha]
    failed = []
    for row in rows:
        exit_code = row.get("exit_code", 1)
        if row.get("status") not in {"PASS", "PASS_WITH_LIMITS"} or exit_code is None or int(exit_code) != 0:
            failed.append(row)
    ok = not any(
        (
            missing,
            duplicate_result_files,
            duplicate_result_hashes,
            invalid_commands,
            missing_result_hash,
            missing_times,
            missing_counts,
            uncategorized_skips,
            wrong_candidate,
            wrong_run,
            wrong_commit,
            failed,
        )
    )
    return {
        "status": "PASS" if ok else "NEEDS_REWORK",
        "missing_profiles": missing,
        "duplicate_result_files": duplicate_result_files,
        "duplicate_result_hashes": duplicate_result_hashes,
        "invalid_commands": invalid_commands,
        "missing_result_hash": missing_result_hash,
        "missing_times": missing_times,
        "missing_counts": missing_counts,
        "uncategorized_skips": uncategorized_skips,
        "wrong_candidate": wrong_candidate,
        "wrong_run": wrong_run,
        "wrong_commit": wrong_commit,
        "failed_profiles": failed,
    }
