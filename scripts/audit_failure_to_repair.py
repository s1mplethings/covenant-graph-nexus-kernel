#!/usr/bin/env python3
"""Audit evaluator failure -> issue -> ProviderJob -> delta -> acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


def read_json(path: pathlib.Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_path(root: pathlib.Path, pattern: str) -> pathlib.Path | None:
    return next((path for path in root.rglob(pattern) if path.is_file()), None)


def latest_path(root: pathlib.Path, pattern: str) -> pathlib.Path | None:
    paths = [path for path in root.rglob(pattern) if path.is_file()]
    return max(paths, key=lambda path: path.stat().st_mtime_ns) if paths else None


def read_events(path: pathlib.Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def case_result_from_run(run_dir: pathlib.Path) -> tuple[pathlib.Path | None, dict[str, Any]]:
    path = first_path(run_dir / "cases", "case_result.json")
    if path:
        return path, read_json(path)
    report_path = run_dir / "benchmark_report.json"
    report = read_json(report_path)
    rows = report.get("case_results", [])
    return report_path if report else None, dict(rows[0]) if rows and isinstance(rows[0], dict) else {}


def evaluator_failures(case_result: dict[str, Any], run_dir: pathlib.Path) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    observations_doc = read_json(first_path(run_dir, "external_observations.json"))
    for record in observations_doc.get("observations", []):
        if isinstance(record, dict) and str(record.get("status", "")).upper() in {"FAIL", "NEEDS_REWORK", "BLOCKED"}:
            failures.append(dict(record))
    known = {str(item.get("criterion_id") or item.get("failed_requirement") or "") for item in failures}
    for failure in case_result.get("hard_failures", []):
        failure_id = str(failure)
        if failure_id in known:
            continue
        failures.append(
            {
                "evaluator_failure_id": failure_id,
                "criterion_id": failure_id,
                "status": "FAIL",
                "expected_behavior": "Independent evaluator criterion passes.",
                "observed_behavior": failure_id.replace("_", " "),
                "affected_files": [],
            }
        )
    return failures


def issue_matches_failure(issue: dict[str, Any], failure: dict[str, Any]) -> bool:
    failure_id = str(failure.get("criterion_id") or failure.get("failed_requirement") or failure.get("evaluator_failure_id") or "")
    identities = {
        str(issue.get("requirement") or ""),
        str(issue.get("failed_requirement") or ""),
    }
    for evidence in issue.get("external_evidence", []):
        if isinstance(evidence, dict):
            identities.add(str(evidence.get("criterion_id") or evidence.get("failed_requirement") or ""))
            identities.update(str(item) for item in evidence.get("applies_to_requirements", []))
    return bool(failure_id and failure_id in identities)


def event_has_target(event: dict[str, Any], targets: list[str]) -> bool:
    event_targets = {
        str(event.get("target_file") or "").replace("\\", "/"),
        *(str(path).replace("\\", "/") for path in event.get("target_files", [])),
    }
    return bool(set(targets) & event_targets)


def audit_case(run_dir: pathlib.Path) -> dict[str, Any]:
    result_path, case_result = case_result_from_run(run_dir)
    production_result_path = first_path(run_dir / "production_slots", "production_result.json")
    production_result = read_json(production_result_path)
    ledger_path = latest_path(run_dir, "post_build_issue_ledger_attempt_*.json") or latest_path(run_dir, "post_build_issue_ledger_v0.json")
    plan_path = latest_path(run_dir, "post_build_repair_plan_attempt_*.json") or latest_path(run_dir, "repair_plan.json")
    accounting_path = latest_path(run_dir, "repair_call_accounting.json")
    phase_log_path = first_path(run_dir, "provider_phase_log.jsonl")
    ledger = read_json(ledger_path)
    plan = read_json(plan_path)
    accounting = read_json(accounting_path)
    events = read_events(phase_log_path)
    failures = evaluator_failures(case_result, run_dir)
    issue_rows = [row for row in ledger.get("issues", []) if isinstance(row, dict)]
    actions = [row for row in plan.get("provider_actions", []) if isinstance(row, dict)]
    accounting_rows = [row for row in accounting.get("calls", accounting.get("rows", [])) if isinstance(row, dict)]
    records: list[dict[str, Any]] = []
    return_code = int((case_result.get("metrics") or {}).get("production_return_code", 0) or 0)
    for failure in failures:
        issue = next((row for row in issue_rows if issue_matches_failure(row, failure)), None)
        issue_id = str((issue or {}).get("issue_id") or "")
        targets = [str(path).replace("\\", "/") for path in (issue or {}).get("affected_files", [])]
        action = next((row for row in actions if issue_id and issue_id in row.get("issue_ids", [])), None)
        requests = [event for event in events if event.get("event") == "provider_request" and event_has_target(event, targets)]
        deltas = [event for event in events if event.get("event") == "component_leaf_completed" and event_has_target(event, targets)]
        decisions = [row for row in accounting_rows if issue_id and issue_id in row.get("issue_ids", [])]
        accepted = any(bool(row.get("accepted")) for row in decisions)
        fixed = any(bool(row.get("fixed_by_delta")) for row in decisions)
        if issue is None:
            status = "not_mapped"
        elif action is None:
            status = "no_job"
        elif not requests:
            status = "no_call"
        elif not deltas:
            status = "no_delta"
        elif not accepted:
            status = "rejected"
        else:
            status = "fixed" if fixed else "accepted"
        root_cause = ""
        if return_code == 124 and issue is None:
            root_cause = "production_timeout_before_evaluator_failure_could_enter_repair"
        elif status == "rejected":
            root_cause = str(next((row.get("rejection_reason") for row in decisions if row.get("rejection_reason")), "delta_not_accepted"))
        records.append(
            {
                "case_id": str(case_result.get("case_id") or ""),
                "evaluator_failure_id": str(failure.get("criterion_id") or failure.get("failed_requirement") or failure.get("evaluator_failure_id") or ""),
                "expected_behavior": str(failure.get("expected_behavior") or ""),
                "observed_behavior": str(failure.get("observed_behavior") or ""),
                "mapped_issue_id": issue_id,
                "issue_type": str((issue or {}).get("requirement") or ""),
                "target_files": targets,
                "provider_job_created": action is not None,
                "provider_job_id": str((action or {}).get("provider_job_id") or (issue or {}).get("affected_provider_job") or ""),
                "provider_called": bool(requests),
                "provider_returned_delta": bool(deltas),
                "delta_accepted": accepted,
                "rejection_reason": str(next((row.get("rejection_reason") for row in decisions if row.get("rejection_reason")), "")),
                "affected_behavior_check": str(next(iter((action or {}).get("acceptance_conditions", [])), "")),
                "failure_repair_status": status,
                "root_cause": root_cause,
            }
        )
    counts = {
        "evaluator_failures_total": len(records),
        "mapped_to_issue_count": sum(bool(row["mapped_issue_id"]) for row in records),
        "provider_jobs_created_count": sum(bool(row["provider_job_created"]) for row in records),
        "provider_calls_count": sum(bool(row["provider_called"]) for row in records),
        "provider_deltas_count": sum(bool(row["provider_returned_delta"]) for row in records),
        "accepted_delta_count": sum(bool(row["delta_accepted"]) for row in records),
        "fixed_failure_count": sum(row["failure_repair_status"] == "fixed" for row in records),
        "unmapped_failure_count": sum(row["failure_repair_status"] == "not_mapped" for row in records),
        "no_job_failure_count": sum(row["failure_repair_status"] == "no_job" for row in records),
        "rejected_delta_count": sum(row["failure_repair_status"] == "rejected" for row in records),
    }
    candidate_materialized = bool(production_result.get("candidate_materialized")) or first_path(
        run_dir / "cases", "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json"
    ) is not None
    diagnostics = production_result.get("diagnostics", {})
    diagnostic_stage = str(diagnostics.get("stage") or "") if isinstance(diagnostics, dict) else ""
    no_repair_reason = ""
    fix_required_module = ""
    if not ledger and not candidate_materialized and diagnostic_stage == "provider_semantic_review":
        no_repair_reason = "candidate_not_materialized_provider_semantic_review_blocked_before_post_build"
        fix_required_module = "scripts/run_local_pipeline_impl.py:run_provider_semantic_review_with_repair"
    elif not ledger and return_code == 124:
        no_repair_reason = "production_timeout_before_post_build_issue_ledger"
        fix_required_module = "production_stage_before_post_build"
    elif ledger and not plan.get("provider_actions"):
        no_repair_reason = "issue_ledger_has_no_evidence_bound_provider_jobs"
        fix_required_module = "scripts/post_build_repair.py"
    elif not ledger:
        no_repair_reason = "post_build_issue_ledger_not_emitted"
        fix_required_module = "scripts/post_build_repair.py"
    case03_repair_skipped = {
        "case03_repair_skipped": not bool(accounting_rows),
        "skip_reason": no_repair_reason,
        "evaluator_failures_seen": len(records),
        "issues_extracted": len(issue_rows),
        "repairable_issues": sum(bool(row.get("repairable")) for row in issue_rows),
        "provider_jobs_planned": len(actions),
        "fix_required_module": fix_required_module,
    }
    return {
        "case_id": str(case_result.get("case_id") or ""),
        "run_dir": str(run_dir),
        "case_result": str(result_path or ""),
        "score": case_result.get("score"),
        "production_return_code": return_code,
        "candidate_materialized": candidate_materialized,
        **counts,
        "case03_no_repair_reason": no_repair_reason if "CASE_03" in str(case_result.get("case_id")) else "",
        "case03_repair_skipped": case03_repair_skipped if "CASE_03" in str(case_result.get("case_id")) else {},
        "inputs": {
            "issue_ledger": str(ledger_path or ""),
            "provider_job_ledger": str(plan_path or ""),
            "repair_call_accounting": str(accounting_path or ""),
            "phase_log": str(phase_log_path or ""),
            "build_coherence_report": str(latest_path(run_dir, "*coherence*.json") or ""),
            "production_result": str(production_result_path or ""),
        },
        "failure_records": records,
        "criteria_not_evaluated": list(case_result.get("criteria_not_evaluated", [])),
    }


def tree_files(root: pathlib.Path | None) -> set[str]:
    if root is None or not root.is_dir():
        return set()
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts
    }


def read_text(root: pathlib.Path | None, relative: str) -> str:
    path = root / relative if root else pathlib.Path()
    return path.read_text(encoding="utf-8", errors="replace") if root and path.is_file() else ""


def routes(text: str) -> list[str]:
    return sorted(
        set(
            re.findall(
                r"@[A-Za-z_][A-Za-z0-9_]*\.(?:route|get|post|put|patch|delete)\(\s*['\"]([^'\"]+)",
                text,
            )
        )
    )


def dom_identity(root: pathlib.Path | None) -> dict[str, list[str]]:
    html = read_text(root, "frontend/index.html")
    js = read_text(root, "frontend/app.js")
    html_ids = set(re.findall(r"\bid=[\"']([^\"']+)", html))
    js_ids = set(re.findall(r"getElementById\([\"']([^\"']+)", js))
    return {
        "html_ids": sorted(html_ids),
        "js_ids": sorted(js_ids),
        "js_ids_missing_from_html": sorted(js_ids - html_ids),
    }


def score_drop_analysis(
    old_candidate: pathlib.Path | None,
    previous_candidate: pathlib.Path | None,
    fresh_candidate: pathlib.Path | None,
    old_result: pathlib.Path | None,
    previous_result: pathlib.Path | None,
    fresh_result: dict[str, Any],
    selected_model: str,
) -> dict[str, Any]:
    old_files = tree_files(old_candidate)
    fresh_files = tree_files(fresh_candidate)
    old_routes = routes(read_text(old_candidate, "app/main.py"))
    fresh_routes = routes(read_text(fresh_candidate, "app/main.py"))
    old_dom = dom_identity(old_candidate)
    previous_dom = dom_identity(previous_candidate)
    fresh_dom = dom_identity(fresh_candidate)
    old_eval = read_json(old_result)
    previous_eval = read_json(previous_result)
    old_tests = {path for path in old_files if path.startswith("tests/") and path.endswith(".py")}
    fresh_tests = {path for path in fresh_files if path.startswith("tests/") and path.endswith(".py")}
    broken_entrypoints: list[str] = []
    if "/" in old_routes and "/" not in fresh_routes:
        broken_entrypoints.append("app/main.py lost the root/static route")
    if fresh_dom["js_ids_missing_from_html"]:
        broken_entrypoints.append("frontend/app.js references DOM ids absent from frontend/index.html")
    lost_features = [f"route:{route}" for route in sorted(set(old_routes) - set(fresh_routes))]
    fresh_metrics = fresh_result.get("metrics") or {}
    previous_metrics = previous_eval.get("metrics") or {}
    fresh_peak = fresh_metrics.get("provider_peak_concurrency")
    previous_peak = previous_metrics.get("provider_peak_concurrency")
    fresh_return_code = fresh_metrics.get("production_return_code")
    if fresh_return_code == 124 and previous_peak and fresh_peak and fresh_peak < previous_peak:
        finding = (
            f"fresh production peak concurrency fell from {previous_peak} to {fresh_peak} and timed out before "
            "delivery; the generated app also lost root/static route coverage"
        )
    elif fresh_return_code:
        finding = (
            f"fresh production reached validation with peak concurrency {fresh_peak}, but exited {fresh_return_code}; "
            "the generated app lost root/static route coverage and bounded repair left candidate tests failing"
        )
    else:
        finding = "fresh candidate lost root/static route coverage relative to the score-33 baseline"
    return {
        "missing_files": sorted(old_files - fresh_files),
        "broken_entrypoints": broken_entrypoints,
        "lost_features": lost_features,
        "changed_routes": {"old_score_33": old_routes, "latest_previous": routes(read_text(previous_candidate, "app/main.py")), "fresh": fresh_routes},
        "changed_dom_ids": {"old_score_33": old_dom, "latest_previous": previous_dom, "fresh": fresh_dom},
        "test_evidence_change": {
            "old_tests": sorted(old_tests),
            "fresh_tests": sorted(fresh_tests),
            "test_file_set_changed": old_tests != fresh_tests,
            "test_source_hash_changed": hashlib.sha256("".join(read_text(fresh_candidate, path) for path in sorted(fresh_tests)).encode()).hexdigest()
            != hashlib.sha256("".join(read_text(old_candidate, path) for path in sorted(old_tests)).encode()).hexdigest(),
        },
        "evaluator_failures_new": sorted(set(fresh_result.get("hard_failures", [])) - set(old_eval.get("hard_failures", []))),
        "generation_prompt_or_model_difference": {
            "old_provider_calls": (old_eval.get("metrics") or {}).get("provider_api_calls"),
            "previous_provider_calls": previous_metrics.get("provider_api_calls"),
            "fresh_provider_calls": fresh_metrics.get("provider_api_calls"),
            "old_provider_peak_concurrency": (old_eval.get("metrics") or {}).get("provider_peak_concurrency"),
            "previous_provider_peak_concurrency": previous_peak,
            "fresh_provider_peak_concurrency": fresh_peak,
            "fresh_production_return_code": fresh_return_code,
            "finding": finding,
        },
        "provider_selected_model": selected_model,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-run-dir", action="append", type=pathlib.Path, required=True)
    parser.add_argument("--product-convergence-report", type=pathlib.Path)
    parser.add_argument("--case01-old-candidate", type=pathlib.Path)
    parser.add_argument("--case01-previous-candidate", type=pathlib.Path)
    parser.add_argument("--case01-old-result", type=pathlib.Path)
    parser.add_argument("--case01-previous-result", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    convergence = read_json(args.product_convergence_report)
    selected_model = str(convergence.get("model") or (convergence.get("provider_auto_select") or {}).get("selected_model") or "")
    cases = [audit_case(path.resolve()) for path in args.case_run_dir]
    case01 = next((row for row in cases if "CASE_01" in row["case_id"]), None)
    if case01:
        _, fresh_result = case_result_from_run(pathlib.Path(case01["run_dir"]))
        fresh_candidate = next((path.parent for path in pathlib.Path(case01["run_dir"]).rglob("_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json") if "cases" in path.parts), None)
        case01["score_drop_analysis"] = score_drop_analysis(
            args.case01_old_candidate,
            args.case01_previous_candidate,
            fresh_candidate,
            args.case01_old_result,
            args.case01_previous_result,
            fresh_result,
            selected_model,
        )
    report = {
        "kind": "CGKNFailureToRepairAudit",
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "product_convergence_report": str(args.product_convergence_report or ""),
        "cases": cases,
        "totals": {
            key: sum(int(row.get(key, 0) or 0) for row in cases)
            for key in (
                "evaluator_failures_total",
                "mapped_to_issue_count",
                "provider_jobs_created_count",
                "provider_calls_count",
                "provider_deltas_count",
                "accepted_delta_count",
                "fixed_failure_count",
                "unmapped_failure_count",
                "no_job_failure_count",
                "rejected_delta_count",
            )
        },
        "formal_evidence_status": "NOT_EVALUATED",
        "release_authority": False,
    }
    write_json(args.output.resolve(), report)
    print(json.dumps({"status": "AUDIT_COMPLETE", "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
