#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import zipfile
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import agent_problem_classifier
import large_project_complexity_audit


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def base_state(run_dir: pathlib.Path) -> dict[str, Any]:
    return {
        "latest_reports": {"agent_led_verify": str(run_dir / "agent_led_verify_report.json"), "large_project_benchmark": str(run_dir / "large_project_benchmark_report.json")},
        "latest_report_status": {"agent_led_verify": "pass", "large_project_benchmark": "pass"},
        "agent_led": {"director_loop_used": True, "decision_ledger_exists": True, "selected_tools": ["formal_generation:local_only", "final_promotion"]},
        "provider": {"provider_available": True, "provider_error_type": None, "provider_quota_exceeded": False, "local_model_available": True},
        "generation": {
            "formal_generation_materialized": True,
            "writable_project_files_exist": True,
            "candidate_exists": True,
            "final_project_exists": True,
            "semantic_review_status": "pass",
        },
        "delivery": {
            "delivery_manifest_exists": True,
            "delivery_manifest": str(run_dir / "final_project" / "delivery_manifest.json"),
            "final_bundle_exists": True,
            "final_bundle": str(run_dir / "final_project" / "final_project_bundle.zip"),
            "screenshot_evidence_exists": True,
            "screenshot_evidence": str(run_dir / "final_project" / "artifacts" / "screenshots" / "overview.png"),
            "public_gate_status": "READY",
        },
        "quality": {
            "complexity_status": "pass",
            "page_count": 9,
            "module_count": 9,
            "product_acceptance_status": "pass",
            "missing_core_features": [],
            "weak_features": [],
            "ux_score": 85,
            "commercial_status": "COMMERCIAL_READY",
            "remaining_blockers": [],
            "model_participation_status": "pass",
            "artifact_integrity_status": "pass",
            "security_status": "pass",
        },
        "tests": {"last_pytest_status": "pass", "failed_tests": []},
        "ledgers": {"agent_decision_ledger": str(run_dir / "artifacts" / "agent_decision_ledger.jsonl"), "model_call_ledger": str(run_dir / "artifacts" / "model_call_ledger.jsonl")},
    }


def make_small_project(root: pathlib.Path) -> dict[str, Any]:
    project = root / "small_final_project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "README.md").write_text("Dashboard and tasks only.\n", encoding="utf-8")
    (project / "index.html").write_text("<h1>Small</h1>\n", encoding="utf-8")
    write_json(project / "page_map.json", {"pages": [{"id": "dashboard"}, {"id": "tasks"}]})
    write_json(project / "feature_matrix.json", {"modules": [{"id": "dashboard"}]})
    return large_project_complexity_audit.audit_large_project(project)


def make_marker_zip(root: pathlib.Path) -> pathlib.Path:
    final_project = root / "marker_final_project"
    final_project.mkdir(parents=True, exist_ok=True)
    (final_project / "README.md").write_text("Marker zip fixture.\n", encoding="utf-8")
    bundle = final_project / "final_project_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("README.md", "Marker zip fixture.\n")
        zf.writestr("_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json", "{}")
    return bundle


def run_case(name: str, state: dict[str, Any], expected_problem: str, expected_status: str = "pass") -> dict[str, Any]:
    diagnosis = agent_problem_classifier.classify_problem(state)
    passed = diagnosis.get("problem_type") == expected_problem and str(diagnosis.get("status", "pass")) == expected_status
    return {
        "case": name,
        "status": "pass" if passed else "fail",
        "expected_problem_type": expected_problem,
        "actual_problem_type": diagnosis.get("problem_type"),
        "expected_status": expected_status,
        "actual_status": diagnosis.get("status"),
        "selected_tool": diagnosis.get("selected_tool"),
        "remaining_blockers": diagnosis.get("remaining_blockers", []),
        "diagnosis": diagnosis,
    }


def run_fault_injection_suite(output_dir: str | pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []

    state = base_state(root / "case_missing_ledger")
    state["agent_led"]["decision_ledger_exists"] = False
    cases.append(run_case("missing_decision_ledger", state, "AGENT_DECISION_LEDGER_MISSING"))

    state = base_state(root / "case_missing_manifest")
    state["delivery"]["delivery_manifest_exists"] = False
    state["delivery"]["public_gate_status"] = "NOT_READY"
    state["quality"]["commercial_status"] = "COMMERCIAL_BETA"
    cases.append(run_case("missing_delivery_manifest", state, "DELIVERY_MANIFEST_MISSING"))

    state = base_state(root / "case_missing_bundle")
    state["delivery"]["final_bundle_exists"] = False
    state["quality"]["commercial_status"] = "COMMERCIAL_BETA"
    cases.append(run_case("missing_final_bundle", state, "FINAL_BUNDLE_MISSING"))

    state = base_state(root / "case_missing_screenshot")
    state["delivery"]["screenshot_evidence_exists"] = False
    state["delivery"]["public_gate_status"] = "NOT_READY"
    state["quality"]["commercial_status"] = "COMMERCIAL_BETA"
    cases.append(run_case("missing_screenshot", state, "SCREENSHOT_EVIDENCE_MISSING"))

    complexity = make_small_project(root / "case_complexity_insufficient")
    state = base_state(root / "case_complexity_insufficient")
    state["latest_report_status"]["large_project_benchmark"] = "needs_rework"
    state["quality"]["complexity_status"] = complexity.get("status")
    state["quality"]["page_count"] = complexity.get("page_count", 0)
    state["quality"]["module_count"] = complexity.get("module_count", 0)
    state["quality"]["commercial_status"] = "COMMERCIAL_BETA"
    cases.append(run_case("complexity_insufficient", state, "COMPLEXITY_INSUFFICIENT"))

    state = base_state(root / "case_product_acceptance_pollution")
    state["latest_report_status"]["large_project_benchmark"] = "needs_rework"
    state["quality"]["product_acceptance_status"] = "fail"
    state["quality"]["missing_core_features"] = ["commercial", "readiness"]
    cases.append(run_case("product_acceptance_pollution", state, "PRODUCT_ACCEPTANCE_POLLUTION"))

    state = base_state(root / "case_provider_quota_no_local")
    state["latest_report_status"]["agent_led_verify"] = "blocked"
    state["provider"]["provider_available"] = False
    state["provider"]["provider_error_code"] = "403"
    state["provider"]["provider_error_type"] = "PROVIDER_QUOTA_EXCEEDED"
    state["provider"]["provider_quota_exceeded"] = True
    state["provider"]["local_model_available"] = False
    state["generation"]["formal_generation_materialized"] = False
    state["generation"]["writable_project_files_exist"] = False
    cases.append(run_case("provider_quota_local_unavailable", state, "PROVIDER_QUOTA_OR_TRANSPORT", expected_status="blocked"))

    bundle = make_marker_zip(root / "case_candidate_marker_final_zip")
    state = base_state(root / "case_candidate_marker_final_zip")
    state["delivery"]["final_bundle"] = str(bundle)
    state["quality"]["artifact_integrity_status"] = "fail"
    state["quality"]["commercial_status"] = "COMMERCIAL_BETA"
    cases.append(run_case("candidate_marker_in_final_zip", state, "ARTIFACT_INTEGRITY_FAILED"))

    report = {
        "status": "pass" if all(case["status"] == "pass" for case in cases) else "fail",
        "created_at": now(),
        "fault_injection_cases": len(cases),
        "fault_injection_pass": sum(1 for case in cases if case["status"] == "pass"),
        "cases": cases,
        "output_dir": str(root),
    }
    write_json(root / "agent_fault_injection_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "generated" / "agent_fault_injection_suite" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_fault_injection_suite(args.output_dir)
    summary = report if args.json else {
        "status": report["status"],
        "fault_injection_cases": report["fault_injection_cases"],
        "fault_injection_pass": report["fault_injection_pass"],
        "report_path": str(pathlib.Path(args.output_dir) / "agent_fault_injection_report.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
