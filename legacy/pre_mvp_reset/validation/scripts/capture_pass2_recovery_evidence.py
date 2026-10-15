from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_KIT_SOURCE = ROOT / "tools" / "cgkn-agent-kit" / "src"
if str(AGENT_KIT_SOURCE) not in sys.path:
    sys.path.insert(0, str(AGENT_KIT_SOURCE))

from cgkn_agent_kit import core  # noqa: E402


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(root: pathlib.Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]


def manifest_hash(entries: list[dict[str, Any]]) -> str:
    encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def safe_status(status: dict[str, Any], copied_root: pathlib.Path) -> dict[str, Any]:
    allowed = {
        "exists",
        "state",
        "job_alive",
        "terminal_reason",
        "formal_evidence_status",
        "resume_safe",
        "candidate_present",
        "execution_classification",
        "waiting_for",
        "next_action",
        "provider_attempts_started",
        "provider_attempts_completed",
        "provider_successes",
        "provider_timeouts",
        "admitted_provider_result_present",
    }
    projected = {key: status.get(key) for key in sorted(allowed)}
    projected["copy_root"] = copied_root.name
    return projected


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture read-only pass-2 recovery evidence in an isolated copy")
    parser.add_argument("--source", type=pathlib.Path, default=ROOT / ".cgkn" / "agent-kit")
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    output_dir = args.output_dir.resolve()
    copy_root = output_dir / "isolated_agent_kit"
    output_dir.mkdir(parents=True, exist_ok=True)
    if copy_root.exists():
        shutil.rmtree(copy_root)

    before = tree_manifest(source)
    shutil.copytree(source, copy_root)
    copied = tree_manifest(copy_root)
    observed = core.generation_job_status(copy_root)
    after = tree_manifest(source)

    job = json.loads((copy_root / "generation_job.json").read_text(encoding="utf-8"))
    result = json.loads((copy_root / "generation_result.json").read_text(encoding="utf-8"))
    pending = list(result.get("pending_requests", []))
    current_head = git("rev-parse", "HEAD")
    recorded_head = str(job.get("source_commit_sha", "") or result.get("commit_sha", ""))
    report = {
        "kind": "CGKNPass2RecoveryIsolationEvidence",
        "schema_version": "1.0",
        "formal_evidence_status": "NOT_EVALUATED",
        "support_result": "PASS" if before == after and before == copied else "FAIL",
        "original_unchanged": before == after,
        "copy_matches_original": before == copied,
        "original_manifest_sha256_before": manifest_hash(before),
        "original_manifest_sha256_after": manifest_hash(after),
        "copy_manifest_sha256": manifest_hash(copied),
        "file_count": len(before),
        "status_from_isolated_copy": safe_status(observed, copy_root),
        "wait_identity": {
            "run_id": job.get("run_id"),
            "generation_job_id": job.get("job_id"),
            "request_id": pending[0].get("job_id") if pending else "",
            "correlation_id": pending[0].get("attempt_id") if pending else "",
            "request_hash": pending[0].get("request_hash") if pending else "",
            "deadline": None,
            "responded": pending[0].get("responded") if pending else None,
            "consumed": pending[0].get("consumed") if pending else None,
        },
        "identity_drift": {
            "recorded_commit_sha": recorded_head,
            "current_commit_sha": current_head,
            "commit_changed": bool(recorded_head and recorded_head != current_head),
            "working_tree_changes_present": bool(git("status", "--short")),
            "decision": "SAFE_REFUSAL_REQUIRES_NEW_RUN_OR_FIXED_IDENTITY_COPY",
            "old_hashes_rewritten": False,
        },
        "interpretation": {
            "normal_wait": observed.get("execution_classification") == "external_wait",
            "automatic_recovery_claimed": False,
            "safe_refusal_counted_as_recovery": False,
            "original_run_action": "READ_ONLY",
        },
    }
    report_path = output_dir / "recovery_isolation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["support_result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
