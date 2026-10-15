#!/usr/bin/env python3
"""Reproducible engineering stress entry for the existing CGKN authorities.

This runner creates no generation, scheduling, evidence, packaging, or delivery
path.  It measures the canonical WorkNode/ProviderJob validators and invokes
the repository's real pytest-covered scheduler, recovery, surrogate, evidence,
and delivery entrypoints.
"""

from __future__ import annotations

import argparse
import hashlib
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


def _deterministic_load_source(index: int) -> str:
    """Return the acceptance oracle fixed before any Provider work starts."""
    return (
        '\"\"\"Deterministic Provider boundary substitute.\"\"\"\n\n'
        "class WorkUnit:\n"
        "    def __init__(self, value: int):\n"
        "        self.value = value\n\n"
        "    def validate(self) -> None:\n"
        "        if self.value < 0:\n"
        '            raise ValueError("value must be non-negative")\n\n'
        "    def run(self) -> int:\n"
        "        self.validate()\n"
        "        return self.value\n\n"
        f"UNIT = WorkUnit({index})\n"
    )


def _canonical_receipt_sha256(receipt: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_arrival_task_result(
    result: dict[str, Any], manifest: list[dict[str, Any]]
) -> dict[str, Any]:
    """Independently verify one load result instead of trusting Provider receipts."""
    errors: list[str] = []
    expected = {
        str(row["path"]): str(row["expected_content_sha256"])
        for row in manifest
    }
    files = result.get("files", [])
    receipts = result.get("boundary_check_receipts", [])
    if not isinstance(files, list):
        files = []
        errors.append("files_not_a_list")
    if not isinstance(receipts, list):
        receipts = []
        errors.append("receipts_not_a_list")

    observed_files: dict[str, str] = {}
    for row in files:
        if not isinstance(row, dict):
            errors.append("malformed_file")
            continue
        path = str(row.get("path", "")).replace("\\", "/").strip()
        content = row.get("content")
        if not path or not isinstance(content, str):
            errors.append("malformed_file")
            continue
        if path in observed_files:
            errors.append(f"duplicate_file:{path}")
        observed_files[path] = content
    if set(observed_files) != set(expected):
        errors.append("file_set_mismatch")
    for path, expected_sha in expected.items():
        content = observed_files.get(path)
        if content is None:
            continue
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != expected_sha:
            errors.append(f"content_sha256_mismatch:{path}")
        try:
            compile(content, path, "exec")
        except SyntaxError:
            errors.append(f"python_syntax_error:{path}")

    observed_receipts: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, dict):
            errors.append("malformed_receipt")
            continue
        path = str(receipt.get("target_file", "")).replace("\\", "/").strip()
        if not path or path in observed_receipts:
            errors.append(f"duplicate_or_missing_receipt_target:{path}")
            continue
        observed_receipts[path] = receipt
        if receipt.get("kind") != "CGKNLeafBoundaryCheckReceipt":
            errors.append(f"receipt_kind_mismatch:{path}")
        if receipt.get("status") != "PASS":
            errors.append(f"receipt_not_pass:{path}")
        if receipt.get("receipt_sha256") != _canonical_receipt_sha256(receipt):
            errors.append(f"receipt_sha256_mismatch:{path}")
    if set(observed_receipts) != set(expected):
        errors.append("receipt_set_mismatch")
    return {
        "status": "PASS" if not errors else "FAIL",
        "accepted": not errors,
        "errors": errors,
        "expected_file_count": len(expected),
        "observed_file_count": len(observed_files),
        "observed_receipt_count": len(observed_receipts),
    }


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
    required_faults: tuple[str, ...] = (),
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
    long_tail_provider_calls = 0
    duplicate_callbacks_completed = 0
    events: list[dict[str, Any]] = []
    original_provider_text = run_local_pipeline_impl.provider_text
    manifest = [
        {
            "path": f"src/unit_{index:02d}.py",
            "purpose": f"bounded load unit {index}",
            "dependencies": [f"src/unit_{index - 2:02d}.py"] if index >= 2 else [],
            "estimated_complexity": "medium",
            "expected_content_sha256": hashlib.sha256(
                _deterministic_load_source(index).encode("utf-8")
            ).hexdigest(),
        }
        for index in range(8)
    ]

    def emit(event: str, task_id: str, **details: Any) -> None:
        with lock:
            events.append({"at": _now(), "event": event, "task_id": task_id, **details})

    def deterministic_provider(messages, model, timeout, **kwargs):
        nonlocal active_provider, peak_provider, long_tail_provider_calls
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
                with lock:
                    long_tail_provider_calls += 1
                time.sleep(0.012)
            else:
                time.sleep(0.001)
            files = [
                {
                    "path": path,
                    "content": _deterministic_load_source(
                        int(pathlib.PurePosixPath(path).stem.rsplit("_", 1)[-1])
                    ),
                }
                for path in targets
            ]
            return json.dumps({"files": files} if any("provider_job" in payload for payload in payloads) else files[0])
        finally:
            with lock:
                active_provider -= 1

    def execute(task_id: str, fault: str) -> dict[str, Any]:
        nonlocal duplicate_callbacks_completed
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
            with lock:
                duplicate_callbacks_completed += 1
        acceptance = evaluate_arrival_task_result(result, manifest)
        emit("independent_acceptance", task_id, passed=acceptance["accepted"], errors=acceptance["errors"])
        return {"accepted": acceptance["accepted"], "files": len(result["files"]), "fault": fault, "acceptance": acceptance}

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
    execution_ok = accounted == accounting["planned"] and accounting["execution_completed"] > 0
    acceptance_ok = (
        accounting["execution_completed"] > 0
        and accounting["independent_acceptance_passed"] == accounting["execution_completed"]
    )
    observed_faults = {
        "overload_rejection": accounting["rejected"] > 0,
        "cancellation_before_execution": accounting["cancelled"] > 0,
        "simulated_timeout": accounting["timed_out"] > 0,
        "simulated_worker_exit": accounting["failed"] > 0,
        "duplicate_callback": duplicate_callbacks_completed > 0,
        "long_tail_provider_call": long_tail_provider_calls > 0,
    }
    missing_required_faults = [
        name for name in required_faults if not observed_faults.get(name, False)
    ]
    fault_coverage_ok = not missing_required_faults
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
        "long_tail_observed": long_tail_provider_calls > 0,
        "overload_fallback_observed": accounting["rejected"] > 0 and accounting["execution_completed"] > 0,
        "fault_observations": observed_faults,
        "fault_injection_fidelity": {
            "simulated_timeout": "in-process pre-execution exception",
            "simulated_worker_exit": "in-process pre-execution exception",
            "cancellation_before_execution": "admission-time cancellation, not a cancellation race",
            "duplicate_callback": "real repeated canonical scheduler call",
            "long_tail_provider_call": "real delayed deterministic Provider-boundary call",
        },
        "resources": {
            "before": resource_before,
            "after": resource_after,
            "delta": resource_delta,
            "rss_peak_note": "Only endpoint RSS was observed; a sampled peak was not collected.",
        },
        "verdict_sections": {
            "accounting": {"status": "PASS" if accounted == accounting["planned"] else "FAIL"},
            "execution": {"status": "PASS" if execution_ok else "FAIL"},
            "independent_acceptance": {"status": "PASS" if acceptance_ok else "FAIL"},
            "required_fault_coverage": {
                "status": (
                    "PASS"
                    if required_faults and fault_coverage_ok
                    else "FAIL"
                    if required_faults
                    else "NOT_EVALUATED"
                ),
                "required": list(required_faults),
                "missing": missing_required_faults,
            },
        },
        "status": "PASS" if execution_ok and acceptance_ok and fault_coverage_ok else "FAIL",
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
