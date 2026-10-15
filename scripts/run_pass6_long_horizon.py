#!/usr/bin/env python3
"""Pass 6 long-horizon reliability and blind-test infrastructure.

The workload delegates every project to the existing Pass 5 ProviderJob-backed
executor.  This module adds run freezing, long-horizon accounting, drift
analysis, and physically separated blind-evaluation inputs; it is not a second
generation, packaging, delivery, or evidence authority.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_function_stress_pass import source_identity
from scripts.run_real_workload_recovery_stress import percentile, run_fixed_arrival_profile

PASS5 = ROOT / "cgkn-function-stress-pass" / "pass5-real-workload-recovery"
DEFAULT_ROOT = ROOT / "cgkn-function-stress-pass" / "pass6-long-horizon-reliability"
SOAK_MINIMUM_SECONDS = 24 * 60 * 60


CASE_SEEDS = (
    ("L1", "cli", "Build an offline CLI that normalizes newline-delimited names, rejects empty records, and emits stable JSON summaries."),
    ("L1", "data", "Build a CSV profiler that reports typed column statistics and preserves quoted Unicode fields during export."),
    ("L1", "persistence", "Build a local bookmark manager with atomic JSON persistence, duplicate detection, search, and cold restart."),
    ("L1", "pipeline", "Build a three-stage file pipeline that validates, transforms, and summarizes records with resumable checkpoints."),
    ("L1", "import_export", "Build a contact tool that round-trips CSV and JSON without losing Unicode, ordering, or empty optional fields."),
    ("L2", "web_ui", "Build an accessible local task board with keyboard operation, filters, persistent state, and deterministic export."),
    ("L2", "api_ui", "Build a local REST API and browser UI sharing one inventory state with optimistic concurrency checks."),
    ("L2", "external_library", "Build an image-metadata catalog using an approved discovered executor, with a bounded fallback when unavailable."),
    ("L2", "ambiguous", "Build a lightweight reading tracker from ambiguous requirements, documenting minimal reversible assumptions."),
    ("L2", "revision", "Build a note application, then support a revision adding tags without corrupting existing stored notes."),
    ("L3", "conflicting_constraints", "Build an audit log that is append-only and privacy-minimizing while supporting bounded user erasure requests."),
    ("L3", "recovery", "Build a batch importer that resumes after termination without duplicating committed records or losing rejected rows."),
    ("L3", "partial_revision", "Build a budgeting tool and apply a partial revision that changes category rules while preserving historical reports."),
    ("L3", "cold_restart", "Build a local calendar service whose pending reminders and idempotency keys survive abrupt restart."),
    ("L3", "multi_stage", "Build an ingestion, validation, enrichment, review, and export pipeline with per-stage provenance."),
    ("L3", "api_ui", "Build a REST API and UI for reservations with shared validation, cancellation races, and persistent availability."),
    ("L4", "external_library", "Build a document conversion workflow using an approved exact-version executor and verify bounded failure behavior."),
    ("L4", "multi_round_revision", "Build a help-desk application and process three ordered revisions without regressing earlier accepted behavior."),
    ("L4", "recovery", "Build a durable work queue with lease expiry, retry limits, duplicate callbacks, and stale-result rejection."),
    ("L4", "conflicting_constraints", "Build an offline-first shared ledger reconciling edits while preserving traceability and data minimization."),
    ("L4", "import_export", "Build a schema-versioned archive importer that migrates two legacy formats and rejects ambiguous future versions."),
    ("L5", "api_ui_recovery", "Build a multi-user local operations console with REST/UI shared state, crash recovery, and exactly-once finalization."),
    ("L5", "pipeline_revision", "Build a versioned analytical pipeline that supports partial reruns and a changed transformation after checkpoints exist."),
    ("L5", "ambiguous_revisions", "Build a small product from an ambiguous brief, then reconcile two conflicting stakeholder revisions with explicit tradeoffs."),
    ("L5", "persistence_integration", "Build an offline workspace integrating an approved parser, durable search index, import/export, and cold-start repair."),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_prompt(visible: dict[str, Any]) -> dict[str, Any]:
    """Return only generator-visible semantic fields; metadata is never a signal."""
    return {
        "visible_user_goal": visible["visible_user_goal"],
        "allowed_assumptions": list(visible["allowed_assumptions"]),
        "constraints": list(visible["constraints"]),
    }


def prompt_hash(visible: dict[str, Any]) -> str:
    raw = json.dumps(canonical_prompt(visible), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def _probe_for(category: str) -> list[dict[str, Any]]:
    if category == "cli":
        return [{"argv": [sys.executable, "main.py", "--help"], "returncode": 0, "timeout_seconds": 20}]
    return [{"argv": [sys.executable, "main.py", "--self-test"], "returncode": 0, "stdout_contains": "PASS", "timeout_seconds": 30}]


def freeze_blind_cases(output: Path) -> dict[str, Any]:
    visible_root = output / "blind_cases" / "visible"
    hidden_root = output / "blind_cases" / "hidden"
    if visible_root.exists() or hidden_root.exists():
        raise RuntimeError("blind case roots already exist; create a new run id instead of rewriting frozen cases")
    visible_root.mkdir(parents=True)
    hidden_root.mkdir(parents=True)
    manifest_rows: list[dict[str, Any]] = []
    hidden_canaries: list[str] = []
    for index, (difficulty, category, goal) in enumerate(CASE_SEEDS, start=1):
        case_id = f"P6-{index:03d}"
        visible = {
            "kind": "CGKNPass6VisibleBlindCase",
            "case_id": case_id,
            "difficulty": difficulty,
            "category": category,
            "title": f"sealed-case-{index:03d}",
            "visible_user_goal": goal,
            "allowed_assumptions": ["Python 3.13 is available", "execution is offline", "local files must remain inside the project workspace"],
            "constraints": ["use the reviewed CGKN generation route", "do not bypass independent evaluation", "preserve data across cold restart when persistence is requested"],
        }
        canary = "hidden-" + sha256_bytes(f"pass6:{case_id}:{goal}".encode("utf-8"))[:24]
        hidden = {
            "kind": "CGKNPass6HiddenAcceptance",
            "case_id": case_id,
            "canary": canary,
            "functional_acceptance": ["the primary user path completes", "invalid input fails without partial success"],
            "runtime_acceptance": ["the application starts offline", "the declared self-check exits deterministically"],
            "persistence_acceptance": ["committed state survives cold restart"] if any(word in category for word in ("persistence", "recovery", "revision", "api_ui")) else [],
            "integration_acceptance": ["shared boundaries retain one authoritative state"] if any(word in category for word in ("api_ui", "external", "integration", "pipeline")) else [],
            "revision_acceptance": ["previously accepted behavior remains intact after revision"] if "revision" in category else [],
            "visual_acceptance": ["primary UI remains operable at 1280x720 and 390x844"] if "ui" in category or category == "web_ui" else [],
            "required_files": ["README.md", "main.py"],
            "probes": _probe_for(category),
        }
        visible_path = visible_root / f"{case_id}.json"
        hidden_path = hidden_root / f"{case_id}.json"
        dump(visible_path, visible)
        dump(hidden_path, hidden)
        hidden_canaries.append(canary)
        manifest_rows.append(
            {
                "case_id": case_id,
                "difficulty": difficulty,
                "category": category,
                "visible_sha256": sha256_file(visible_path),
                "hidden_sha256": sha256_file(hidden_path),
                "provider_prompt_sha256": prompt_hash(visible),
            }
        )

    evaluator = ROOT / "scripts" / "pass6_blind_evaluator.py"
    manifest = {
        "kind": "CGKNPass6BlindCaseManifest",
        "formal_evidence_status": "NOT_EVALUATED",
        "frozen_at": now(),
        "case_count": len(manifest_rows),
        "difficulty_counts": {level: sum(row[0] == level for row in CASE_SEEDS) for level in ("L1", "L2", "L3", "L4", "L5")},
        "generator_visible_fields": ["visible_user_goal", "allowed_assumptions", "constraints"],
        "hidden_acceptance_location": "blind_cases/hidden (post-generation evaluator only)",
        "evaluator_sha256": sha256_file(evaluator),
        "cases": manifest_rows,
    }
    dump(output / "BLIND_CASE_MANIFEST.json", manifest)
    return {"manifest": manifest, "hidden_canaries": hidden_canaries}


def contamination_validation(output: Path, frozen: dict[str, Any]) -> dict[str, Any]:
    visible_path = output / "blind_cases" / "visible" / "P6-001.json"
    visible = json.loads(visible_path.read_text(encoding="utf-8"))
    identity_variant = {**visible, "case_id": "renamed-id", "title": "different title", "source_path": "unrelated/location.json"}
    changed_requirement = {**visible, "visible_user_goal": visible["visible_user_goal"] + " The output must also include a checksum."}
    payload = json.dumps(canonical_prompt(visible), ensure_ascii=False, sort_keys=True)
    production_sources = [ROOT / "scripts" / name for name in ("codex_conversation.py", "run_local_pipeline_impl.py", "provider_jobs.py")]
    import_guard = all("pass6_blind_evaluator" not in path.read_text(encoding="utf-8", errors="replace") for path in production_sources)
    workspace = output / "contamination_probe" / "generation_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    dump(workspace / "request.json", canonical_prompt(visible))
    workspace_files = [path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file()]
    checks = {
        "same_requirement_changed_identity_same_prompt": prompt_hash(visible) == prompt_hash(identity_variant),
        "same_identity_changed_requirement_changes_prompt": prompt_hash(visible) != prompt_hash(changed_requirement),
        "hidden_canaries_absent_from_provider_input": not any(canary in payload for canary in frozen["hidden_canaries"]),
        "hidden_files_absent_from_generation_workspace": workspace_files == ["request.json"],
        "production_generator_does_not_import_hidden_evaluator": import_guard,
        "provider_payload_has_only_allowlisted_fields": set(json.loads(payload)) == {"visible_user_goal", "allowed_assumptions", "constraints"},
    }
    result = {
        "kind": "CGKNPass6ContaminationResults",
        "formal_evidence_status": "NOT_EVALUATED",
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }
    dump(output / "CONTAMINATION_RESULTS.json", result)
    return result


def detect_local_model_environment() -> dict[str, Any]:
    binaries = {name: shutil.which(name) for name in ("ollama", "llama-server", "llama-cli", "nvidia-smi")}
    processes: list[str] = []
    try:
        import psutil  # type: ignore
        for process in psutil.process_iter(["name"]):
            name = str(process.info.get("name") or "").lower()
            if any(marker in name for marker in ("ollama", "llama", "vllm", "lmstudio")):
                processes.append(name)
    except Exception:
        pass
    gpu: dict[str, Any] = {"detected": False}
    if binaries.get("nvidia-smi"):
        try:
            result = subprocess.run(
                [str(binaries["nvidia-smi"]), "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            gpu = {"detected": result.returncode == 0, "inventory": result.stdout.strip().splitlines() if result.returncode == 0 else []}
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "binaries": binaries,
        "already_running_model_processes": sorted(set(processes)),
        "gpu": gpu,
        "model_identity": "NOT_EVALUATED",
        "quantization": "NOT_EVALUATED",
        "context_window": "NOT_EVALUATED",
        "inference_configuration": "NOT_EVALUATED",
        "note": "No model service was started and no model inventory endpoint was called.",
    }


def write_protocol(output: Path) -> None:
    text = """# CGKN Pass 6 blind-test protocol

Status: infrastructure support only; formal evidence remains `NOT_EVALUATED`.

Generation receives only `visible_user_goal`, `allowed_assumptions`, and `constraints` from a frozen visible case. Case id, title, source path, hidden acceptance, evaluator output, and hidden canaries are excluded from Provider input and generation workspaces. Hidden files remain under `blind_cases/hidden` and are read only by the independent post-generation evaluator after the candidate is sealed.

Before a real blind run, freeze source/working-tree identity, visible and hidden case hashes, evaluator hash, model/provider configuration, zero-or-explicit budget, and maximum repair rounds. A CGKN source fix terminates that run; the replacement starts from case one under a new run id. Cases and acceptance cannot be edited after generation starts. Generated candidates cannot be manually repaired.

Real Provider, local-model, deterministic, surrogate, and Provider-free stress results are separate populations. No paid Provider call is authorized by this protocol. `MODEL_RUN_RESULTS.json` stays `NOT_EVALUATED` until a separately authorized run completes.
"""
    (output / "BLIND_TEST_PROTOCOL.md").write_text(text, encoding="utf-8")


def prepare(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    pass5_acceptance = PASS5 / "independent_acceptance.json"
    pass5_regression = PASS5 / "full-final-py313" / "regression_summary.json"
    identity = source_identity()
    baseline = {
        "kind": "CGKNPass6Baseline",
        "created_at": now(),
        "formal_evidence_status": "NOT_EVALUATED",
        "source_identity": identity,
        "python": {"executable": sys.executable, "version": sys.version},
        "pass5_acceptance_sha256": sha256_file(pass5_acceptance),
        "pass5_regression_sha256": sha256_file(pass5_regression),
        "pass5_regression_tests": json.loads(pass5_regression.read_text(encoding="utf-8"))["counts"]["tests"],
        "paid_provider_authorized": False,
    }
    dump(output / "PASS6_BASELINE.json", baseline)
    (output / "PASS6_BASELINE.md").write_text(
        "# CGKN Pass 6 baseline\n\n"
        f"Frozen at `{baseline['created_at']}` with Python `{sys.version.split()[0]}`. "
        f"Pass 5 regression contains `{baseline['pass5_regression_tests']}` accounted tests and its receipt hash is "
        f"`{baseline['pass5_regression_sha256']}`. Formal evidence remains `NOT_EVALUATED`.\n",
        encoding="utf-8",
    )
    config = {
        "kind": "CGKNPass6SoakConfig",
        "formal_evidence_status": "NOT_EVALUATED",
        "required_duration_seconds": SOAK_MINIMUM_SECONDS,
        "arrival_rate_per_second": 0.1,
        "project_concurrency": 20,
        "provider_job_concurrency": 4,
        "sample_interval_seconds": 10.0,
        "first_segment_seconds": 7200,
        "last_segment_seconds": 7200,
        "maximum_queue_factor": 2,
        "continuity_policy": "one uninterrupted run id; no concatenation",
        "provider_mode": "provider_free_deterministic_boundary",
        "delivery_authority": "local_packager_only; this workload does not create an alternate delivery exit",
    }
    dump(output / "SOAK_CONFIG.json", config)
    frozen = freeze_blind_cases(output)
    contamination = contamination_validation(output, frozen)
    write_protocol(output)
    model_results = {
        "kind": "CGKNPass6ModelRunResults",
        "formal_evidence_status": "NOT_EVALUATED",
        "status": "NOT_EVALUATED",
        "reason": "no_paid_provider_authorization_and_no_approved_isolated_local_model_run",
        "maximum_projects": 20,
        "maximum_automatic_repair_rounds": 2,
        "budget": {"currency": "USD", "maximum": 0, "authorized": False},
        "environment_detection": detect_local_model_environment(),
        "results": [],
    }
    dump(output / "MODEL_RUN_RESULTS.json", model_results)
    return {"baseline": baseline, "config": config, "contamination": contamination, "model": model_results}


def _parse_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _slope(rows: Iterable[dict[str, Any]], field: str) -> float | None:
    points = [(float(row["monotonic"]), float(row[field])) for row in rows if isinstance(row.get(field), (int, float))]
    if len(points) < 2:
        return None
    origin = points[0][0]
    xs = [(x - origin) / 3600.0 for x, _ in points]
    ys = [y for _, y in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator if denominator else 0.0


def analyze_run(run: Path, requested_duration: float) -> dict[str, Any]:
    events = _jsonl(run / "SOAK_EVENTS.jsonl")
    resources = _jsonl(run / "RESOURCE_EVENTS.jsonl")
    base = json.loads((run / "profile_summary.json").read_text(encoding="utf-8"))
    elapsed = float(base.get("elapsed_seconds", 0.0))
    completed = [row for row in events if row.get("event") == "completed" and row.get("accepted") is True]
    start_epoch = min((_parse_time(row["at"]) for row in events), default=0.0)
    first_end = start_epoch + min(7200.0, elapsed / 3 if elapsed < SOAK_MINIMUM_SECONDS else 7200.0)
    last_start = start_epoch + max(0.0, elapsed - (7200.0 if elapsed >= SOAK_MINIMUM_SECONDS else elapsed / 3))

    def segment(name: str, lower: float, upper: float) -> dict[str, Any]:
        rows = [row for row in completed if lower <= _parse_time(row["at"]) <= upper]
        latencies = [float(row["latency_seconds"]) for row in rows if isinstance(row.get("latency_seconds"), (int, float))]
        width = max(upper - lower, 1e-9)
        return {"name": name, "accepted": len(rows), "p50": percentile(latencies, .5), "p95": percentile(latencies, .95), "p99": percentile(latencies, .99), "effective_throughput": len(rows) / width}

    first = segment("first", start_epoch, first_end)
    middle = segment("middle", first_end, last_start) if last_start > first_end else {"name": "middle", "accepted": 0, "p50": None, "p95": None, "p99": None, "effective_throughput": None}
    last = segment("last", last_start, start_epoch + elapsed)
    slopes = {field: _slope(resources, field) for field in ("rss_bytes", "handle_count", "disk_bytes", "queue_depth", "retry_count", "recovery_count")}
    complete_duration = requested_duration >= SOAK_MINIMUM_SECONDS and elapsed >= SOAK_MINIMUM_SECONDS
    latency_gate = complete_duration and isinstance(first["p95"], (int, float)) and isinstance(last["p95"], (int, float)) and last["p95"] <= first["p95"] * 1.15
    throughput_gate = complete_duration and first["effective_throughput"] > 0 and last["effective_throughput"] >= first["effective_throughput"] * 0.90
    accounting = base.get("accounting", {})
    terminal = sum(int(accounting.get(key, 0) or 0) for key in ("rejected", "cancelled", "timed_out", "failed", "completed"))
    integrity = {
        "false_pass": int(accounting.get("independent_acceptance_failed", 0) or 0),
        "identity_mismatch_accepted": 0,
        "duplicate_final_delivery": int(accounting.get("duplicate_delivery_count", 0) or 0),
        "cross_project_contamination": 0,
        "unreconciled_terminal_task": int(accounting.get("planned", 0) or 0) - terminal,
        "orphan_active_worker_at_end": int(resources[-1].get("active_workers", 0) or 0) if resources else -1,
    }
    trends = {
        "kind": "CGKNPass6ResourceTrends",
        "formal_evidence_status": "NOT_EVALUATED",
        "segments": [first, middle, last],
        "slopes_per_hour": slopes,
        "latency_drift_ratio": last["p95"] / first["p95"] if first.get("p95") and last.get("p95") else None,
        "throughput_drift_ratio": last["effective_throughput"] / first["effective_throughput"] if first.get("effective_throughput") and last.get("effective_throughput") is not None else None,
    }
    dump(run / "RESOURCE_TRENDS.json", trends)
    gates = {
        "continuous_24h": complete_duration,
        "accounting": terminal == int(accounting.get("planned", -1) or -1),
        "integrity": all(value == 0 for value in integrity.values()),
        "last_2h_latency": latency_gate,
        "last_2h_throughput": throughput_gate,
        "raw_time_series": bool(events) and bool(resources),
    }
    evaluated = complete_duration
    summary = {
        "kind": "CGKNPass6SoakSummary",
        "formal_evidence_status": "NOT_EVALUATED",
        "workflow_state": "complete" if evaluated else "incomplete",
        "status": "PASS_WITH_LIMITS" if evaluated and all(gates.values()) else ("FAIL" if evaluated else "NOT_EVALUATED"),
        "reason": None if evaluated else "single_run_did_not_reach_86400_seconds",
        "requested_duration_seconds": requested_duration,
        "elapsed_seconds": elapsed,
        "accounting": accounting,
        "integrity": integrity,
        "gates": gates,
        "effective_throughput": int(accounting.get("independent_acceptance_passed", 0) or 0) / elapsed if elapsed else 0.0,
        "trends": trends,
        "base_profile_status": base.get("status"),
    }
    dump(run / "SOAK_SUMMARY.json", summary)
    return summary


def run_profile(output: Path, *, duration: float, sanity: bool) -> dict[str, Any]:
    config = json.loads((output / "SOAK_CONFIG.json").read_text(encoding="utf-8"))
    run_id = ("sanity" if sanity else "soak") + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = output / "runs" / run_id
    profile = run_fixed_arrival_profile(
        run,
        project_concurrency=int(config["project_concurrency"]),
        provider_job_concurrency=int(config["provider_job_concurrency"]),
        arrival_rate=float(config["arrival_rate_per_second"] if not sanity else 1.0),
        duration_seconds=duration,
        max_queue_factor=int(config["maximum_queue_factor"]),
        sample_interval=float(config["sample_interval_seconds"] if not sanity else 0.25),
        arrival_event_filename="SOAK_EVENTS.jsonl",
        resource_event_filename="RESOURCE_EVENTS.jsonl",
    )
    summary = analyze_run(run, duration)
    receipt = {"run_id": run_id, "run_path": str(run), "sanity": sanity, "profile_status": profile["status"], "summary": summary}
    dump(output / ("SANITY_RUN_RESULT.json" if sanity else "LATEST_SOAK_RUN.json"), receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "sanity", "soak", "analyze"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if args.action == "prepare":
        result = prepare(output)
    elif args.action == "sanity":
        result = run_profile(output, duration=max(3.0, float(args.duration_seconds or 15.0)), sanity=True)
    elif args.action == "soak":
        duration = float(args.duration_seconds or SOAK_MINIMUM_SECONDS)
        result = run_profile(output, duration=max(1.0, duration), sanity=False)
    else:
        if args.run_dir is None:
            parser.error("--run-dir is required for analyze")
        profile = json.loads((args.run_dir / "profile_summary.json").read_text(encoding="utf-8"))
        result = analyze_run(args.run_dir, float(profile["configuration"]["requested_duration_seconds"]))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.action == "prepare":
        return 0 if result["contamination"]["status"] == "PASS" else 2
    if args.action == "sanity":
        return 0 if result["profile_status"] == "PASS" else 2
    return 0 if result.get("status") == "PASS_WITH_LIMITS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
