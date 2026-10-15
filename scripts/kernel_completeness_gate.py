from __future__ import annotations

import json
import subprocess

from kernel_gate_common import VALID_COMPLETENESS, ROOT, load_json, result
from kernel_source_identity import identity
from test_architecture_gate import check as coverage_check
from verify_kernel_test_receipt import verify as verify_receipt


STRICT_P0 = {
    "cgkn/artifacts/store.py", "cgkn/orchestration/capability_tree.py", "cgkn/orchestration/execution_dag.py",
    "cgkn/orchestration/tree_edits.py", "cgkn/execution/contracts.py", "cgkn/providers/client.py",
    "cgkn/state/store.py", "cgkn/executors/llm.py", "cgkn/executors/registry.py",
    "cgkn/runtime/dag_runner.py", "cgkn/capabilities/registry.py", "cgkn/growth/admission.py",
    "cgkn/growth/loop.py", "cgkn/agent/composer.py", "cgkn/agent/project_loop.py",
}
ALLOWED_EVIDENCE_PATHS = {
    "governance/kernel_completeness.json", "governance/kernel_coverage_report.json",
    "governance/kernel_test_receipt.json", "project_management/current/active_iteration.json",
}


def _changed_since(commit: str) -> set[str]:
    completed = subprocess.run(["git", "diff", "--name-only", f"{commit}..HEAD"], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    return {line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()}


def check() -> dict:
    errors: list[str] = []
    value = load_json("governance/kernel_completeness.json")
    if value.get("functional_readiness") != "LEVEL_4": errors.append("functional_readiness_changed")
    if value.get("kernel_foundation") not in {"PARTIAL", "COMPLETE", "BLOCKED"}: errors.append("invalid_kernel_foundation")
    layers = dict(value.get("layers", {}))
    lower_incomplete = False
    for level in sorted(layers):
        entry = layers[level]
        status = entry.get("status")
        if status not in VALID_COMPLETENESS: errors.append(f"invalid_status:{level}")
        if status == "COMPLETE":
            if entry.get("blockers"): errors.append(f"complete_with_blocker:{level}")
            if not entry.get("evidence"): errors.append(f"complete_without_evidence:{level}")
            if lower_incomplete: errors.append(f"upper_complete_with_lower_incomplete:{level}")
        elif level != "L6":
            lower_incomplete = True
    if value.get("kernel_foundation") == "COMPLETE" and any(entry.get("status") != "COMPLETE" for level, entry in layers.items() if level != "L6"):
        errors.append("foundation_complete_with_incomplete_layer")
    coverage = coverage_check()
    if coverage["status"] != "PASS": errors.append("test_coverage_manifest_failed")
    if value.get("kernel_foundation") == "COMPLETE":
        if layers.get("L6", {}).get("status") != "BLOCKED": errors.append("l6_must_remain_blocked")
        try:
            receipt = load_json("governance/kernel_test_receipt.json")
            coverage_report = load_json("governance/kernel_coverage_report.json")
            source = identity(str(receipt["source_commit"]))
            current = identity("HEAD")
        except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
            errors.append(f"evidence_unreadable:{exc}")
        else:
            for field in ("source_commit", "source_tree_sha", "core_source_hash"):
                if receipt.get(field) != source.get(field) or coverage_report.get(field) != source.get(field): errors.append(f"evidence_identity_mismatch:{field}")
            if current.get("core_source_hash") != source.get("core_source_hash"): errors.append("stale_core_source_hash")
            if coverage_report.get("pytest_result", {}).get("exit_code") != 0: errors.append("coverage_pytest_failed")
            if verify_receipt(ROOT / "governance/kernel_test_receipt.json").get("status") != "PASS": errors.append("receipt_verification_failed")
            manifest = load_json("governance/test_coverage_manifest.json")
            passed = set(receipt.get("test_node_ids", []))
            for source_path, entry in manifest.get("sources", {}).items():
                for case in entry.get("test_cases", []):
                    if case.get("nodeid") not in passed: errors.append(f"required_test_not_passed:{source_path}:{case.get('nodeid')}")
                measured = coverage_report.get("files", {}).get(source_path)
                if not measured:
                    errors.append(f"coverage_missing:{source_path}")
                    continue
                criticality = entry.get("criticality")
                statement_min, branch_min = (95, 90) if source_path in STRICT_P0 else (90, 85) if criticality == "P0" else (85, 75)
                if float(measured.get("statement_percent", 0)) < statement_min: errors.append(f"statement_below_threshold:{source_path}")
                if float(measured.get("branch_percent", 0)) < branch_min: errors.append(f"branch_below_threshold:{source_path}")
            required_profiles = {"static", "unit", "boundary", "fault", "security", "local-functional", "full-core", "active-repository", "live-provider"}
            profiles = {str(item.get("profile")): item.get("status") for item in receipt.get("profile_results", [])}
            for profile in sorted(required_profiles - set(profiles)): errors.append(f"profile_missing:{profile}")
            for profile, status in profiles.items():
                if status not in ({"PASS", "BLOCKED_ENVIRONMENT"} if profile == "live-provider" else {"PASS"}): errors.append(f"profile_not_pass:{profile}:{status}")
            try:
                changed = _changed_since(str(receipt["source_commit"]))
                disallowed = {path for path in changed if path not in ALLOWED_EVIDENCE_PATHS and not path.startswith("project_management/summaries/")}
                for path in sorted(disallowed): errors.append(f"evidence_commit_modified_source:{path}")
            except RuntimeError as exc:
                errors.append(f"evidence_diff_failed:{exc}")
    return result("CGKNKernelCompletenessGate", errors, kernel_foundation=value.get("kernel_foundation"))


if __name__ == "__main__":
    value = check(); print(json.dumps(value, indent=2)); raise SystemExit(0 if value["status"] == "PASS" else 1)
