#!/usr/bin/env python3
"""Reproducible engineering stress entry for the existing CGKN authorities.

This runner creates no generation, scheduling, evidence, packaging, or delivery
path.  It measures the canonical WorkNode/ProviderJob validators and invokes
the repository's real pytest-covered scheduler, recovery, surrogate, evidence,
and delivery entrypoints.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.provider_jobs import ProviderJob, validate_jobs
from scripts.work_nodes import WorkNode, validate_work_nodes
from scripts import run_local_pipeline_impl


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20
    )
    return (result.stdout if result.returncode == 0 else result.stderr).strip()


def source_identity() -> dict[str, Any]:
    return {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "status_porcelain": _git("status", "--short"),
        "python": sys.version,
        "platform": platform.platform(),
        "created_at": _now(),
    }


def validator_measurements(sizes: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for count in sizes:
        nodes = [
            WorkNode(
                f"node_{index:06d}",
                "stress",
                depends_on=(
                    (f"node_{index + 1:06d}",) if index < count - 1 else ()
                ),
                owns=(f"src/{index}.py",),
            )
            for index in range(count)
        ]
        jobs = [
            ProviderJob(
                node.id,
                node.goal,
                depends_on=node.depends_on,
                owns=node.owns,
            )
            for node in nodes
        ]
        for name, values, validator in (
            ("work_nodes", nodes, validate_work_nodes),
            ("provider_jobs", jobs, validate_jobs),
        ):
            started = time.perf_counter()
            errors = validator(values)
            elapsed = time.perf_counter() - started
            rows.append(
                {
                    "case": f"{name}_forward_chain_{count}",
                    "node_count": count,
                    "elapsed_seconds": elapsed,
                    "error_count": len(errors),
                    "status": "PASS" if not errors else "FAIL",
                }
            )
    return rows


def provider_job_arrival_load(
    output_dir: pathlib.Path,
    *,
    planned_tasks: int = 18,
    project_workers: int = 3,
    overload_limit: int = 5,
    arrival_interval: float = 0.002,
) -> dict[str, Any]:
    """Drive the canonical split ProviderJob scheduler under bounded synthetic load."""
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None

    def resource_snapshot() -> dict[str, Any]:
        disk_bytes = sum(path.stat().st_size for path in output_dir.rglob("*") if path.is_file())
        if psutil is None:
            return {"available": False, "disk_bytes": disk_bytes, "reason": "psutil_not_installed", "gpu": "unavailable"}
        process = psutil.Process()
        children = process.children(recursive=True)
        memory = process.memory_info()
        cpu = process.cpu_times()
        return {
            "available": True,
            "rss_bytes": int(memory.rss),
            "cpu_user_seconds": float(cpu.user),
            "cpu_system_seconds": float(cpu.system),
            "child_process_count": len(children),
            "process_count": 1 + len(children),
            "handle_count": int(process.num_handles()) if hasattr(process, "num_handles") else None,
            "fd_count": int(process.num_fds()) if hasattr(process, "num_fds") else None,
            "disk_bytes": disk_bytes,
            "gpu": "unavailable_no_task_scoped_gpu_telemetry",
        }

    resource_before = resource_snapshot()
    lock = threading.Lock()
    active_provider = 0
    peak_provider = 0
    events: list[dict[str, Any]] = []
    original_provider_text = run_local_pipeline_impl.provider_text
    manifest = [
        {
            "path": f"src/unit_{index:02d}.py",
            "purpose": f"bounded load unit {index}",
            "dependencies": [f"src/unit_{index - 2:02d}.py"] if index >= 2 else [],
            "estimated_complexity": "medium",
        }
        for index in range(8)
    ]

    def emit(event: str, task_id: str, **details: Any) -> None:
        with lock:
            events.append({"at": _now(), "event": event, "task_id": task_id, **details})

    def deterministic_provider(messages, model, timeout, **kwargs):
        nonlocal active_provider, peak_provider
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        payloads = []
        for message in reversed(messages):
            try:
                payloads.append(json.loads(message["content"]))
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        targets = next((list(payload.get("provider_job", {}).get("emission_paths", [])) for payload in payloads if payload.get("provider_job", {}).get("emission_paths")), [str(kwargs.get("target_file", ""))])
        with lock:
            active_provider += 1
            peak_provider = max(peak_provider, active_provider)
        try:
            if any(path.endswith("unit_06.py") for path in targets):
                time.sleep(0.012)
            else:
                time.sleep(0.001)
            files = [{"path": path, "content": '"""Deterministic Provider boundary substitute."""\n\nclass WorkUnit:\n    def __init__(self, value: int):\n        self.value = value\n\n    def validate(self) -> None:\n        if self.value < 0:\n            raise ValueError("value must be non-negative")\n\n    def run(self) -> int:\n        self.validate()\n        return self.value\n\nUNIT = WorkUnit(1)\n'} for path in targets]
            return json.dumps({"files": files} if any("provider_job" in payload for payload in payloads) else files[0])
        finally:
            with lock:
                active_provider -= 1

    def execute(task_id: str, fault: str) -> dict[str, Any]:
        emit("execution_started", task_id, fault=fault)
        if fault == "worker_exit":
            raise RuntimeError("injected isolated worker exit")
        if fault == "timeout":
            raise TimeoutError("injected bounded task timeout")
        root = output_dir / "projects" / task_id
        component = {"id": "backend", "required_paths": [str(row["path"]) for row in manifest], "minimum_file_count": len(manifest)}
        pipeline = {"components": [component], "merge_policy": {"required_final_files": component["required_paths"]}}
        common = dict(
            goal=f"provider-free arrival load {task_id}", component=component,
            component_pipeline=pipeline, prior_manifest=[], prior_files=[], repair_errors=[],
            model="deterministic-provider-boundary", timeout=30, deadline=None,
            checkpoint_dir=root / "provider_components", run_dir=root,
            spec_hash=f"spec-{task_id}", phase_log_path=root / "provider_phase_log.jsonl",
            routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
            split_reason="provider_free_arrival_load", original_prompt_chars=0,
        )
        result = run_local_pipeline_impl.provider_generate_project_component_split(**common)
        if fault == "duplicate_callback":
            duplicate = run_local_pipeline_impl.provider_generate_project_component_split(**common)
            if [row["path"] for row in duplicate["files"]] != [row["path"] for row in result["files"]]:
                raise RuntimeError("duplicate result changed canonical output set")
        accepted = len(result["files"]) == len(manifest) and all(row.get("status") == "PASS" for row in result["boundary_check_receipts"])
        emit("independent_acceptance", task_id, passed=accepted)
        return {"accepted": accepted, "files": len(result["files"]), "fault": fault}

    futures = {}
    outstanding = 0
    accounting = {key: 0 for key in ("planned", "actual_submitted", "rejected", "cancelled", "failed", "timed_out", "execution_completed", "independent_acceptance_passed")}
    accounting["planned"] = planned_tasks
    started = time.perf_counter()
    run_local_pipeline_impl.provider_text = deterministic_provider
    try:
        with ThreadPoolExecutor(max_workers=project_workers, thread_name_prefix="cgkn-load-project") as pool:
            for index in range(planned_tasks):
                task_id = f"load-{index:04d}"
                emit("planned", task_id)
                if index % 17 == 5:
                    accounting["cancelled"] += 1
                    emit("cancelled_before_execution", task_id)
                    continue
                fault = "duplicate_callback" if index % 13 == 4 else "timeout" if index % 11 == 3 else "worker_exit" if index % 9 == 2 else "none"
                running = sum(not future.done() for future in futures)
                if running >= overload_limit:
                    accounting["rejected"] += 1
                    emit("overload_rejected", task_id, outstanding=running)
                    time.sleep(arrival_interval * 4)
                    continue
                future = pool.submit(execute, task_id, fault)
                futures[future] = task_id
                accounting["actual_submitted"] += 1
                emit("submitted", task_id, fault=fault)
                time.sleep(arrival_interval)
            for future in as_completed(futures):
                task_id = futures[future]
                try:
                    result = future.result()
                except TimeoutError as exc:
                    accounting["timed_out"] += 1
                    emit("timed_out", task_id, error=str(exc))
                except Exception as exc:
                    accounting["failed"] += 1
                    emit("failed", task_id, error=f"{type(exc).__name__}: {exc}")
                else:
                    accounting["execution_completed"] += 1
                    accounting["independent_acceptance_passed"] += int(bool(result["accepted"]))
                    emit("execution_completed", task_id, **result)
    finally:
        run_local_pipeline_impl.provider_text = original_provider_text
    accounted = accounting["rejected"] + accounting["cancelled"] + accounting["failed"] + accounting["timed_out"] + accounting["execution_completed"]
    resource_after = resource_snapshot()
    resource_delta = {
        key: resource_after[key] - resource_before[key]
        for key in ("rss_bytes", "cpu_user_seconds", "cpu_system_seconds", "disk_bytes")
        if isinstance(resource_before.get(key), (int, float)) and isinstance(resource_after.get(key), (int, float))
    }
    report = {
        "kind": "CGKNProviderFreeArrivalLoad",
        "formal_evidence_status": "NOT_EVALUATED",
        "accounting": accounting,
        "denominator_balanced": accounted == accounting["planned"],
        "peak_provider_concurrency": peak_provider,
        "elapsed_seconds": time.perf_counter() - started,
        "long_tail_injected": True,
        "overload_fallback_observed": accounting["rejected"] > 0 and accounting["execution_completed"] > 0,
        "combined_faults": ["overload_rejection", "cancellation", "timeout", "worker_exit", "duplicate_callback", "long_tail"],
        "resources": {
            "before": resource_before,
            "after": resource_after,
            "delta": resource_delta,
            "rss_peak_note": "Only endpoint RSS was observed; a sampled peak was not collected.",
        },
        "status": "PASS" if accounted == accounting["planned"] and accounting["execution_completed"] > 0 else "FAIL",
    }
    (output_dir / "arrival_events.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in events), encoding="utf-8")
    (output_dir / "arrival_load_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


TEST_GROUPS = {
    "scheduler_scale": [
        "--run-profile-marked",
        "-m",
        "benchmark",
        "tests/test_generation_scale_ladder.py",
    ],
    "recovery_faults": [
        "tools/cgkn-agent-kit/tests/test_agent_kit.py",
        "tests/test_provider_retry_recovery.py",
        "tests/test_generation_timeout_result.py",
        "tests/test_false_pass_auditor.py",
    ],
    "surrogate_contract": ["tests/test_surrogate_provider_ingestion.py"],
    "delivery_contract": [
        "tests/test_canonical_delivery_manifest.py::CanonicalDeliveryManifestTests::test_producer_and_inspector_recompute_all_hashes",
        "tests/test_canonical_delivery_receipt.py::CanonicalDeliveryReceiptTests::test_nonvisual_final_package_has_canonical_receipt_before_delivered",
    ],
    "holdout": ["tests/test_project_generation_benchmark_v1.py"],
}


def run_test_group(name: str, tests: list[str], output_dir: pathlib.Path) -> dict[str, Any]:
    argv = [sys.executable, "-m", "pytest", "-q", *tests, "--tb=short"]
    started = time.perf_counter()
    result = subprocess.run(
        argv,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    elapsed = time.perf_counter() - started
    log_path = output_dir / f"{name}.log"
    log_path.write_text(
        result.stdout + ("\n[stderr]\n" + result.stderr if result.stderr else ""),
        encoding="utf-8",
    )
    return {
        "name": name,
        "argv": argv,
        "returncode": result.returncode,
        "elapsed_seconds": elapsed,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "log": str(log_path),
    }


def run(
    output_dir: pathlib.Path,
    *,
    validators_only: bool = False,
    selected_groups: list[str] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    identity = source_identity()
    (output_dir / "source_identity.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    measurements = validator_measurements([1500, 3000, 10000])
    arrival_load = provider_job_arrival_load(output_dir / "arrival_load")
    selected = selected_groups or list(TEST_GROUPS)
    groups = [] if validators_only else [
        run_test_group(name, TEST_GROUPS[name], output_dir) for name in selected
    ]
    report = {
        "kind": "CGKNFunctionStressEngineeringReport",
        "formal_evidence_status": "NOT_EVALUATED",
        "authority": "engineering_measurement_only",
        "created_at": _now(),
        "source_identity": identity,
        "validator_measurements": measurements,
        "arrival_load": arrival_load,
        "test_groups": groups,
        "status": (
            "PASS"
            if all(row["status"] == "PASS" for row in measurements)
            and arrival_load["status"] == "PASS"
            and all(group["status"] == "PASS" for group in groups)
            else "FAIL"
        ),
        "limitations": [
            "No live Provider or local-model call is performed by this runner.",
            "This is not a 24-hour soak and cannot authorize formal delivery PASS.",
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=ROOT / "artifacts" / "function_stress_pass" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )
    parser.add_argument("--validators-only", action="store_true")
    parser.add_argument("--group", action="append", choices=sorted(TEST_GROUPS))
    args = parser.parse_args(argv)
    report = run(
        args.output_dir.resolve(),
        validators_only=args.validators_only,
        selected_groups=args.group,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
