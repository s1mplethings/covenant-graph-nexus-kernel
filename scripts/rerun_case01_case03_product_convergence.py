#!/usr/bin/env python3
"""Quota-gated fresh two-project convergence through the frozen benchmark runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.project_generation_v1 import run_benchmark  # noqa: E402
from scripts import provider_jobs, provider_resilience  # noqa: E402


EXPECTED_BENCHMARK_HASHES = {
    "cases.json": "1DBD6AAE9DBAC9FBCB0C321DAC6A07D6DA45D8B31605EACEA127C499149C0462",
    "evaluator.py": "227E330E8BA037DE38A163631E005D29F6AD6626B0AD46582604860707E95A18",
}
BENCHMARK_PATHS = {
    "cases.json": ROOT / "benchmarks" / "project_generation_v1" / "cases.json",
    "evaluator.py": ROOT / "benchmarks" / "project_generation_v1" / "evaluator.py",
}
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "project_generation_benchmark"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def benchmark_hashes() -> dict[str, str]:
    return {name: file_sha256(path) for name, path in BENCHMARK_PATHS.items()}


def run_provider_preflight(model: str = "") -> dict[str, Any]:
    report = provider_resilience.provider_preflight(
        goal="fresh product generation and bounded repair convergence",
        live=True,
        requested_model=model,
        required_role="generation",
        timeout=20,
    )
    provider_resilience.write_health_report(report)
    return report


def provider_gate(preflight: dict[str, Any]) -> tuple[str, str]:
    metadata = preflight.get("metadata", {}) if isinstance(preflight.get("metadata"), dict) else {}
    if metadata.get("live_generation_allowed") and metadata.get("selected_model"):
        return "PASS", ""
    return "BLOCKED_NO_AVAILABLE_PROVIDER", "WAITING_FOR_PROVIDER_QUOTA"


def run_fresh_case(
    selector: str,
    *,
    run_id: str,
    output_root: pathlib.Path,
    model: str,
    parallelism: int,
) -> tuple[pathlib.Path, dict[str, Any]]:
    benchmark_args = run_benchmark.build_parser().parse_args(
        [
            "--case",
            selector,
            "--run-id",
            run_id,
            "--output-root",
            str(output_root),
            "--model",
            model,
            "--parallelism",
            str(parallelism),
        ]
    )
    return run_benchmark.execute(benchmark_args)


def write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute(args: argparse.Namespace) -> tuple[pathlib.Path, dict[str, Any]]:
    current_hashes = benchmark_hashes()
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "CGKN_FRESH_PRODUCT_CONVERGENCE_%Y%m%dT%H%M%SZ"
    )
    convergence_dir = args.output_root.resolve() / run_id
    report_path = convergence_dir / "fresh_convergence_report.json"
    report: dict[str, Any] = {
        "kind": "CGKNCase01Case03ProductConvergenceReport",
        "created_at": utc_now(),
        "run_id": run_id,
        "requested_model": args.model,
        "benchmark_hash_before": current_hashes,
        "benchmark_hash_expected": EXPECTED_BENCHMARK_HASHES,
        "benchmark_hash_unchanged": current_hashes == EXPECTED_BENCHMARK_HASHES,
        "provider_status": "NOT_CHECKED",
        "workflow_state": "PREFLIGHT",
        "case_runs": [],
        "manual_candidate_patch": False,
        "provider_execution_path": "existing production split-file leaf executor",
        "provider_parallelism": args.parallelism,
    }
    if current_hashes != EXPECTED_BENCHMARK_HASHES:
        report.update(
            status="BENCHMARK_HASH_MISMATCH",
            workflow_state="BLOCKED",
            final_next_action="RESTORE_FROZEN_BENCHMARK",
        )
        write_json(report_path, report)
        return report_path, report

    preflight = run_provider_preflight(args.model)
    write_json(convergence_dir / "provider_preflight.json", preflight)
    provider_status, workflow_state = provider_gate(preflight)
    provider_meta = preflight.get("metadata", {}) if isinstance(preflight.get("metadata"), dict) else {}
    selected_model = str(provider_meta.get("selected_generation_model") or provider_meta.get("selected_model") or "")
    selected_repair_model = str(provider_meta.get("selected_repair_model") or selected_model)
    report["provider_auto_select"] = provider_meta
    report["model"] = selected_model
    report["selected_generation_model"] = selected_model
    report["selected_repair_model"] = selected_repair_model
    report["selected_provider"] = str((provider_meta.get("selected_provider") or {}).get("name") or "")
    report["selected_role"] = str(provider_meta.get("selected_role") or "")
    report["endpoint"] = str(provider_meta.get("endpoint") or "")
    report["provider_status"] = provider_status
    report["workflow_state"] = workflow_state or "RUNNING"
    if provider_status != "PASS":
        report.update(
            status=provider_status,
            final_next_action=workflow_state,
            benchmark_hash_after=benchmark_hashes(),
        )
        write_json(report_path, report)
        return report_path, report

    prior_repair_model = os.environ.get("CGKN_PROVIDER_REPAIR_MODEL")
    os.environ["CGKN_PROVIDER_REPAIR_MODEL"] = selected_repair_model
    try:
        for selector, run_label in (("01", "PROJECT_A"), ("03", "PROJECT_B")):
            case_run_id = f"{run_id}_{run_label}"
            case_run_dir, case_report = run_fresh_case(
                selector,
                run_id=case_run_id,
                output_root=convergence_dir / "benchmark_runs",
                model=selected_model,
                parallelism=args.parallelism,
            )
            case_result = dict((case_report.get("case_results") or [{}])[0])
            report["case_runs"].append(
                {
                    "case_id": str(case_result.get("case_id") or selector),
                    "run_id": case_run_id,
                    "run_dir": str(case_run_dir),
                    "benchmark_report": str(case_run_dir / "benchmark_report.json"),
                    "result": case_result.get("result", "NOT_EVALUATED"),
                    "score": case_result.get("score"),
                }
            )
            if case_result.get("result") == "BLOCKED_PROVIDER":
                report["provider_status"] = "BLOCKED_PROVIDER"
                report["workflow_state"] = "WAITING_FOR_PROVIDER"
                break
    finally:
        if prior_repair_model is None:
            os.environ.pop("CGKN_PROVIDER_REPAIR_MODEL", None)
        else:
            os.environ["CGKN_PROVIDER_REPAIR_MODEL"] = prior_repair_model

    final_hashes = benchmark_hashes()
    report["benchmark_hash_after"] = final_hashes
    report["benchmark_hash_unchanged"] = (
        current_hashes == final_hashes == EXPECTED_BENCHMARK_HASHES
    )
    if not report["benchmark_hash_unchanged"]:
        report.update(
            status="BENCHMARK_HASH_CHANGED_DURING_RUN",
            workflow_state="BLOCKED",
            final_next_action="RESTORE_FROZEN_BENCHMARK",
        )
    elif report["provider_status"] != "PASS":
        report.update(
            status=report["provider_status"],
            final_next_action=report["workflow_state"],
        )
    else:
        report.update(
            status="COMPLETE",
            workflow_state="COMPLETE",
            final_next_action="REVIEW_FRESH_CONVERGENCE_REPORT",
        )
    write_json(report_path, report)
    return report_path, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="", help="Optional explicit model; omit to auto-select.")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-root", type=pathlib.Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--parallelism",
        type=int,
        default=provider_jobs.configured_parallelism(),
        help="Worker count for the existing production split-file leaf executor.",
    )
    return parser


def main() -> int:
    report_path, report = execute(build_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "workflow_state": report["workflow_state"],
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "COMPLETE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
