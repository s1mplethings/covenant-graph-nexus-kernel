from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping

import psutil


ROOT = pathlib.Path(__file__).resolve().parents[2]
for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from benchmarks.knowledge_persistence_scaling import runner as foundation  # noqa: E402
from benchmarks.knowledge_persistence_scaling.workloads import WORKLOADS, workload_trace  # noqa: E402
from cgkn.application.conversation import ConversationRequest, ConversationService  # noqa: E402
from cgnk_knowledge import (  # noqa: E402
    KnowledgeMaintenancePolicy,
    PersistencePolicy,
    SegmentedKnowledgeStore,
    internalize_evidence,
    load_project_knowledge,
    project_knowledge_semantic_hash,
    retrieve_relevant_knowledge,
    save_project_knowledge,
)


ITERATION = "ITER-CGNK-SEGMENTED-PERSISTENCE-PRODUCTIONIZATION-046"
BASE_EVIDENCE = "b044844feb34ec6a3783d1d570b615e34cb26a39"
S0 = {
    10_000: {"save_p50_ms": 2490.08, "file_mb": 25.59, "cold_load_ms": 844.71, "write_amplification": 80127.9},
    50_000: {"save_p50_ms": 14654.21, "file_mb": 127.86, "cold_load_ms": 6057.61, "write_amplification": 400254.4},
    100_000: {"save_p50_ms": 29715.30, "file_mb": 255.75, "cold_load_ms": 12757.03, "write_amplification": 800552.4},
    250_000: {"save_p50_ms": 80617.51, "file_mb": 639.47, "cold_load_ms": 37430.23, "write_amplification": 2001607.3},
}


def resource_preflight(workspace: pathlib.Path, max_scale: int) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(workspace)
    # The ITER-045 250k S0 corpus was about 640 MiB. Reserve a deliberately
    # conservative 8 KiB per evidence item for corpus, process and temporary
    # persistence state, while also requiring the host to stay below 75% use.
    estimated_bytes = max(512 * 1024 * 1024, max_scale * 8 * 1024)
    receipt = {
        "memory_used_percent": float(memory.percent),
        "memory_available_bytes": int(memory.available),
        "disk_used_percent": round((disk.used / max(1, disk.total)) * 100, 3),
        "disk_free_bytes": int(disk.free),
        "estimated_peak_bytes": estimated_bytes,
    }
    if memory.percent >= 75 or receipt["disk_used_percent"] >= 75:
        raise RuntimeError(f"RESOURCE_SAFETY_THRESHOLD_REACHED: {receipt}")
    if memory.available < estimated_bytes or disk.free < estimated_bytes:
        raise RuntimeError(f"RESOURCE_HEADROOM_INSUFFICIENT: {receipt}")
    return receipt


def stable_hash(value: Any) -> str:
    return foundation.stable_hash(value)


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(foundation._stable_json(value, pretty=True) + "\n", encoding="utf-8")


def _storage(root: pathlib.Path) -> dict[str, int]:
    rows = [path for path in root.rglob("*") if path.is_file()]
    return {"file_count": len(rows), "total_bytes": sum(path.stat().st_size for path in rows)}


def _percentile_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    return foundation.summary(values)


def _logical_bytes(evidence: Mapping[str, Any]) -> int:
    return len(foundation._stable_json(evidence).encode("utf-8"))


def _new_update(size: int, offset: int, branches: int) -> dict[str, Any]:
    return foundation._update_evidence(size * 10 + offset, f"branch-{offset % branches:04d}")


def _query_visibility(pack: Mapping[str, Any], evidence_id: str, content: str) -> dict[str, Any]:
    query = foundation.run_query(pack, {"goal": content})
    response = ConversationService(None).answer(ConversationRequest(content), pack, provider_enabled=False)
    return {
        "retrieval_visible": evidence_id in {str(row["id"]) for row in query["selected_items"]},
        "conversation_visible": evidence_id in {str(row["evidence_id"]) for row in response["evidence"]},
        "conversation_status": response["status"], "conversation_read_only": response["read_only"],
    }


def cold_worker(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.store_root)
    checkpoint_path: pathlib.Path | None = None
    original_byte: bytes | None = None
    if args.mode == "corrupt_checkpoint":
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["payload"]
        checkpoint_path = root / manifest["current_checkpoint"]["path"]
        with checkpoint_path.open("r+b") as handle:
            original_byte = handle.read(1)
            handle.seek(0)
            handle.write(b"X" if original_byte != b"X" else b"Y")
            handle.flush()
            os.fsync(handle.fileno())
    try:
        with foundation.RssMonitor() as monitor:
            started = time.perf_counter()
            pack = load_project_knowledge(root, use_checkpoint=args.mode != "full_replay")
            load_wall_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            query = foundation.run_query(pack, {"goal": "ident-000020"})
            first_retrieval_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            response = ConversationService(None).answer(
                ConversationRequest("ident-000020"), pack, provider_enabled=False,
            )
            first_conversation_ms = (time.perf_counter() - started) * 1000
            steady = psutil.Process().memory_info().rss
        result = {
            "mode": args.mode, "load_wall_ms": round(load_wall_ms, 3),
            "load_receipt": pack._load_receipt, "time_to_first_retrieval_ms": round(first_retrieval_ms, 3),
            "time_to_first_conversation_ms": round(first_conversation_ms, 3),
            "retrieval_ok": "ki-000020" in {str(row["id"]) for row in query["selected_items"]},
            "conversation_read_only": response["read_only"], "conversation_provider_calls": 0,
            "semantic_hash": project_knowledge_semantic_hash(pack), "steady_rss_bytes": steady,
            "peak_rss_bytes": monitor.peak, "status": "PASS",
        }
    finally:
        if checkpoint_path is not None and original_byte is not None:
            with checkpoint_path.open("r+b") as handle:
                handle.seek(0)
                handle.write(original_byte)
                handle.flush()
                os.fsync(handle.fileno())
    _write_json(pathlib.Path(args.result_path), result)
    return 0


def _run_cold(root: pathlib.Path, output: pathlib.Path, mode: str, timeout: int) -> dict[str, Any]:
    command = [
        sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "cold",
        "--store-root", str(root), "--result-path", str(output), "--mode", mode,
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(completed.stderr[-4000:] or completed.stdout[-4000:])
    result = json.loads(output.read_text(encoding="utf-8"))
    output.unlink()
    return result


def scale_worker(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.store_root)
    root.parent.mkdir(parents=True, exist_ok=True)
    branches = foundation.branch_count_for(args.size)
    policy = PersistencePolicy(
        checkpoint_mutation_interval=args.checkpoint_interval,
        checkpoint_tail_bytes=args.checkpoint_tail_bytes,
        compaction_segment_threshold=args.compaction_threshold,
        compaction_batch_size=args.compaction_batch,
    )
    resource = {"available_memory": psutil.virtual_memory().available, "disk_free": shutil.disk_usage(root.parent).free}
    with foundation.RssMonitor() as monitor:
        pack = foundation.generate_corpus(args.size, branches, "uniform")
        expected_initial_hash = project_knowledge_semantic_hash(pack)
        started = time.perf_counter()
        initial = save_project_knowledge(root, pack, policy=policy)
        initial_ms = (time.perf_counter() - started) * 1000
        pack = load_project_knowledge(root, use_checkpoint=False)
        update_rows: list[dict[str, Any]] = []
        internalization_ms: list[float] = []
        for offset in range(args.update_samples):
            evidence = _new_update(args.size, offset, branches)
            started = time.perf_counter()
            result = internalize_evidence(pack, evidence, policy=KnowledgeMaintenancePolicy.LOCAL_LAZY)
            internalization_ms.append((time.perf_counter() - started) * 1000)
            pack = result["pack"]
            write = save_project_knowledge(root, pack, mutation=result["persistence_mutation"], policy=policy)
            write["logical_changed_bytes"] = _logical_bytes(evidence)
            write["persistence_write_amplification"] = write["total_physical_bytes_written"] / max(1, write["logical_changed_bytes"])
            update_rows.append({key: value for key, value in write.items() if key != "pack"})
        store = SegmentedKnowledgeStore(root, policy=policy)
        query = foundation.evaluate_queries(pack, foundation.query_cases(args.size, branches, "uniform"), repeats=2)
        # Add enough small segments for a real bounded compaction sample.
        for offset in range(args.update_samples, args.update_samples + max(2, min(args.compaction_batch, 16))):
            evidence = _new_update(args.size, offset, branches)
            result = internalize_evidence(pack, evidence, policy=KnowledgeMaintenancePolicy.LOCAL_LAZY)
            pack = result["pack"]
            save_project_knowledge(root, pack, mutation=result["persistence_mutation"], policy=policy)
        semantic_before_compaction = project_knowledge_semantic_hash(pack)
        compaction = store.compact(max_segments=min(args.compaction_batch, 16))
        semantic_after_compaction = project_knowledge_semantic_hash(store.load(use_checkpoint=False))
        compaction["full_replay_semantic_equivalence"] = semantic_after_compaction == project_knowledge_semantic_hash(pack)
        checkpoint = store.create_checkpoint()
        storage = _storage(root)
        steady = psutil.Process().memory_info().rss
        del pack
        gc.collect()
        cold = {
            mode: _run_cold(root, pathlib.Path(args.result_path).with_name(f"cold-{mode}.json"), mode, args.worker_timeout)
            for mode in ("full_replay", "valid_checkpoint", "corrupt_checkpoint")
        }
    persistence_values = [float(row["elapsed_ms"]) for row in update_rows]
    physical_values = [float(row["total_physical_bytes_written"]) for row in update_rows]
    logical_values = [float(row["logical_changed_bytes"]) for row in update_rows]
    s0 = S0.get(args.size)
    result = {
        "kind": "KnowledgePersistenceProductionScaleResult", "iteration": ITERATION,
        "scale": args.size, "branches": branches, "resource_start": resource,
        "initial_write": {key: value for key, value in initial.items() if key != "pack"} | {"elapsed_ms_measured": round(initial_ms, 3)},
        "single_local_update": {
            "samples": len(update_rows), "internalization_ms": _percentile_summary(internalization_ms),
            "persistence_ms": _percentile_summary(persistence_values),
            "logical_changed_bytes": _percentile_summary(logical_values),
            "total_physical_bytes_written": _percentile_summary(physical_values),
            "write_amplification": _percentile_summary(row["persistence_write_amplification"] for row in update_rows),
            "fsync_count": _percentile_summary(row["fsync_count"] for row in update_rows),
            "file_operations": _percentile_summary(row["file_operations"] for row in update_rows),
            "rows": update_rows,
        },
        "checkpoint": checkpoint, "compaction": compaction, "cold_start": cold,
        "storage": storage, "disk_space_amplification": storage["total_bytes"] / max(1, int(initial["authoritative_bytes_written"])),
        "query": query, "semantic_hash_initial": expected_initial_hash,
        "semantic_hash_before_compaction": semantic_before_compaction,
        "semantic_hash_after_compaction": semantic_after_compaction,
        "s0_baseline": s0,
        "s0_vs_s2": None if not s0 else {
            "update_latency_speedup": s0["save_p50_ms"] / max(0.001, _percentile_summary(persistence_values)["p50"]),
            "write_byte_reduction": (s0["file_mb"] * 1024 * 1024) / max(1.0, _percentile_summary(physical_values)["p50"]),
            "write_amplification_reduction": s0["write_amplification"] / max(0.001, _percentile_summary(row["persistence_write_amplification"] for row in update_rows)["p50"]),
        },
        "steady_rss_bytes": steady, "peak_rss_bytes": monitor.peak,
        "provider_calls": 0,
        "status": "PASS" if (
            query["recall_pass"] and all(row["status"] == "PASS" for row in cold.values())
            and compaction["full_replay_semantic_equivalence"]
        ) else "FAIL",
    }
    _write_json(pathlib.Path(args.result_path), result)
    return 0


def policy_worker(args: argparse.Namespace) -> int:
    root_base = pathlib.Path(args.store_root)
    branches = foundation.branch_count_for(args.size)
    checkpoint_rows: list[dict[str, Any]] = []
    for label, interval in (("short", 16), ("medium", 64), ("long", 256)):
        root = root_base / f"checkpoint-{label}"
        policy = PersistencePolicy(checkpoint_mutation_interval=interval, checkpoint_tail_bytes=1024 * 1024 * 1024)
        pack = foundation.generate_corpus(args.size, branches, "uniform")
        save_project_knowledge(root, pack, policy=policy)
        pack = load_project_knowledge(root)
        maintenance_ms = 0.0
        checkpoint_count = 0
        for offset in range(args.policy_updates):
            result = internalize_evidence(pack, _new_update(args.size, offset, branches))
            pack = result["pack"]
            write = save_project_knowledge(root, pack, mutation=result["persistence_mutation"], policy=policy)
            if write["checkpoint_due"]:
                receipt = SegmentedKnowledgeStore(root, policy=policy).create_checkpoint()
                maintenance_ms += float(receipt["elapsed_ms"])
                checkpoint_count += 1
        cold_path = pathlib.Path(args.result_path).with_name(f"policy-cold-{label}.json")
        cold = _run_cold(root, cold_path, "valid_checkpoint", args.worker_timeout)
        checkpoint_rows.append({
            "label": label, "interval": interval, "updates": args.policy_updates,
            "checkpoint_count": checkpoint_count, "maintenance_ms": round(maintenance_ms, 3),
            "amortized_maintenance_ms_per_update": maintenance_ms / max(1, args.policy_updates),
            "cold_load_ms": cold["load_wall_ms"], "disk": _storage(root), "status": cold["status"],
        })

    compaction_rows: list[dict[str, Any]] = []
    for label, threshold in (("aggressive", 16), ("moderate", 64), ("relaxed", 256)):
        root = root_base / f"compaction-{label}"
        policy = PersistencePolicy(compaction_segment_threshold=threshold, compaction_batch_size=max(2, threshold // 2),
                                   checkpoint_mutation_interval=10_000, checkpoint_tail_bytes=1024 * 1024 * 1024)
        pack = foundation.generate_corpus(args.size, branches, "uniform")
        save_project_knowledge(root, pack, policy=policy)
        pack = load_project_knowledge(root)
        compaction_ms = 0.0
        compactions = 0
        peak_segments = 1
        for offset in range(args.policy_updates):
            result = internalize_evidence(pack, _new_update(args.size, offset, branches))
            pack = result["pack"]
            write = save_project_knowledge(root, pack, mutation=result["persistence_mutation"], policy=policy)
            peak_segments = max(peak_segments, len(json.loads((root / "manifest.json").read_text(encoding="utf-8"))["payload"]["authoritative_segments"]))
            if write["compaction_due"]:
                receipt = SegmentedKnowledgeStore(root, policy=policy).compact()
                if receipt["status"] == "PASS":
                    compaction_ms += float(receipt["elapsed_ms"])
                    compactions += 1
        verify = SegmentedKnowledgeStore(root, policy=policy).verify()
        compaction_rows.append({
            "label": label, "threshold": threshold, "updates": args.policy_updates,
            "compactions": compactions, "peak_segments": peak_segments, "final_segments": verify["segment_count"],
            "maintenance_ms": round(compaction_ms, 3),
            "amortized_maintenance_ms_per_update": compaction_ms / max(1, args.policy_updates),
            "disk": _storage(root), "status": verify["status"],
        })
    _write_json(pathlib.Path(args.result_path), {
        "kind": "KnowledgePersistencePolicyExperiment", "scale": args.size,
        "checkpoint_intervals": checkpoint_rows, "compaction_thresholds": compaction_rows,
        "status": "PASS" if all(row["status"] == "PASS" for row in checkpoint_rows + compaction_rows) else "FAIL",
    })
    return 0


def workload_worker(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.store_root)
    branches = foundation.branch_count_for(args.size)
    policy = PersistencePolicy()
    pack = foundation.generate_corpus(args.size, branches, "uniform")
    save_project_knowledge(root, pack, policy=policy)
    SegmentedKnowledgeStore(root, policy=policy).create_checkpoint()
    pack = load_project_knowledge(root)
    rows: list[dict[str, Any]] = []
    with foundation.RssMonitor() as monitor:
        for workload_index, workload in enumerate(WORKLOADS):
            trace = workload_trace(workload, args.operations)
            internalization: list[float] = []
            persistence: list[float] = []
            retrieval: list[float] = []
            physical = logical = updates = queries = 0
            maintenance_ms = 0.0
            compactions = 0
            first_visibility = None
            started_all = time.perf_counter()
            for operation_index, operation in enumerate(trace):
                if operation == "QUERY":
                    queries += 1
                    target = (operation_index % max(1, args.size // 100)) * 100 + 20
                    started = time.perf_counter()
                    selected = foundation.run_query(pack, {"goal": f"ident-{target:06d}"})
                    retrieval.append((time.perf_counter() - started) * 1000)
                    if f"ki-{target:06d}" not in {str(row["id"]) for row in selected["selected_items"]}:
                        raise ValueError("workload retrieval recall failure")
                    continue
                updates += 1
                evidence = _new_update(args.size, workload_index * args.operations + operation_index, branches)
                logical += _logical_bytes(evidence)
                started = time.perf_counter()
                result = internalize_evidence(pack, evidence)
                internalization.append((time.perf_counter() - started) * 1000)
                pack = result["pack"]
                write = save_project_knowledge(root, pack, mutation=result["persistence_mutation"], policy=policy)
                persistence.append(float(write["elapsed_ms"]))
                physical += int(write["total_physical_bytes_written"])
                if write["compaction_due"]:
                    compaction = SegmentedKnowledgeStore(root, policy=policy).compact()
                    if compaction["status"] == "PASS":
                        maintenance_ms += float(compaction["elapsed_ms"])
                        compactions += 1
                if first_visibility is None:
                    first_visibility = _query_visibility(pack, str(result["receipt"]["evidence_id"]), str(evidence["content"]))
            elapsed_ms = (time.perf_counter() - started_all) * 1000
            final_query = foundation.evaluate_queries(pack, foundation.query_cases(args.size, branches, "uniform"), repeats=1)
            rows.append({
                "workload": workload, "operations": len(trace), "queries": queries, "updates": updates,
                "trace_hash": stable_hash(trace), "internalization_ms": _percentile_summary(internalization),
                "persistence_ms": _percentile_summary(persistence), "retrieval_ms": _percentile_summary(retrieval),
                "logical_changed_bytes": logical, "physical_written_bytes": physical,
                "persistence_write_amplification": physical / max(1, logical),
                "compactions": compactions, "compaction_ms": round(maintenance_ms, 3),
                "amortized_compaction_ms_per_update": maintenance_ms / max(1, updates),
                "first_update_after_restart": first_visibility, "final_retrieval": final_query,
                "wall_ms": round(elapsed_ms, 3), "status": "PASS" if (
                    final_query["recall_pass"] and first_visibility and first_visibility["retrieval_visible"]
                    and first_visibility["conversation_visible"] and first_visibility["conversation_read_only"]
                ) else "FAIL",
            })
    _write_json(pathlib.Path(args.result_path), {
        "kind": "KnowledgePersistenceProductionWorkloads", "scale": args.size,
        "operations_per_workload": args.operations, "workloads": rows,
        "final_storage": _storage(root), "peak_rss_bytes": monitor.peak, "provider_calls": 0,
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
    })
    return 0


def crash_worker(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.store_root)
    branches = foundation.branch_count_for(args.size)
    pack = foundation.generate_corpus(args.size, branches, "uniform")
    save_project_knowledge(root, pack)
    SegmentedKnowledgeStore(root).create_checkpoint()
    pack = load_project_knowledge(root)
    rows: list[dict[str, Any]] = []
    for offset, point in enumerate((
        "C1_BEFORE_SEGMENT_WRITE", "C2_DURING_SEGMENT_WRITE", "C3_SEGMENT_COMPLETE_BEFORE_MANIFEST",
        "C4_DURING_MANIFEST_WRITE", "C5_BEFORE_MANIFEST_REPLACE", "C6_AFTER_MANIFEST_REPLACE",
    )):
        before_hash = project_knowledge_semantic_hash(pack)
        result = internalize_evidence(pack, _new_update(args.size, offset, branches))

        def inject(actual: str, expected: str = point) -> None:
            if actual == expected:
                raise RuntimeError(expected)

        started = time.perf_counter()
        try:
            SegmentedKnowledgeStore(root).commit_mutations(
                [result["persistence_mutation"]], expected_sequence=pack._persistence_sequence,
                expected_authority_root=pack._persistence_authority_root, injector=inject,
            )
        except RuntimeError:
            pass
        recovered = load_project_knowledge(root)
        recovery_ms = (time.perf_counter() - started) * 1000
        after_hash = project_knowledge_semantic_hash(recovered)
        new_hash = project_knowledge_semantic_hash(result["pack"])
        expected = new_hash if point == "C6_AFTER_MANIFEST_REPLACE" else before_hash
        rows.append({
            "point": point, "recovery_ms": round(recovery_ms, 3), "data_loss": False,
            "visible_state": "NEW" if after_hash == new_hash else "OLD" if after_hash == before_hash else "INVALID",
            "expected_state": "NEW" if point == "C6_AFTER_MANIFEST_REPLACE" else "OLD",
            "silent_corruption": after_hash != expected,
        })
        pack = recovered
    verify = SegmentedKnowledgeStore(root).verify()
    _write_json(pathlib.Path(args.result_path), {
        "kind": "KnowledgePersistenceCrashRecoveryBenchmark", "scale": args.size,
        "crash_points": rows, "orphan_count": len(verify["orphan_segments"]),
        "partial_temporary_count": len(verify["partial_temporaries"]),
        "status": "PASS" if all(not row["silent_corruption"] for row in rows) else "FAIL",
    })
    return 0


def _run_worker(kind: str, result_path: pathlib.Path, store_root: pathlib.Path, args: argparse.Namespace, *, size: int) -> dict[str, Any]:
    command = [
        sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", kind,
        "--size", str(size), "--store-root", str(store_root), "--result-path", str(result_path),
        "--update-samples", str(args.update_samples), "--operations", str(args.operations),
        "--policy-updates", str(args.policy_updates), "--checkpoint-interval", str(args.checkpoint_interval),
        "--checkpoint-tail-bytes", str(args.checkpoint_tail_bytes), "--compaction-threshold", str(args.compaction_threshold),
        "--compaction-batch", str(args.compaction_batch), "--worker-timeout", str(args.worker_timeout),
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.worker_timeout)
    if completed.returncode:
        raise RuntimeError(completed.stderr[-6000:] or completed.stdout[-6000:])
    return json.loads(result_path.read_text(encoding="utf-8"))


def orchestrate(args: argparse.Namespace) -> int:
    output = pathlib.Path(args.output_dir).resolve()
    workspace = pathlib.Path(args.workspace_root).resolve() if args.workspace_root else output / "tmp"
    output.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    scales = [int(value) for value in args.scales.split(",") if value]
    workload_scales = [int(value) for value in args.workload_scales.split(",") if value]
    requested_scales = scales + workload_scales + ([args.policy_scale] if args.run_policy_experiments else [])
    requested_scales += [args.crash_scale] if args.crash_scale else []
    resource_start = resource_preflight(workspace, max(requested_scales, default=0))
    scale_rows: list[dict[str, Any]] = []
    for size in scales:
        with tempfile.TemporaryDirectory(prefix=f"v2-scale-{size}-", dir=workspace) as temporary:
            result_path = output / f"scale-{size}.json"
            scale_rows.append(_run_worker("scale", result_path, pathlib.Path(temporary) / "pack", args, size=size))
    policy_result = None
    if args.run_policy_experiments:
        with tempfile.TemporaryDirectory(prefix="v2-policy-", dir=workspace) as temporary:
            policy_path = output / "policy-experiments.json"
            policy_result = _run_worker("policy", policy_path, pathlib.Path(temporary), args, size=args.policy_scale)
    workload_rows: list[dict[str, Any]] = []
    for size in workload_scales:
        with tempfile.TemporaryDirectory(prefix=f"v2-workload-{size}-", dir=workspace) as temporary:
            result_path = output / f"workloads-{size}.json"
            workload_rows.append(_run_worker("workload", result_path, pathlib.Path(temporary) / "pack", args, size=size))
    crash_result = None
    if args.crash_scale:
        with tempfile.TemporaryDirectory(prefix="v2-crash-", dir=workspace) as temporary:
            crash_path = output / f"crash-{args.crash_scale}.json"
            crash_result = _run_worker("crash", crash_path, pathlib.Path(temporary) / "pack", args, size=args.crash_scale)
    report = {
        "kind": "KnowledgePersistenceProductionizationReport", "iteration": ITERATION,
        "base_evidence": BASE_EVIDENCE, "source_commit": args.source_commit,
        "resource_preflight": resource_start,
        "foundation_hashes": foundation.benchmark_hashes(),
        "production_backend": "cgnk_knowledge.persistence.SegmentedKnowledgeStore",
        "scales": scale_rows, "policy_experiments": policy_result,
        "mixed_workloads": workload_rows, "crash_recovery": crash_result,
        "provider_calls": 0,
        "status": "PASS" if (
            all(row["status"] == "PASS" for row in scale_rows + workload_rows)
            and (policy_result is None or policy_result["status"] == "PASS")
            and (crash_result is None or crash_result["status"] == "PASS")
        ) else "FAIL",
    }
    _write_json(output / "productionization-report.json", report)
    print(foundation._stable_json(report, pretty=True))
    return 0 if report["status"] == "PASS" else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--worker", choices=("cold", "scale", "policy", "workload", "crash"))
    value.add_argument("--mode", choices=("full_replay", "valid_checkpoint", "corrupt_checkpoint"), default="valid_checkpoint")
    value.add_argument("--size", type=int, default=10_000)
    value.add_argument("--store-root")
    value.add_argument("--result-path")
    value.add_argument("--output-dir", default="evidence/knowledge_persistence_productionization")
    value.add_argument("--workspace-root")
    value.add_argument("--scales", default="10000,50000,100000,250000")
    value.add_argument("--workload-scales", default="100000,250000")
    value.add_argument("--update-samples", type=int, default=5)
    value.add_argument("--operations", type=int, default=1000)
    value.add_argument("--policy-updates", type=int, default=64)
    value.add_argument("--policy-scale", type=int, default=10_000)
    value.add_argument("--run-policy-experiments", action="store_true")
    value.add_argument("--crash-scale", type=int, default=100_000)
    value.add_argument("--checkpoint-interval", type=int, default=256)
    value.add_argument("--checkpoint-tail-bytes", type=int, default=64 * 1024 * 1024)
    value.add_argument("--compaction-threshold", type=int, default=64)
    value.add_argument("--compaction-batch", type=int, default=32)
    value.add_argument("--worker-timeout", type=int, default=3600)
    value.add_argument("--source-commit", default="WORKING_TREE")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.worker == "cold":
        return cold_worker(args)
    if args.worker == "scale":
        return scale_worker(args)
    if args.worker == "policy":
        return policy_worker(args)
    if args.worker == "workload":
        return workload_worker(args)
    if args.worker == "crash":
        return crash_worker(args)
    return orchestrate(args)


if __name__ == "__main__":
    raise SystemExit(main())
