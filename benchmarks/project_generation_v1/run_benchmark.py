#!/usr/bin/env python3
"""CLI runner for CGKN Project Generation Benchmark v1."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from benchmarks.project_generation_v1.evaluator import (  # type: ignore
        BENCHMARK_ID, SCHEMA_VERSION, aggregate_results, candidate_tree_hash, classify_provider_blocker,
        collect_invocation_metrics, compare_reports, evaluate_case, inspect_delivery, load_case_catalog,
        read_json, scan_production_contamination, utc_now, write_json,
    )
    from benchmarks.project_generation_v1.fixtures import create_fake_candidate, run_dry_case_probes  # type: ignore
else:
    from .evaluator import (
        BENCHMARK_ID, SCHEMA_VERSION, aggregate_results, candidate_tree_hash, classify_provider_blocker,
        collect_invocation_metrics, compare_reports, evaluate_case, inspect_delivery, load_case_catalog,
        read_json, scan_production_contamination, utc_now, write_json,
    )
    from .fixtures import create_fake_candidate, run_dry_case_probes


ROOT = pathlib.Path(__file__).resolve().parents[2]
CASES_PATH = pathlib.Path(__file__).with_name("cases.json")
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "project_generation_benchmark"
DEFAULT_PRODUCTION_SCRIPT = ROOT / "scripts" / "run_local_pipeline.py"
BASELINE_LABEL = "CGKN_PROJECT_BENCHMARK_BASELINE_V1"


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def version_binding(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "repo_sha": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "provider": args.provider,
        "model": args.model,
        "parallelism": args.parallelism,
        "codex_version": os.environ.get("CODEX_VERSION", "not_declared"),
        "config_sha256": hashlib.sha256(json.dumps({"provider": args.provider, "model": args.model, "parallelism": args.parallelism}, sort_keys=True).encode()).hexdigest(),
        "schema_version": SCHEMA_VERSION,
    }


def make_run_id(repo_sha: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"PGBV1_{timestamp}_{repo_sha[:8]}"


def normalize_case_selector(value: str) -> str:
    raw = str(value or "").strip().upper()
    if raw.startswith("CASE_"):
        return raw
    if raw.isdigit():
        return f"CASE_{int(raw):02d}_"
    return raw


def select_cases(catalog: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    cases = list(catalog["cases"])
    if args.case:
        selector = normalize_case_selector(args.case)
        selected = [case for case in cases if str(case["case_id"]).startswith(selector)]
    elif args.level:
        selected = [case for case in cases if case["level"] == args.level.upper()]
    elif args.all:
        selected = cases
    elif args.pilot:
        selected = [case for case in cases if case["case_id"] in {
            "CASE_01_CSV_DATA_CLEANER", "CASE_03_LOCAL_PROJECT_BOARD", "CASE_10_CUSTOMER_FEEDBACK_MANAGER"
        }]
    elif args.dry_run:
        selected = [case for case in cases if case["case_id"] in {"CASE_01_CSV_DATA_CLEANER", "CASE_03_LOCAL_PROJECT_BOARD"}]
    else:
        raise ValueError("select --case, --level, --all, or --dry-run")
    if not selected:
        raise ValueError("case selection matched no benchmark cases")
    if args.dry_run and any(case["case_id"] not in {"CASE_01_CSV_DATA_CLEANER", "CASE_03_LOCAL_PROJECT_BOARD"} for case in selected):
        raise ValueError("harness dry-run is intentionally limited to CASE_01 and CASE_03")
    return selected


def provider_readiness_blocker(path: pathlib.Path | None) -> str:
    if not path:
        return ""
    if not path.is_file():
        raise FileNotFoundError(f"readiness file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if classify_provider_blocker(text):
        try:
            value = json.loads(text)
            return json.dumps(value, ensure_ascii=False)[-4000:]
        except ValueError:
            return text[-4000:]
    return ""


def _public_context(case: dict[str, Any]) -> dict[str, str]:
    return {"user_goal": str(case["user_goal"])}


def _run_external_command(command_text: str, extra_args: list[str], *, cwd: pathlib.Path, timeout: int) -> subprocess.CompletedProcess[str]:
    command = shlex.split(command_text, posix=os.name != "nt") + extra_args
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def invoke_production(case: dict[str, Any], *, run_dir: pathlib.Path, case_dir: pathlib.Path, args: argparse.Namespace) -> tuple[pathlib.Path, str, dict[str, Any]]:
    """Invoke the existing production facade in an opaque slot; only user_goal is case content."""
    slot_name = hashlib.sha256(f"{run_dir.name}:{case['case_id']}".encode()).hexdigest()[:16]
    slot = run_dir / "production_slots" / slot_name
    candidate_slot = slot / "candidate"
    production_run = slot / "run"
    result_path = slot / "production_result.json"
    slot.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable, str(args.production_script), "--goal", str(case["user_goal"]),
        "--out-dir", str(candidate_slot), "--run-dir", str(production_run), "--result", str(result_path),
        "--allow-network", "--allow-provider", "--use-api", "--model", args.model,
        "--timeout", str(args.production_timeout), "--json",
    ]
    write_json(case_dir / "production_context_receipt.json", {
        "kind": "BenchmarkProductionContextReceipt",
        "visible_keys": ["user_goal"],
        "user_goal_sha256": hashlib.sha256(str(case["user_goal"]).encode()).hexdigest(),
        "hidden_acceptance_visible": False,
        "opaque_production_slot": slot_name,
    })
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=args.production_timeout + 60, check=False)
        raw_error = "\n".join([completed.stdout[-4000:], completed.stderr[-4000:]])
        return_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        raw_error = f"provider timeout: {exc}"
        return_code = 124
    elapsed = round(time.perf_counter() - started, 3)
    production_result: dict[str, Any] = {}
    if result_path.is_file():
        try:
            production_result = read_json(result_path)
            raw_error += "\n" + json.dumps(production_result, ensure_ascii=False)[-4000:]
        except (OSError, ValueError, TypeError) as exc:
            raw_error += f"\nresult parse error: {exc}"
    candidate = case_dir / "candidate"
    if candidate_slot.is_dir():
        shutil.copytree(candidate_slot, candidate)
    for artifact_name in ("final_project_bundle.zip", "delivery_receipt.json"):
        sources = [path for path in slot.rglob(artifact_name) if path.is_file() and candidate_slot not in path.parents]
        if sources:
            shutil.copy2(sources[0], case_dir / artifact_name)
    metrics = collect_invocation_metrics(slot)
    metrics["elapsed_seconds"] = elapsed
    metrics["production_return_code"] = return_code
    write_json(case_dir / "production_execution_receipt.json", {
        "kind": "BenchmarkProductionExecutionReceipt", "created_at": utc_now(), "return_code": return_code,
        "elapsed_seconds": elapsed, "result_path": str(result_path.relative_to(run_dir)),
        "candidate_copied": candidate.is_dir(), "metrics": metrics,
    })
    return candidate, raw_error, metrics


def _load_external_observations(case_dir: pathlib.Path) -> list[dict[str, Any]]:
    path = case_dir / "evidence" / "external_observations.json"
    if not path.is_file():
        return []
    value = read_json(path)
    observations = value.get("observations", [])
    return [dict(item) for item in observations if isinstance(item, dict)] if isinstance(observations, list) else []


def run_external_evaluator(case: dict[str, Any], run_id: str, candidate: pathlib.Path, case_dir: pathlib.Path, args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.evaluator_command:
        return []
    evaluator_input = case_dir / "evaluator_input.json"
    write_json(evaluator_input, {
        "kind": "ProjectBenchmarkEvaluatorInput", "schema_version": SCHEMA_VERSION, "case": case,
        "benchmark_run_id": run_id, "candidate_dir": str(candidate.resolve()),
        "candidate_sha256": candidate_tree_hash(candidate), "output_path": str((case_dir / "evidence" / "external_observations.json").resolve()),
    })
    completed = _run_external_command(args.evaluator_command, ["--input", str(evaluator_input)], cwd=ROOT, timeout=args.evaluator_timeout)
    write_json(case_dir / "evaluator_execution_receipt.json", {
        "return_code": completed.returncode, "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:]
    })
    return _load_external_observations(case_dir)


def run_controlled_repair(case: dict[str, Any], candidate: pathlib.Path, case_dir: pathlib.Path, args: argparse.Namespace) -> dict[str, Any] | None:
    """Ask an external benchmark adapter to inject one safe fault and enter existing recovery."""
    if not args.repair_command:
        return None
    receipt_path = case_dir / "repair" / "repair_receipt.json"
    request_path = case_dir / "repair" / "fault_request.json"
    write_json(request_path, {
        "kind": "ProjectBenchmarkControlledFaultRequest", "schema_version": SCHEMA_VERSION,
        "case_id": case["case_id"], "candidate_dir": str(candidate.resolve()),
        "candidate_sha256_before_fault": candidate_tree_hash(candidate),
        "constraints": {
            "fault_count": 1, "safe_and_recoverable": True, "inject_after_happy_path": True,
            "use_existing_cgkn_recovery": True, "provider_scope": "affected_jobs_only",
        },
        "output_path": str(receipt_path.resolve()),
    })
    completed = _run_external_command(args.repair_command, ["--input", str(request_path)], cwd=ROOT, timeout=args.repair_timeout)
    write_json(case_dir / "repair" / "repair_execution_receipt.json", {
        "return_code": completed.returncode, "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:]
    })
    if completed.returncode != 0 or not receipt_path.is_file():
        return {"attempted": True, "injected_after_happy_path": True, "recovery_status": "FAIL", "affected_jobs": [], "provider_recalled_jobs": [], "invalidated_evidence": [], "reemitted_evidence": []}
    receipt = read_json(receipt_path)
    receipt["attempted"] = True
    receipt["initial_happy_path_pass"] = True
    return receipt


def blocked_case_result(case: dict[str, Any], blocker: str, *, dry_run: bool = False) -> dict[str, Any]:
    return {
        "kind": "ProjectGenerationBenchmarkCaseResult", "schema_version": SCHEMA_VERSION,
        "evaluated_at": utc_now(), "case_id": case["case_id"], "level": case["level"],
        "user_goal": case["user_goal"],
        "result": "BLOCKED_PROVIDER", "score": None, "score_breakdown": {}, "hard_failures": [],
        "runtime_status": "NOT_EVALUATED", "delivery_status": "NOT_EVALUATED", "candidate_sha256": "",
        "provider_blocker": blocker[-4000:], "accepted_observation_count": 0, "rejected_observations": [],
        "metrics": {"provider_api_calls": 0, "codex_invocations": 0, "elapsed_seconds": 0.0},
        "repair": {"attempted": False}, "dry_run": dry_run, "production_verdict_used": False,
    }


def run_case(case: dict[str, Any], *, run_id: str, run_dir: pathlib.Path, args: argparse.Namespace, preflight_blocker: str = "") -> dict[str, Any]:
    case_dir = run_dir / "cases" / str(case["case_id"])
    result_path = case_dir / "case_result.json"
    if args.resume and result_path.is_file():
        prior = read_json(result_path)
        prior["resumed_without_overwrite"] = True
        return prior
    case_dir.mkdir(parents=True, exist_ok=False)
    if preflight_blocker:
        result = blocked_case_result(case, preflight_blocker)
        write_json(result_path, result)
        return result
    if args.dry_run:
        candidate = create_fake_candidate(case, case_dir, _public_context(case))
        observations = run_dry_case_probes(case, run_id, candidate, case_dir)
        metrics = {"provider_api_calls": 0, "codex_invocations": 0, "total_tokens": 0, "actual_cost": None, "elapsed_seconds": 0.0}
        result = evaluate_case(case, run_id=run_id, candidate_dir=candidate, observations=observations, metrics=metrics, dry_run=True)
    else:
        candidate, provider_error, metrics = invoke_production(case, run_dir=run_dir, case_dir=case_dir, args=args)
        if not candidate.is_dir() and classify_provider_blocker(provider_error):
            result = blocked_case_result(case, provider_error)
            result["metrics"] = metrics
        else:
            observations = run_external_evaluator(case, run_id, candidate, case_dir, args)
            if candidate.is_dir():
                observations.append(inspect_delivery(candidate, case_dir, case_id=str(case["case_id"]), run_id=run_id))
            initial = evaluate_case(
                case, run_id=run_id, candidate_dir=candidate, observations=observations, metrics=metrics,
                provider_error=provider_error, require_repair=False,
            )
            if initial["result"] == "PROJECT_PASS":
                repair = run_controlled_repair(case, candidate, case_dir, args)
                if repair is None:
                    result = dict(initial)
                    result["result"] = "NOT_EVALUATED"
                    result["criteria_not_evaluated"] = sorted(set(result.get("criteria_not_evaluated", []) + ["controlled_repair"]))
                    result["repair"] = {"attempted": False, "initial_happy_path_pass": True}
                else:
                    observations = run_external_evaluator(case, run_id, candidate, case_dir, args)
                    observations.append(inspect_delivery(candidate, case_dir, case_id=str(case["case_id"]), run_id=run_id))
                    result = evaluate_case(
                        case, run_id=run_id, candidate_dir=candidate, observations=observations, metrics=metrics,
                        provider_error=provider_error, repair=repair, require_repair=True,
                    )
            else:
                result = initial
    write_json(result_path, result)
    return result


def build_report(run_id: str, manifest: dict[str, Any], cases: list[dict[str, Any]], results: list[dict[str, Any]], repo_root: pathlib.Path, baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    isolation_pass = all(
        not result.get("production_context_hidden_acceptance", False) for result in results
    )
    contamination = scan_production_contamination(repo_root)
    dry_checks = None
    if manifest["mode"] == "HARNESS_DRY_RUN":
        dry_checks = {
            "case_loading": "PASS" if {case["case_id"] for case in cases} == {"CASE_01_CSV_DATA_CLEANER", "CASE_03_LOCAL_PROJECT_BOARD"} else "FAIL",
            "case_isolation": "PASS" if isolation_pass else "FAIL",
            "artifact_layout": "PASS" if all(result.get("candidate_sha256") for result in results) else "FAIL",
            "scoring": "PASS" if all(isinstance(result.get("score"), int) for result in results) else "FAIL",
            "runtime_evaluator": "PASS" if all(result.get("runtime_status") == "PASS" for result in results) else "FAIL",
            "aggregation": "PASS" if aggregate_results(results)["case_count"] == 2 else "FAIL",
            "blocked_provider_handling": "PASS" if classify_provider_blocker("HTTP 403 quota exhausted") and not classify_provider_blocker("customer feature failed") else "FAIL",
            "non_live_score_guard": "PASS" if all(result.get("result") == "NOT_EVALUATED" for result in results) else "FAIL",
        }
        dry_checks["overall"] = "PASS" if all(value == "PASS" for value in dry_checks.values()) else "FAIL"
    report = {
        "kind": "CGKNProjectGenerationBenchmarkReport", "schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID, "run_id": run_id, "generated_at": utc_now(),
        "mode": manifest["mode"], "version_binding": manifest["version_binding"],
        "selected_cases": [{"case_id": case["case_id"], "level": case["level"], "title": case["title"]} for case in cases],
        "hidden_acceptance_isolation": "PASS" if isolation_pass else "FAIL",
        "evaluator_independent": True,
        "production_verdict_used": False,
        "harness_checks": dry_checks,
        "production_call_graph": [
            "benchmark runner",
            "scripts/run_local_pipeline.py reviewed production facade",
            "existing ProviderJob leaf executor",
            "Provider output validation",
            "post-build finalization",
            "local_packager",
            "public_delivery_gate",
            "independent black-box evaluator",
            "controlled one-unit fault and existing CGKN recovery",
            "independent re-evaluation"
        ],
        "summary": aggregate_results(results),
        "case_results": results,
        "production_contamination": {"status": "PASS" if not contamination else "FAIL", "findings": contamination},
        "baseline_label": None,
        "comparison": compare_reports({"run_id": run_id, "summary": aggregate_results(results)}, baseline) if baseline else None,
    }
    return report


def report_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# CGKN Project Generation Benchmark v1", "",
        f"- Repository SHA: `{report['version_binding']['repo_sha']}`",
        f"- Provider/model: `{report['version_binding']['provider']}` / `{report['version_binding']['model']}`",
        f"- Benchmark run id: `{report['run_id']}`",
        f"- Projects PASS / FAIL / BLOCKED: `{summary['counts']['PROJECT_PASS']}` / `{summary['counts']['PROJECT_FAIL']}` / `{summary['counts']['BLOCKED_PROVIDER']}`",
        f"- Project Pass Rate: `{summary['pass_rate']}`",
        f"- First-run Success Rate: `{summary['one_shot_success_rate']}`",
        f"- Repair Recovery Rate: `{summary['repair_success_rate']}`",
        f"- Requirement Coverage: `{summary['requirement_coverage']}`",
        f"- Median Provider Calls: `{summary['median_provider_calls']}`",
        f"- Median Provider Wall Time: `{summary['median_provider_wall_time']}`",
        f"- Median Codex Calls: `{summary['median_codex_calls']}`",
        f"- Overall Score: `{summary['overall_score']}`", "", "## Cases", "",
        "| Case | Level | Result | Score | Runtime | Delivery |", "|---|---:|---|---:|---|---|",
    ]
    for result in report["case_results"]:
        lines.append(f"| {result['case_id']} | {result['level']} | {result['result']} | {result.get('score')} | {result.get('runtime_status')} | {result.get('delivery_status')} |")
    for result in report["case_results"]:
        metrics = result.get("metrics", {})
        lines.extend([
            "", f"### {result['case_id']}", "", f"Goal: {result.get('user_goal', '')}", "",
            f"- Verdict / score: `{result.get('result')}` / `{result.get('score')}`",
            f"- Score breakdown: `{json.dumps(result.get('score_breakdown', {}), sort_keys=True)}`",
            f"- Provider jobs / calls / peak concurrency: `{metrics.get('provider_jobs_total')}` / `{metrics.get('provider_api_calls')}` / `{metrics.get('provider_peak_concurrency')}`",
            f"- Codex calls / wall time: `{metrics.get('codex_invocations')}` / `{metrics.get('elapsed_seconds')}`",
            f"- Failure reason: `{json.dumps(result.get('hard_failures') or result.get('criteria_not_evaluated') or result.get('provider_blocker', ''), ensure_ascii=False)}`",
        ])
    lines.extend([
        "", "## Evaluation integrity", "",
        f"- Hidden acceptance isolation: `{report['hidden_acceptance_isolation']}`",
        f"- Independent evaluator: `{report['evaluator_independent']}`",
        f"- Production contamination: `{report['production_contamination']['status']}`",
        f"- Actual provider-reported cost: `{summary['actual_cost']}`; token count: `{summary['total_tokens']}`",
        f"- Failure taxonomy: `{json.dumps(summary['failure_taxonomy'], sort_keys=True)}`", "",
        "Dry-run results validate only the harness and are never counted as CGKN project-generation PASS.", "",
    ])
    return "\n".join(lines)


def execute(args: argparse.Namespace) -> tuple[pathlib.Path, dict[str, Any]]:
    catalog = load_case_catalog(CASES_PATH)
    binding = version_binding(args)
    run_id = args.run_id or make_run_id(binding["repo_sha"])
    output_root = args.output_root.resolve()
    run_dir = output_root / run_id
    manifest_path = run_dir / "run_manifest.json"
    selection_unspecified = not (args.case or args.level or args.all or args.pilot or args.dry_run)
    if args.report_only and selection_unspecified:
        if not args.run_id or not manifest_path.is_file():
            raise ValueError("--report-only without a selection requires an existing --run-id")
        existing_manifest = read_json(manifest_path)
        selected_ids = set(existing_manifest.get("selected_case_ids", []))
        selected = [case for case in catalog["cases"] if case["case_id"] in selected_ids]
    else:
        selected = select_cases(catalog, args)
    if run_dir.exists() and not (args.resume or args.report_only):
        raise FileExistsError(f"benchmark run already exists; use --resume or a new --run-id: {run_dir}")
    if args.report_only:
        if not manifest_path.is_file():
            raise FileNotFoundError(f"run manifest missing: {manifest_path}")
        manifest = read_json(manifest_path)
        results = [read_json(run_dir / "cases" / str(case["case_id"]) / "case_result.json") for case in selected]
    else:
        run_dir.mkdir(parents=True, exist_ok=args.resume)
        if manifest_path.is_file():
            manifest = read_json(manifest_path)
            if manifest.get("version_binding", {}).get("repo_sha") != binding["repo_sha"]:
                raise RuntimeError("resume repo SHA does not match the original benchmark run")
        else:
            manifest = {
                "kind": "CGKNProjectGenerationBenchmarkRunManifest", "schema_version": SCHEMA_VERSION,
                "benchmark_id": BENCHMARK_ID, "run_id": run_id, "created_at": utc_now(),
                "mode": "HARNESS_DRY_RUN" if args.dry_run else "LIVE", "version_binding": binding,
                "selected_case_ids": [case["case_id"] for case in selected],
                "hidden_acceptance_forwarded_to_production": False,
            }
            write_json(manifest_path, manifest)
        blocker = provider_readiness_blocker(args.readiness_file) if not args.dry_run else ""
        results = [run_case(case, run_id=run_id, run_dir=run_dir, args=args, preflight_blocker=blocker) for case in selected]
    baseline = read_json(args.compare_baseline) if args.compare_baseline else None
    report = build_report(run_id, manifest, selected, results, ROOT, baseline)
    valid_live = manifest["mode"] == "LIVE" and all(result["result"] in {"PROJECT_PASS", "PROJECT_FAIL"} for result in results)
    if args.baseline and valid_live:
        report["baseline_label"] = BASELINE_LABEL
    report_json = run_dir / "benchmark_report.json"
    report_md = run_dir / "benchmark_report.md"
    if report_json.exists():
        snapshot = run_dir / "reports" / datetime.now(timezone.utc).strftime("benchmark_report_%Y%m%dT%H%M%S%fZ.json")
        write_json(snapshot, report)
        snapshot.with_suffix(".md").write_text(report_markdown(report), encoding="utf-8")
    else:
        write_json(report_json, report)
        report_md.write_text(report_markdown(report), encoding="utf-8")
    return run_dir, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", default="")
    selection.add_argument("--level", choices=["L1", "L2", "L3", "L4", "L5"], default="")
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--pilot", action="store_true", help="Select the fixed CASE_01/CASE_03/CASE_10 live pilot")
    parser.add_argument("--dry-run", action="store_true", help="Validate the harness with non-live CASE_01/CASE_03 fixtures")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-root", type=pathlib.Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--provider", default="openai-compatible")
    parser.add_argument("--model", default="qwen3.8-max")
    parser.add_argument("--parallelism", type=int, default=1)
    parser.add_argument("--production-script", type=pathlib.Path, default=DEFAULT_PRODUCTION_SCRIPT)
    parser.add_argument("--production-timeout", type=int, default=900)
    parser.add_argument("--readiness-file", type=pathlib.Path)
    parser.add_argument("--evaluator-command", default="")
    parser.add_argument("--evaluator-timeout", type=int, default=600)
    parser.add_argument("--repair-command", default="")
    parser.add_argument("--repair-timeout", type=int, default=900)
    parser.add_argument("--compare-baseline", type=pathlib.Path)
    parser.add_argument("--baseline", action="store_true")
    return parser


def main() -> int:
    try:
        run_dir, report = execute(build_parser().parse_args())
    except Exception as exc:
        print(f"BENCHMARK HARNESS FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"run_dir": str(run_dir), "summary": report["summary"], "contamination": report["production_contamination"]["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
