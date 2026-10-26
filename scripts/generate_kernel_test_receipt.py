from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import platform
import sys
from datetime import datetime, timezone

from kernel_source_identity import ROOT, identity


def _hash_file(path: pathlib.Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: dict) -> str:
    payload = {key: item for key, item in value.items() if key != "receipt_hash"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def generate(profile_path: pathlib.Path, coverage_path: pathlib.Path, source_commit: str) -> dict:
    source = identity(source_commit)
    profiles = json.loads(profile_path.read_text(encoding="utf-8"))
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    results = list(profiles.get("results", []))
    commands = [{"argv": command.get("argv", []), "returncode": command.get("returncode")} for profile in results for command in profile.get("commands", [])]
    totals = {key: sum(int(profile.get("totals", {}).get(key, 0)) for profile in results) for key in ("passed", "failed", "errors", "skipped")}
    totals["duration_seconds"] = round(sum(float(profile.get("duration_ms", 0)) for profile in results) / 1000, 3)
    nodeids = sorted({nodeid for profile in results if profile.get("status") == "PASS" for nodeid in profile.get("test_node_ids", [])})
    required_profiles = {"static", "unit", "boundary", "fault", "security", "local-functional", "full-core", "active-repository", "live-provider"}
    profile_names = {str(profile.get("profile")) for profile in results}
    coverage_matches = all(coverage.get(key) == source.get(key) for key in ("source_commit", "source_tree_sha", "core_source_hash"))
    verdict = "PASS" if required_profiles <= profile_names and all(profile.get("status") in {"PASS", "BLOCKED_ENVIRONMENT"} for profile in results) and totals["failed"] == totals["errors"] == 0 and coverage_matches and coverage.get("pytest_result", {}).get("exit_code") == 0 else "FAIL"
    value = {
        "kind": "CGKNKernelTestReceipt", "schema_version": "1.0",
        "source_commit": source["source_commit"], "source_tree_sha": source["source_tree_sha"], "core_source_hash": source["core_source_hash"],
        "commands": commands, "totals": totals, "test_node_ids": nodeids, "profile_results": results,
        "coverage_file_hash": _hash_file(coverage_path), "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "provider_network_usage": {"live_provider_executed": any(profile.get("profile") == "live-provider" and profile.get("status") == "PASS" for profile in results), "secret_persisted": False},
        "final_verdict": verdict,
    }
    value["receipt_hash"] = _canonical_hash(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", default="governance/kernel_test_receipt.json")
    args = parser.parse_args()
    value = generate(ROOT / args.profiles, ROOT / args.coverage, args.source_commit)
    (ROOT / args.output).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, indent=2))
    return 0 if value["final_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
