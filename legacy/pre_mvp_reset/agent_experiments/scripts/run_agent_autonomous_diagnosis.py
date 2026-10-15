#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import agent_decision_ledger
import agent_problem_classifier
import agent_state_observer
import agent_tool_registry


GOAL = "diagnose and repair current project generation system"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def run_command(argv: list[str], *, cwd: pathlib.Path, timeout: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return {
            "status": "pass" if proc.returncode == 0 else "fail",
            "returncode": proc.returncode,
            "argv": argv,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    except Exception as exc:
        return {"status": "fail", "returncode": -1, "argv": argv, "error": str(exc)}


def append_diagnosis_decision(run_dir: pathlib.Path, state: dict[str, Any], diagnosis: dict[str, Any], report_path: pathlib.Path) -> pathlib.Path:
    tool = agent_tool_registry.get_tool(str(diagnosis.get("selected_tool") or "inspect_latest_reports")) or {}
    decision = {
        "step": 1,
        "agent_role": "Diagnostic Director",
        "observed_state_hash": agent_decision_ledger.observed_state_hash(state),
        "observed_state_summary": {
            "problem_type": diagnosis.get("problem_type"),
            "director_loop_used": state.get("agent_led", {}).get("director_loop_used"),
            "decision_ledger_exists": state.get("agent_led", {}).get("decision_ledger_exists"),
            "provider_error_type": state.get("provider", {}).get("provider_error_type"),
            "provider_quota_exceeded": state.get("provider", {}).get("provider_quota_exceeded"),
            "formal_generation_materialized": state.get("generation", {}).get("formal_generation_materialized"),
            "public_gate_status": state.get("delivery", {}).get("public_gate_status"),
            "commercial_status": state.get("quality", {}).get("commercial_status"),
            "last_pytest_status": state.get("tests", {}).get("last_pytest_status"),
        },
        "goal": GOAL,
        "decision": "classify_problem",
        "selected_tool": diagnosis.get("selected_tool", "inspect_latest_reports"),
        "rejected_tools": diagnosis.get("rejected_tools", []),
        "reason": diagnosis.get("why_this_problem", ""),
        "expected_outputs": tool.get("outputs", diagnosis.get("expected_outputs", ["diagnosis_report"])),
        "status": "planned",
        "result_refs": [],
    }
    return agent_decision_ledger.append_decision(
        run_dir,
        decision,
        {
            "status": "executed" if diagnosis.get("status") != "blocked" else "blocked",
            "artifacts": [str(report_path)],
            "metadata": {
                "problem_type": diagnosis.get("problem_type"),
                "confidence": diagnosis.get("confidence"),
                "recommended_action": diagnosis.get("recommended_action"),
            },
        },
    )


def execute_selected_tool(selected_tool: str, diagnosis: dict[str, Any], *, repo: pathlib.Path, timeout: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = []
    test_results: list[dict[str, Any]] = []
    if diagnosis.get("problem_type") == "NO_ISSUE_DETECTED":
        return actions, test_results
    if diagnosis.get("status") == "blocked" or selected_tool == "BLOCKED":
        actions.append({"tool": selected_tool, "status": "blocked", "reason": diagnosis.get("remaining_blockers", [])})
        return actions, test_results
    if selected_tool == "run_targeted_tests":
        result = run_command([sys.executable, "-m", "pytest", "tests", "-q", "-x"], cwd=repo, timeout=timeout)
        actions.append({"tool": selected_tool, "status": result["status"]})
        test_results.append(result)
        return actions, test_results
    if selected_tool == "run_agent_led_verify":
        result = run_command(["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts\\verify_repo.ps1"], cwd=repo, timeout=timeout)
        actions.append({"tool": selected_tool, "status": result["status"]})
        test_results.append(result)
        return actions, test_results
    actions.append(
        {
            "tool": selected_tool,
            "status": "not_executed",
            "reason": "diagnosis selected a repair class, but this runner will not modify code without a concrete failing artifact and a scoped repair implementation",
        }
    )
    return actions, test_results


def report_statuses(observed_state: dict[str, Any]) -> dict[str, str]:
    latest = observed_state.get("latest_report_status", {}) if isinstance(observed_state.get("latest_report_status"), dict) else {}
    quality = observed_state.get("quality", {}) if isinstance(observed_state.get("quality"), dict) else {}
    return {
        "agent_led_verify": "pass" if latest.get("agent_led_verify") == "pass" else ("fail" if latest.get("agent_led_verify") not in {"missing", "", None} else "not_run"),
        "large_project_benchmark": "pass" if latest.get("large_project_benchmark") == "pass" else ("fail" if latest.get("large_project_benchmark") not in {"missing", "", None} else "not_run"),
        "commercial_status": str(quality.get("commercial_status") or "not_evaluated"),
    }


def build_report(
    *,
    run_dir: pathlib.Path,
    report_path: pathlib.Path,
    observed_state: dict[str, Any],
    diagnosis: dict[str, Any],
    decision_ledger: pathlib.Path,
    actions_taken: list[dict[str, Any]],
    tests_run: list[str],
    test_results: list[dict[str, Any]],
    files_modified: list[str],
) -> dict[str, Any]:
    latest_reports = observed_state.get("latest_reports", {}) if isinstance(observed_state.get("latest_reports"), dict) else {}
    return {
        "status": diagnosis.get("status", "pass"),
        "problem_type": diagnosis.get("problem_type", "UNKNOWN"),
        "confidence": diagnosis.get("confidence", 0.0),
        "evidence_refs": diagnosis.get("evidence_refs", []),
        "why_this_problem": diagnosis.get("why_this_problem", ""),
        "why_not_other_problems": diagnosis.get("why_not_other_problems", []),
        "observed_state": observed_state,
        "latest_reports": latest_reports,
        "selected_tool": diagnosis.get("selected_tool", ""),
        "rejected_tools": diagnosis.get("rejected_tools", []),
        "decision_ledger": str(decision_ledger),
        "actions_taken": actions_taken,
        "files_modified": files_modified,
        "tests_run": tests_run,
        "test_results": test_results,
        "post_fix_verify": report_statuses(observed_state),
        "remaining_blockers": diagnosis.get("remaining_blockers", []),
        "required_external_action": diagnosis.get("required_external_action", ""),
        "report_path": str(report_path),
        "run_dir": str(run_dir),
        "created_at": now(),
    }


def run_diagnosis(args: argparse.Namespace) -> dict[str, Any]:
    repo = pathlib.Path(args.repo).resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = pathlib.Path(args.output_root).resolve() if args.output_root else repo / "generated" / "agent_autonomous_diagnosis"
    work_root = root / timestamp
    run_dir = work_root / "run"
    report_path = work_root / "agent_autonomous_diagnosis_report.json"
    run_dir.mkdir(parents=True, exist_ok=True)

    observed_state = agent_state_observer.observe_repository_state(repo)
    diagnosis = agent_problem_classifier.classify_problem(observed_state)
    decision_ledger = append_diagnosis_decision(run_dir, observed_state, diagnosis, report_path)

    selected_tool = str(diagnosis.get("selected_tool") or "")
    actions_taken, test_results = execute_selected_tool(selected_tool, diagnosis, repo=repo, timeout=args.timeout)
    tests_run = [" ".join(item.get("argv", [])) for item in test_results if isinstance(item.get("argv"), list)]

    report = build_report(
        run_dir=run_dir,
        report_path=report_path,
        observed_state=observed_state,
        diagnosis=diagnosis,
        decision_ledger=decision_ledger,
        actions_taken=actions_taken,
        tests_run=tests_run,
        test_results=test_results,
        files_modified=[],
    )
    write_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--output-root", default="")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_diagnosis(args)
    print(json.dumps(report if args.json else {
        "status": report["status"],
        "problem_type": report["problem_type"],
        "confidence": report["confidence"],
        "selected_tool": report["selected_tool"],
        "report_path": report["report_path"],
        "decision_ledger": report["decision_ledger"],
        "remaining_blockers": report["remaining_blockers"],
    }, ensure_ascii=False, indent=2, default=str))
    return 0 if report.get("status") in {"pass", "repaired"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
