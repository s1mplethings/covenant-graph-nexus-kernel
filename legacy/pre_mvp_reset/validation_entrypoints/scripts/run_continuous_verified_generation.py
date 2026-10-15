#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import continuous_generation_ledger


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def run_command(command: list[str]) -> dict[str, Any]:
    started = now()
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    return {
        "command": " ".join(command),
        "started_at": started,
        "ended_at": now(),
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
        "status": "PASS" if proc.returncode == 0 else "FAIL",
    }


def current_status() -> dict[str, Any]:
    requirement = read_json(ARTIFACTS / "requirement_decision_benchmark.json")
    complexity = read_json(ARTIFACTS / "complexity_scale_acceptance.json")
    naming_report = ARTIFACTS / "cgkn_naming_consistency_report.md"
    return {
        "requirement_decision_benchmark": requirement,
        "complexity_scale_acceptance": complexity,
        "naming_report_exists": naming_report.exists(),
        "layered_status": {
            "requirement_decision_status": complexity.get("requirement_decision_status", ""),
            "product_contract_status": complexity.get("product_contract_status", ""),
            "implementation_status": complexity.get("implementation_status", ""),
            "delivery_status": complexity.get("delivery_status", ""),
            "overall_status": complexity.get("layered_overall_status", complexity.get("overall_status", "")),
        },
    }


def select_gap(status: dict[str, Any], focus: str) -> dict[str, str]:
    if focus == "naming" or not status.get("naming_report_exists"):
        return {
            "selected_gap": "cgkn_naming_consistency_guard",
            "layer": "naming_consistency",
            "reason_for_priority": "New outputs need a repeatable CGKN naming guard before deeper generation work.",
            "next_recommended_action": "Keep the naming check in every iteration before running benchmarks.",
        }
    layered = status.get("layered_status", {}) if isinstance(status.get("layered_status"), dict) else {}
    if focus in {"product_contract", "all"} and layered.get("product_contract_status") not in {"PASS", ""}:
        return {
            "selected_gap": "product_contract_incomplete",
            "layer": "product_contract",
            "reason_for_priority": "Complexity benchmark shows planning docs are incomplete.",
            "next_recommended_action": "Strengthen provider validation for product_brief, technical_plan, interaction_design, and acceptance_matrix.",
        }
    if focus in {"implementation", "all"} and layered.get("implementation_status") not in {"PASS", ""}:
        return {
            "selected_gap": "implementation_structure_incomplete",
            "layer": "implementation",
            "reason_for_priority": "Complexity benchmark shows missing orchestrator, stages, or shared GUI/CLI core.",
            "next_recommended_action": "Use contract-driven materialization checks to block incomplete core structure.",
        }
    if focus in {"delivery", "all"} and layered.get("delivery_status") != "PASS":
        return {
            "selected_gap": "delivery_evidence_incomplete",
            "layer": "delivery",
            "reason_for_priority": "Delivery cannot pass without final zip, screenshot, and run evidence.",
            "next_recommended_action": "Keep delivery in NEEDS_REWORK until strict evidence exists.",
        }
    return {
        "selected_gap": "continuous_test_infrastructure",
        "layer": "test_infrastructure",
        "reason_for_priority": "The next iteration should preserve test and benchmark evidence.",
        "next_recommended_action": "Run focused tests and record the next ledger entry.",
    }


def benchmark_commands(benchmark: str, no_provider: bool) -> list[list[str]]:
    commands: list[list[str]] = []
    if benchmark in {"requirement_decision", "all"}:
        commands.append([sys.executable, "scripts/run_requirement_decision_benchmark.py"])
    if benchmark in {"complexity_scale", "all"} and not no_provider:
        commands.append([sys.executable, "scripts/run_complexity_scale_workbench_benchmark.py"])
    return commands


def run_iteration(args: argparse.Namespace, index: int) -> dict[str, Any]:
    started = now()
    status_before = current_status()
    gap = select_gap(status_before, args.focus)
    commands: list[list[str]] = [[sys.executable, "scripts/check_cgkn_naming_consistency.py"]]
    commands.extend(benchmark_commands(args.benchmark, args.no_provider))
    if args.write_plan_only:
        command_results: list[dict[str, Any]] = []
    else:
        command_results = []
        for command in commands:
            result = run_command(command)
            command_results.append(result)
            if args.stop_on_failure and result["returncode"] != 0:
                break
    status_after = current_status()
    benchmark_results = []
    req = status_after.get("requirement_decision_benchmark", {})
    if isinstance(req, dict) and req:
        benchmark_results.append(
            {
                "name": "requirement_decision",
                "score": req.get("score"),
                "verdict": req.get("verdict"),
            }
        )
    complexity = status_after.get("complexity_scale_acceptance", {})
    if isinstance(complexity, dict) and complexity:
        benchmark_results.append(
            {
                "name": "complexity_scale",
                "score": complexity.get("overall_score"),
                "verdict": complexity.get("verdict"),
                "requirement_decision_status": complexity.get("requirement_decision_status"),
                "product_contract_status": complexity.get("product_contract_status"),
                "implementation_status": complexity.get("implementation_status"),
                "delivery_status": complexity.get("delivery_status"),
                "overall_status": complexity.get("layered_overall_status"),
            }
        )
    failures = [result for result in command_results if result.get("returncode") != 0]
    ledger_status = "PARTIAL" if args.write_plan_only else ("FAIL" if failures else "PASS")
    known_gaps = []
    layered = status_after.get("layered_status", {}) if isinstance(status_after.get("layered_status"), dict) else {}
    for key, value in layered.items():
        if value and value not in {"PASS"}:
            known_gaps.append(f"{key}:{value}")
    if args.no_provider and args.benchmark in {"complexity_scale", "all"}:
        known_gaps.append("complexity_scale_benchmark_reused_existing_artifacts_due_to_no_provider")
    record = {
        "iteration": continuous_generation_ledger.next_iteration(),
        "started_at": started,
        "ended_at": now(),
        "selected_gap": gap["selected_gap"],
        "layer": gap["layer"],
        "reason_for_priority": gap["reason_for_priority"],
        "micro_plan": [
            "Inspect current benchmark and acceptance artifacts.",
            "Run naming check and selected benchmarks.",
            "Record evidence in the iteration ledger.",
            "Select the next highest-priority action.",
        ],
        "acceptance_criteria": [
            "CGKN naming check writes a report.",
            "Requirement Decision benchmark remains readable or reruns.",
            "Complexity benchmark layered status remains readable.",
            "Iteration ledger records commands, results, known gaps, and next action.",
        ],
        "files_changed": ["artifacts/continuous_generation_iterations.jsonl"],
        "tests_added_or_updated": [],
        "commands_run": [result["command"] for result in command_results],
        "test_results": [
            {"command": result["command"], "status": result["status"], "returncode": result["returncode"]}
            for result in command_results
            if "pytest" in result["command"] or "check_cgkn_naming_consistency.py" in result["command"]
        ],
        "benchmark_results": benchmark_results,
        "status": ledger_status,
        "known_gaps_after_iteration": known_gaps,
        "next_recommended_action": gap["next_recommended_action"],
    }
    written = continuous_generation_ledger.append_iteration(record)
    return {"iteration": index, "ledger_record": written, "command_results": command_results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--focus", choices=["requirement_decision", "product_contract", "implementation", "delivery", "tests", "provider", "naming", "all"], default="all")
    parser.add_argument("--benchmark", choices=["requirement_decision", "complexity_scale", "all"], default="requirement_decision")
    parser.add_argument("--no-provider", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--write-plan-only", action="store_true")
    args = parser.parse_args()
    results = [run_iteration(args, index + 1) for index in range(max(1, args.max_iterations))]
    last = results[-1]["ledger_record"]
    print(json.dumps({"iterations": results, "next_recommended_action": last["next_recommended_action"]}, ensure_ascii=False, indent=2))
    return 0 if all(record["ledger_record"]["status"] in {"PASS", "PARTIAL"} for record in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
