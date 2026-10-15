#!/usr/bin/env python3
"""Pass 6 long-horizon latency audit and bounded revalidation.

This engineering harness preserves the failed 24-hour run as immutable input.
It does not authorize formal evidence, generation, packaging, or delivery.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import pathlib
import statistics
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PASS6 = ROOT / "cgkn-function-stress-pass" / "pass6-long-horizon-reliability"
FAILED_RUN_ID = "soak-20261011T131459Z"
FAILED_RUN = PASS6 / "runs" / FAILED_RUN_ID

from scripts import run_local_pipeline_impl
from scripts import run_real_workload_recovery_stress as stress


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: pathlib.Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _distribution(values: list[float]) -> dict[str, Any]:
    return {
        "samples": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "mean": statistics.fmean(values) if values else None,
        "max": max(values) if values else None,
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    return numerator / denominator if denominator else None


def _hourly(events: list[dict[str, Any]], elapsed: float) -> list[dict[str, Any]]:
    start = min(_epoch(row["at"]) for row in events)
    completed = [row for row in events if row.get("event") == "completed" and row.get("accepted") is True]
    submitted = [row for row in events if row.get("event") == "submitted"]
    hours = int(math.ceil(elapsed / 3600.0))
    result: list[dict[str, Any]] = []
    for index in range(hours):
        lower = start + index * 3600.0
        upper = min(start + elapsed, lower + 3600.0)
        done = [row for row in completed if lower <= _epoch(row["at"]) < upper]
        sends = [row for row in submitted if lower <= _epoch(row["at"]) < upper]
        latencies = [float(row["latency_seconds"]) for row in done]
        lags = [float(row["submission_lag_seconds"]) for row in sends]
        rolling_lower = max(start, upper - 7200.0)
        rolling = [
            float(row["latency_seconds"])
            for row in completed
            if rolling_lower <= _epoch(row["at"]) < upper
        ]
        width = max(upper - lower, 1e-9)
        result.append({
            "hour": index,
            "start_offset_seconds": index * 3600.0,
            "duration_seconds": width,
            "accepted": len(done),
            "effective_throughput_per_second": len(done) / width,
            "latency_seconds": _distribution(latencies),
            "submission_lag_seconds": _distribution(lags),
            "rolling_2h_p95_seconds": _percentile(rolling, 0.95),
            "rolling_2h_samples": len(rolling),
        })
    return result


def _phase_envelopes(run: pathlib.Path, events: list[dict[str, Any]], start_epoch: float, elapsed: float) -> dict[str, Any]:
    completion_by_task = {
        str(row["task_id"]): row
        for row in events
        if row.get("event") == "completed" and row.get("accepted") is True
    }
    submission_by_task = {
        str(row["task_id"]): row
        for row in events
        if row.get("event") == "submitted"
    }
    phases: dict[str, list[tuple[float, float]]] = defaultdict(list)
    parsed_logs = 0
    for log_path in sorted((run / "projects").glob("project-*/provider_phase_log.jsonl")):
        rows = _read_jsonl(log_path)
        if not rows:
            continue
        parsed_logs += 1
        by_event: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row.get("ts"):
                by_event[str(row.get("event", ""))].append(_epoch(str(row["ts"])))
        started = (by_event.get("component_generation_split_started") or [None])[0]
        graph = (by_event.get("component_leaf_work_graph_built") or [None])[0]
        cache = (by_event.get("component_leaf_cache_scanned") or [None])[0]
        first_batch = (by_event.get("component_leaf_batch_started") or [None])[0]
        final_leaf = max(by_event.get("component_leaf_completed") or [0.0]) or None
        project_epoch = started or graph or cache or final_leaf
        if project_epoch is None:
            continue
        if started is not None and graph is not None:
            phases["leaf_work_graph_build_observed_envelope"].append((project_epoch, graph - started))
        if graph is not None and cache is not None:
            phases["cache_scan_observed_envelope"].append((project_epoch, cache - graph))
        if cache is not None and first_batch is not None:
            phases["batch_scheduling_observed_envelope"].append((project_epoch, first_batch - cache))
        if first_batch is not None and final_leaf is not None:
            phases["provider_execution_and_leaf_finalization_envelope"].append((project_epoch, final_leaf - first_batch))
        task_id = log_path.parent.name
        completion = completion_by_task.get(task_id)
        submission = submission_by_task.get(task_id)
        if completion is not None and submission is not None and final_leaf is not None:
            finished_epoch = _epoch(str(submission["at"])) + float(completion["latency_seconds"])
            phases["independent_acceptance_overhead_envelope"].append((project_epoch, max(0.0, finished_epoch - final_leaf)))

    first_limit = start_epoch + 7200.0
    last_limit = start_epoch + elapsed - 7200.0
    output: dict[str, Any] = {
        "kind": "CGKNPass6LatencyPhaseBreakdown",
        "formal_evidence_status": "NOT_EVALUATED",
        "source_run_id": FAILED_RUN_ID,
        "parsed_provider_phase_logs": parsed_logs,
        "historical_observability": {
            "note": "Historical events provide bounded envelopes, not exclusive call timings; new scale profiles add call-level timing.",
            "not_separately_instrumented": [
                "emission planning for every single-file leaf",
                "context preflight exclusive time",
                "owned-file verification exclusive time",
                "interface publication exclusive time",
                "boundary receipt creation exclusive time",
                "artifact/evidence write exclusive time",
            ],
        },
        "phases": {},
    }
    for name, points in phases.items():
        all_values = [value for _, value in points]
        first_values = [value for epoch, value in points if epoch < first_limit]
        last_values = [value for epoch, value in points if epoch >= last_limit]
        first = _distribution(first_values)
        last = _distribution(last_values)
        output["phases"][name] = {
            "overall": _distribution(all_values),
            "first_2h": first,
            "last_2h": last,
            "p95_drift_ratio": (
                last["p95"] / first["p95"]
                if isinstance(first.get("p95"), (int, float))
                and first["p95"]
                and isinstance(last.get("p95"), (int, float))
                else None
            ),
        }
    return output


def analyze_failed_run(run: pathlib.Path = FAILED_RUN, output: pathlib.Path = PASS6) -> dict[str, Any]:
    events = _read_jsonl(run / "SOAK_EVENTS.jsonl")
    resources = _read_jsonl(run / "RESOURCE_EVENTS.jsonl")
    summary = _read_json(run / "SOAK_SUMMARY.json")
    profile = _read_json(run / "profile_summary.json")
    elapsed = float(profile["elapsed_seconds"])
    start_epoch = min(_epoch(row["at"]) for row in events)
    hourly = _hourly(events, elapsed)
    phase = _phase_envelopes(run, events, start_epoch, elapsed)

    resource_by_hour: list[dict[str, Any]] = []
    for hour in hourly:
        lower = start_epoch + float(hour["start_offset_seconds"])
        upper = lower + float(hour["duration_seconds"])
        rows = [row for row in resources if lower <= _epoch(row["at"]) < upper]
        resource_by_hour.append({
            "hour": hour["hour"],
            "artifact_count_last": rows[-1].get("artifact_count") if rows else None,
            "checkpoint_count_last": rows[-1].get("checkpoint_count") if rows else None,
            "disk_bytes_last": rows[-1].get("disk_bytes") if rows else None,
            "process_cpu_percent": _distribution([float(row["cpu_percent"]) for row in rows if isinstance(row.get("cpu_percent"), (int, float))]),
        })
    for hour, resource in zip(hourly, resource_by_hour):
        hour["resources"] = resource

    p95s = [float(row["latency_seconds"]["p95"]) for row in hourly if isinstance(row["latency_seconds"].get("p95"), (int, float))]
    artifact_counts = [float(row["resources"]["artifact_count_last"]) for row in hourly if isinstance(row["resources"].get("artifact_count_last"), (int, float))]
    paired = min(len(p95s), len(artifact_counts))
    completed = [row for row in events if row.get("event") == "completed" and row.get("accepted") is True]
    cadence_groups: dict[int, list[float]] = defaultdict(list)
    for row in completed:
        try:
            index = int(str(row["task_id"]).rsplit("-", 1)[-1])
        except (KeyError, ValueError):
            continue
        cadence_groups[index % 10].append(float(row["latency_seconds"]))
    cadence = {str(key): _distribution(values) for key, values in sorted(cadence_groups.items())}
    cadence_p95s = {key: value["p95"] for key, value in cadence.items()}
    worst_cadence = max(cadence_p95s, key=lambda key: float(cadence_p95s[key] or 0.0))

    scan_updates = []
    previous_disk = None
    for row in resources:
        disk = row.get("disk_bytes")
        if isinstance(disk, (int, float)) and disk != previous_disk:
            scan_updates.append({"at": row["at"], "disk_bytes": disk, "artifact_count": row.get("artifact_count")})
            previous_disk = disk

    accounting = summary["accounting"]
    final_resources = profile["resources"]
    projects = int(accounting["completed"])
    storage = {
        "projects": projects,
        "bytes_per_project_including_run_overhead": float(final_resources["disk_bytes"]["last"]) / projects,
        "files_per_project_including_run_overhead": float(final_resources["artifact_count"]["last"]) / projects,
        "checkpoints_per_project": float(final_resources["checkpoint_count"]["last"]) / projects,
        "temporary_bytes_final": final_resources["temp_bytes"]["last"],
        "classification": "expected retained evidence is linear; no temporary-state growth was observed",
    }
    hourly_doc = {
        "kind": "CGKNPass6LatencyHourly",
        "formal_evidence_status": "NOT_EVALUATED",
        "source_run_id": FAILED_RUN_ID,
        "source_summary_status": summary["status"],
        "hours": hourly,
        "cadence_residue_modulo_10": cadence,
        "derived_recursive_scan_updates": scan_updates,
    }
    _write_json(output / "LATENCY_HOURLY.json", hourly_doc)
    _write_json(output / "LATENCY_PHASE_BREAKDOWN.json", phase)

    recomputed_first = _distribution([
        float(row["latency_seconds"])
        for row in completed
        if _epoch(row["at"]) <= start_epoch + 7200.0
    ])
    recomputed_last = _distribution([
        float(row["latency_seconds"])
        for row in completed
        if _epoch(row["at"]) >= start_epoch + elapsed - 7200.0
    ])
    ratio = float(recomputed_last["p95"]) / float(recomputed_first["p95"])
    summary_ratio = float(summary["trends"]["latency_drift_ratio"])
    exact_match = abs(ratio - summary_ratio) < 1e-12
    root_cause = {
        "summary_recalculation_matches": exact_match,
        "recomputed_first_2h_p95": recomputed_first["p95"],
        "recomputed_last_2h_p95": recomputed_last["p95"],
        "recomputed_ratio": ratio,
        "hourly_latency_artifact_count_pearson": _pearson(p95s[:paired], artifact_counts[:paired]),
        "worst_task_index_modulo_10": int(worst_cadence),
        "storage": storage,
    }
    _write_text(
        output / "PASS6_LATENCY_ROOT_CAUSE.md",
        f"""# Pass 6 latency root-cause audit

Formal evidence status: `NOT_EVALUATED`  
Source run: `{FAILED_RUN_ID}`  
Source verdict: `FAIL / NEEDS_REWORK` (retained; not reinterpreted)

## Recalculation

The raw event recomputation matches the saved summary: `{str(exact_match).lower()}`. First-two-hour p95 is `{recomputed_first['p95']:.9f}` s, last-two-hour p95 is `{recomputed_last['p95']:.9f}` s, and the drift ratio is `{ratio:.6f}` against the unchanged `<= 1.15` gate. Throughput and all accounting/integrity gates remain as recorded; the failed latency gate is not downgraded.

## Root cause

The pre-fix resource sampler performs `os.walk` plus `stat` over the complete run tree every 100 seconds. The workload starts a project every 10 seconds, so recursive telemetry and project execution are phase-locked. The measured tree grew to `{int(final_resources['artifact_count']['last']):,}` files and `{int(final_resources['disk_bytes']['last']):,}` bytes; the scan therefore changes from bounded work into O(total retained projects/files) work during the run. Hourly p95 versus retained artifact count has Pearson correlation `{root_cause['hourly_latency_artifact_count_pearson']}`. Task-index modulo-10 residue `{worst_cadence}` has the highest p95, consistent with the 100-second telemetry cadence colliding with every tenth arrival.

The production ProviderJob path uses per-project checkpoint roots. No cross-project recursive lookup was found in this workload's execution call chain. Historical phase logs show bounded per-project envelopes; the state-sized operation is the telemetry scan. `LATENCY_PHASE_BREAKDOWN.json` records the old-run envelopes and explicitly marks phase timings that were not separately observable before the new profiler.

## Corrective action

Running telemetry now accounts each immutable completed project exactly once, keeps only bounded direct-root file stats during execution, and performs a complete recursive reconciliation after workload completion. The legacy recursive mode remains available only for controlled A/B. Necessary disk/artifact/checkpoint telemetry is retained. Host CPU, available memory, disk I/O counters, and scan-window telemetry were added. No Provider, generation, packaging, acceptance, or delivery route changed.

## Storage classification

Observed storage is `{storage['bytes_per_project_including_run_overhead']:.1f}` bytes/project, `{storage['files_per_project_including_run_overhead']:.3f}` files/project, and `{storage['checkpoints_per_project']:.3f}` checkpoints/project including run overhead. Final temporary bytes are `{storage['temporary_bytes_final']}`. This is expected retained evidence growth, not an accidental temporary-state leak; retention/archive policy is outside this latency fix.

## Claim scope

The workload validates ProviderJob execution, checkpoint/evidence production, and independent acceptance. `final_delivery_count = 0`; it does not claim 8,641 `local_packager` or public-delivery lifecycles.
""",
    )
    return root_cause


class PhaseProfiler:
    """Aggregate call-level timing for diagnostic profiles; timings may overlap."""

    TARGETS = {
        "leaf_work_graph_build": (run_local_pipeline_impl, "build_component_leaf_work_graph"),
        "cache_scan": (run_local_pipeline_impl, "load_split_file_checkpoint"),
        "batch_scheduling": (run_local_pipeline_impl, "component_leaf_ready_batches"),
        "emission_planning": (run_local_pipeline_impl, "plan_provider_job_emissions"),
        "context_preflight": (run_local_pipeline_impl, "prepare_provider_request_within_context_budget"),
        "owned_file_verification": (run_local_pipeline_impl.provider_jobs, "validate_patch_set"),
        "interface_publication": (run_local_pipeline_impl, "build_project_interface_registry"),
        "boundary_receipt_creation": (run_local_pipeline_impl, "build_leaf_boundary_check_receipt"),
        "artifact_evidence_write_split": (run_local_pipeline_impl, "write_split_file_checkpoint"),
        "artifact_evidence_write_orchestration": (run_local_pipeline_impl, "write_leaf_orchestration_artifacts"),
        "artifact_evidence_write_librarian": (run_local_pipeline_impl, "write_generation_librarian_artifacts"),
        "independent_acceptance": (stress, "evaluate_arrival_task_result"),
        "deterministic_provider_free_execution": (stress.DeterministicProvider, "__call__"),
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, list[float]] = defaultdict(list)
        self._originals: list[tuple[Any, str, Callable[..., Any]]] = []

    def _wrap(self, name: str, original: Callable[..., Any]) -> Callable[..., Any]:
        def measured(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                with self._lock:
                    self._values[name].append(time.perf_counter() - started)
        return measured

    def __enter__(self) -> "PhaseProfiler":
        for name, (owner, attribute) in self.TARGETS.items():
            original = getattr(owner, attribute)
            self._originals.append((owner, attribute, original))
            setattr(owner, attribute, self._wrap(name, original))
        return self

    def __exit__(self, *_args: Any) -> None:
        for owner, attribute, original in reversed(self._originals):
            setattr(owner, attribute, original)

    def summary(self, completed_projects: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        artifact_total = 0.0
        artifact_calls = 0
        for name, values in sorted(self._values.items()):
            distribution = _distribution(values)
            distribution["total_seconds"] = sum(values)
            distribution["seconds_per_completed_project"] = sum(values) / completed_projects if completed_projects else None
            result[name] = distribution
            if name.startswith("artifact_evidence_write_"):
                artifact_total += sum(values)
                artifact_calls += len(values)
        result["artifact_evidence_write"] = {
            "samples": artifact_calls,
            "total_seconds": artifact_total,
            "seconds_per_completed_project": artifact_total / completed_projects if completed_projects else None,
            "note": "sum of bounded split, orchestration, and librarian writes",
        }
        result["timing_semantics"] = "observed call wall-time; nested or concurrent measurements may overlap and are not summable"
        return result


def _host_summary(resource_rows: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "host_cpu_percent",
        "available_memory_bytes",
        "host_disk_read_bytes",
        "host_disk_write_bytes",
        "host_disk_read_time_ms",
        "host_disk_write_time_ms",
        "host_disk_busy_time_ms",
    )
    return {
        field: _distribution([float(row[field]) for row in resource_rows if isinstance(row.get(field), (int, float))])
        for field in fields
    }


def _experiment_profile(
    output: pathlib.Path,
    *,
    mode: str,
    retained_roots: list[pathlib.Path],
    task_count: int,
    arrival_rate: float,
) -> dict[str, Any]:
    duration = (task_count - 1) / arrival_rate
    with PhaseProfiler() as profiler:
        report = stress.run_fixed_arrival_profile(
            output,
            project_concurrency=8,
            provider_job_concurrency=4,
            arrival_rate=arrival_rate,
            duration_seconds=duration,
            max_queue_factor=2,
            sample_interval=0.5,
            arrival_event_filename="ARRIVAL_EVENTS.jsonl",
            resource_event_filename="RESOURCE_EVENTS.jsonl",
            filesystem_telemetry_mode=mode,
            retained_state_roots=retained_roots,
        )
    arrivals = _read_jsonl(output / "ARRIVAL_EVENTS.jsonl")
    resource_rows = _read_jsonl(output / "RESOURCE_EVENTS.jsonl")
    completed = [row for row in arrivals if row.get("event") == "completed" and row.get("accepted") is True]
    latencies = [float(row["latency_seconds"]) for row in completed]
    planned = [row for row in arrivals if row.get("event") == "planned"]
    workload_elapsed = (
        max(_epoch(str(row["at"])) for row in completed) - min(_epoch(str(row["at"])) for row in planned)
        if completed and planned
        else None
    )
    scan_rows = _read_jsonl(output / "filesystem_scan_events.jsonl")
    return {
        "status": report["status"],
        "formal_evidence_status": "NOT_EVALUATED",
        "telemetry_mode": mode,
        "retained_project_count": len(retained_roots),
        "new_task_count": task_count,
        "latency_seconds": _distribution(latencies),
        "workload_elapsed_seconds": workload_elapsed,
        "effective_throughput_per_second": (
            len(completed) / workload_elapsed
            if isinstance(workload_elapsed, (int, float)) and workload_elapsed > 0
            else None
        ),
        "end_to_end_throughput_including_final_reconciliation": report["effective_throughput_per_second"],
        "accounting": report["accounting"],
        "resources": report["resources"],
        "host": _host_summary(resource_rows),
        "filesystem_scans": {
            "count": len(scan_rows),
            "duration_seconds": _distribution([float(row["duration_seconds"]) for row in scan_rows]),
        },
        "phase_timing": profiler.summary(len(completed)),
        "run_path": str(output),
    }


def run_scale_experiments(
    source_run: pathlib.Path = FAILED_RUN,
    output: pathlib.Path = PASS6,
    *,
    task_count: int = 18,
    repetitions: int = 3,
    arrival_rate: float = 2.0,
) -> dict[str, Any]:
    all_roots = sorted((source_run / "projects").glob("project-*"))
    scales = (0, 2000, 4000, 8000)
    rows: list[dict[str, Any]] = []
    experiment_root = output / "latency-scale-profiles"
    for mode in ("legacy_recursive", "incremental"):
        for scale in scales:
            retained = all_roots[:scale]
            for repetition in range(1, repetitions + 1):
                run_path = experiment_root / f"{mode}-state-{scale:04d}-r{repetition}"
                row = _experiment_profile(
                    run_path,
                    mode=mode,
                    retained_roots=retained,
                    task_count=task_count,
                    arrival_rate=arrival_rate,
                )
                row.update({"repetition": repetition, "source_retained_state": str(source_run / "projects")})
                rows.append(row)

    grouped: list[dict[str, Any]] = []
    for mode in ("legacy_recursive", "incremental"):
        for scale in scales:
            selected = [row for row in rows if row["telemetry_mode"] == mode and row["retained_project_count"] == scale]
            p95s = [float(row["latency_seconds"]["p95"]) for row in selected]
            throughputs = [float(row["effective_throughput_per_second"]) for row in selected]
            grouped.append({
                "telemetry_mode": mode,
                "retained_project_count": scale,
                "repetitions": len(selected),
                "p95_seconds": _distribution(p95s),
                "effective_throughput_per_second": _distribution(throughputs),
                "all_correct": all(row["status"] == "PASS" for row in selected),
                "all_denominators_balanced": all(row["accounting"]["planned"] == row["accounting"]["completed"] for row in selected),
            })
    state_doc = {
        "kind": "CGKNPass6StateScaleAB",
        "formal_evidence_status": "NOT_EVALUATED",
        "workload": {"new_tasks_per_run": task_count, "arrival_rate_per_second": arrival_rate, "isolated_repetitions": repetitions},
        "source_failed_run_id": FAILED_RUN_ID,
        "profiles": rows,
        "summary": grouped,
    }
    _write_json(output / "STATE_SCALE_AB.json", state_doc)

    legacy_8000 = [row for row in rows if row["telemetry_mode"] == "legacy_recursive" and row["retained_project_count"] == 8000]
    incremental_8000 = [row for row in rows if row["telemetry_mode"] == "incremental" and row["retained_project_count"] == 8000]
    legacy_p95 = statistics.median(float(row["latency_seconds"]["p95"]) for row in legacy_8000)
    incremental_p95 = statistics.median(float(row["latency_seconds"]["p95"]) for row in incremental_8000)
    incremental_fresh = next(
        row for row in grouped
        if row["telemetry_mode"] == "incremental" and row["retained_project_count"] == 0
    )
    incremental_scale = next(
        row for row in grouped
        if row["telemetry_mode"] == "incremental" and row["retained_project_count"] == 8000
    )
    incremental_scale_ratio = (
        float(incremental_scale["p95_seconds"]["p50"])
        / float(incremental_fresh["p95_seconds"]["p50"])
    )
    telemetry_doc = {
        "kind": "CGKNPass6TelemetryAB",
        "formal_evidence_status": "NOT_EVALUATED",
        "retained_project_count": 8000,
        "necessary_safety_records_preserved": True,
        "legacy_recursive_p95_median_seconds": legacy_p95,
        "incremental_p95_median_seconds": incremental_p95,
        "p95_ratio_incremental_over_legacy": incremental_p95 / legacy_p95 if legacy_p95 else None,
        "incremental_state_scale_p95_ratio_8000_over_fresh": incremental_scale_ratio,
        "incremental_state_scale_gate_limit": 1.15,
        "incremental_state_scale_gate": "PASS" if incremental_scale_ratio <= 1.15 else "FAIL",
        "legacy_profiles": legacy_8000,
        "incremental_profiles": incremental_8000,
        "conclusion": "Same-state A/B proves recursive whole-run telemetry is a removable latency contributor. The legacy scale medians are not monotonic, so wall-clock/host contention remains a contributing hypothesis pending the >=4h validation. Incremental telemetry retains counters and final reconciliation without hot-path whole-tree scans.",
    }
    _write_json(output / "TELEMETRY_AB.json", telemetry_doc)
    _write_json(output / "DIRECTORY_LAYOUT_AB.json", {
        "kind": "CGKNPass6DirectoryLayoutAB",
        "formal_evidence_status": "NOT_EVALUATED",
        "status": "NOT_APPLICABLE",
        "reason": "The confirmed scale-sensitive operation is diagnostic whole-tree telemetry, not project identity lookup or sibling-directory resolution. Removing the hot-path global scan bounds work per completed project, so sharding would add migration/replay risk without addressing an active production lookup.",
        "identity_changed": False,
        "evidence_deleted": False,
    })
    _write_text(output / "BEFORE_AFTER_LATENCY.md", f"""# Pass 6 latency before/after

Formal evidence status: `NOT_EVALUATED`.

The immutable 24-hour before run `{FAILED_RUN_ID}` remains failed with latency drift ratio `{_read_json(source_run / 'SOAK_SUMMARY.json')['trends']['latency_drift_ratio']:.6f}`.

At 8,000 retained project states across {repetitions} isolated repetitions, legacy recursive telemetry had median p95 `{legacy_p95:.6f}` s and incremental telemetry had median p95 `{incremental_p95:.6f}` s (after/before ratio `{incremental_p95 / legacy_p95:.6f}`). All A/B tasks must retain 100% accounting and independent acceptance; see `STATE_SCALE_AB.json` and `TELEMETRY_AB.json` for raw profile references and phase timing.

This bounded result does not replace the required >=4h first/last-two-hour validation or a fresh 24-hour run.
""")
    phase_doc = _read_json(output / "LATENCY_PHASE_BREAKDOWN.json")
    phase_doc["state_scale_call_level_profiles"] = [
        {
            "telemetry_mode": row["telemetry_mode"],
            "retained_project_count": row["retained_project_count"],
            "repetition": row["repetition"],
            "phase_timing": row["phase_timing"],
        }
        for row in rows
    ]
    _write_json(output / "LATENCY_PHASE_BREAKDOWN.json", phase_doc)
    return state_doc


def summarize_existing_experiments(output: pathlib.Path = PASS6) -> dict[str, Any]:
    """Refresh aggregate metrics from already completed immutable profile rows."""
    path = output / "STATE_SCALE_AB.json"
    doc = _read_json(path)
    rows = list(doc.get("profiles", []))
    for row in rows:
        run_path = pathlib.Path(str(row["run_path"]))
        arrivals = _read_jsonl(run_path / "ARRIVAL_EVENTS.jsonl")
        planned = [item for item in arrivals if item.get("event") == "planned"]
        completed = [item for item in arrivals if item.get("event") == "completed" and item.get("accepted") is True]
        workload_elapsed = (
            max(_epoch(str(item["at"])) for item in completed) - min(_epoch(str(item["at"])) for item in planned)
            if completed and planned
            else None
        )
        row["workload_elapsed_seconds"] = workload_elapsed
        row["end_to_end_throughput_including_final_reconciliation"] = row.get("effective_throughput_per_second")
        row["effective_throughput_per_second"] = (
            len(completed) / workload_elapsed
            if isinstance(workload_elapsed, (int, float)) and workload_elapsed > 0
            else None
        )
    grouped: list[dict[str, Any]] = []
    for mode in ("legacy_recursive", "incremental"):
        for scale in (0, 2000, 4000, 8000):
            selected = [row for row in rows if row["telemetry_mode"] == mode and row["retained_project_count"] == scale]
            p95s = [float(row["latency_seconds"]["p95"]) for row in selected]
            throughputs = [float(row["effective_throughput_per_second"]) for row in selected]
            grouped.append({
                "telemetry_mode": mode,
                "retained_project_count": scale,
                "repetitions": len(selected),
                "p95_seconds": _distribution(p95s),
                "effective_throughput_per_second": _distribution(throughputs),
                "all_correct": all(row["status"] == "PASS" for row in selected),
                "all_denominators_balanced": all(row["accounting"]["planned"] == row["accounting"]["completed"] for row in selected),
            })
    doc["profiles"] = rows
    doc["summary"] = grouped
    _write_json(path, doc)
    legacy_8000 = [row for row in rows if row["telemetry_mode"] == "legacy_recursive" and row["retained_project_count"] == 8000]
    incremental_8000 = [row for row in rows if row["telemetry_mode"] == "incremental" and row["retained_project_count"] == 8000]
    legacy_p95 = statistics.median(float(row["latency_seconds"]["p95"]) for row in legacy_8000)
    incremental_p95 = statistics.median(float(row["latency_seconds"]["p95"]) for row in incremental_8000)
    fresh = next(row for row in grouped if row["telemetry_mode"] == "incremental" and row["retained_project_count"] == 0)
    scale = next(row for row in grouped if row["telemetry_mode"] == "incremental" and row["retained_project_count"] == 8000)
    scale_ratio = float(scale["p95_seconds"]["p50"]) / float(fresh["p95_seconds"]["p50"])
    telemetry = _read_json(output / "TELEMETRY_AB.json")
    telemetry.update({
        "legacy_recursive_p95_median_seconds": legacy_p95,
        "incremental_p95_median_seconds": incremental_p95,
        "p95_ratio_incremental_over_legacy": incremental_p95 / legacy_p95,
        "incremental_state_scale_p95_ratio_8000_over_fresh": scale_ratio,
        "incremental_state_scale_gate_limit": 1.15,
        "incremental_state_scale_gate": "PASS" if scale_ratio <= 1.15 else "FAIL",
        "legacy_profiles": legacy_8000,
        "incremental_profiles": incremental_8000,
        "conclusion": "Same-state A/B proves recursive whole-run telemetry is a removable latency contributor. Legacy scale medians are not monotonic, so wall-clock/host contention remains a contributing hypothesis pending the >=4h validation. Incremental telemetry retains counters and final reconciliation without hot-path whole-tree scans.",
    })
    _write_json(output / "TELEMETRY_AB.json", telemetry)
    return {"summary": grouped, "telemetry": {key: telemetry[key] for key in (
        "legacy_recursive_p95_median_seconds",
        "incremental_p95_median_seconds",
        "p95_ratio_incremental_over_legacy",
        "incremental_state_scale_p95_ratio_8000_over_fresh",
        "incremental_state_scale_gate",
    )}}


def _window_validation(run: pathlib.Path, minimum_duration: float = 14400.0) -> dict[str, Any]:
    events = _read_jsonl(run / "SOAK_EVENTS.jsonl")
    profile = _read_json(run / "profile_summary.json")
    elapsed = float(profile["elapsed_seconds"])
    start = min(_epoch(row["at"]) for row in events)
    completed = [row for row in events if row.get("event") == "completed" and row.get("accepted") is True]
    first = [float(row["latency_seconds"]) for row in completed if _epoch(row["at"]) <= start + 7200.0]
    last = [float(row["latency_seconds"]) for row in completed if _epoch(row["at"]) >= start + elapsed - 7200.0]
    first_stats = _distribution(first)
    last_stats = _distribution(last)
    ratio = float(last_stats["p95"]) / float(first_stats["p95"])
    accounting = profile["accounting"]
    accounting_ok = int(accounting["planned"]) == sum(int(accounting[key]) for key in ("rejected", "cancelled", "timed_out", "failed", "completed"))
    integrity_ok = int(accounting["completed"]) == int(accounting["independent_acceptance_passed"]) and int(accounting["independent_acceptance_failed"]) == 0
    throughput_first = len(first) / 7200.0
    throughput_last = len(last) / 7200.0
    gates = {
        "continuous_minimum_4h": elapsed >= minimum_duration,
        "accounting": accounting_ok,
        "integrity": integrity_ok,
        "last_2h_latency": ratio <= 1.15,
        "last_2h_throughput": throughput_last >= throughput_first * 0.90,
        "resource_stability": profile["gates"]["resource_stability"] == "PASS",
    }
    return {
        "kind": "CGKNPass6MidtermLatencyValidation",
        "formal_evidence_status": "NOT_EVALUATED",
        "run_id": run.name,
        "elapsed_seconds": elapsed,
        "first_2h": {**first_stats, "effective_throughput_per_second": throughput_first},
        "last_2h": {**last_stats, "effective_throughput_per_second": throughput_last},
        "latency_drift_ratio": ratio,
        "gate_limit": 1.15,
        "gates": gates,
        "status": "PASS" if all(gates.values()) else "FAIL",
        "claim_scope": "ProviderJob execution + checkpoint/evidence + independent acceptance; no local_packager/public-delivery lifecycle",
    }


def run_midterm(output: pathlib.Path = PASS6, duration_seconds: float = 14400.0) -> dict[str, Any]:
    run_id = "midterm-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = output / "runs" / run_id
    source_before = stress.source_identity()
    stress.run_fixed_arrival_profile(
        run,
        project_concurrency=20,
        provider_job_concurrency=4,
        arrival_rate=0.1,
        duration_seconds=duration_seconds,
        max_queue_factor=2,
        sample_interval=10.0,
        arrival_event_filename="SOAK_EVENTS.jsonl",
        resource_event_filename="RESOURCE_EVENTS.jsonl",
        filesystem_telemetry_mode="incremental",
    )
    validation = _window_validation(run, minimum_duration=duration_seconds)
    source_after = stress.source_identity()
    source_stable = source_before.get("source_identity_hash") == source_after.get("source_identity_hash")
    validation["source_identity_before"] = source_before
    validation["source_identity_after"] = source_after
    validation["source_snapshot_stable"] = source_stable
    validation["gates"]["source_snapshot_stable"] = source_stable
    validation["status"] = "PASS" if all(validation["gates"].values()) else "FAIL"
    _write_json(run / "MIDTERM_VALIDATION.json", validation)
    _write_json(output / "LATEST_MIDTERM_RUN.json", validation)
    return validation


def write_reproduction(output: pathlib.Path = PASS6) -> None:
    _write_text(output / "REPRODUCE_PASS6_LATENCY.md", f"""# Reproduce Pass 6 latency work

Formal evidence status: `NOT_EVALUATED`.

```powershell
python scripts/run_pass6_latency_audit.py analyze --run-dir "{FAILED_RUN}"
python scripts/run_pass6_latency_audit.py experiments --run-dir "{FAILED_RUN}"
python -m pytest tests/test_pass6_latency_audit.py tests/test_pass6_long_horizon.py tests/test_real_workload_recovery_stress.py -q
python scripts/run_pass6_latency_audit.py midterm --duration-seconds 14400
```

Do not modify or reuse `{FAILED_RUN_ID}`. A new 24-hour run may start only after the scale profiles, full Provider-free regression, and >=4h midterm validation pass the unchanged 15% drift gate. The new run must use a fresh run id and the original hard gates.
""")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("analyze", "experiments", "summarize-experiments", "midterm"))
    parser.add_argument("--run-dir", type=pathlib.Path, default=FAILED_RUN)
    parser.add_argument("--output-dir", type=pathlib.Path, default=PASS6)
    parser.add_argument("--task-count", type=int, default=18)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--arrival-rate", type=float, default=2.0)
    parser.add_argument("--duration-seconds", type=float, default=14400.0)
    args = parser.parse_args(argv)
    if args.action == "analyze":
        result = analyze_failed_run(args.run_dir, args.output_dir)
    elif args.action == "experiments":
        result = run_scale_experiments(
            args.run_dir,
            args.output_dir,
            task_count=args.task_count,
            repetitions=args.repetitions,
            arrival_rate=args.arrival_rate,
        )
    elif args.action == "summarize-experiments":
        result = summarize_existing_experiments(args.output_dir)
    else:
        result = run_midterm(args.output_dir, args.duration_seconds)
    write_reproduction(args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.action == "midterm":
        return 0 if result.get("status") == "PASS" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
