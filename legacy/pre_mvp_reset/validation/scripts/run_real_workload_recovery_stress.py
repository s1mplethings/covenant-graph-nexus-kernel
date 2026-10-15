#!/usr/bin/env python3
"""Provider-free real-workload and recovery stress for the existing CGKN path.

This is an engineering evidence harness, not a generation, acceptance,
packaging, or delivery authority.  Project work still enters the production
``run_local_pipeline_impl`` ProviderJob scheduler and managed-worker recovery
still enters the Agent Kit lifecycle implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import signal
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any, Callable

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_KIT_SRC = ROOT / "tools" / "cgkn-agent-kit" / "src"
for import_root in (ROOT, AGENT_KIT_SRC):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from cgkn_agent_kit import core as agent_kit_core
from scripts import run_local_pipeline_impl
from scripts.run_function_stress_pass import (
    _canonical_receipt_sha256,
    _deterministic_load_source,
    evaluate_arrival_task_result,
    source_identity,
)

REQUIRED_FAULTS = (
    "worker_kill",
    "timeout_termination",
    "cancellation_race",
    "duplicate_callback",
    "corrupt_checkpoint_recovery",
    "late_result_rejection",
    "identity_drift_rejection",
)
REQUIRED_RESOURCE_FIELDS = (
    "cpu_percent",
    "rss_bytes",
    "disk_bytes",
    "handle_count",
    "process_count",
    "thread_count",
    "temp_bytes",
    "checkpoint_count",
    "artifact_count",
    "stale_artifact_count",
    "queue_depth",
    "active_workers",
    "completed_work",
    "retry_count",
    "recovery_count",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: pathlib.Path, value: dict[str, Any], lock: threading.Lock | None = None) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if lock is None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload)
        return
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload)


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _directory_metrics(root: pathlib.Path) -> dict[str, int]:
    total = 0
    artifacts = 0
    checkpoints = 0
    stale = 0
    temp_bytes = 0
    try:
        for current, _dirs, files in os.walk(root):
            for name in files:
                try:
                    path = pathlib.Path(current) / name
                    size = path.stat().st_size
                    total += size
                    artifacts += 1
                    lowered = path.as_posix().lower()
                    if "checkpoint" in lowered or "provider_components" in lowered:
                        checkpoints += 1
                    if any(marker in lowered for marker in ("stale", "superseded", "corrupt")):
                        stale += 1
                    if any(part.lower() in {"tmp", "temp"} for part in path.parts):
                        temp_bytes += size
                except OSError:
                    pass
    except OSError:
        pass
    return {
        "disk_bytes": total,
        "artifact_count": artifacts,
        "checkpoint_count": checkpoints,
        "stale_artifact_count": stale,
        "temp_bytes": temp_bytes,
    }


def _add_directory_metrics(*values: dict[str, int]) -> dict[str, int]:
    """Add compatible directory measurements without rescanning their roots."""
    fields = ("disk_bytes", "artifact_count", "checkpoint_count", "stale_artifact_count", "temp_bytes")
    return {field: sum(int(value.get(field, 0) or 0) for value in values) for field in fields}


def _bounded_root_file_metrics(root: pathlib.Path) -> dict[str, int]:
    """Measure only direct run files; completed project trees are accounted separately."""
    result = _add_directory_metrics()
    try:
        files = [path for path in root.iterdir() if path.is_file()]
    except OSError:
        files = []
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        result["disk_bytes"] += size
        result["artifact_count"] += 1
        lowered = path.name.lower()
        if "checkpoint" in lowered:
            result["checkpoint_count"] += 1
        if any(marker in lowered for marker in ("stale", "superseded", "corrupt")):
            result["stale_artifact_count"] += 1
        if any(part.lower() in {"tmp", "temp"} for part in path.parts):
            result["temp_bytes"] += size
    return result


def _directory_bytes(root: pathlib.Path) -> int:
    return _directory_metrics(root)["disk_bytes"]


class ResourceSampler:
    def __init__(
        self,
        output: pathlib.Path,
        state: Callable[[], dict[str, int]],
        interval: float = 0.25,
        event_filename: str = "resource_events.jsonl",
        filesystem_mode: str = "incremental",
        retained_state_roots: list[pathlib.Path] | None = None,
        scan_event_filename: str = "filesystem_scan_events.jsonl",
    ) -> None:
        self.output = output
        self.state = state
        self.interval = max(0.05, float(interval))
        self.event_filename = event_filename
        if filesystem_mode not in {"incremental", "legacy_recursive"}:
            raise ValueError(f"unsupported filesystem telemetry mode: {filesystem_mode}")
        self.filesystem_mode = filesystem_mode
        self.retained_state_roots = [pathlib.Path(path) for path in (retained_state_roots or [])]
        self.scan_event_filename = scan_event_filename
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cgkn-resource-sampler", daemon=True)
        self._disk_thread = (
            threading.Thread(target=self._run_disk, name="cgkn-disk-sampler", daemon=True)
            if filesystem_mode == "legacy_recursive"
            else None
        )
        self._disk_lock = threading.Lock()
        self._accounted_project_roots: set[str] = set()
        retained_metrics = [_directory_metrics(path) for path in self.retained_state_roots]
        self._retained_filesystem_metrics = _add_directory_metrics(*retained_metrics)
        self._completed_project_metrics = _add_directory_metrics()
        self._filesystem_metrics = _add_directory_metrics(
            _bounded_root_file_metrics(self.output),
            self._retained_filesystem_metrics,
        )
        self._filesystem_scan_active = False
        self._filesystem_scan_seconds = 0.0
        self._filesystem_scan_count = 0
        self._disk_refresh_interval = max(5.0, self.interval * 10)
        try:
            import psutil  # type: ignore
        except ImportError:
            psutil = None
        self.psutil = psutil
        self.process = psutil.Process() if psutil is not None else None
        if self.process is not None:
            self.process.cpu_percent(interval=None)
            psutil.cpu_percent(interval=None)

    def start(self) -> None:
        if self._disk_thread is not None:
            self._disk_thread.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, self.interval * 4))
        if self._disk_thread is not None:
            self._disk_thread.join(timeout=10.0)
        scan_started = time.monotonic()
        exact_metrics = _directory_metrics(self.output)
        retained_metrics = [_directory_metrics(path) for path in self.retained_state_roots]
        with self._disk_lock:
            self._filesystem_metrics = _add_directory_metrics(exact_metrics, *retained_metrics)
            self._filesystem_scan_seconds = time.monotonic() - scan_started
            self._filesystem_scan_count += 1
        self._sample(phase="shutdown_final")

    def record_completed_project(self, project_root: pathlib.Path) -> None:
        """Account one immutable completed project with work proportional to that project only."""
        if self.filesystem_mode != "incremental":
            return
        identity = str(project_root.resolve())
        with self._disk_lock:
            if identity in self._accounted_project_roots:
                return
            self._accounted_project_roots.add(identity)
        measured = _directory_metrics(project_root)
        with self._disk_lock:
            self._completed_project_metrics = _add_directory_metrics(
                self._completed_project_metrics,
                measured,
            )
            self._filesystem_metrics = _add_directory_metrics(
                _bounded_root_file_metrics(self.output),
                self._retained_filesystem_metrics,
                self._completed_project_metrics,
            )

    def _sample(self, *, phase: str = "active") -> None:
        snapshot = self.state()
        with self._disk_lock:
            if self.filesystem_mode == "incremental":
                self._filesystem_metrics = _add_directory_metrics(
                    _bounded_root_file_metrics(self.output),
                    self._retained_filesystem_metrics,
                    self._completed_project_metrics,
                )
            filesystem_metrics = dict(self._filesystem_metrics)
            filesystem_scan_active = self._filesystem_scan_active
            filesystem_scan_seconds = self._filesystem_scan_seconds
            filesystem_scan_count = self._filesystem_scan_count
        row: dict[str, Any] = {
            "at": now(),
            "monotonic": time.monotonic(),
            "phase": phase,
            **filesystem_metrics,
            **snapshot,
            "filesystem_mode": self.filesystem_mode,
            "filesystem_scan_active": filesystem_scan_active,
            "filesystem_scan_seconds": filesystem_scan_seconds,
            "filesystem_scan_count": filesystem_scan_count,
        }
        if self.process is None:
            row.update({"cpu_percent": None, "rss_bytes": None, "handle_count": None, "process_count": None, "thread_count": None})
        else:
            processes = [self.process]
            try:
                processes.extend(self.process.children(recursive=True))
            except Exception:
                pass
            cpu = 0.0
            rss = 0
            handles = 0
            threads = 0
            live = 0
            for process in processes:
                try:
                    cpu += float(process.cpu_percent(interval=None))
                    rss += int(process.memory_info().rss)
                    if hasattr(process, "num_handles"):
                        handles += int(process.num_handles())
                    elif hasattr(process, "num_fds"):
                        handles += int(process.num_fds())
                    threads += int(process.num_threads())
                    live += 1
                except Exception:
                    continue
            host_cpu = None
            available_memory = None
            disk_read_bytes = None
            disk_write_bytes = None
            disk_read_time_ms = None
            disk_write_time_ms = None
            disk_busy_time_ms = None
            try:
                host_cpu = float(self.psutil.cpu_percent(interval=None))
                available_memory = int(self.psutil.virtual_memory().available)
                disk = self.psutil.disk_io_counters()
                if disk is not None:
                    disk_read_bytes = int(getattr(disk, "read_bytes", 0))
                    disk_write_bytes = int(getattr(disk, "write_bytes", 0))
                    disk_read_time_ms = int(getattr(disk, "read_time", 0))
                    disk_write_time_ms = int(getattr(disk, "write_time", 0))
                    busy = getattr(disk, "busy_time", None)
                    disk_busy_time_ms = int(busy) if busy is not None else None
            except Exception:
                pass
            row.update({
                "cpu_percent": cpu,
                "rss_bytes": rss,
                "handle_count": handles,
                "process_count": live,
                "thread_count": threads,
                "host_cpu_percent": host_cpu,
                "available_memory_bytes": available_memory,
                "host_disk_read_bytes": disk_read_bytes,
                "host_disk_write_bytes": disk_write_bytes,
                "host_disk_read_time_ms": disk_read_time_ms,
                "host_disk_write_time_ms": disk_write_time_ms,
                "host_disk_busy_time_ms": disk_busy_time_ms,
            })
        self.samples.append(row)
        append_jsonl(self.output / self.event_filename, row)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval)

    def _run_disk(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            with self._disk_lock:
                self._filesystem_scan_active = True
            measured = _add_directory_metrics(
                _directory_metrics(self.output),
                *[_directory_metrics(path) for path in self.retained_state_roots],
            )
            finished = time.monotonic()
            with self._disk_lock:
                self._filesystem_metrics = measured
                self._filesystem_scan_active = False
                self._filesystem_scan_seconds = finished - started
                self._filesystem_scan_count += 1
                scan_count = self._filesystem_scan_count
            append_jsonl(
                self.output / self.scan_event_filename,
                {
                    "at": now(),
                    "event": "filesystem_recursive_scan_completed",
                    "mode": self.filesystem_mode,
                    "started_monotonic": started,
                    "finished_monotonic": finished,
                    "duration_seconds": finished - started,
                    "scan_count": scan_count,
                    **measured,
                },
            )
            self._stop.wait(self._disk_refresh_interval)

    def summary(self) -> dict[str, Any]:
        def numeric(field: str) -> list[float]:
            return [float(row[field]) for row in self.samples if isinstance(row.get(field), (int, float))]

        active_samples = [row for row in self.samples if row.get("phase", "active") == "active"]
        gaps = [
            float(current["monotonic"]) - float(previous["monotonic"])
            for previous, current in zip(active_samples, active_samples[1:])
        ]
        result: dict[str, Any] = {
            "sample_count": len(self.samples),
            "active_sample_count": len(active_samples),
            "requested_interval_seconds": self.interval,
            "observed_interval_seconds": {
                "p50": percentile(gaps, 0.50),
                "p95": percentile(gaps, 0.95),
                "p99": percentile(gaps, 0.99),
                "max": max(gaps) if gaps else None,
            },
            "disk_refresh_interval_seconds": self._disk_refresh_interval,
            "filesystem_mode": self.filesystem_mode,
            "filesystem_scan_count": self._filesystem_scan_count,
            "last_filesystem_scan_seconds": self._filesystem_scan_seconds,
        }
        for field in REQUIRED_RESOURCE_FIELDS:
            values = numeric(field)
            result[field] = {
                "min": min(values) if values else None,
                "max": max(values) if values else None,
                "mean": statistics.fmean(values) if values else None,
                "first": values[0] if values else None,
                "last": values[-1] if values else None,
                "delta": values[-1] - values[0] if values else None,
            }
        return result


def managed_worker(args: argparse.Namespace) -> int:
    """Small real process used only to exercise Agent Kit lifecycle semantics."""
    state_path = pathlib.Path(args.generation_job_state)
    artifact_dir = state_path.parent
    with agent_kit_core.generation_job_lock(artifact_dir):
        state = agent_kit_core.read_json(state_path)
        if state.get("job_id") != args.generation_job_id or state.get("attempt_id") != args.generation_attempt_id:
            return 17
        state.update(
            {
                "state": "RUNNING",
                "run_id": args.worker_run_id,
                "process_id": os.getpid(),
                "updated_at": now(),
                "revision": int(state.get("revision", 0) or 0) + 1,
            }
        )
        agent_kit_core.write_json(state_path, state)
    time.sleep(max(0.0, args.worker_sleep))
    result_path = pathlib.Path(args.result)
    result = {
        "kind": "CGKNStressManagedWorkerResult",
        "generation_job_id": args.generation_job_id,
        "generation_attempt_id": args.generation_attempt_id,
        "run_id": args.worker_run_id,
        "candidate_hash": hashlib.sha256(args.worker_run_id.encode("utf-8")).hexdigest(),
        "formal_evidence_status": "NOT_EVALUATED",
    }
    agent_kit_core.write_json(result_path, result)
    with agent_kit_core.generation_job_lock(artifact_dir):
        state = agent_kit_core.read_json(state_path)
        if state.get("job_id") == args.generation_job_id and state.get("attempt_id") == args.generation_attempt_id:
            state.update(
                {
                    "state": "COMPLETE",
                    "terminal_reason": "",
                    "updated_at": now(),
                    "revision": int(state.get("revision", 0) or 0) + 1,
                }
            )
            agent_kit_core.write_json(state_path, state)
    return 0


def _worker_command(sleep_seconds: float, run_id: str) -> list[str]:
    return [
        sys.executable,
        str(pathlib.Path(__file__).resolve()),
        "--managed-worker",
        "--worker-sleep",
        str(sleep_seconds),
        "--worker-run-id",
        run_id,
    ]


def _wait_for(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _terminate_pid(pid: int) -> None:
    try:
        import psutil  # type: ignore

        process = psutil.Process(pid)
        process.kill()
        process.wait(timeout=5)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def _manifest(file_count: int = 8) -> list[dict[str, Any]]:
    return [
        {
            "path": f"src/unit_{index:02d}.py",
            "purpose": f"bounded real workload unit {index}",
            "dependencies": [f"src/unit_{index - 2:02d}.py"] if index >= 2 else [],
            "estimated_complexity": "medium",
            "expected_content_sha256": hashlib.sha256(_deterministic_load_source(index).encode("utf-8")).hexdigest(),
        }
        for index in range(file_count)
    ]


class DeterministicProvider:
    def __init__(self, manifest: list[dict[str, Any]], delay: float = 0.002) -> None:
        self.manifest = manifest
        self.delay = delay
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.calls = 0

    def __call__(self, messages: list[dict[str, Any]], model: str, timeout: int, **kwargs: Any) -> str:
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": self.manifest})
        payloads: list[dict[str, Any]] = []
        for message in reversed(messages):
            try:
                value = json.loads(message["content"])
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                payloads.append(value)
        targets = next(
            (
                list(payload.get("provider_job", {}).get("emission_paths", []))
                for payload in payloads
                if payload.get("provider_job", {}).get("emission_paths")
            ),
            [str(kwargs.get("target_file", ""))],
        )
        with self.lock:
            self.active += 1
            self.calls += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            files = [
                {
                    "path": path,
                    "content": _deterministic_load_source(int(pathlib.PurePosixPath(path).stem.rsplit("_", 1)[-1])),
                }
                for path in targets
            ]
            return json.dumps({"files": files} if any("provider_job" in payload for payload in payloads) else files[0])
        finally:
            with self.lock:
                self.active -= 1


def execute_project(root: pathlib.Path, task_id: str, manifest: list[dict[str, Any]]) -> dict[str, Any]:
    component = {
        "id": "backend",
        "required_paths": [str(row["path"]) for row in manifest],
        "minimum_file_count": len(manifest),
    }
    pipeline = {"components": [component], "merge_policy": {"required_final_files": component["required_paths"]}}
    result = run_local_pipeline_impl.provider_generate_project_component_split(
        goal=f"provider-free real workload {task_id}",
        component=component,
        component_pipeline=pipeline,
        prior_manifest=[],
        prior_files=[],
        repair_errors=[],
        model="deterministic-provider-boundary",
        timeout=30,
        deadline=None,
        checkpoint_dir=root / "provider_components",
        run_dir=root,
        spec_hash=f"spec-{task_id}",
        phase_log_path=root / "provider_phase_log.jsonl",
        routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
        split_reason="provider_free_real_workload",
        original_prompt_chars=0,
    )
    acceptance = evaluate_arrival_task_result(result, manifest)
    return {"accepted": bool(acceptance["accepted"]), "acceptance": acceptance, "files": len(result.get("files", []))}


def run_fault_suite(output: pathlib.Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    events = output / "fault_events.jsonl"
    observations: dict[str, bool] = {name: False for name in REQUIRED_FAULTS}
    details: dict[str, Any] = {}

    killed_dir = output / "worker-kill"
    killed_dir.mkdir(parents=True, exist_ok=True)
    killed = agent_kit_core.start_generation_job(
        _worker_command(60.0, "run-killed"), cgkn_root=ROOT, artifact_dir=killed_dir, start_timeout=2.0
    )
    killed_pid = int(killed.get("process_id", 0) or 0)
    append_jsonl(events, {"at": now(), "event": "worker_started", "pid": killed_pid, "job_id": killed.get("job_id")})
    alive_before = bool(agent_kit_core._process_liveness(killed_pid).get("alive"))
    _terminate_pid(killed_pid)
    dead_after = _wait_for(lambda: not agent_kit_core._process_liveness(killed_pid).get("alive"), 5.0)
    killed_status = agent_kit_core.generation_job_status(killed_dir)
    observations["worker_kill"] = alive_before and dead_after and killed_status.get("terminal_reason") == "WORKER_PROCESS_NOT_ALIVE"
    details["worker_kill"] = {"pid": killed_pid, "alive_before": alive_before, "dead_after": dead_after, "status": killed_status}
    append_jsonl(events, {"at": now(), "event": "worker_killed", "pid": killed_pid, "observed": observations["worker_kill"]})

    timeout_dir = output / "timeout"
    timeout_dir.mkdir(parents=True, exist_ok=True)
    timeout_job = agent_kit_core.start_generation_job(
        _worker_command(60.0, "run-timeout"), cgkn_root=ROOT, artifact_dir=timeout_dir, start_timeout=1.0
    )
    timeout_pid = int(timeout_job.get("process_id", 0) or 0)
    timeout_started = time.monotonic()
    deadline_seconds = 0.25
    while time.monotonic() - timeout_started < deadline_seconds:
        time.sleep(0.01)
    _terminate_pid(timeout_pid)
    timeout_dead = _wait_for(lambda: not agent_kit_core._process_liveness(timeout_pid).get("alive"), 5.0)
    timeout_status = agent_kit_core.generation_job_status(timeout_dir)
    observations["timeout_termination"] = timeout_dead and time.monotonic() - timeout_started >= deadline_seconds and timeout_status.get("execution_classification") == "worker_exit"
    details["timeout_termination"] = {"pid": timeout_pid, "deadline_seconds": deadline_seconds, "status": timeout_status}
    append_jsonl(events, {"at": now(), "event": "timeout_terminated", "pid": timeout_pid, "observed": observations["timeout_termination"]})

    race_dir = output / "cancel-race"
    race_dir.mkdir(parents=True, exist_ok=True)
    race_job = agent_kit_core.start_generation_job(
        _worker_command(2.0, "run-cancel"), cgkn_root=ROOT, artifact_dir=race_dir, start_timeout=1.0
    )
    duplicate = agent_kit_core.start_generation_job(
        _worker_command(2.0, "run-duplicate"), cgkn_root=ROOT, artifact_dir=race_dir, start_timeout=0.0
    )
    observations["duplicate_callback"] = bool(duplicate.get("deduplicated")) and duplicate.get("job_id") == race_job.get("job_id")
    barrier = threading.Barrier(2)
    cancel_result: dict[str, Any] = {}

    def cancel() -> None:
        barrier.wait()
        cancel_result.update(agent_kit_core.cancel_generation_job(race_dir, expected_job_id=str(race_job["job_id"])))

    cancel_thread = threading.Thread(target=cancel, name="cgkn-cancel-race")
    cancel_thread.start()
    barrier.wait()
    cancel_thread.join(timeout=10)
    cancelled = agent_kit_core.generation_job_status(race_dir)
    observations["cancellation_race"] = cancelled.get("state") == "CANCELLED" and not cancelled.get("candidate_present")
    old_result_path = pathlib.Path(str(race_job["result_path"]))
    agent_kit_core.write_json(
        old_result_path,
        {
            "generation_job_id": race_job["job_id"],
            "generation_attempt_id": race_job["attempt_id"],
            "run_id": "run-cancel",
            "candidate_hash": "late-result",
        },
    )
    late_status = agent_kit_core.generation_job_status(race_dir)
    observations["late_result_rejection"] = late_status.get("state") == "CANCELLED" and not late_status.get("candidate_present")
    details["cancel_duplicate_late"] = {"initial": race_job, "duplicate": duplicate, "cancel": cancel_result, "late_status": late_status}

    replacement = agent_kit_core.start_generation_job(
        _worker_command(0.02, "run-replacement"), cgkn_root=ROOT, artifact_dir=race_dir, start_timeout=3.0
    )
    _wait_for(lambda: bool(agent_kit_core.generation_job_status(race_dir).get("candidate_present")), 5.0)
    replacement_status = agent_kit_core.generation_job_status(race_dir)
    replacement_result_path = pathlib.Path(str(replacement["result_path"]))
    admitted_before_drift = bool(replacement_status.get("candidate_present"))
    agent_kit_core.write_json(
        replacement_result_path,
        {
            "generation_job_id": race_job["job_id"],
            "generation_attempt_id": race_job["attempt_id"],
            "run_id": "run-replacement",
            "candidate_hash": "identity-drift",
        },
    )
    drift_status = agent_kit_core.generation_job_status(race_dir)
    observations["identity_drift_rejection"] = admitted_before_drift and not drift_status.get("candidate_present")
    details["identity_drift"] = {"replacement": replacement_status, "after_drift": drift_status}

    checkpoint_root = output / "checkpoint-recovery"
    manifest = _manifest()
    provider = DeterministicProvider(manifest)
    original_provider = run_local_pipeline_impl.provider_text
    run_local_pipeline_impl.provider_text = provider
    try:
        first = execute_project(checkpoint_root, "checkpoint", manifest)
        calls_before = provider.calls
        component_checkpoint = checkpoint_root / "provider_components" / "backend.json"
        split_checkpoint = checkpoint_root / "provider_components" / "split_files" / "backend" / "src_unit_03.py.json"
        component_checkpoint.write_text("{corrupt", encoding="utf-8")
        split_checkpoint.write_text("{corrupt", encoding="utf-8")
        second = execute_project(checkpoint_root, "checkpoint", manifest)
        recovery_calls = provider.calls - calls_before
    finally:
        run_local_pipeline_impl.provider_text = original_provider
    observations["corrupt_checkpoint_recovery"] = bool(first["accepted"] and second["accepted"] and recovery_calls >= 1)
    details["corrupt_checkpoint_recovery"] = {"first": first, "second": second, "recovery_provider_calls": recovery_calls}
    append_jsonl(events, {"at": now(), "event": "fault_suite_complete", "observations": observations})

    report = {
        "kind": "CGKNRealRecoveryFaultReport",
        "formal_evidence_status": "NOT_EVALUATED",
        "observations": observations,
        "details": details,
        "status": "PASS" if all(observations.values()) else "FAIL",
    }
    write_json(output / "fault_report.json", report)
    return report


def run_fixed_arrival_profile(
    output: pathlib.Path,
    *,
    project_concurrency: int,
    provider_job_concurrency: int,
    arrival_rate: float,
    duration_seconds: float,
    max_queue_factor: int = 2,
    sample_interval: float = 0.25,
    arrival_event_filename: str = "arrival_events.jsonl",
    resource_event_filename: str = "resource_events.jsonl",
    filesystem_telemetry_mode: str = "incremental",
    retained_state_roots: list[pathlib.Path] | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    event_path = output / arrival_event_filename
    event_lock = threading.Lock()
    state_lock = threading.Lock()
    counters = {key: 0 for key in (
        "planned", "attempted_submissions", "accepted_submissions", "submitted", "rejected", "cancelled",
        "timed_out", "worker_process_failures", "failed", "execution_completions", "completed",
        "independent_acceptance_passed", "independent_acceptance_failed", "retries", "recoveries",
        "duplicate_callbacks", "stale_late_result_rejections", "checkpoint_repairs", "checkpoint_rejections",
        "final_delivery_count", "duplicate_delivery_count",
    )}
    live = {"queue_depth": 0, "in_flight": 0, "active_workers": 0, "completed": 0, "completed_work": 0, "retry_count": 0, "recovery_count": 0}
    latencies: list[float] = []
    manifest = _manifest()
    provider = DeterministicProvider(manifest)
    original_provider = run_local_pipeline_impl.provider_text
    original_parallelism = os.environ.get("CGKN_PROVIDER_PARALLELISM")
    os.environ["CGKN_PROVIDER_PARALLELISM"] = str(provider_job_concurrency)
    run_local_pipeline_impl.provider_text = provider

    def state() -> dict[str, int]:
        with state_lock:
            return dict(live)

    sampler = ResourceSampler(
        output,
        state,
        interval=sample_interval,
        event_filename=resource_event_filename,
        filesystem_mode=filesystem_telemetry_mode,
        retained_state_roots=retained_state_roots,
    )
    futures: dict[Future[dict[str, Any]], tuple[str, float]] = {}
    pending: set[Future[dict[str, Any]]] = set()
    finished_times: dict[Future[dict[str, Any]], float] = {}
    started = time.monotonic()
    planned_tasks = max(1, int(math.floor(duration_seconds * arrival_rate)) + 1)
    queue_limit = max(project_concurrency, project_concurrency * max_queue_factor)

    def reap(done: set[Future[dict[str, Any]]]) -> None:
        for future in done:
            task_id, submitted_at = futures[future]
            with state_lock:
                finished_at = finished_times.pop(future, time.monotonic())
            latency = finished_at - submitted_at
            latencies.append(latency)
            try:
                result = future.result()
            except TimeoutError as exc:
                terminal = "timed_out"
                payload: dict[str, Any] = {"error": f"{type(exc).__name__}: {exc}"}
            except Exception as exc:
                terminal = "failed"
                payload = {"error": f"{type(exc).__name__}: {exc}"}
            else:
                terminal = "completed"
                payload = result
            if terminal == "completed":
                sampler.record_completed_project(output / "projects" / task_id)
            with state_lock:
                counters["execution_completions"] += 1
                counters[terminal] += 1
                if terminal == "completed" and bool(payload.get("accepted")):
                    counters["independent_acceptance_passed"] += 1
                elif terminal == "completed":
                    counters["independent_acceptance_failed"] += 1
                live["completed"] = counters["completed"]
                live["completed_work"] = counters["execution_completions"]
                live["in_flight"] = len(pending)
                live["active_workers"] = min(len(pending), project_concurrency)
                live["queue_depth"] = max(0, len(pending) - project_concurrency)
            append_jsonl(event_path, {"at": now(), "event": terminal, "task_id": task_id, "latency_seconds": latency, **payload}, event_lock)
            # A retained Future owns a threading.Condition; on Windows that can
            # retain one kernel handle.  Long-lived supervisors must not keep a
            # completed project's Future merely for historical accounting.
            futures.pop(future, None)

    def record_finished(future: Future[dict[str, Any]]) -> None:
        with state_lock:
            finished_times[future] = time.monotonic()

    sampler.start()
    try:
        with ThreadPoolExecutor(max_workers=project_concurrency, thread_name_prefix="cgkn-real-project") as pool:
            for index in range(planned_tasks):
                scheduled = started + index / arrival_rate
                remaining = scheduled - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                completed_now = {future for future in pending if future.done()}
                pending.difference_update(completed_now)
                reap(completed_now)
                task_id = f"project-{index:06d}"
                with state_lock:
                    counters["planned"] += 1
                    counters["attempted_submissions"] += 1
                    outstanding = len(pending)
                    live["queue_depth"] = max(0, outstanding - project_concurrency)
                    live["in_flight"] = outstanding
                append_jsonl(event_path, {"at": now(), "event": "planned", "task_id": task_id, "scheduled_offset_seconds": index / arrival_rate}, event_lock)
                if outstanding >= queue_limit:
                    with state_lock:
                        counters["rejected"] += 1
                    append_jsonl(event_path, {"at": now(), "event": "rejected", "task_id": task_id, "reason": "bounded_queue", "outstanding": outstanding}, event_lock)
                    continue
                submitted_at = time.monotonic()
                future = pool.submit(execute_project, output / "projects" / task_id, task_id, manifest)
                futures[future] = (task_id, submitted_at)
                pending.add(future)
                future.add_done_callback(record_finished)
                with state_lock:
                    counters["submitted"] += 1
                    counters["accepted_submissions"] += 1
                append_jsonl(event_path, {"at": now(), "event": "submitted", "task_id": task_id, "submission_lag_seconds": submitted_at - scheduled}, event_lock)

            while pending:
                done, still_pending = wait(pending, timeout=0.1, return_when="FIRST_COMPLETED")
                pending = set(still_pending)
                reap(set(done))
    finally:
        sampler.stop()
        run_local_pipeline_impl.provider_text = original_provider
        if original_parallelism is None:
            os.environ.pop("CGKN_PROVIDER_PARALLELISM", None)
        else:
            os.environ["CGKN_PROVIDER_PARALLELISM"] = original_parallelism

    elapsed = time.monotonic() - started
    terminal_count = sum(counters[key] for key in ("rejected", "cancelled", "timed_out", "failed", "completed"))
    accounting_ok = terminal_count == counters["planned"]
    acceptance_ok = counters["completed"] > 0 and counters["independent_acceptance_passed"] == counters["completed"]
    telemetry = sampler.summary()
    minimum_samples = max(2, int(duration_seconds / max(sample_interval * 4, 0.2)))
    observed_gap_max = telemetry.get("observed_interval_seconds", {}).get("max")
    telemetry_ok = (
        telemetry["sample_count"] >= minimum_samples
        and isinstance(observed_gap_max, (int, float))
        and observed_gap_max <= max(10.0, sample_interval * 10)
        and all(telemetry[field]["max"] is not None for field in REQUIRED_RESOURCE_FIELDS)
    )
    handle_delta = telemetry.get("handle_count", {}).get("delta")
    rss_delta = telemetry.get("rss_bytes", {}).get("delta")
    handle_growth_limit = max(64, project_concurrency * 4)
    rss_growth_limit = max(128 * 1024 * 1024, project_concurrency * 1024 * 1024)
    resource_stability_ok = (
        isinstance(handle_delta, (int, float))
        and handle_delta <= handle_growth_limit
        and isinstance(rss_delta, (int, float))
        and rss_delta <= rss_growth_limit
    )
    duration_ok = elapsed + max(0.05, 1.0 / arrival_rate) >= duration_seconds
    report = {
        "kind": "CGKNFixedArrivalRealWorkloadProfile",
        "formal_evidence_status": "NOT_EVALUATED",
        "configuration": {
            "project_concurrency": project_concurrency,
            "provider_job_concurrency": provider_job_concurrency,
            "arrival_rate_per_second": arrival_rate,
            "requested_duration_seconds": duration_seconds,
            "planned_tasks": planned_tasks,
            "queue_limit": queue_limit,
            "filesystem_telemetry_mode": filesystem_telemetry_mode,
            "retained_state_root_count": len(retained_state_roots or []),
        },
        "accounting": counters,
        "terminal_count": terminal_count,
        "denominator_balanced": accounting_ok,
        "elapsed_seconds": elapsed,
        "latency_seconds": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "samples": len(latencies),
        },
        "effective_throughput_per_second": counters["independent_acceptance_passed"] / elapsed if elapsed else 0.0,
        "provider": {"calls": provider.calls, "peak_concurrency": provider.peak},
        "resources": telemetry,
        "resource_stability_limits": {
            "max_handle_growth": handle_growth_limit,
            "max_rss_growth_bytes": rss_growth_limit,
            "minimum_samples": minimum_samples,
            "max_sample_gap_seconds": max(10.0, sample_interval * 10),
        },
        "gates": {
            "accounting": "PASS" if accounting_ok else "FAIL",
            "independent_acceptance": "PASS" if acceptance_ok else "FAIL",
            "resource_telemetry": "PASS" if telemetry_ok else "FAIL",
            "resource_stability": "PASS" if resource_stability_ok else "FAIL",
            "duration": "PASS" if duration_ok else "FAIL",
        },
        "status": "PASS" if accounting_ok and acceptance_ok and telemetry_ok and resource_stability_ok and duration_ok else "FAIL",
    }
    write_json(output / "profile_summary.json", report)
    return report


def validate_evidence(summary: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    faults = summary.get("faults", {})
    observations = faults.get("observations", {}) if isinstance(faults, dict) else {}
    for name in REQUIRED_FAULTS:
        if observations.get(name) is not True:
            errors.append(f"fault_not_observed:{name}")
    profiles = summary.get("profiles", [])
    if not isinstance(profiles, list) or not profiles:
        errors.append("profiles_missing")
        profiles = []
    for index, profile in enumerate(profiles):
        accounting = profile.get("accounting", {})
        terminal = sum(int(accounting.get(key, 0) or 0) for key in ("rejected", "cancelled", "timed_out", "failed", "completed"))
        if terminal != int(accounting.get("planned", -1)):
            errors.append(f"profile_{index}:denominator_unbalanced")
        if int(accounting.get("completed", 0)) != int(accounting.get("independent_acceptance_passed", -1)):
            errors.append(f"profile_{index}:independent_acceptance_incomplete")
        resources = profile.get("resources", {})
        limits = profile.get("resource_stability_limits", {})
        minimum_samples = int(limits.get("minimum_samples", 2) or 2)
        if int(resources.get("sample_count", 0) or 0) < minimum_samples:
            errors.append(f"profile_{index}:resource_samples_missing")
        observed_gap = resources.get("observed_interval_seconds", {}).get("max")
        if not isinstance(observed_gap, (int, float)) or observed_gap > float(limits.get("max_sample_gap_seconds", 0) or 0):
            errors.append(f"profile_{index}:resource_sample_gap_exceeded")
        for field in REQUIRED_RESOURCE_FIELDS:
            if not isinstance(resources.get(field), dict) or resources[field].get("max") is None:
                errors.append(f"profile_{index}:resource_missing:{field}")
        handle_delta = resources.get("handle_count", {}).get("delta")
        rss_delta = resources.get("rss_bytes", {}).get("delta")
        if not isinstance(handle_delta, (int, float)) or handle_delta > float(limits.get("max_handle_growth", 0) or 0):
            errors.append(f"profile_{index}:handle_growth_unbounded")
        if not isinstance(rss_delta, (int, float)) or rss_delta > float(limits.get("max_rss_growth_bytes", 0) or 0):
            errors.append(f"profile_{index}:rss_growth_unbounded")
        requested = float(profile.get("configuration", {}).get("requested_duration_seconds", 0) or 0)
        elapsed = float(profile.get("elapsed_seconds", 0) or 0)
        rate = float(profile.get("configuration", {}).get("arrival_rate_per_second", 0) or 0)
        tolerance = max(0.05, 1.0 / rate) if rate > 0 else 0.05
        if elapsed + tolerance < requested:
            errors.append(f"profile_{index}:duration_short")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def run_campaign(
    output: pathlib.Path,
    *,
    short_run_seconds: float,
    short_repetitions: int,
    steady_seconds: float,
    include_steady: bool,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    identity_before = source_identity()
    write_json(output / "source_identity.before.json", identity_before)
    faults = run_fault_suite(output / "faults")
    profiles: list[dict[str, Any]] = []
    matrix = ((1, 1), (5, 2), (10, 4), (20, 8))
    for repetition in range(1, short_repetitions + 1):
        for project_concurrency, provider_concurrency in matrix:
            profile = run_fixed_arrival_profile(
                output / "short" / f"run-{repetition:02d}-p{project_concurrency}-j{provider_concurrency}",
                project_concurrency=project_concurrency,
                provider_job_concurrency=provider_concurrency,
                arrival_rate=max(2.0, float(project_concurrency)),
                duration_seconds=short_run_seconds,
            )
            profile["phase"] = "short"
            profile["repetition"] = repetition
            profiles.append(profile)
    short_gate = faults.get("status") == "PASS" and all(profile.get("status") == "PASS" for profile in profiles)
    steady: dict[str, Any] = {"status": "NOT_EVALUATED", "reason": "not_requested"}
    if include_steady and short_gate:
        steady = run_fixed_arrival_profile(
            output / "steady-30m",
            project_concurrency=20,
            provider_job_concurrency=4,
            arrival_rate=1.0,
            duration_seconds=steady_seconds,
            sample_interval=1.0,
        )
        steady["phase"] = "steady"
        profiles.append(steady)
    elif include_steady:
        steady = {"status": "NOT_EVALUATED", "reason": "short_correctness_or_resource_gate_failed"}
    identity_after = source_identity()
    write_json(output / "source_identity.after.json", identity_after)
    same_source = identity_before.get("head") == identity_after.get("head") and identity_before.get("status_porcelain") == identity_after.get("status_porcelain")
    summary = {
        "kind": "CGKNRealWorkloadRecoveryStressCampaign",
        "formal_evidence_status": "NOT_EVALUATED",
        "authority": "engineering_test_only",
        "created_at": now(),
        "source_identity_before": identity_before,
        "source_identity_after": identity_after,
        "source_identity_stable": same_source,
        "faults": faults,
        "profiles": profiles,
        "short_gate": "PASS" if short_gate else "FAIL",
        "steady": steady,
        "soak_24h": {"status": "NOT_EVALUATED", "reason": "not_run"},
    }
    validation = validate_evidence(summary)
    summary["independent_validation"] = validation
    summary["status"] = "PASS" if validation["status"] == "PASS" and same_source and (not include_steady or steady.get("status") == "PASS") else "FAIL"
    write_json(output / "campaign_summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=pathlib.Path, default=ROOT / "artifacts" / "real_workload_recovery" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--short-run-seconds", type=float, default=3.0)
    parser.add_argument("--short-repetitions", type=int, default=3)
    parser.add_argument("--steady-seconds", type=float, default=1800.0)
    parser.add_argument("--include-steady", action="store_true")
    parser.add_argument("--managed-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-sleep", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--worker-run-id", default="stress-worker", help=argparse.SUPPRESS)
    parser.add_argument("--result", default="", help=argparse.SUPPRESS)
    parser.add_argument("--generation-job-state", default="", help=argparse.SUPPRESS)
    parser.add_argument("--generation-job-id", default="", help=argparse.SUPPRESS)
    parser.add_argument("--generation-attempt-id", default="", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.managed_worker:
        return managed_worker(args)
    summary = run_campaign(
        args.output_dir.resolve(),
        short_run_seconds=max(0.2, args.short_run_seconds),
        short_repetitions=max(1, args.short_repetitions),
        steady_seconds=max(1.0, args.steady_seconds),
        include_steady=bool(args.include_steady),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
