#!/usr/bin/env python3
"""Independent, black-box evaluator for CGKN Project Generation Benchmark v1.

This module deliberately does not import the CGKN runtime, its verdict helpers, or
Provider adapters.  It accepts only externally observed process/HTTP/browser/file
facts bound to the exact candidate tree being evaluated.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import statistics
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import Any, Iterable


SCHEMA_VERSION = "1.0.0"
BENCHMARK_ID = "CGKN_PROJECT_GENERATION_BENCHMARK_V1"
CATEGORY_POINTS = {
    "requirement_coverage": 20,
    "functional": 25,
    "runtime": 15,
    "persistence": 10,
    "integration": 10,
    "repair": 10,
    "delivery": 5,
    "efficiency": 5,
}
ALLOWED_EXTERNAL_PRODUCERS = {
    "benchmark_process_probe",
    "benchmark_http_probe",
    "benchmark_browser_probe",
    "benchmark_file_probe",
    "benchmark_persistence_probe",
    "benchmark_fault_probe",
}
PROVIDER_BLOCKER_PATTERNS = (
    r"\b403\b",
    r"quota",
    r"insufficient[_ ]quota",
    r"provider.*(?:unavailable|timeout|timed out)",
    r"tls|ssl|certificate",
    r"connection (?:error|refused|reset)",
    r"blocked_provider",
)
FORBIDDEN_PRODUCTION_MARKERS = (
    "CGKN_PROJECT_GENERATION_BENCHMARK_V1",
    "case_01",
    "case_03",
    "case_10_customer_feedback_manager",
    "customer_feedback_manager benchmark",
    "local project board benchmark",
    "CGKN_PROJECT_BENCHMARK_CASE_",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: pathlib.Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_case_catalog(path: pathlib.Path) -> dict[str, Any]:
    catalog = read_json(path)
    if catalog.get("kind") != "CGKNProjectGenerationBenchmarkCaseCatalog":
        raise ValueError("unexpected benchmark case catalog kind")
    if catalog.get("schema_version") != SCHEMA_VERSION or catalog.get("benchmark_id") != BENCHMARK_ID:
        raise ValueError("unsupported benchmark catalog identity")
    cases = catalog.get("cases")
    if not isinstance(cases, list) or len(cases) != 10:
        raise ValueError("benchmark v1 requires exactly ten cases")
    ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(ids) != 10 or len(set(ids)) != 10:
        raise ValueError("benchmark case ids must be unique")
    return catalog


def candidate_tree_hash(candidate_dir: pathlib.Path) -> str:
    root = candidate_dir.resolve()
    digest = hashlib.sha256()
    if not root.is_dir():
        return ""
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def make_observation(
    *,
    case_id: str,
    run_id: str,
    candidate_sha256: str,
    criterion_id: str,
    status: str,
    producer: str,
    details: str,
    requirement_ids: Iterable[str] = (),
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    if producer not in ALLOWED_EXTERNAL_PRODUCERS:
        raise ValueError(f"producer is not independent: {producer}")
    normalized = str(status).upper()
    if normalized not in {"PASS", "PARTIAL", "FAIL", "NOT_EVALUATED"}:
        raise ValueError(f"invalid observation status: {status}")
    return {
        "kind": "ProjectBenchmarkExternalObservation",
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "case_id": case_id,
        "benchmark_run_id": run_id,
        "candidate_sha256": candidate_sha256,
        "criterion_id": criterion_id,
        "status": normalized,
        "producer": producer,
        "details": details,
        "requirement_ids": sorted(set(str(item) for item in requirement_ids)),
        "elapsed_ms": max(0, int(elapsed_ms)),
    }


def classify_provider_blocker(raw_error: str) -> bool:
    text = str(raw_error or "").lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in PROVIDER_BLOCKER_PATTERNS)


def validate_observations(
    observations: Iterable[dict[str, Any]], *, case_id: str, run_id: str, candidate_sha256: str
) -> tuple[list[dict[str, Any]], list[str]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[str] = []
    for index, observation in enumerate(observations):
        reason = ""
        if observation.get("producer") not in ALLOWED_EXTERNAL_PRODUCERS:
            reason = "untrusted_producer"
        elif observation.get("case_id") != case_id:
            reason = "case_identity_mismatch"
        elif observation.get("benchmark_run_id") != run_id:
            reason = "run_identity_mismatch"
        elif not candidate_sha256 or observation.get("candidate_sha256") != candidate_sha256:
            reason = "stale_candidate_identity"
        elif str(observation.get("status", "")).upper() not in {"PASS", "PARTIAL", "FAIL", "NOT_EVALUATED"}:
            reason = "invalid_status"
        if reason:
            rejected.append(f"observation[{index}]:{reason}")
        else:
            accepted.append(dict(observation))
    return accepted, rejected


def _zip_is_safe(package: pathlib.Path) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if not names:
                return False, "package is empty"
            for name in names:
                normalized = pathlib.PurePosixPath(name.replace("\\", "/"))
                if normalized.is_absolute() or ".." in normalized.parts:
                    return False, f"unsafe package member: {name}"
            lowered = {pathlib.PurePosixPath(name).name.lower() for name in names}
            if "readme.md" not in lowered:
                return False, "package does not contain README.md"
            if not lowered.intersection({"app.py", "main.py", "index.html", "package.json", "pyproject.toml"}):
                return False, "package does not contain a runnable entry point"
    except (OSError, zipfile.BadZipFile) as exc:
        return False, f"invalid package: {exc}"
    return True, "package is readable, traversal-safe, and contains runnable content"


def inspect_delivery(candidate_dir: pathlib.Path, case_dir: pathlib.Path, *, case_id: str, run_id: str) -> dict[str, Any]:
    candidate_sha = candidate_tree_hash(candidate_dir)
    manifest = candidate_dir / "delivery_manifest.json"
    readme = candidate_dir / "README.md"
    packages = sorted(case_dir.glob("*.zip")) + sorted(candidate_dir.glob("*.zip"))
    receipt = case_dir / "delivery_receipt.json"
    failures: list[str] = []
    if not readme.is_file():
        failures.append("README.md missing")
    if not manifest.is_file():
        failures.append("delivery_manifest.json missing")
    else:
        try:
            read_json(manifest)
        except (OSError, ValueError, TypeError) as exc:
            failures.append(f"delivery manifest unreadable: {exc}")
    if not receipt.is_file():
        failures.append("delivery receipt missing")
    if not packages:
        failures.append("delivery package missing")
    else:
        safe, details = _zip_is_safe(packages[0])
        if not safe:
            failures.append(details)
    return make_observation(
        case_id=case_id,
        run_id=run_id,
        candidate_sha256=candidate_sha,
        criterion_id="delivery.independent",
        status="FAIL" if failures else "PASS",
        producer="benchmark_file_probe",
        details="; ".join(failures) if failures else "Independent package, manifest, receipt, README, and entry-point checks passed.",
    )


def run_process_probe(
    command: list[str], *, cwd: pathlib.Path, timeout: int = 30, expected_exit: int = 0
) -> tuple[bool, str, int]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        output = (completed.stdout + "\n" + completed.stderr).strip()[-2000:]
        return completed.returncode == expected_exit, output, elapsed_ms
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc), round((time.perf_counter() - started) * 1000)


def probe_http(url: str, *, timeout: int = 10) -> tuple[bool, str, int]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # nosec - evaluator targets local controlled URLs
            body = response.read(200_000)
            ok = 200 <= response.status < 400 and bool(body)
            details = f"HTTP {response.status}; {len(body)} bytes"
    except Exception as exc:  # evaluator reports the real transport error
        ok, details = False, str(exc)
    return ok, details, round((time.perf_counter() - started) * 1000)


def validate_repair_scope(repair: dict[str, Any]) -> tuple[bool, list[str]]:
    affected = {str(item) for item in repair.get("affected_jobs", [])}
    recalled = {str(item) for item in repair.get("provider_recalled_jobs", [])}
    invalidated = {str(item) for item in repair.get("invalidated_evidence", [])}
    reemitted = {str(item) for item in repair.get("reemitted_evidence", [])}
    problems: list[str] = []
    if not repair.get("injected_after_happy_path", False):
        problems.append("fault was not injected after happy-path success")
    if not affected:
        problems.append("affected job scope is empty")
    if not recalled.issubset(affected):
        problems.append("Provider recall escaped affected job scope")
    if invalidated and not invalidated.issubset(reemitted):
        problems.append("stale evidence was not fully re-emitted")
    return not problems, problems


def collect_invocation_metrics(case_dir: pathlib.Path) -> dict[str, Any]:
    provider_ids: set[str] = set()
    codex_ids: set[str] = set()
    token_total = 0
    actual_cost_total = 0.0
    actual_cost_observed = False
    jobs: set[str] = set()
    peak_concurrency = jobs_total = jobs_reused = jobs_repaired = 0
    canonical_provider_calls = codex_supervisor_calls = codex_kernel_calls = 0
    primary_provider_calls = fallback_provider_calls = 0
    fallback_executed = fallback_selected = 0
    files_authored_by_primary: set[str] = set()
    files_authored_by_fallback: set[str] = set()
    provider_wall_time = repair_wall_time = 0.0
    for path in case_dir.rglob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        stack: list[Any] = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                stack.extend(item.values())
                kind = str(item.get("kind", "")).lower()
                invocation_id = str(item.get("invocation_id", "")).strip()
                if "provider" in kind and invocation_id:
                    provider_ids.add(invocation_id)
                if "codex" in kind and invocation_id:
                    codex_ids.add(invocation_id)
                if item.get("provider_api_call") is True and invocation_id:
                    provider_ids.add(invocation_id)
                if item.get("codex_invocation") is True and invocation_id:
                    codex_ids.add(invocation_id)
                job_id = str(item.get("job_id", "")).strip()
                if job_id:
                    jobs.add(job_id)
                peak_concurrency = max(peak_concurrency, int(item.get("provider_peak_concurrency", item.get("actual_peak_concurrency", 0)) or 0))
                canonical_provider_calls = max(canonical_provider_calls, int(item.get("provider_api_call_count", 0) or 0))
                primary_provider_calls = max(primary_provider_calls, int(item.get("primary_provider_calls", 0) or 0))
                fallback_provider_calls = max(fallback_provider_calls, int(item.get("fallback_provider_calls", 0) or 0))
                fallback_executed = max(fallback_executed, int(item.get("fallback_executed", 0) or 0))
                fallback_selected = max(fallback_selected, int(item.get("fallback_selected", 0) or 0))
                if isinstance(item.get("files_authored_by_primary"), list):
                    files_authored_by_primary.update(str(path) for path in item["files_authored_by_primary"] if str(path).strip())
                if isinstance(item.get("files_authored_by_fallback"), list):
                    files_authored_by_fallback.update(str(path) for path in item["files_authored_by_fallback"] if str(path).strip())
                codex_supervisor_calls = max(codex_supervisor_calls, int(item.get("codex_supervisor_invocation_count", 0) or 0))
                codex_kernel_calls = max(codex_kernel_calls, int(item.get("codex_kernel_repair_invocation_count", 0) or 0))
                jobs_total = max(jobs_total, int(item.get("provider_jobs_total", item.get("unique_provider_jobs", 0)) or 0))
                jobs_reused = max(jobs_reused, int(item.get("provider_jobs_reused_after_pass", item.get("reused_jobs", 0)) or 0))
                jobs_repaired = max(jobs_repaired, int(item.get("provider_jobs_repaired", item.get("repaired_jobs", 0)) or 0))
                stage_timing = item.get("wall_clock_stage_timing", {}) if isinstance(item.get("wall_clock_stage_timing"), dict) else {}
                provider_wall_time = max(
                    provider_wall_time,
                    float(item.get("provider_generation_wall_time", 0.0) or 0.0),
                    float(stage_timing.get("component_file_generation", 0.0) or 0.0),
                )
                repair_wall_time = max(repair_wall_time, float(item.get("repair_wall_time", 0.0) or 0.0))
                usage = item.get("usage")
                if isinstance(usage, dict):
                    token_total += int(usage.get("total_tokens", 0) or 0)
                    if isinstance(usage.get("actual_cost"), (int, float)):
                        actual_cost_total += float(usage["actual_cost"])
                        actual_cost_observed = True
    return {
        "provider_api_calls": max(len(provider_ids), canonical_provider_calls),
        "primary_provider_calls": primary_provider_calls,
        "fallback_provider_calls": fallback_provider_calls,
        "fallback_executed": fallback_executed,
        "fallback_selected": fallback_selected,
        "files_authored_by_primary": sorted(files_authored_by_primary),
        "files_authored_by_fallback": sorted(files_authored_by_fallback),
        "codex_invocations": max(len(codex_ids), codex_supervisor_calls + codex_kernel_calls),
        "codex_supervisor_invocation_count": codex_supervisor_calls,
        "codex_kernel_repair_invocation_count": codex_kernel_calls,
        "total_tokens": token_total,
        "actual_cost": round(actual_cost_total, 6) if actual_cost_observed else None,
        "cost_currency": "provider_reported" if actual_cost_observed else None,
        "distinct_jobs": max(len(jobs), jobs_total),
        "provider_jobs_total": max(len(jobs), jobs_total),
        "provider_peak_concurrency": peak_concurrency,
        "provider_jobs_reused_after_pass": jobs_reused,
        "provider_jobs_repaired": jobs_repaired,
        "provider_generation_wall_time": provider_wall_time,
        "repair_wall_time": repair_wall_time,
    }


def _criterion_score(status: str) -> float:
    return {"PASS": 1.0, "PARTIAL": 0.5}.get(str(status).upper(), 0.0)


def evaluate_case(
    case: dict[str, Any],
    *,
    run_id: str,
    candidate_dir: pathlib.Path,
    observations: list[dict[str, Any]],
    metrics: dict[str, Any] | None = None,
    provider_error: str = "",
    repair: dict[str, Any] | None = None,
    dry_run: bool = False,
    require_repair: bool = True,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    candidate_sha = candidate_tree_hash(candidate_dir)
    if not candidate_sha and classify_provider_blocker(provider_error):
        return {
            "kind": "ProjectGenerationBenchmarkCaseResult",
            "schema_version": SCHEMA_VERSION,
            "case_id": case_id,
            "level": case["level"],
            "user_goal": case["user_goal"],
            "result": "BLOCKED_PROVIDER",
            "score": None,
            "hard_failures": [],
            "provider_blocker": provider_error[-2000:],
            "candidate_sha256": "",
            "metrics": metrics or {},
            "dry_run": dry_run,
        }
    accepted, rejected = validate_observations(
        observations, case_id=case_id, run_id=run_id, candidate_sha256=candidate_sha
    )
    by_id = {str(item.get("criterion_id")): item for item in accepted}
    criteria = list(case.get("hidden_acceptance", []))
    category_scores: dict[str, int] = {}

    requirement_values: list[float] = []
    for requirement in case.get("hard_requirements", []):
        requirement_id = str(requirement["id"])
        related = [
            item for item in accepted if requirement_id in {str(value) for value in item.get("requirement_ids", [])}
        ]
        requirement_values.append(max((_criterion_score(item.get("status", "")) for item in related), default=0.0))
    category_scores["requirement_coverage"] = round(
        CATEGORY_POINTS["requirement_coverage"] * sum(requirement_values) / max(1, len(requirement_values))
    )

    for category in ("functional", "runtime", "persistence", "integration"):
        category_criteria = [item for item in criteria if item.get("category") == category]
        values = [_criterion_score(by_id.get(str(item["id"]), {}).get("status", "")) for item in category_criteria]
        category_scores[category] = round(CATEGORY_POINTS[category] * sum(values) / max(1, len(values)))

    repair_ok = False
    repair_problems: list[str] = []
    if repair:
        repair_ok, repair_problems = validate_repair_scope(repair)
    category_scores["repair"] = CATEGORY_POINTS["repair"] if repair_ok and repair.get("recovery_status") == "PASS" else 0
    delivery = by_id.get("delivery.independent", {})
    category_scores["delivery"] = CATEGORY_POINTS["delivery"] if delivery.get("status") == "PASS" else 0
    metric_values = metrics or {}
    efficiency_known = all(key in metric_values for key in ("provider_api_calls", "codex_invocations", "elapsed_seconds"))
    if efficiency_known:
        provider_calls = int(metric_values.get("provider_api_calls", 0) or 0)
        codex_calls = int(metric_values.get("codex_invocations", 0) or 0)
        category_scores["efficiency"] = 5 if provider_calls > 0 and codex_calls <= 2 else 3 if provider_calls > 0 else 0
    else:
        category_scores["efficiency"] = 0

    hard_failures: list[str] = []
    missing_criteria: list[str] = []
    for criterion in criteria:
        observation = by_id.get(str(criterion["id"]))
        if criterion.get("hard") and not observation:
            missing_criteria.append(str(criterion["id"]))
        elif criterion.get("hard") and observation.get("status") != "PASS":
            hard_failures.append(str(criterion["id"]))
    if not dry_run:
        visual = by_id.get("visual.independent")
        if not visual:
            missing_criteria.append("visual.independent")
        elif visual.get("status") != "PASS" or visual.get("producer") != "benchmark_browser_probe":
            hard_failures.append("visual_independent_failed")
    if rejected:
        hard_failures.extend(rejected)
    runtime_criteria = [item for item in criteria if item.get("category") == "runtime"]
    runtime_pass = bool(runtime_criteria) and all(by_id.get(str(item["id"]), {}).get("status") == "PASS" for item in runtime_criteria)
    delivery_pass = delivery.get("status") == "PASS"
    if not candidate_sha:
        hard_failures.append("candidate_missing")
    if not delivery_pass:
        hard_failures.append("delivery_not_independently_runnable")
    hard_failures.extend(repair_problems)
    if require_repair and not dry_run and not repair:
        missing_criteria.append("controlled_repair")
    score = sum(category_scores.values())
    project_pass = score >= 80 and not hard_failures and not missing_criteria and runtime_pass and delivery_pass
    if project_pass:
        result = "PROJECT_PASS"
    elif missing_criteria and not hard_failures:
        result = "NOT_EVALUATED"
    else:
        result = "PROJECT_FAIL"
    if dry_run:
        result = "NOT_EVALUATED"
    return {
        "kind": "ProjectGenerationBenchmarkCaseResult",
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": utc_now(),
        "case_id": case_id,
        "level": case["level"],
        "user_goal": case["user_goal"],
        "result": result,
        "harness_probe_status": "PASS" if dry_run and not hard_failures else "FAIL" if dry_run else None,
        "score": score,
        "score_breakdown": category_scores,
        "hard_failures": sorted(set(hard_failures)),
        "criteria_not_evaluated": sorted(set(missing_criteria)),
        "runtime_status": "PASS" if runtime_pass else "FAIL",
        "delivery_status": "PASS" if delivery_pass else "FAIL",
        "candidate_sha256": candidate_sha,
        "accepted_observation_count": len(accepted),
        "rejected_observations": rejected,
        "metrics": metric_values,
        "repair": repair or {"attempted": False},
        "dry_run": dry_run,
        "production_verdict_used": False,
    }


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {key: 0 for key in ("PROJECT_PASS", "PROJECT_FAIL", "BLOCKED_PROVIDER", "NOT_EVALUATED")}
    live_scores: list[float] = []
    provider_calls = codex_calls = tokens = 0
    actual_cost = elapsed = 0.0
    actual_cost_known = True
    attempted_repairs = successful_repairs = one_shot_passes = 0
    attempts: list[float] = []
    reuse_values: list[float] = []
    scope_values: list[float] = []
    stale_rejections = rejected_total = 0
    failure_taxonomy: dict[str, int] = {}
    for result in results:
        counts[str(result.get("result", "NOT_EVALUATED"))] = counts.get(str(result.get("result")), 0) + 1
        if result.get("result") in {"PROJECT_PASS", "PROJECT_FAIL"} and isinstance(result.get("score"), (int, float)):
            live_scores.append(float(result["score"]))
        metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
        provider_calls += int(metrics.get("provider_api_calls", 0) or 0)
        codex_calls += int(metrics.get("codex_invocations", 0) or 0)
        tokens += int(metrics.get("total_tokens", 0) or 0)
        if isinstance(metrics.get("actual_cost"), (int, float)):
            actual_cost += float(metrics["actual_cost"])
        else:
            actual_cost_known = False
        elapsed += float(metrics.get("elapsed_seconds", 0.0) or 0.0)
        if isinstance(metrics.get("attempts_to_success"), (int, float)):
            attempts.append(float(metrics["attempts_to_success"]))
        if isinstance(metrics.get("job_reuse_rate"), (int, float)):
            reuse_values.append(float(metrics["job_reuse_rate"]))
        repair = result.get("repair", {}) if isinstance(result.get("repair"), dict) else {}
        if repair.get("initial_happy_path_pass") is True:
            one_shot_passes += 1
        if repair.get("attempted") or repair.get("injected_after_happy_path"):
            attempted_repairs += 1
            if repair.get("recovery_status") == "PASS":
                successful_repairs += 1
            valid_scope, _ = validate_repair_scope(repair)
            scope_values.append(1.0 if valid_scope else 0.0)
        rejected = list(result.get("rejected_observations", []))
        rejected_total += len(rejected) + int(result.get("accepted_observation_count", 0) or 0)
        stale_rejections += sum("stale_candidate_identity" in str(item) for item in rejected)
        for failure in result.get("hard_failures", []):
            label = str(failure).split(":", 1)[0]
            failure_taxonomy[label] = failure_taxonomy.get(label, 0) + 1
        if result.get("result") == "BLOCKED_PROVIDER":
            failure_taxonomy["provider_blocker"] = failure_taxonomy.get("provider_blocker", 0) + 1
    evaluated = counts["PROJECT_PASS"] + counts["PROJECT_FAIL"]
    summary = {
        "case_count": len(results),
        "counts": counts,
        "pass_rate": round(counts["PROJECT_PASS"] / evaluated, 4) if evaluated else None,
        "average_score": round(sum(live_scores) / len(live_scores), 2) if live_scores else None,
        "provider_api_calls": provider_calls,
        "codex_invocations": codex_calls,
        "total_tokens": tokens,
        "actual_cost": round(actual_cost, 6) if actual_cost_known and results else None,
        "elapsed_seconds": round(elapsed, 3),
        "one_shot_success_rate": round(one_shot_passes / evaluated, 4) if evaluated else None,
        "repair_success_rate": round(successful_repairs / attempted_repairs, 4) if attempted_repairs else None,
        "average_provider_calls_per_case": round(provider_calls / len(results), 3) if results else None,
        "average_codex_calls_per_case": round(codex_calls / len(results), 3) if results else None,
        "average_attempts_to_success": round(sum(attempts) / len(attempts), 3) if attempts else None,
        "job_reuse_rate": round(sum(reuse_values) / len(reuse_values), 4) if reuse_values else None,
        "repair_scope_accuracy": round(sum(scope_values) / len(scope_values), 4) if scope_values else None,
        "stale_evidence_rejection_rate": round(stale_rejections / rejected_total, 4) if rejected_total else None,
        "failure_taxonomy": dict(sorted(failure_taxonomy.items())),
    }
    successful = [result for result in results if result.get("result") == "PROJECT_PASS"]
    evaluated_results = [result for result in results if result.get("result") in {"PROJECT_PASS", "PROJECT_FAIL"}]
    successful_metrics = [result.get("metrics", {}) for result in successful]
    summary["requirement_coverage"] = round(statistics.mean(float(result.get("score_breakdown", {}).get("requirement_coverage", 0)) / 20 for result in evaluated_results), 4) if evaluated_results else None
    summary["median_provider_calls"] = statistics.median(int(item.get("provider_api_calls", 0) or 0) for item in successful_metrics) if successful_metrics else None
    summary["median_provider_wall_time"] = statistics.median(float(item.get("provider_generation_wall_time", 0.0) or 0.0) for item in successful_metrics) if successful_metrics else None
    summary["median_codex_calls"] = statistics.median(int(item.get("codex_invocations", 0) or 0) for item in successful_metrics) if successful_metrics else None
    successful_costs = [float(item["actual_cost"]) for item in successful_metrics if isinstance(item.get("actual_cost"), (int, float))]
    summary["cost_per_successful_project"] = round(sum(successful_costs) / len(successful_costs), 6) if len(successful_costs) == len(successful) and successful else None
    summary["overall_score"] = summary["average_score"]
    return summary


def compare_reports(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    current_summary = current.get("summary", {})
    baseline_summary = baseline.get("summary", {})
    deltas: dict[str, Any] = {}
    for field in (
        "pass_rate", "one_shot_success_rate", "repair_success_rate", "requirement_coverage",
        "median_provider_calls", "median_provider_wall_time", "median_codex_calls",
    ):
        left, right = current_summary.get(field), baseline_summary.get(field)
        deltas[field] = round(float(left) - float(right), 6) if isinstance(left, (int, float)) and isinstance(right, (int, float)) else None
    return {"baseline_run_id": baseline.get("run_id"), "deltas": deltas}


def scan_production_contamination(repo_root: pathlib.Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    production_roots = [repo_root / "scripts", repo_root / "agents", repo_root / "skills"]
    for root in production_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".json", ".md", ".yaml", ".yml"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lowered = text.lower()
            for marker in FORBIDDEN_PRODUCTION_MARKERS:
                if marker.lower() in lowered:
                    findings.append({"path": path.relative_to(repo_root).as_posix(), "marker": marker})
    return findings


def python_executable() -> str:
    return sys.executable
