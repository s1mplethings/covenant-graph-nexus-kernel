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
import zipfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from scripts import provider_api_budget, repair_evidence_contract

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
DEFAULT_PRODUCTION_SCRIPT = ROOT / "scripts" / "run_codex_conversation_generation.py"
DEFAULT_EVALUATOR_SCRIPT = pathlib.Path(__file__).with_name("independent_evaluator.py")
BASELINE_LABEL = "CGKN_PROJECT_BENCHMARK_BASELINE_V1"
EXTERNAL_PROVIDER_PROFILE = ROOT / "config" / "provider_profiles" / "project-generation-external-api.json"
FIXED10_SHA256 = "9B470B65970D6A3A33D45CDCAA4646B785F1F348C27F6121573F23E7D57974AF"


def _first_environment_source(names: list[str]) -> str:
    return next((name for name in names if str(os.environ.get(name, "")).strip()), "")


def external_api_config_audit(args: argparse.Namespace) -> dict[str, Any]:
    """Validate live external-API prerequisites without sending any request."""
    profile = read_json(EXTERNAL_PROVIDER_PROFILE)
    base_source = _first_environment_source(list(profile.get("base_url_env_names", [])))
    key_source = _first_environment_source(list(profile.get("api_key_env_names", [])))
    base_url = str(os.environ.get(base_source, "")).strip() if base_source else ""
    missing: list[str] = []
    if not base_source:
        missing.append("explicit_base_url_environment_variable")
    if not key_source:
        missing.append("api_key_environment_variable")
    if not str(args.model or "").strip():
        missing.append("generation_model")
    if not 1 <= int(args.parallelism) <= 4:
        missing.append("parallelism_between_1_and_4")
    for field in ("max_api_calls", "max_total_input_tokens", "max_total_output_tokens", "max_estimated_cost"):
        value = getattr(args, field)
        if value is None:
            missing.append(field)
        elif float(value) <= 0:
            missing.append(f"positive_{field}")
    price_verified = args.input_cost_per_million is not None and args.output_cost_per_million is not None
    dependency_ready = True
    dependency_reason = ""
    if args.dependency_mode == "wheelhouse":
        dependency_ready = bool(args.wheelhouse and args.wheelhouse.resolve().is_dir())
        if not dependency_ready:
            dependency_reason = "wheelhouse_directory_required"
            missing.append(dependency_reason)
    elif args.dependency_mode == "registry":
        dependency_ready = bool(args.approve_package_registry)
        if not dependency_ready:
            dependency_reason = "explicit_package_registry_approval_required"
            missing.append(dependency_reason)
    audit_status = "READY" if not missing else "BLOCKED_CONFIGURATION"
    return {
        "kind": "CGKNExternalAPIProviderConfigAudit",
        "schema_version": "1.0",
        "created_at": utc_now(),
        "status": audit_status,
        "transport_attempted": False,
        "profile_id": profile.get("profile_id"),
        "profile_path": str(EXTERNAL_PROVIDER_PROFILE.relative_to(ROOT)),
        "execution_mode": "external_api",
        "provider_protocol": profile.get("protocol"),
        "base_url_configured": bool(base_source),
        "base_url_source": base_source or None,
        "base_url_host": urlparse(base_url).netloc if base_url else None,
        "api_key_configured": bool(key_source),
        "api_key_source": key_source or None,
        "credential_value_recorded": False,
        "generation_model": args.model,
        "repair_model": args.repair_model or args.model,
        "repair_model_escalation_configured": bool(args.repair_model),
        "limits": {
            "max_api_calls": args.max_api_calls,
            "max_total_input_tokens": args.max_total_input_tokens,
            "max_total_output_tokens": args.max_total_output_tokens,
            "max_estimated_cost": args.max_estimated_cost,
            "input_cost_per_million": args.input_cost_per_million,
            "output_cost_per_million": args.output_cost_per_million,
            "price_status": "VERIFIED_CONFIG" if price_verified else "PRICE_NOT_AVAILABLE",
            "estimated_cost_enforced": bool(price_verified),
        },
        "dependency_policy": {
            "mode": args.dependency_mode,
            "ready": dependency_ready,
            "reason": dependency_reason,
            "wheelhouse": str(args.wheelhouse.resolve()) if args.wheelhouse else "",
            "package_registry_approved": bool(args.approve_package_registry),
            "provider_network_separate_from_package_registry": True,
        },
        "cache": {
            "mode": str(os.environ.get("CGKN_PROVIDER_CACHE_MODE", profile.get("cache_mode", "off"))),
            "directory_configured": bool(str(os.environ.get("CGKN_PROVIDER_RESPONSE_CACHE_DIR", "")).strip()),
            "live_and_replay_distinguished": True,
        },
        "missing_requirements": missing,
        "codex_generation_calls_allowed": 0,
        "codex_repair_calls_allowed": 0,
    }


def _not_evaluated_external_result(case: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    return {
        "kind": "ProjectGenerationBenchmarkCaseResult", "schema_version": SCHEMA_VERSION,
        "evaluated_at": utc_now(), "case_id": case["case_id"], "level": case["level"],
        "user_goal": case["user_goal"], "result": "NOT_EVALUATED", "first_result": "NOT_EVALUATED",
        "workflow_state": "EXTERNAL_API_CONFIGURATION_REQUIRED", "score": None, "score_breakdown": {},
        "hard_failures": [], "criteria_not_evaluated": ["external_api_not_authorized"],
        "configuration_requirements": missing, "runtime_status": "NOT_EVALUATED",
        "dependency_status": "NOT_EVALUATED", "persistence_status": "NOT_EVALUATED",
        "integration_status": "NOT_EVALUATED", "goal_fidelity_status": "NOT_EVALUATED",
        "delivery_status": "NOT_EVALUATED", "candidate_sha256": "",
        "accepted_observation_count": 0, "rejected_observations": [],
        "metrics": {"provider_api_calls": 0, "codex_invocations": 0, "total_tokens": 0,
                    "actual_cost": 0.0, "elapsed_seconds": 0.0},
        "repair": {"attempted": False}, "repairs": [], "repair_rounds": 0,
        "dry_run": False, "production_verdict_used": False, "false_pass": False,
        "false_negative": False, "root_failure": None,
    }


def write_external_api_readiness_package(
    run_dir: pathlib.Path, run_id: str, cases: list[dict[str, Any]], args: argparse.Namespace,
    binding: dict[str, Any], audit: dict[str, Any],
) -> dict[str, Any]:
    """Write the complete zero-call handoff package for a later authorized run."""
    run_dir.mkdir(parents=True, exist_ok=True)
    results = [_not_evaluated_external_result(case, list(audit["missing_requirements"])) for case in cases]
    summary = aggregate_results(results)
    manifest = {
        "kind": "CGKNProjectGenerationBenchmarkRunManifest", "schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID, "run_id": run_id, "created_at": utc_now(),
        "mode": "EXTERNAL_API_READINESS_AUDIT", "version_binding": binding,
        "selected_case_ids": [case["case_id"] for case in cases],
        "case_catalog_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
        "fixed10_manifest_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest().upper(),
        "hidden_acceptance_forwarded_to_production": False, "execution_mode": "external_api",
        "transport_attempted": False, "api_budget": audit["limits"],
    }
    report = {
        "kind": "CGKNProjectGenerationBenchmarkReport", "schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID, "run_id": run_id, "generated_at": utc_now(),
        "mode": manifest["mode"], "version_binding": binding, "summary": summary,
        "case_results": results, "revision_results": [], "config_audit": audit,
        "production_contamination": {"status": "NOT_EVALUATED", "findings": []},
        "formal_evidence_status": "NOT_EVALUATED", "pass6_evidence_changed": False,
    }
    write_json(run_dir / "run_manifest.json", manifest)
    write_json(run_dir / "benchmark_report.json", report)
    write_json(run_dir / "EXTERNAL_API_PROVIDER_CONFIG_AUDIT.json", audit)
    write_json(run_dir / "EXTERNAL_API_SMOKE_RESULT.json", {
        "kind": "CGKNExternalAPISmokeResult", "status": "NOT_EVALUATED",
        "reason": "configuration_or_budget_not_explicitly_authorized", "transport_attempted": False,
        "provider_api_calls": 0, "codex_invocations": 0,
    })
    write_json(run_dir / "FIXED10_EXTERNAL_API_RESULTS.json", {"run_id": run_id, "results": results})
    write_json(run_dir / "FIXED10_EXTERNAL_API_REPAIRS.json", {
        "run_id": run_id, "maximum_rounds_per_project": 2, "repairs": [],
    })
    write_json(run_dir / "FIXED10_EXTERNAL_API_METRICS.json", summary)
    write_json(run_dir / "FIXED10_EXTERNAL_API_COST.json", {
        "kind": "CGKNExternalProviderCostSummary", "run_id": run_id, "call_mode": "NO_CALL",
        "api_calls": 0, "generation_calls": 0, "repair_calls": 0, "evaluation_calls": 0,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "limits": audit["limits"],
    })
    write_json(run_dir / "FIXED10_EXTERNAL_API_FAILURES.json", {
        "run_id": run_id, "failures": [], "not_evaluated": [case["case_id"] for case in cases],
        "reason": "external_api_configuration_required",
    })
    write_json(run_dir / "REVISION_EXTERNAL_API_RESULTS.json", {
        "run_id": run_id, "status": "NOT_EVALUATED", "revisions": [],
    })
    write_json(run_dir / "CODEX_USAGE_REDUCTION.json", {
        "run_id": run_id, "codex_generation_calls": 0, "codex_repair_calls": 0,
        "external_api_calls": 0, "target_codex_generation_and_repair_calls": 0,
        "status": "PASS",
    })
    (run_dir / "FIXED10_EXTERNAL_API_COMPARISON.md").write_text(
        "# Fixed10 External API Comparison\n\n"
        "- Frozen manifest SHA-256: `" + FIXED10_SHA256 + "`\n"
        "- Current external API run: `NOT_EVALUATED` (no authorized paid call)\n"
        "- Provider API calls: `0`; Codex generation/repair calls: `0`\n"
        "- Existing Fixed10 and Pass 6 evidence were not modified or reinterpreted.\n",
        encoding="utf-8",
    )
    (run_dir / "KNOWN_LIMITS_EXTERNAL_API.md").write_text(
        "# Known Limits — External API\n\n"
        + "\n".join(f"- Missing: `{item}`" for item in audit["missing_requirements"])
        + "\n- No connectivity probe, generation, repair, evaluation, packaging, or delivery was attempted.\n"
        "- This readiness package cannot authorize formal evidence PASS.\n",
        encoding="utf-8",
    )
    (run_dir / "REPRODUCE_EXTERNAL_API.md").write_text(
        "# Reproduce External API Readiness\n\n```powershell\n"
        f"python benchmarks/project_generation_v1/run_benchmark.py --all --provider-mode live --external-api-audit-only --run-id {run_id}\n"
        "```\n\nRemove `--external-api-audit-only` only after supplying explicit environment credentials, base URL, "
        "model, dependency source, and all numeric budget flags.\n",
        encoding="utf-8",
    )
    write_json(run_dir / "RESULT_PACKAGE_MANIFEST.json", {
        "kind": "CGKNExternalAPIReadinessResultPackage", "run_id": run_id,
        "status": "NOT_EVALUATED", "transport_attempted": False,
        "fixed10_manifest_sha256": FIXED10_SHA256,
        "pass6_evidence_changed": False, "formal_release_authority": False,
    })
    if args.provider_free_regression_result:
        regression_source = args.provider_free_regression_result.resolve()
        if not regression_source.is_file():
            raise FileNotFoundError(f"Provider-free regression result missing: {regression_source}")
        shutil.copy2(regression_source, run_dir / "FULL_PROVIDER_FREE_REGRESSION.json")
    package_path = run_dir.parent / f"{run_id}_RESULT_PACKAGE.zip"
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in run_dir.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(run_dir))
    return report


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def benchmark_source_identity() -> str:
    digest = hashlib.sha256()
    for relative in (
        "benchmarks/project_generation_v1/run_benchmark.py",
        "benchmarks/project_generation_v1/evaluator.py",
        "benchmarks/project_generation_v1/cases.json",
        "schemas/project_generation_benchmark_case_v1.schema.json",
        "scripts/run_codex_conversation_generation.py",
        "scripts/codex_conversation.py",
        "scripts/run_local_pipeline.py",
        "scripts/run_local_pipeline_impl.py",
        "scripts/provider_jobs.py",
        "scripts/local_packager.py",
        "scripts/public_delivery_gate.py",
        "tools/cgkn-agent-kit/src/cgkn_agent_kit/core.py",
    ):
        path = ROOT / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"MISSING")
        digest.update(b"\0")
    return digest.hexdigest()


def version_binding(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "repo_sha": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "provider": args.provider,
        "provider_mode": args.provider_mode,
        "execution_mode": "external_api" if args.provider_mode == "live" else args.provider_mode,
        "model": args.model,
        "repair_model": args.repair_model,
        "parallelism": args.parallelism,
        "codex_version": os.environ.get("CODEX_VERSION", "not_declared"),
        "config_sha256": hashlib.sha256(json.dumps({"provider": args.provider, "provider_mode": args.provider_mode, "model": args.model, "repair_model": args.repair_model, "parallelism": args.parallelism, "dependency_mode": args.dependency_mode, "wheelhouse": str(args.wheelhouse or ""), "package_registry_approved": args.approve_package_registry}, sort_keys=True).encode()).hexdigest(),
        "schema_version": SCHEMA_VERSION,
        "source_identity_sha256": benchmark_source_identity(),
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
    command = shlex.split(command_text, posix=os.name != "nt")
    if os.name == "nt":
        command = [
            token[1:-1]
            if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}
            else token
            for token in command
        ]
    command += extra_args
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def invoke_production(
    case: dict[str, Any],
    *,
    run_dir: pathlib.Path,
    case_dir: pathlib.Path,
    args: argparse.Namespace,
    observed_failure_path: pathlib.Path | None = None,
    execution_label: str = "initial",
) -> tuple[pathlib.Path, str, dict[str, Any], dict[str, Any]]:
    """Invoke the existing production facade in an opaque slot; only user_goal is case content."""
    slot_name = hashlib.sha256(f"{run_dir.name}:{case['case_id']}".encode()).hexdigest()[:16]
    slot = run_dir / "production_slots" / slot_name
    project_root = slot / "project_root"
    result_path = project_root / ".cgkn" / "agent-kit" / "generation_result.json"
    slot.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(args.production_script), "--project-root", str(project_root),
        "--goal", str(case["user_goal"]), "--result", str(result_path),
        "--provider-mode", args.provider_mode, "--model", args.model,
        "--timeout", str(args.production_timeout), "--json",
    ]
    if args.repair_model:
        command.extend(["--repair-model", args.repair_model])
    if args.provider_mode == "deterministic_replay":
        if not args.replay_dir:
            raise ValueError("deterministic_replay requires --replay-dir")
        command.extend(["--replay-dir", str(args.replay_dir.resolve())])
    if args.provider_mode == "live":
        command.extend(["--allow-network", "--allow-provider", "--use-api"])
    if observed_failure_path is not None:
        command.extend(["--repair-evidence", str(observed_failure_path.resolve())])
    production_env = os.environ.copy()
    production_env["CGKN_PROVIDER_PARALLELISM"] = str(args.parallelism)
    production_env["CGKN_BENCHMARK_RUN_ID"] = str(run_dir.name)
    production_env["CGKN_BENCHMARK_CASE_ID"] = str(case["case_id"])
    production_env["CGKN_PROVIDER_CALL_PHASE"] = str(execution_label).upper()
    if args.provider_mode == "live":
        production_env["CGKN_EXTERNAL_API_ONLY"] = "1"
        production_env["CGKN_PROVIDER_BUDGET_LEDGER"] = str((run_dir / "external_api_cost_ledger.json").resolve())
        production_env["CGKN_PROVIDER_MAX_API_CALLS"] = str(args.max_api_calls)
        if args.max_planning_calls is not None:
            production_env["CGKN_PROVIDER_MAX_PLANNING_CALLS"] = str(args.max_planning_calls)
        if args.max_generation_calls is not None:
            production_env["CGKN_PROVIDER_MAX_GENERATION_CALLS"] = str(args.max_generation_calls)
        if args.max_repair_calls is not None:
            production_env["CGKN_PROVIDER_MAX_REPAIR_CALLS"] = str(args.max_repair_calls)
        production_env["CGKN_PROVIDER_MAX_INPUT_TOKENS"] = str(args.max_total_input_tokens)
        production_env["CGKN_PROVIDER_MAX_OUTPUT_TOKENS"] = str(args.max_total_output_tokens)
        production_env["CGKN_PROVIDER_MAX_ESTIMATED_COST"] = str(args.max_estimated_cost)
        production_env["CGKN_PROVIDER_MAX_RETRIES"] = str(args.provider_max_retries)
        production_env["CGKN_PROVIDER_PROFILE_MAX_TOKENS"] = str(args.provider_max_tokens)
        production_env["CGKN_PROVIDER_TEMPERATURE"] = str(args.provider_temperature)
        if args.input_cost_per_million is not None:
            production_env["CGKN_PROVIDER_INPUT_COST_PER_MILLION"] = str(args.input_cost_per_million)
        if args.output_cost_per_million is not None:
            production_env["CGKN_PROVIDER_OUTPUT_COST_PER_MILLION"] = str(args.output_cost_per_million)
    write_json(case_dir / "production_context_receipt.json", {
        "kind": "BenchmarkProductionContextReceipt",
        "visible_keys": ["user_goal"],
        "user_goal_sha256": hashlib.sha256(str(case["user_goal"]).encode()).hexdigest(),
        "hidden_acceptance_visible": False,
        "opaque_production_slot": slot_name,
        "canonical_generation_result": str(result_path.relative_to(run_dir)),
    })
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, cwd=ROOT, env=production_env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=args.production_timeout + 60, check=False,
        )
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
    source_candidate = pathlib.Path(str(production_result.get("project_dir", ""))) if production_result.get("project_dir") else None
    if source_candidate and source_candidate.is_dir():
        if candidate.is_dir():
            snapshot = case_dir / "candidate_snapshots" / f"before_resume_{int(time.time())}"
            shutil.copytree(candidate, snapshot)
        shutil.copytree(source_candidate, candidate, dirs_exist_ok=True)
    explicit_artifacts = [production_result.get("package_path"), production_result.get("manifest_path")]
    for raw in explicit_artifacts:
        source = pathlib.Path(str(raw)) if raw else None
        if source and source.is_file():
            shutil.copy2(source, case_dir / source.name)
    for artifact_name in ("final_project_bundle.zip", "delivery_receipt.json"):
        sources = [path for path in slot.rglob(artifact_name) if path.is_file() and candidate not in path.parents]
        if sources and not (case_dir / artifact_name).is_file():
            shutil.copy2(sources[0], case_dir / artifact_name)
    metrics = collect_invocation_metrics(slot)
    metrics["elapsed_seconds"] = elapsed
    metrics["production_return_code"] = return_code
    receipt_name = (
        "production_execution_receipt.json"
        if execution_label == "initial"
        else f"production_execution_receipt_{execution_label}.json"
    )
    write_json(case_dir / receipt_name, {
        "kind": "BenchmarkProductionExecutionReceipt", "created_at": utc_now(), "return_code": return_code,
        "elapsed_seconds": elapsed, "result_path": str(result_path.relative_to(run_dir)),
        "candidate_copied": candidate.is_dir(), "metrics": metrics,
        "production_claim": str(production_result.get("status", "NOT_EVALUATED")).upper(),
        "workflow_state": str(production_result.get("workflow_state", production_result.get("status", "NOT_EVALUATED"))).upper(),
        "provider_mode": args.provider_mode,
    })
    return candidate, raw_error, metrics, production_result


def _load_external_observations(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    value = read_json(path)
    observations = value.get("observations", [])
    return [dict(item) for item in observations if isinstance(item, dict)] if isinstance(observations, list) else []


def run_external_evaluator(
    case: dict[str, Any], run_id: str, candidate: pathlib.Path, case_dir: pathlib.Path,
    args: argparse.Namespace, *, phase: str = "initial", revision: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not args.evaluator_command:
        return []
    phase_dir = case_dir / "evaluations" / phase
    evaluator_input = phase_dir / "evaluator_input.json"
    observations_path = phase_dir / "external_observations.json"
    write_json(evaluator_input, {
        "kind": "ProjectBenchmarkEvaluatorInput", "schema_version": SCHEMA_VERSION, "case": case,
        "evaluation_phase": phase, "revision": revision,
        "benchmark_run_id": run_id, "candidate_dir": str(candidate.resolve()),
        "candidate_sha256": candidate_tree_hash(candidate), "output_path": str(observations_path.resolve()),
        "dependency_policy": {
            "mode": args.dependency_mode,
            "wheelhouse": str(args.wheelhouse.resolve()) if args.wheelhouse else "",
            "registry_approved": bool(args.approve_package_registry),
            "registry_url": args.package_registry_url,
        },
    })
    completed = _run_external_command(args.evaluator_command, ["--input", str(evaluator_input)], cwd=ROOT, timeout=args.evaluator_timeout)
    write_json(phase_dir / "evaluator_execution_receipt.json", {
        "return_code": completed.returncode, "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:]
    })
    return _load_external_observations(observations_path)


def run_controlled_repair(
    case: dict[str, Any], candidate: pathlib.Path, case_dir: pathlib.Path, args: argparse.Namespace,
    *, run_id: str, run_dir: pathlib.Path, round_number: int,
    failed_result: dict[str, Any], observations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Route one observed project failure into the existing bounded CGKN recovery path."""
    round_dir = case_dir / "repairs" / f"round_{round_number}"
    receipt_path = round_dir / "repair_receipt.json"
    request_path = round_dir / "repair_request.json"
    ordinary_categories = {
        "CODE_GENERATION", "DEPENDENCY", "RUNTIME", "INTEGRATION",
        "PERSISTENCE", "TEST", "EVIDENCE", "REPAIR", "DELIVERY",
    }
    root_failure = str(failed_result.get("root_failure", "UNKNOWN")).upper()
    repair_eligible = root_failure in ordinary_categories
    failed_observations = [
        {
            "criterion_id": str(item.get("criterion_id", "")),
            "status": str(item.get("status", "FAIL")),
            "failure_category": root_failure,
            "observed_behavior": str(item.get("details", ""))[:4000],
            "failure_stack": str(item.get("failure_stack", ""))[:4000],
            "affected_files": [
                str(path).replace("\\", "/")
                for path in item.get("affected_files", [])
                if str(path).strip()
            ],
            "affected_work_nodes": [
                str(node)
                for node in item.get("affected_work_nodes", [])
                if str(node).strip()
            ],
            "requirement_ids": [str(value) for value in item.get("requirement_ids", [])],
        }
        for item in observations
        if str(item.get("status", "")).upper() not in {"PASS", "NOT_APPLICABLE"}
    ]
    if not failed_observations:
        failed_observations = [
            {
                "criterion_id": str(item),
                "status": "FAIL",
                "failure_category": root_failure,
                "observed_behavior": str(item),
                "affected_files": [],
                "affected_work_nodes": [],
                "requirement_ids": [],
            }
            for item in (
                list(failed_result.get("hard_failures", []))
                + list(failed_result.get("criteria_not_evaluated", []))
            )
        ]
    write_json(request_path, repair_evidence_contract.build(
        run_id=run_id,
        project_id=str(case["case_id"]),
        user_goal=str(case["user_goal"]),
        candidate_dir=candidate,
        candidate_sha256=candidate_tree_hash(candidate),
        repair_round=round_number,
        failure_category=root_failure,
        failures=failed_observations,
        repair_eligible=repair_eligible,
        blocking_reason="" if repair_eligible else "non_repairable_failure_classification",
        constraints={
            "maximum_total_rounds": 2, "manual_candidate_edits_forbidden": True,
            "use_existing_cgkn_recovery": True, "provider_scope": "affected_jobs_only",
            "tests_may_not_be_deleted_or_weakened": True, "benchmark_inputs_may_not_be_hardcoded": True,
        },
    ))
    if not repair_eligible:
        receipt = {
            "attempted": False,
            "triggered_by_independent_failure": True,
            "repair_round": round_number,
            "recovery_status": "BLOCKED",
            "blocking_reason": "non_repairable_failure_classification",
            "affected_jobs": [],
            "provider_recalled_jobs": [],
            "invalidated_evidence": [],
            "reemitted_evidence": [],
        }
        write_json(receipt_path, receipt)
        return receipt
    repaired_candidate, raw_error, metrics, production_result = invoke_production(
        case,
        run_dir=run_dir,
        case_dir=case_dir,
        args=args,
        observed_failure_path=request_path,
        execution_label=f"repair_{round_number}",
    )
    preparation = production_result.get("observed_failure_repair", {})
    affected_components = [str(item) for item in preparation.get("affected_components", [])]
    provider_job_ids = [str(item) for item in preparation.get("provider_job_ids", [])]
    affected_files = [str(item) for item in preparation.get("affected_files", [])]
    workflow_state = str(
        production_result.get("workflow_state", production_result.get("status", ""))
    ).upper()
    receipt = {
        "attempted": True,
        "triggered_by_independent_failure": True,
        "repair_round": round_number,
        "recovery_status": (
            "BLOCKED" if str(preparation.get("status", "")).lower() == "blocked"
            else "WAITING_SURROGATE_RESPONSE" if workflow_state == "WAITING_SURROGATE_RESPONSE"
            else "PENDING_REEVALUATION"
        ),
        "workflow_state": workflow_state,
        "affected_jobs": provider_job_ids or affected_components,
        "provider_recalled_jobs": provider_job_ids or affected_components,
        "affected_work_nodes": preparation.get("affected_work_nodes", []),
        "affected_files": affected_files,
        "invalidated_evidence": affected_files,
        "reemitted_evidence": [],
        "candidate_sha256_before_repair": read_json(request_path)["candidate_sha256"],
        "candidate_sha256_after_repair": candidate_tree_hash(repaired_candidate),
        "production_metrics": metrics,
        "production_error": raw_error[-2000:],
        "official_route": "scripts.run_codex_conversation_generation --repair-evidence",
        "external_repair_command_used": False,
        "preparation": preparation,
    }
    write_json(receipt_path, receipt)
    return receipt


def blocked_case_result(case: dict[str, Any], blocker: str, *, dry_run: bool = False) -> dict[str, Any]:
    blocker_lower = str(blocker or "").lower()
    provider_failure_kind = (
        "RATE_LIMIT" if "429" in blocker_lower or "rate limit" in blocker_lower else
        "AUTH" if "401" in blocker_lower or "403" in blocker_lower or "auth" in blocker_lower else
        "QUOTA" if "quota" in blocker_lower else
        "PROVIDER_5XX" if any(str(code) in blocker_lower for code in range(500, 600)) else
        "TIMEOUT" if "timeout" in blocker_lower or "timed out" in blocker_lower else
        "TRANSPORT"
    )
    return {
        "kind": "ProjectGenerationBenchmarkCaseResult", "schema_version": SCHEMA_VERSION,
        "evaluated_at": utc_now(), "case_id": case["case_id"], "level": case["level"],
        "user_goal": case["user_goal"],
        "result": "BLOCKED_PROVIDER", "score": None, "score_breakdown": {}, "hard_failures": [],
        "runtime_status": "NOT_EVALUATED", "delivery_status": "NOT_EVALUATED", "candidate_sha256": "",
        "provider_blocker": blocker[-4000:], "provider_failure_kind": provider_failure_kind,
        "accepted_observation_count": 0, "rejected_observations": [],
        "metrics": {"provider_api_calls": 0, "codex_invocations": 0, "elapsed_seconds": 0.0},
        "repair": {"attempted": False}, "dry_run": dry_run, "production_verdict_used": False,
        "first_result": "BLOCKED_PROVIDER", "repair_rounds": 0, "repairs": [],
        "persistence_status": "NOT_EVALUATED", "integration_status": "NOT_EVALUATED",
        "goal_fidelity_status": "NOT_EVALUATED", "false_pass": False, "false_negative": False,
        "root_failure": "PROVIDER_FAILURE",
    }


def budget_exhausted_case_result(case: dict[str, Any], detail: str) -> dict[str, Any]:
    result = blocked_case_result(case, detail)
    result.update({
        "result": "BUDGET_EXHAUSTED",
        "first_result": "BUDGET_EXHAUSTED",
        "workflow_state": "BUDGET_EXHAUSTED",
        "root_failure": "PROVIDER_FAILURE",
        "budget_exhausted": True,
    })
    return result


def run_case(case: dict[str, Any], *, run_id: str, run_dir: pathlib.Path, args: argparse.Namespace, preflight_blocker: str = "") -> dict[str, Any]:
    case_dir = run_dir / "cases" / str(case["case_id"])
    result_path = case_dir / "case_result.json"
    progress_path = case_dir / "repair_progress.json"
    progress = read_json(progress_path) if progress_path.is_file() else {}
    if args.resume and result_path.is_file():
        prior = read_json(result_path)
        if (
            str(prior.get("workflow_state", "")).upper()
            not in {"WAITING_SURROGATE_RESPONSE", "WAITING_REQUIREMENT_REPLAN"}
            and str(progress.get("status", "")) != "repair_waiting"
        ):
            prior["resumed_without_overwrite"] = True
            return prior
        snapshots = case_dir / "result_snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result_path, snapshots / f"before_resume_{int(time.time())}.json")
    case_dir.mkdir(parents=True, exist_ok=args.resume)
    if preflight_blocker:
        result = blocked_case_result(case, preflight_blocker)
        write_json(result_path, result)
        return result
    if args.dry_run:
        candidate = create_fake_candidate(case, case_dir, _public_context(case))
        observations = run_dry_case_probes(case, run_id, candidate, case_dir)
        metrics = {"provider_api_calls": 0, "codex_invocations": 0, "total_tokens": 0, "actual_cost": None, "elapsed_seconds": 0.0}
        result = evaluate_case(case, run_id=run_id, candidate_dir=candidate, observations=observations, metrics=metrics, dry_run=True)
        result.update({"first_result": result["result"], "repair_rounds": 0, "repairs": [], "workflow_state": "HARNESS_DRY_RUN"})
    else:
        active_repair_round = int(progress.get("current_round", 0) or 0)
        candidate, provider_error, metrics, production_result = invoke_production(
            case,
            run_dir=run_dir,
            case_dir=case_dir,
            args=args,
            execution_label=(
                f"repair_{active_repair_round}"
                if active_repair_round
                else "initial"
            ),
        )
        production_claim = str(production_result.get("status", "NOT_EVALUATED")).upper()
        workflow_state = str(production_result.get("workflow_state", production_claim)).upper()
        if workflow_state in {"WAITING_SURROGATE_RESPONSE", "WAITING_REQUIREMENT_REPLAN"}:
            result = {
                "kind": "ProjectGenerationBenchmarkCaseResult", "schema_version": SCHEMA_VERSION,
                "evaluated_at": utc_now(), "case_id": case["case_id"], "level": case["level"],
                "user_goal": case["user_goal"], "result": "NOT_EVALUATED", "first_result": "NOT_EVALUATED",
                "score": None, "score_breakdown": {}, "hard_failures": [],
                "criteria_not_evaluated": [workflow_state.lower()], "runtime_status": "NOT_EVALUATED",
                "persistence_status": "NOT_EVALUATED", "integration_status": "NOT_EVALUATED",
                "goal_fidelity_status": "NOT_EVALUATED", "delivery_status": "NOT_EVALUATED",
                "candidate_sha256": "", "accepted_observation_count": 0, "rejected_observations": [],
                "metrics": metrics, "repair": {"attempted": False}, "repairs": [], "repair_rounds": 0,
                "dry_run": False, "production_verdict_used": False, "production_claim": production_claim,
                "workflow_state": workflow_state, "false_pass": False, "false_negative": False,
                "root_failure": None,
            }
            if active_repair_round:
                result["first_result"] = str(
                    progress.get("first_independent_acceptance", {}).get(
                        "result", "PROJECT_FAIL"
                    )
                )
                result["first_independent_acceptance"] = progress.get(
                    "first_independent_acceptance", {}
                )
                result["repairs"] = list(progress.get("repairs", []))
                result["repair_rounds"] = active_repair_round
                result["repair"] = (
                    result["repairs"][-1]
                    if result["repairs"]
                    else {"attempted": True, "repair_round": active_repair_round}
                )
            write_json(result_path, result)
            return result
        if not candidate.is_dir() and "PROVIDER_BUDGET_EXHAUSTED" in provider_error:
            result = budget_exhausted_case_result(case, provider_error)
            result["metrics"] = metrics
            result["production_claim"] = production_claim
            result["workflow_state"] = "BUDGET_EXHAUSTED"
        elif not candidate.is_dir() and classify_provider_blocker(provider_error):
            result = blocked_case_result(case, provider_error)
            result["metrics"] = metrics
            result["production_claim"] = production_claim
            result["workflow_state"] = workflow_state
        else:
            evaluation_phase = (
                f"repair_{active_repair_round}"
                if active_repair_round
                else "initial"
            )
            observations = run_external_evaluator(
                case, run_id, candidate, case_dir, args, phase=evaluation_phase
            )
            if candidate.is_dir():
                observations.append(inspect_delivery(candidate, case_dir, case_id=str(case["case_id"]), run_id=run_id))
            repairs = list(progress.get("repairs", [])) if active_repair_round else []
            evaluation_repair = repairs[-1] if repairs else None
            if evaluation_repair is not None:
                evaluation_repair = dict(evaluation_repair)
                evaluation_repair["recovery_status"] = "PASS"
                evaluation_repair["reemitted_evidence"] = list(
                    evaluation_repair.get("invalidated_evidence", [])
                )
            current = evaluate_case(
                case, run_id=run_id, candidate_dir=candidate, observations=observations, metrics=metrics,
                provider_error=provider_error, repair=evaluation_repair,
                require_repair=False, production_claim=production_claim,
            )
            if evaluation_repair is not None and current["result"] != "PROJECT_PASS":
                evaluation_repair["recovery_status"] = "FAIL"
                current = evaluate_case(
                    case, run_id=run_id, candidate_dir=candidate,
                    observations=observations, metrics=metrics,
                    provider_error=provider_error, repair=evaluation_repair,
                    require_repair=False, production_claim=production_claim,
                )
            if active_repair_round:
                repairs[-1] = evaluation_repair or repairs[-1]
                initial_acceptance = dict(progress.get("first_independent_acceptance", {}))
            else:
                initial_acceptance = {
                    "result": current["result"],
                    "root_failure": current.get("root_failure"),
                    "hard_failures": current.get("hard_failures", []),
                    "criteria_not_evaluated": current.get("criteria_not_evaluated", []),
                    "candidate_sha256": current.get("candidate_sha256", ""),
                }
            result = dict(current)
            while result["result"] == "PROJECT_FAIL" and len(repairs) < 2:
                round_number = len(repairs) + 1
                repair = run_controlled_repair(
                    case,
                    candidate,
                    case_dir,
                    args,
                    run_id=run_id,
                    run_dir=run_dir,
                    round_number=round_number,
                    failed_result=result,
                    observations=observations,
                )
                if repair is None:
                    break
                repairs.append(repair)
                if repair.get("recovery_status") == "BLOCKED":
                    result["workflow_state"] = "REWORK_BLOCKED"
                    break
                if repair.get("recovery_status") == "WAITING_SURROGATE_RESPONSE":
                    write_json(
                        progress_path,
                        {
                            "status": "repair_waiting",
                            "current_round": round_number,
                            "first_independent_acceptance": initial_acceptance,
                            "repairs": repairs,
                        },
                    )
                    result.update(
                        {
                            "result": "NOT_EVALUATED",
                            "workflow_state": "WAITING_SURROGATE_RESPONSE",
                            "first_result": initial_acceptance.get("result", "PROJECT_FAIL"),
                            "first_independent_acceptance": initial_acceptance,
                            "repairs": repairs,
                            "repair_rounds": len(repairs),
                            "repair": repairs[-1],
                        }
                    )
                    write_json(result_path, result)
                    return result
                observations = run_external_evaluator(
                    case,
                    run_id,
                    candidate,
                    case_dir,
                    args,
                    phase=f"repair_{round_number}",
                )
                if candidate.is_dir():
                    observations.append(
                        inspect_delivery(
                            candidate,
                            case_dir,
                            case_id=str(case["case_id"]),
                            run_id=run_id,
                        )
                    )
                repair["recovery_status"] = "PASS"
                repair["reemitted_evidence"] = list(
                    repair.get("invalidated_evidence", [])
                )
                result = evaluate_case(
                    case, run_id=run_id, candidate_dir=candidate,
                    observations=observations, metrics=metrics,
                    provider_error=provider_error, repair=repair,
                    require_repair=False, production_claim=production_claim,
                )
                if result["result"] != "PROJECT_PASS":
                    repair["recovery_status"] = "FAIL"
                    result = evaluate_case(
                        case, run_id=run_id, candidate_dir=candidate,
                        observations=observations, metrics=metrics,
                        provider_error=provider_error, repair=repair,
                        require_repair=False, production_claim=production_claim,
                    )
            result["first_result"] = initial_acceptance.get("result", result["result"])
            result["first_root_failure"] = initial_acceptance.get("root_failure", current.get("root_failure"))
            result["first_independent_acceptance"] = initial_acceptance
            result["repairs"] = repairs
            result["repair_rounds"] = len(repairs)
            result["repair"] = repairs[-1] if repairs else {"attempted": False, "initial_happy_path_pass": initial_acceptance.get("result") == "PROJECT_PASS"}
            result["workflow_state"] = (
                "FINAL_FAIL"
                if result["result"] == "PROJECT_FAIL" and len(repairs) >= 2
                else result.get("workflow_state", workflow_state)
            )
            result["false_pass"] = bool(result.get("false_pass"))
            result["false_negative"] = bool(result.get("false_negative"))
            write_json(
                progress_path,
                {
                    "status": "complete",
                    "current_round": len(repairs),
                    "first_independent_acceptance": initial_acceptance,
                    "repairs": repairs,
                    "final_result": result["result"],
                },
            )
    write_json(result_path, result)
    return result


def run_revision(
    case: dict[str, Any], result: dict[str, Any], *, run_id: str, run_dir: pathlib.Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    revision = case.get("revision") if isinstance(case.get("revision"), dict) else None
    if not revision:
        return {}
    case_dir = run_dir / "cases" / str(case["case_id"])
    candidate = case_dir / "candidate"
    base = {
        "case_id": case["case_id"], "revision_id": revision["revision_id"],
        "change_type": revision["change_type"], "status": "NOT_EVALUATED",
        "revision_inefficiency": False,
    }
    if result.get("result") != "PROJECT_PASS":
        return {**base, "reason": "base_project_not_independently_accepted"}
    if not args.revision_command:
        return {**base, "reason": "revision_command_not_configured"}
    revision_dir = case_dir / "revision"
    request_path = revision_dir / "revision_request.json"
    receipt_path = revision_dir / "revision_receipt.json"
    before_hash = candidate_tree_hash(candidate)
    write_json(request_path, {
        "kind": "ProjectBenchmarkRevisionRequest", "schema_version": SCHEMA_VERSION,
        "benchmark_run_id": run_id, "candidate_dir": str(candidate.resolve()),
        "candidate_sha256_before": before_hash,
        "user_request": revision["user_request"],
        "constraints": {
            "use_existing_cgkn_revision_route": True, "preserve_unaffected_pass_work": True,
            "manual_candidate_edits_forbidden": True, "full_rebuild_requires_justification": True,
        },
        "output_path": str(receipt_path.resolve()),
    })
    started = time.perf_counter()
    completed = _run_external_command(
        args.revision_command, ["--input", str(request_path)], cwd=ROOT, timeout=args.revision_timeout,
    )
    elapsed = round(time.perf_counter() - started, 3)
    write_json(revision_dir / "revision_execution_receipt.json", {
        "return_code": completed.returncode, "elapsed_seconds": elapsed,
        "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:],
    })
    if completed.returncode != 0 or not receipt_path.is_file():
        return {**base, "status": "FAIL", "reason": "revision_route_failed", "wall_time": elapsed}
    receipt = read_json(receipt_path)
    after_hash = candidate_tree_hash(candidate)
    observations = run_external_evaluator(
        case, run_id, candidate, case_dir, args, phase="revision", revision=revision,
    )
    observations.append(inspect_delivery(candidate, case_dir, case_id=str(case["case_id"]), run_id=run_id))
    regression = evaluate_case(
        case, run_id=run_id, candidate_dir=candidate, observations=observations,
        metrics=collect_invocation_metrics(revision_dir), production_claim="NOT_EVALUATED",
    )
    by_id = {str(item.get("criterion_id")): item for item in observations}
    required = ("revision.new_behavior", "revision.unchanged_behavior", "revision.data_preserved")
    revision_acceptance = all(by_id.get(item, {}).get("status") == "PASS" for item in required)
    changed_files = [str(item) for item in receipt.get("files_changed", [])]
    inefficiency = bool(receipt.get("full_rebuild")) or bool(receipt.get("revision_inefficiency"))
    status = "PASS" if after_hash and after_hash != before_hash and regression["result"] == "PROJECT_PASS" and revision_acceptance else "FAIL"
    return {
        **base, "status": status, "candidate_sha256_before": before_hash,
        "candidate_sha256_after": after_hash, "files_changed": changed_files,
        "work_nodes_affected": receipt.get("work_nodes_affected", []),
        "provider_calls": receipt.get("provider_calls", 0),
        "reused_pass_work": receipt.get("reused_pass_work", []),
        "repair_scope": receipt.get("repair_scope", []),
        "revision_inefficiency": inefficiency, "wall_time": elapsed,
        "new_behavior_status": by_id.get("revision.new_behavior", {}).get("status", "NOT_EVALUATED"),
        "unchanged_behavior_status": by_id.get("revision.unchanged_behavior", {}).get("status", "NOT_EVALUATED"),
        "data_preservation_status": by_id.get("revision.data_preserved", {}).get("status", "NOT_EVALUATED"),
        "regression_result": regression["result"],
    }


def write_quality_artifacts(
    run_dir: pathlib.Path, manifest: dict[str, Any], cases: list[dict[str, Any]],
    results: list[dict[str, Any]], revisions: list[dict[str, Any]], report: dict[str, Any],
    args: argparse.Namespace, baseline: dict[str, Any] | None,
) -> None:
    frozen_cases = {
        "kind": "CGKNProjectGenerationFrozenCases", "schema_version": SCHEMA_VERSION,
        "run_id": manifest["run_id"],
        "fixed10_manifest_path": str(CASES_PATH.resolve()),
        "fixed10_manifest_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest().upper(),
        "catalog_sha256": hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "cases": [{**case, "user_goal_sha256": hashlib.sha256(str(case["user_goal"]).encode()).hexdigest()} for case in cases],
    }
    baseline_doc = {
        "kind": "CGKNProjectGenerationBaseline", "schema_version": SCHEMA_VERSION,
        "run_id": manifest["run_id"], "created_at": manifest["created_at"],
        "version_binding": manifest["version_binding"], "projects_total": len(cases),
        "generation_route": "scripts.run_codex_conversation_generation -> scripts.codex_conversation.start_generation_from_income",
        "provider_mode": args.provider_mode,
        "real_model": "NOT_EVALUATED" if args.provider_mode != "live" else "EVALUATED",
        "formal_evidence_status": "NOT_EVALUATED",
        "pass6_evidence_changed": False,
    }
    failures = [{
        "case_id": item["case_id"], "root_failure": item.get("root_failure"),
        "hard_failures": item.get("hard_failures", []),
        "criteria_not_evaluated": item.get("criteria_not_evaluated", []),
        "final_state": item.get("result"),
    } for item in results if item.get("result") != "PROJECT_PASS"]
    repairs = [{"case_id": item["case_id"], "rounds": item.get("repairs", [])} for item in results if item.get("repairs")]
    metrics = dict(report["summary"])
    metrics["revision_pass"] = sum(item.get("status") == "PASS" for item in revisions)
    metrics["revision_total"] = len(revisions)
    for name, payload in (
        ("PROJECT_GENERATION_BASELINE.json", baseline_doc),
        ("PROJECT_GENERATION_CASES.json", frozen_cases),
        ("PROJECT_GENERATION_RESULTS.json", {"run_id": manifest["run_id"], "results": results}),
        ("PROJECT_GENERATION_FAILURES.json", {"run_id": manifest["run_id"], "failures": failures}),
        ("PROJECT_GENERATION_REPAIRS.json", {"run_id": manifest["run_id"], "repairs": repairs, "maximum_rounds_per_project": 2}),
        ("PROJECT_REVISION_RESULTS.json", {"run_id": manifest["run_id"], "revisions": revisions}),
        ("PROJECT_GENERATION_METRICS.json", metrics),
    ):
        write_json(run_dir / name, payload)
    if args.provider_mode == "live":
        ledger_path = run_dir / "external_api_cost_ledger.json"
        ledger = read_json(ledger_path) if ledger_path.is_file() else {
            "kind": "CGKNExternalProviderCostLedger", "execution_mode": "external_api",
            "totals": {"api_calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0},
            "calls": [],
        }
        calls = [item for item in ledger.get("calls", []) if isinstance(item, dict)]
        purpose = lambda item: str(item.get("purpose", "")).lower()
        write_json(run_dir / "EXTERNAL_API_PROVIDER_CONFIG_AUDIT.json", external_api_config_audit(args))
        write_json(run_dir / "FIXED10_EXTERNAL_API_RESULTS.json", {"run_id": manifest["run_id"], "results": results})
        write_json(run_dir / "FIXED10_EXTERNAL_API_REPAIRS.json", {"run_id": manifest["run_id"], "repairs": repairs, "maximum_rounds_per_project": 2})
        write_json(run_dir / "FIXED10_EXTERNAL_API_METRICS.json", metrics)
        write_json(run_dir / "FIXED10_EXTERNAL_API_COST.json", {
            "kind": "CGKNExternalProviderCostSummary", "run_id": manifest["run_id"],
            "call_mode": "LIVE_CALL", "totals": ledger.get("totals", {}),
            "generation_calls": sum("repair" not in purpose(item) for item in calls),
            "repair_calls": sum("repair" in purpose(item) for item in calls),
            "evaluation_calls": 0, "calls": calls, "limits": ledger.get("limits", {}),
        })
        write_json(run_dir / "FIXED10_EXTERNAL_API_FAILURES.json", {"run_id": manifest["run_id"], "failures": failures})
        write_json(run_dir / "REVISION_EXTERNAL_API_RESULTS.json", {"run_id": manifest["run_id"], "revisions": revisions})
        write_json(run_dir / "CODEX_USAGE_REDUCTION.json", {
            "run_id": manifest["run_id"], "codex_generation_calls": 0, "codex_repair_calls": 0,
            "external_api_calls": int(ledger.get("totals", {}).get("api_calls", 0) or 0),
            "target_codex_generation_and_repair_calls": 0,
            "status": "PASS" if int(metrics.get("codex_invocations", 0) or 0) == 0 else "FAIL",
        })
    for name, payload in (
        ("PROJECT_GENERATION_RESULTS_AFTER.json", {"run_id": manifest["run_id"], "results": results}),
        ("PROJECT_GENERATION_REPAIRS_AFTER.json", {"run_id": manifest["run_id"], "repairs": repairs, "maximum_rounds_per_project": 2}),
        ("PROJECT_REVISION_RESULTS_AFTER.json", {"run_id": manifest["run_id"], "revisions": revisions}),
        ("PROJECT_GENERATION_METRICS_AFTER.json", metrics),
    ):
        write_json(run_dir / name, payload)
    runtime_rows = []
    dependency_rows = []
    for item in results:
        case_dir = run_dir / "cases" / str(item["case_id"])
        receipts = sorted(case_dir.glob("evaluations/*/clean_runtime_receipt.json"))
        receipt = read_json(receipts[-1]) if receipts else {}
        runtime_rows.append({
            "case_id": item["case_id"], "status": item.get("runtime_status", "NOT_EVALUATED"),
            "clean_runtime_receipt": str(receipts[-1]) if receipts else "",
            "documented_entrypoint": receipt.get("runtime", {}).get("documented_entrypoint", ""),
            "pid": receipt.get("runtime", {}).get("pid"), "port": receipt.get("runtime", {}).get("port"),
            "shutdown": receipt.get("runtime", {}).get("shutdown", "NOT_EVALUATED"),
            "restart": receipt.get("runtime", {}).get("restart", {}).get("status", "NOT_EVALUATED"),
        })
        dependency_rows.append({
            "case_id": item["case_id"], "status": item.get("dependency_status", "NOT_EVALUATED"),
            "fresh_virtualenv": receipt.get("clean_environment", {}).get("fresh_virtualenv", False),
            "system_site_packages": receipt.get("clean_environment", {}).get("system_site_packages"),
            "network_attempts": receipt.get("clean_environment", {}).get("network_attempts"),
            "declared_dependencies": receipt.get("clean_environment", {}).get("declared_dependencies", []),
            "install": receipt.get("clean_environment", {}).get("dependency_install", {}),
        })
    write_json(run_dir / "RUNTIME_BOOTSTRAP_AUDIT.json", {"kind": "CGKNFixed10RuntimeBootstrapAudit", "run_id": manifest["run_id"], "cases": runtime_rows})
    write_json(run_dir / "DEPENDENCY_AUDIT.json", {"kind": "CGKNFixed10DependencyAudit", "run_id": manifest["run_id"], "cases": dependency_rows})
    comparison = report.get("comparison") or {"baseline_run_id": None, "deltas": {}}
    (run_dir / "PROJECT_GENERATION_BEFORE_AFTER.md").write_text(
        "# Project Generation Before / After\n\n"
        f"- Current run: `{manifest['run_id']}`\n"
        f"- Compared run: `{comparison.get('baseline_run_id')}`\n"
        f"- First pass: `{metrics.get('first_pass_count')}/{metrics.get('projects_total')}`\n"
        f"- Final after repair: `{metrics.get('final_pass_count')}/{metrics.get('projects_total')}`\n"
        f"- False pass: `{metrics.get('false_pass')}`\n"
        f"- Deltas: `{json.dumps(comparison.get('deltas', {}), sort_keys=True)}`\n\n"
        "This report evaluates project-generation quality only and does not grant commercial readiness or formal CGKN evidence.\n",
        encoding="utf-8",
    )
    (run_dir / "PROJECT_GENERATION_FIXED10_COMPARISON.md").write_text(
        "# Fixed10 Project Generation Comparison\n\n"
        "## Before\n\n"
        "- First pass: `0/10`\n- Final pass: `0/10`\n- Repair actually executed: `0`\n"
        "- RUNTIME: `5`\n- DEPENDENCY: `1`\n- CODE_GENERATION: `4`\n\n"
        "## After\n\n"
        f"- First pass: `{metrics.get('first_pass_count')}/{metrics.get('projects_total')}`\n"
        f"- Final pass: `{metrics.get('final_pass_count')}/{metrics.get('projects_total')}`\n"
        f"- Repair round 1 attempted / successful: `{metrics.get('repair_round1_attempted')}` / `{metrics.get('repair_round1_success')}`\n"
        f"- Repair round 2 attempted / successful: `{metrics.get('repair_round2_attempted')}` / `{metrics.get('repair_round2_success')}`\n"
        f"- FINAL_FAIL: `{metrics.get('final_fail_count')}`; REWORK_BLOCKED: `{metrics.get('rework_blocked_count')}`\n"
        f"- Failure taxonomy: `{json.dumps(metrics.get('failure_taxonomy', {}), sort_keys=True)}`\n\n"
        "The manifest and hidden acceptance are unchanged; remaining failures are not omitted.\n",
        encoding="utf-8",
    )
    limits = [
        "Formal CGKN evidence remains under its original authority and is NOT_EVALUATED by this benchmark.",
        "Existing Pass 6 24-hour evidence was not changed or reinterpreted.",
    ]
    if not args.evaluator_command:
        limits.append("No external evaluator command was configured, so real functional acceptance remains NOT_EVALUATED.")
    limits.append("Ordinary independent failures use the identity-bound existing ProviderJob repair route, with a hard limit of two rounds.")
    if not args.revision_command:
        limits.append("No revision adapter was configured; four revision cases remain NOT_EVALUATED.")
    if args.provider_mode != "live":
        limits.append("Paid real-model evaluation was not authorized and remains NOT_EVALUATED; surrogate results are separate.")
    (run_dir / "KNOWN_LIMITS_PROJECT_GENERATION.md").write_text(
        "# Known Limits — Project Generation\n\n" + "\n".join(f"- {item}" for item in limits) + "\n",
        encoding="utf-8",
    )
    reproduce = [
        "# Reproduce Project Generation Quality Pass", "",
        "Harness preflight:", "", "```powershell",
        "python benchmarks/project_generation_v1/run_benchmark.py --dry-run", "```", "",
        "Provider-free reviewed-route run (resume each identity-bound surrogate wait through the CGKN plugin):", "", "```powershell",
        f"python benchmarks/project_generation_v1/run_benchmark.py --all --provider-mode codex_surrogate --run-id {manifest['run_id']}",
        "```", "",
        "Do not use `--provider-mode live` without explicit Provider budget authorization.", "",
    ]
    (run_dir / "REPRODUCE_PROJECT_GENERATION.md").write_text("\n".join(reproduce), encoding="utf-8")
    (run_dir / "REPRODUCE_PROJECT_GENERATION_REPAIR.md").write_text(
        "# Reproduce Fixed10 generation and repair\n\n```powershell\n"
        f"python benchmarks/project_generation_v1/run_benchmark.py --all --provider-mode codex_surrogate --run-id {manifest['run_id']} --resume\n"
        "```\n\nSubmit only scheduler-created requests through the CGKN surrogate-response tool. "
        "Ordinary failures re-enter the same identity-bound ProviderJob run and stop after two repair rounds.\n",
        encoding="utf-8",
    )
    from benchmarks.project_generation_v1.audit_failure_to_repair import fixed10_failure_audit
    failure_audit, root_audit, repair_audit = fixed10_failure_audit(run_dir)
    write_json(run_dir / "FIXED10_FAILURE_AUDIT.json", failure_audit)
    write_json(run_dir / "FIXED10_ROOT_CAUSE_CLUSTERS.json", root_audit)
    write_json(run_dir / "REPAIR_ROUTING_AUDIT.json", repair_audit)


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
            "scripts/run_codex_conversation_generation.py reviewed Codex conversation facade",
            "scripts.codex_conversation.start_generation_from_income",
            "existing ProviderJob leaf executor",
            "Provider output validation",
            "post-build finalization",
            "local_packager",
            "public_delivery_gate",
            "independent black-box evaluator",
            "observed failure and existing affected-only CGKN recovery (maximum two rounds)",
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
        f"- First pass: `{summary['first_pass_count']}/{summary['projects_total']}` (`{summary['first_pass_rate']}`)",
        f"- Final after repair: `{summary['final_pass_count']}/{summary['projects_total']}` (`{summary['final_pass_rate']}`)",
        f"- Repair Recovery Rate: `{summary['repair_success_rate']}`",
        f"- False pass / false negative: `{summary['false_pass']}` / `{summary['false_negative']}`",
        f"- Requirement Coverage: `{summary['requirement_coverage']}`",
        f"- Median Provider Calls: `{summary['median_provider_calls']}`",
        f"- Median Provider Wall Time: `{summary['median_provider_wall_time']}`",
        f"- Median Codex Calls: `{summary['median_codex_calls']}`",
        f"- Overall Score: `{summary['overall_score']}`", "", "## Cases", "",
        "| Case | Level | First Pass | Repair Rounds | Final | Runtime | Persistence | Integration | Revision | Time | Calls | Root Failure |",
        "|---|---:|---|---:|---|---|---|---|---|---:|---:|---|",
    ]
    revisions = {item.get("case_id"): item for item in report.get("revision_results", [])}
    for result in report["case_results"]:
        revision = revisions.get(result["case_id"], {})
        metrics = result.get("metrics", {})
        lines.append(
            f"| {result['case_id']} | {result['level']} | {result.get('first_result')} | {result.get('repair_rounds', 0)} | "
            f"{result['result']} | {result.get('runtime_status')} | {result.get('persistence_status')} | "
            f"{result.get('integration_status')} | {revision.get('status', 'N/A')} | {metrics.get('elapsed_seconds')} | "
            f"{metrics.get('provider_api_calls')} | {result.get('root_failure') or ''} |"
        )
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


def persist_benchmark_report(run_dir: pathlib.Path, report: dict[str, Any]) -> None:
    report_json = run_dir / "benchmark_report.json"
    report_md = run_dir / "benchmark_report.md"
    if report_json.exists():
        snapshot = run_dir / "reports" / datetime.now(timezone.utc).strftime("benchmark_report_%Y%m%dT%H%M%S%fZ.json")
        write_json(snapshot, report)
        snapshot.with_suffix(".md").write_text(report_markdown(report), encoding="utf-8")
    write_json(report_json, report)
    report_md.write_text(report_markdown(report), encoding="utf-8")


def execute(args: argparse.Namespace) -> tuple[pathlib.Path, dict[str, Any]]:
    if args.repair_command:
        raise ValueError("--repair-command is forbidden: ordinary failures must use the existing identity-bound ProviderJob repair route")
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
    fixed10_sha = hashlib.sha256(CASES_PATH.read_bytes()).hexdigest().upper()
    if args.all and fixed10_sha != FIXED10_SHA256:
        raise RuntimeError(f"frozen Fixed10 manifest changed: expected {FIXED10_SHA256}, got {fixed10_sha}")
    if run_dir.exists() and not (args.resume or args.report_only):
        raise FileExistsError(f"benchmark run already exists; use --resume or a new --run-id: {run_dir}")
    if args.external_api_audit_only:
        if args.provider_mode != "live":
            raise ValueError("--external-api-audit-only requires --provider-mode live")
        if args.report_only or args.resume:
            raise ValueError("external API readiness audit must use a new run id")
        audit = external_api_config_audit(args)
        report = write_external_api_readiness_package(run_dir, run_id, selected, args, binding, audit)
        return run_dir, report
    if args.provider_mode == "live" and not args.report_only:
        audit = external_api_config_audit(args)
        if audit["status"] != "READY":
            report = write_external_api_readiness_package(run_dir, run_id, selected, args, binding, audit)
            return run_dir, report
    if args.report_only:
        if not manifest_path.is_file():
            raise FileNotFoundError(f"run manifest missing: {manifest_path}")
        manifest = read_json(manifest_path)
        results = []
        for case in selected:
            case_dir = run_dir / "cases" / str(case["case_id"])
            result = read_json(case_dir / "case_result.json")
            execution_receipt_path = case_dir / "production_execution_receipt.json"
            if execution_receipt_path.is_file():
                execution_receipt = read_json(execution_receipt_path)
                relative_result = pathlib.Path(str(execution_receipt.get("result_path", "")))
                production_slot = (run_dir / relative_result).parent
                refreshed_metrics = collect_invocation_metrics(production_slot)
                refreshed_metrics["elapsed_seconds"] = float(execution_receipt.get("elapsed_seconds", 0.0) or 0.0)
                refreshed_metrics["production_return_code"] = int(execution_receipt.get("return_code", 0) or 0)
                result = dict(result)
                result["metrics"] = refreshed_metrics
                result["metrics_refreshed_for_report"] = True
            results.append(result)
    else:
        run_dir.mkdir(parents=True, exist_ok=args.resume)
        if args.provider_mode == "live":
            provider_api_budget.reconcile_incomplete_calls(
                run_dir / "external_api_cost_ledger.json"
            )
        if manifest_path.is_file():
            manifest = read_json(manifest_path)
            original_binding = manifest.get("version_binding", {})
            if original_binding.get("repo_sha") != binding["repo_sha"]:
                raise RuntimeError("resume repo SHA does not match the original benchmark run")
            if original_binding.get("source_identity_sha256") != binding["source_identity_sha256"]:
                raise RuntimeError("resume source identity does not match the original benchmark run; use a new run id")
            if original_binding.get("config_sha256") != binding["config_sha256"]:
                raise RuntimeError("resume Provider/model configuration does not match the original benchmark run")
            if manifest.get("case_catalog_sha256") != hashlib.sha256(CASES_PATH.read_bytes()).hexdigest():
                raise RuntimeError("resume case catalog does not match the frozen benchmark run")
        else:
            manifest = {
                "kind": "CGKNProjectGenerationBenchmarkRunManifest", "schema_version": SCHEMA_VERSION,
                "benchmark_id": BENCHMARK_ID, "run_id": run_id, "created_at": utc_now(),
                "mode": "HARNESS_DRY_RUN" if args.dry_run else "LIVE", "version_binding": binding,
                "selected_case_ids": [case["case_id"] for case in selected],
                "hidden_acceptance_forwarded_to_production": False,
                "provider_mode": args.provider_mode,
                "execution_mode": "external_api" if args.provider_mode == "live" else args.provider_mode,
                "generation_model": args.model,
                "repair_model": args.repair_model or args.model,
                "repair_model_escalation_configured": bool(args.repair_model),
                "dependency_policy": {
                    "mode": args.dependency_mode,
                    "wheelhouse": str(args.wheelhouse.resolve()) if args.wheelhouse else "",
                    "registry_approved": bool(args.approve_package_registry),
                    "registry_url": args.package_registry_url,
                },
                "api_budget": {
                    "max_api_calls": args.max_api_calls,
                    "max_planning_calls": args.max_planning_calls,
                    "max_generation_calls": args.max_generation_calls,
                    "max_repair_calls": args.max_repair_calls,
                    "max_total_input_tokens": args.max_total_input_tokens,
                    "max_total_output_tokens": args.max_total_output_tokens,
                    "max_estimated_cost": args.max_estimated_cost,
                } if args.provider_mode == "live" else {},
                "case_catalog_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
            }
            write_json(manifest_path, manifest)
        blocker = provider_readiness_blocker(args.readiness_file) if not args.dry_run else ""
        results = [run_case(case, run_id=run_id, run_dir=run_dir, args=args, preflight_blocker=blocker) for case in selected]
    revision_results: list[dict[str, Any]] = []
    revision_results_path = run_dir / "PROJECT_REVISION_RESULTS.json"
    if args.report_only and revision_results_path.is_file():
        revision_results = list(read_json(revision_results_path).get("revisions", []))
    elif manifest["mode"] == "LIVE":
        result_by_case = {item["case_id"]: item for item in results}
        revision_results = [
            run_revision(case, result_by_case[case["case_id"]], run_id=run_id, run_dir=run_dir, args=args)
            for case in selected if isinstance(case.get("revision"), dict)
        ]
    baseline = read_json(args.compare_baseline) if args.compare_baseline else None
    report = build_report(run_id, manifest, selected, results, ROOT, baseline)
    report["revision_results"] = revision_results
    report["summary"]["revision_pass"] = sum(item.get("status") == "PASS" for item in revision_results)
    report["summary"]["revision_total"] = len(revision_results)
    valid_live = manifest["mode"] == "LIVE" and all(result["result"] in {"PROJECT_PASS", "PROJECT_FAIL"} for result in results)
    if args.baseline and valid_live:
        report["baseline_label"] = BASELINE_LABEL
    persist_benchmark_report(run_dir, report)
    write_quality_artifacts(run_dir, manifest, selected, results, revision_results, report, args, baseline)
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
    parser.add_argument("--external-api-audit-only", action="store_true", help="Write a zero-call readiness/result package; never contact the Provider")
    parser.add_argument("--provider-free-regression-result", type=pathlib.Path, help="Include an existing Provider-free regression receipt in the zero-call result package")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-root", type=pathlib.Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--provider", default="openai-compatible")
    parser.add_argument("--provider-mode", choices=["live", "codex_surrogate", "deterministic_replay"], default="codex_surrogate")
    parser.add_argument("--replay-dir", type=pathlib.Path)
    parser.add_argument("--model", default=os.environ.get("CGKN_PROJECT_GENERATION_MODEL", ""))
    parser.add_argument("--repair-model", default=os.environ.get("CGKN_PROJECT_REPAIR_MODEL", ""))
    parser.add_argument("--parallelism", type=int, default=1)
    parser.add_argument("--provider-max-retries", type=int, default=2)
    parser.add_argument("--provider-max-tokens", type=int, default=5000)
    parser.add_argument("--provider-temperature", type=float, default=0.2)
    parser.add_argument("--max-api-calls", type=int)
    parser.add_argument("--max-planning-calls", type=int)
    parser.add_argument("--max-generation-calls", type=int)
    parser.add_argument("--max-repair-calls", type=int)
    parser.add_argument("--max-total-input-tokens", type=int)
    parser.add_argument("--max-total-output-tokens", type=int)
    parser.add_argument("--max-estimated-cost", type=float)
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--output-cost-per-million", type=float)
    parser.add_argument("--dependency-mode", choices=["wheelhouse", "registry", "no_index"], default="wheelhouse")
    parser.add_argument("--wheelhouse", type=pathlib.Path)
    parser.add_argument("--approve-package-registry", action="store_true")
    parser.add_argument("--package-registry-url", default="")
    parser.add_argument("--production-script", type=pathlib.Path, default=DEFAULT_PRODUCTION_SCRIPT)
    parser.add_argument("--production-timeout", type=int, default=900)
    parser.add_argument("--readiness-file", type=pathlib.Path)
    parser.add_argument(
        "--evaluator-command",
        default=f'"{sys.executable}" "{DEFAULT_EVALUATOR_SCRIPT}"',
    )
    parser.add_argument("--evaluator-timeout", type=int, default=600)
    parser.add_argument("--repair-command", default="", help=argparse.SUPPRESS)
    parser.add_argument("--repair-timeout", type=int, default=900)
    parser.add_argument("--revision-command", default="")
    parser.add_argument("--revision-timeout", type=int, default=900)
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
