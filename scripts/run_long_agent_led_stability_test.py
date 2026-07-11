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

import run_agent_fault_injection_suite


COMPONENTS = [
    "agent_director_loop",
    "tool_registry",
    "state_observer",
    "decision_ledger",
    "provider_fallback",
    "local_formal_generation",
    "final_promotion",
    "artifact_integrity",
    "delivery_manifest",
    "screenshot_capture",
    "public_delivery_gate",
    "complexity_audit",
    "product_acceptance",
    "commercial_readiness",
    "autonomous_diagnosis",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def append_jsonl(path: pathlib.Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def read_json(path: pathlib.Path | str) -> dict[str, Any]:
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def latest_report(root: pathlib.Path, pattern: str) -> pathlib.Path | None:
    matches = [path for path in root.glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def run_command(argv: list[str], *, cwd: pathlib.Path, timeout: int) -> dict[str, Any]:
    started = now()
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return {
            "status": "pass" if proc.returncode == 0 else "fail",
            "returncode": proc.returncode,
            "argv": argv,
            "started_at": started,
            "finished_at": now(),
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    except Exception as exc:
        return {
            "status": "fail",
            "returncode": -1,
            "argv": argv,
            "started_at": started,
            "finished_at": now(),
            "error": str(exc),
        }


def parse_stdout_json(result: dict[str, Any]) -> dict[str, Any]:
    text = str(result.get("stdout_tail") or "").strip()
    if not text:
        return {}
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        doc = json.loads(text[start : end + 1])
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def summarize_verify(command_result: dict[str, Any], generated: pathlib.Path) -> dict[str, Any]:
    stdout_doc = parse_stdout_json(command_result)
    report_path = pathlib.Path(str(stdout_doc.get("report_path") or "")) if stdout_doc.get("report_path") else latest_report(generated, "agent_led_verify/*/agent_led_verify_report.json")
    report = read_json(report_path) if report_path else {}
    state = report.get("state", {}) if isinstance(report.get("state"), dict) else {}
    selected_tools = report.get("selected_tools") or stdout_doc.get("selected_tools") or []
    return {
        "kind": "verify",
        "status": "pass" if command_result.get("status") == "pass" and (report.get("status") == "pass" or stdout_doc.get("status") == "pass") else "fail",
        "report_path": str(report_path) if report_path else "",
        "director_loop_used": bool(report.get("director_loop_used") or stdout_doc.get("director_loop_used")),
        "selected_tools": selected_tools,
        "agent_decision_ledger": str(report.get("agent_decision_ledger") or stdout_doc.get("agent_decision_ledger") or ""),
        "provider_quota_exceeded": bool(state.get("provider_quota_exceeded") or stdout_doc.get("provider_quota_exceeded")),
        "fallback_used": any("local_only" in str(tool) or "local_first" in str(tool) for tool in selected_tools),
        "final_project_exists": bool(report.get("final_project_dir") or stdout_doc.get("final_project_dir")),
        "delivery_manifest_exists": bool(report.get("delivery_manifest") or stdout_doc.get("delivery_manifest")),
        "final_bundle_exists": bool(report.get("final_project_bundle") or stdout_doc.get("final_project_bundle")),
        "screenshot_evidence_exists": bool(report.get("screenshot_evidence_exists") or stdout_doc.get("screenshot_evidence_exists")),
        "public_gate_ready": state.get("public_gate_status") == "READY",
        "commercial_status": report.get("commercial_status") or stdout_doc.get("commercial_status") or "",
        "remaining_blockers": report.get("remaining_blockers") or stdout_doc.get("remaining_blockers") or [],
        "command": command_result,
    }


def summarize_benchmark(command_result: dict[str, Any], generated: pathlib.Path) -> dict[str, Any]:
    stdout_doc = parse_stdout_json(command_result)
    report_path = pathlib.Path(str(stdout_doc.get("report_path") or "")) if stdout_doc.get("report_path") else latest_report(generated, "large_project_agent_led_benchmark/*/large_project_agent_led_benchmark_report.json")
    report = read_json(report_path) if report_path else {}
    complexity = report.get("complexity", {}) if isinstance(report.get("complexity"), dict) else {}
    product = report.get("product_acceptance", {}) if isinstance(report.get("product_acceptance"), dict) else {}
    return {
        "kind": "benchmark",
        "status": "pass" if command_result.get("status") == "pass" and (report.get("status") == "pass" or stdout_doc.get("status") == "pass") else "fail",
        "report_path": str(report_path) if report_path else "",
        "director_loop_used": bool(report.get("director_loop_used") or stdout_doc.get("director_loop_used")),
        "selected_tools": report.get("selected_tools") or stdout_doc.get("selected_tools") or [],
        "final_project_exists": bool(report.get("final_project") or stdout_doc.get("final_project")),
        "delivery_manifest_exists": bool(report.get("delivery_manifest") or stdout_doc.get("delivery_manifest")),
        "final_bundle_exists": bool(report.get("final_bundle") or stdout_doc.get("final_bundle")),
        "screenshot_evidence_exists": bool(report.get("screenshot_evidence") or stdout_doc.get("screenshot_evidence")),
        "complexity_status": (complexity.get("audit") or {}).get("status") if isinstance(complexity.get("audit"), dict) else complexity.get("status"),
        "page_count": int(complexity.get("page_count") or 0),
        "module_count": int(complexity.get("module_count") or 0),
        "product_acceptance_status": product.get("status", ""),
        "commercial_status": report.get("commercial_status") or stdout_doc.get("commercial_status") or "",
        "remaining_blockers": report.get("remaining_blockers") or stdout_doc.get("remaining_blockers") or [],
        "command": command_result,
    }


def summarize_diagnosis(command_result: dict[str, Any], generated: pathlib.Path) -> dict[str, Any]:
    stdout_doc = parse_stdout_json(command_result)
    report_path = pathlib.Path(str(stdout_doc.get("report_path") or "")) if stdout_doc.get("report_path") else latest_report(generated, "agent_autonomous_diagnosis/*/agent_autonomous_diagnosis_report.json")
    report = read_json(report_path) if report_path else {}
    return {
        "kind": "diagnosis",
        "status": "pass" if command_result.get("status") == "pass" and report.get("status") in {"pass", "repaired"} else "fail",
        "report_path": str(report_path) if report_path else "",
        "problem_type": report.get("problem_type") or stdout_doc.get("problem_type"),
        "selected_tool": report.get("selected_tool") or stdout_doc.get("selected_tool"),
        "remaining_blockers": report.get("remaining_blockers") or stdout_doc.get("remaining_blockers") or [],
        "commercial_status": (report.get("post_fix_verify") or {}).get("commercial_status", ""),
        "command": command_result,
    }


def add_component_signal(signals: dict[str, list[dict[str, Any]]], component: str, passed: bool, evidence: str, note: str = "") -> None:
    signals.setdefault(component, []).append({"passed": bool(passed), "evidence_ref": evidence, "note": note})


def collect_signals(records: list[dict[str, Any]], fault_report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    signals: dict[str, list[dict[str, Any]]] = {component: [] for component in COMPONENTS}
    for record in records:
        kind = record.get("kind")
        evidence = str(record.get("report_path") or "")
        if kind == "verify":
            add_component_signal(signals, "agent_director_loop", record.get("director_loop_used") is True, evidence)
            add_component_signal(signals, "tool_registry", bool(record.get("selected_tools")), evidence)
            add_component_signal(signals, "state_observer", record.get("status") == "pass", evidence)
            add_component_signal(signals, "decision_ledger", bool(record.get("agent_decision_ledger")), evidence)
            add_component_signal(signals, "provider_fallback", (not record.get("provider_quota_exceeded")) or record.get("fallback_used"), evidence)
            add_component_signal(signals, "local_formal_generation", record.get("fallback_used") is True, evidence)
            add_component_signal(signals, "final_promotion", record.get("final_project_exists") is True, evidence)
            add_component_signal(signals, "delivery_manifest", record.get("delivery_manifest_exists") is True, evidence)
            add_component_signal(signals, "screenshot_capture", record.get("screenshot_evidence_exists") is True, evidence)
            add_component_signal(signals, "public_delivery_gate", record.get("public_gate_ready") is True, evidence)
            add_component_signal(signals, "commercial_readiness", record.get("commercial_status") == "COMMERCIAL_READY", evidence)
        elif kind == "benchmark":
            add_component_signal(signals, "agent_director_loop", record.get("director_loop_used") is True, evidence)
            add_component_signal(signals, "final_promotion", record.get("final_project_exists") is True, evidence)
            add_component_signal(signals, "artifact_integrity", record.get("final_bundle_exists") is True, evidence)
            add_component_signal(signals, "delivery_manifest", record.get("delivery_manifest_exists") is True, evidence)
            add_component_signal(signals, "screenshot_capture", record.get("screenshot_evidence_exists") is True, evidence)
            add_component_signal(signals, "complexity_audit", record.get("complexity_status") == "pass" and int(record.get("page_count") or 0) >= 8 and int(record.get("module_count") or 0) >= 6, evidence)
            add_component_signal(signals, "product_acceptance", record.get("product_acceptance_status") == "pass", evidence)
            add_component_signal(signals, "commercial_readiness", record.get("commercial_status") == "COMMERCIAL_READY", evidence)
        elif kind == "diagnosis":
            add_component_signal(signals, "autonomous_diagnosis", record.get("status") == "pass" and not record.get("remaining_blockers"), evidence, str(record.get("problem_type") or ""))
    for case in fault_report.get("cases", []):
        evidence = str(fault_report.get("output_dir") or "")
        passed = case.get("status") == "pass"
        problem = str(case.get("actual_problem_type") or "")
        if problem in {"AGENT_DECISION_LEDGER_MISSING"}:
            add_component_signal(signals, "decision_ledger", passed, evidence, case.get("case", ""))
        if problem in {"PROVIDER_QUOTA_OR_TRANSPORT"}:
            add_component_signal(signals, "provider_fallback", passed, evidence, case.get("case", ""))
        if problem in {"DELIVERY_MANIFEST_MISSING"}:
            add_component_signal(signals, "delivery_manifest", passed, evidence, case.get("case", ""))
        if problem in {"FINAL_BUNDLE_MISSING", "ARTIFACT_INTEGRITY_FAILED"}:
            add_component_signal(signals, "artifact_integrity", passed, evidence, case.get("case", ""))
        if problem in {"SCREENSHOT_EVIDENCE_MISSING"}:
            add_component_signal(signals, "screenshot_capture", passed, evidence, case.get("case", ""))
        if problem in {"COMPLEXITY_INSUFFICIENT"}:
            add_component_signal(signals, "complexity_audit", passed, evidence, case.get("case", ""))
        if problem in {"PRODUCT_ACCEPTANCE_POLLUTION"}:
            add_component_signal(signals, "product_acceptance", passed, evidence, case.get("case", ""))
        add_component_signal(signals, "autonomous_diagnosis", passed, evidence, case.get("case", ""))
    return signals


def score_components(signals: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    scores: list[dict[str, Any]] = []
    for component in COMPONENTS:
        rows = signals.get(component, [])
        pass_count = sum(1 for row in rows if row.get("passed"))
        fail_count = sum(1 for row in rows if not row.get("passed"))
        if not rows:
            status = "not_evaluated"
        elif pass_count and fail_count:
            status = "flaky"
        elif fail_count:
            status = "failing"
        else:
            status = "stable"
        scores.append(
            {
                "component": component,
                "status": status,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "evidence_refs": sorted({str(row.get("evidence_ref")) for row in rows if row.get("evidence_ref")}),
                "notes": [str(row.get("note")) for row in rows if row.get("note")],
            }
        )
    return scores


def aggregate_report(records: list[dict[str, Any]], fault_report: dict[str, Any], *, report_path: pathlib.Path, runs_ledger: pathlib.Path) -> dict[str, Any]:
    verify_records = [row for row in records if row.get("kind") == "verify"]
    benchmark_records = [row for row in records if row.get("kind") == "benchmark"]
    diagnosis_records = [row for row in records if row.get("kind") == "diagnosis"]
    signals = collect_signals(records, fault_report)
    component_scores = score_components(signals)
    flaky = [score for score in component_scores if score["status"] == "flaky"]
    unstable = [score["component"] for score in component_scores if score["status"] in {"flaky", "failing"}]
    stable = [score["component"] for score in component_scores if score["status"] == "stable"]
    recommended = [f"Investigate {item['component']} intermittent failures" for item in flaky]
    recommended.extend(f"Repair {score['component']} failing stability checks" for score in component_scores if score["status"] == "failing")
    all_primary_pass = all(row.get("status") == "pass" for row in records) and fault_report.get("status") == "pass"
    status = "pass" if all_primary_pass and not unstable else ("partial" if any(row.get("status") == "pass" for row in records) else "fail")
    return {
        "status": status,
        "created_at": now(),
        "total_runs": len(records) + int(fault_report.get("fault_injection_cases", 0)),
        "verify_pass": sum(1 for row in verify_records if row.get("status") == "pass"),
        "benchmark_pass": sum(1 for row in benchmark_records if row.get("status") == "pass"),
        "diagnosis_pass": sum(1 for row in diagnosis_records if row.get("status") == "pass"),
        "commercial_ready_count": sum(1 for row in records if row.get("commercial_status") == "COMMERCIAL_READY"),
        "fallback_used_count": sum(1 for row in verify_records if row.get("fallback_used")),
        "quota_detected_count": sum(1 for row in verify_records if row.get("provider_quota_exceeded")),
        "fault_injection_cases": int(fault_report.get("fault_injection_cases", 0)),
        "fault_injection_pass": int(fault_report.get("fault_injection_pass", 0)),
        "flaky_failures": flaky,
        "stable_components": stable,
        "unstable_components": unstable,
        "component_scores": component_scores,
        "recommended_next_fixes": recommended,
        "runs_ledger": str(runs_ledger),
        "report_path": str(report_path),
        "records": records,
        "fault_injection": fault_report,
    }


def run_stability_test(args: argparse.Namespace) -> dict[str, Any]:
    rounds = args.rounds
    if args.quick:
        rounds = 1
    if args.stress:
        rounds = max(rounds, 5)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = pathlib.Path(args.output_root).resolve() if args.output_root else ROOT / "generated" / "long_agent_led_stability_test" / timestamp
    output_root.mkdir(parents=True, exist_ok=True)
    runs_ledger = output_root / "long_agent_led_stability_runs.jsonl"
    report_path = output_root / "long_agent_led_stability_report.json"
    generated = ROOT / "generated"
    records: list[dict[str, Any]] = []

    for round_index in range(1, rounds + 1):
        verify_result = run_command(["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts\\verify_repo.ps1"], cwd=ROOT, timeout=args.command_timeout)
        verify = summarize_verify(verify_result, generated)
        verify["round"] = round_index
        records.append(verify)
        append_jsonl(runs_ledger, verify)

        benchmark_result = run_command([sys.executable, "scripts\\run_large_project_agent_led_benchmark.py"], cwd=ROOT, timeout=args.command_timeout)
        benchmark = summarize_benchmark(benchmark_result, generated)
        benchmark["round"] = round_index
        records.append(benchmark)
        append_jsonl(runs_ledger, benchmark)

        diagnosis_result = run_command([sys.executable, "scripts\\run_agent_autonomous_diagnosis.py"], cwd=ROOT, timeout=args.command_timeout)
        diagnosis = summarize_diagnosis(diagnosis_result, generated)
        diagnosis["round"] = round_index
        records.append(diagnosis)
        append_jsonl(runs_ledger, diagnosis)

    fault_dir = output_root / "fault_injection"
    fault_report = run_agent_fault_injection_suite.run_fault_injection_suite(fault_dir)
    append_jsonl(runs_ledger, {"kind": "fault_injection_suite", **fault_report})
    report = aggregate_report(records, fault_report, report_path=report_path, runs_ledger=runs_ledger)
    write_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--stress", action="store_true")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--command-timeout", type=int, default=1200)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_stability_test(args)
    summary = report if args.json else {
        "status": report["status"],
        "total_runs": report["total_runs"],
        "verify_pass": report["verify_pass"],
        "benchmark_pass": report["benchmark_pass"],
        "diagnosis_pass": report["diagnosis_pass"],
        "commercial_ready_count": report["commercial_ready_count"],
        "fault_injection_pass": report["fault_injection_pass"],
        "fault_injection_cases": report["fault_injection_cases"],
        "unstable_components": report["unstable_components"],
        "recommended_next_fixes": report["recommended_next_fixes"],
        "report_path": report["report_path"],
        "runs_ledger": report["runs_ledger"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] in {"pass", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
