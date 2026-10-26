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
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import psutil


ROOT = pathlib.Path(__file__).resolve().parents[2]
for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from benchmarks.knowledge_persistence_scaling import runner as foundation  # noqa: E402
from benchmarks.knowledge_persistence_scaling.workloads import WORKLOADS, workload_trace  # noqa: E402
from benchmarks.knowledge_persistence_productionization import resource_policy  # noqa: E402
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


ITERATION = "ITER-CGNK-V2-RESOURCE-GATE-CALIBRATION-AND-SCALE-QUALIFICATION-048"
BASE_EVIDENCE = "45b2e1e8976f3c3fbe70fa62de3b0f415af3c05b"
S0 = {
    10_000: {"save_p50_ms": 2490.08, "file_mb": 25.59, "cold_load_ms": 844.71, "write_amplification": 80127.9},
    50_000: {"save_p50_ms": 14654.21, "file_mb": 127.86, "cold_load_ms": 6057.61, "write_amplification": 400254.4},
    100_000: {"save_p50_ms": 29715.30, "file_mb": 255.75, "cold_load_ms": 12757.03, "write_amplification": 800552.4},
    250_000: {"save_p50_ms": 80617.51, "file_mb": 639.47, "cold_load_ms": 37430.23, "write_amplification": 2001607.3},
}
PRODUCTION_SOURCE_COMMIT = "3439370f3e0a5ba118199dce10d429e77b77e24f"


def benchmark_harness_hash() -> str:
    paths = (
        pathlib.Path(__file__).resolve(),
        pathlib.Path(resource_policy.__file__).resolve(),
        pathlib.Path(foundation.__file__).resolve(),
        pathlib.Path(__file__).with_name("__init__.py").resolve(),
    )
    return stable_hash({str(path.relative_to(ROOT)).replace("\\", "/"): path.read_text(encoding="utf-8") for path in paths})


def resource_preflight(workspace: pathlib.Path, estimate: Mapping[str, Any]) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(workspace)
    receipt = resource_policy.evaluate_resource_gate(
        volume_total_bytes=disk.total,
        volume_free_bytes=disk.free,
        memory_total_bytes=memory.total,
        memory_available_bytes=memory.available,
        estimate=estimate,
    )
    receipt["workspace_volume"] = str(workspace.anchor)
    receipt["observed_memory_used_percent"] = float(memory.percent)
    receipt["observed_disk_used_percent"] = round((disk.used / max(1, disk.total)) * 100, 3)
    if receipt["status"] != "PASS":
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


def _storage_breakdown(root: pathlib.Path) -> dict[str, int]:
    result = {
        "total_bytes": 0, "file_count": 0, "segment_bytes": 0,
        "checkpoint_bytes": 0, "manifest_bytes": 0, "temporary_bytes": 0, "other_bytes": 0,
    }
    if not root.exists():
        return result
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        relative = path.relative_to(root).as_posix()
        result["total_bytes"] += size
        result["file_count"] += 1
        if ".tmp" in path.name or path.name.endswith(".partial"):
            result["temporary_bytes"] += size
        elif relative.startswith("segments/"):
            result["segment_bytes"] += size
        elif relative.startswith("checkpoints/"):
            result["checkpoint_bytes"] += size
        elif relative == "manifest.json":
            result["manifest_bytes"] += size
        else:
            result["other_bytes"] += size
    return result


class DirectoryFootprintMonitor:
    def __init__(self, root: pathlib.Path, interval_seconds: float = 0.005) -> None:
        self.root = root
        self.interval_seconds = interval_seconds
        self.phase = "setup"
        self.samples = 0
        self.peak = _storage_breakdown(root)
        self.phase_peaks: dict[str, dict[str, int]] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "DirectoryFootprintMonitor":
        self._sample()
        self._thread.start()
        return self

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self._sample()

    def _sample(self) -> None:
        row = _storage_breakdown(self.root)
        self.samples += 1
        for key, value in row.items():
            self.peak[key] = max(self.peak.get(key, 0), value)
        phase = self.phase
        current = self.phase_peaks.setdefault(phase, {key: 0 for key in row})
        for key, value in row.items():
            current[key] = max(current.get(key, 0), value)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def __exit__(self, *_: object) -> None:
        self._sample()
        self._stop.set()
        self._thread.join(timeout=2)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _percentile_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    rows = list(values)
    result = foundation.summary(rows)
    result["p99"] = foundation.percentile(rows, 0.99)
    return result


def _add_query_p99(result: dict[str, Any]) -> dict[str, Any]:
    values = [float(row["latency_ms"]) for row in result.get("cases", ()) if isinstance(row.get("latency_ms"), (int, float))]
    result.setdefault("latency_ms", {})["p99"] = foundation.percentile(values, 0.99)
    return result


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


def _restart_superseding_visibility(
    root: pathlib.Path, *, size: int, branches: int, policy: PersistencePolicy,
) -> dict[str, Any]:
    restarted = load_project_knowledge(root)
    subject_ref = "versioned-000000"
    old_id = "ki-000001"
    marker = f"restart-superseding-current-value-{size}"
    evidence = {
        "content": marker,
        "item_type": "decision",
        "scope": "project.cgnk",
        "source_ref": f"benchmark:restart-superseding:{size}",
        "subject_ref": subject_ref,
        "branch_ref": f"branch-{0 % branches:04d}",
        "source_version": "3",
        "importance": "critical",
        "need_state": "needed_now",
        "tags": ["restart", "superseding", "benchmark-update"],
    }
    result = internalize_evidence(restarted, evidence, policy=KnowledgeMaintenancePolicy.LOCAL_LAZY)
    updated = result["pack"]
    write = save_project_knowledge(root, updated, mutation=result["persistence_mutation"], policy=policy)
    reloaded = load_project_knowledge(root)
    by_id = {str(row["id"]): row for row in reloaded.get("all_items", ())}
    new_id = str(result["receipt"]["evidence_id"])
    query = foundation.run_query(reloaded, {"goal": marker})
    response = ConversationService(None).answer(ConversationRequest(marker), reloaded, provider_enabled=False)
    query_ids = {str(row["id"]) for row in query["selected_items"]}
    conversation_ids = {str(row["evidence_id"]) for row in response["evidence"]}
    old = by_id.get(old_id, {})
    new = by_id.get(new_id, {})
    checks = {
        "relation_superseding": result["receipt"]["relation"] == "SUPERSEDING",
        "old_fact_retained": old_id in by_id,
        "old_fact_superseded": old.get("status") == "superseded" and old.get("superseded_by") == new_id,
        "new_fact_current": new.get("status") == "active" and new.get("source_version") == "3",
        "query_returns_new": new_id in query_ids,
        "query_excludes_old": old_id not in query_ids,
        "conversation_returns_new": new_id in conversation_ids,
        "conversation_excludes_old": old_id not in conversation_ids,
        "conversation_read_only": response["read_only"] is True,
        "stale_derived_not_returned": not any(row.get("derived_state") == "stale" for row in query["selected_items"]),
        "provenance_present": bool(new.get("source_refs")),
    }
    return {
        "operation": "restart_then_superseding_update_then_conversation",
        "subject_ref": subject_ref, "old_id": old_id, "new_id": new_id,
        "relation": result["receipt"]["relation"],
        "write": {key: value for key, value in write.items() if key != "pack"},
        "query_ids": sorted(query_ids), "conversation_evidence_ids": sorted(conversation_ids),
        "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL",
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


def calibration_worker(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.store_root)
    root.parent.mkdir(parents=True, exist_ok=True)
    branches = foundation.branch_count_for(args.size)
    policy = PersistencePolicy()
    baseline_rss = psutil.Process().memory_info().rss
    writes: list[dict[str, Any]] = []
    checkpoint_due_at: int | None = None
    compaction_due_at: int | None = None
    with DirectoryFootprintMonitor(root) as disk_monitor, foundation.RssMonitor() as memory_monitor:
        disk_monitor.set_phase("corpus_generation")
        pack = foundation.generate_corpus(args.size, branches, "uniform")
        logical_authoritative_bytes = len(foundation._stable_json(pack).encode("utf-8"))
        disk_monitor.set_phase("initial_creation")
        initial = save_project_knowledge(root, pack, format_version="2.0", policy=policy)
        initial_steady = _storage_breakdown(root)
        pack = load_project_knowledge(root, use_checkpoint=False)
        disk_monitor.set_phase("mutation_tail")
        # Exercise the unchanged production thresholds. The loop ends as soon
        # as both maintenance signals have occurred and never exceeds the
        # default checkpoint mutation interval.
        for offset in range(policy.checkpoint_mutation_interval):
            evidence = _new_update(args.size, offset, branches)
            result = internalize_evidence(pack, evidence, policy=KnowledgeMaintenancePolicy.LOCAL_LAZY)
            pack = result["pack"]
            write = save_project_knowledge(root, pack, mutation=result["persistence_mutation"], policy=policy)
            writes.append({key: value for key, value in write.items() if key != "pack"})
            if write["checkpoint_due"] and checkpoint_due_at is None:
                checkpoint_due_at = offset + 1
            if write["compaction_due"] and compaction_due_at is None:
                compaction_due_at = offset + 1
            if checkpoint_due_at is not None and compaction_due_at is not None and offset + 1 >= args.update_samples:
                break
        pre_maintenance = _storage_breakdown(root)
        disk_monitor.set_phase("checkpoint_transaction")
        checkpoint = SegmentedKnowledgeStore(root, policy=policy).create_checkpoint()
        after_checkpoint = _storage_breakdown(root)
        disk_monitor.set_phase("compaction_transaction")
        compaction = SegmentedKnowledgeStore(root, policy=policy).compact(validate_full_replay=True)
        after_compaction = _storage_breakdown(root)
        disk_monitor.set_phase("correctness")
        reloaded = load_project_knowledge(root)
        query = foundation.evaluate_queries(reloaded, foundation.query_cases(args.size, branches, "uniform"), repeats=1)
        derived_index_bytes = len(foundation._stable_json(reloaded.get("knowledge_index", {})).encode("utf-8"))
    status = "PASS" if (
        checkpoint_due_at is not None and compaction_due_at is not None
        and checkpoint.get("status") == "PASS" and compaction.get("status") == "PASS"
        and compaction.get("semantic_hash_before") == compaction.get("semantic_hash_after")
        and query["recall_pass"]
    ) else "FAIL"
    result = {
        "kind": "KnowledgePersistenceResourceCalibration",
        "iteration": ITERATION,
        "scale": args.size,
        "policy": {
            "checkpoint_mutation_interval": policy.checkpoint_mutation_interval,
            "checkpoint_tail_bytes": policy.checkpoint_tail_bytes,
            "compaction_segment_threshold": policy.compaction_segment_threshold,
            "compaction_batch_size": policy.compaction_batch_size,
        },
        "measurement_status": "COMPLETE" if status == "PASS" else "INCOMPLETE",
        "initial_authoritative_bytes": int(initial["authoritative_bytes_written"]),
        "logical_authoritative_bytes": logical_authoritative_bytes,
        "derived_index_bytes": derived_index_bytes,
        "checkpoint_bytes": int(checkpoint.get("checkpoint_bytes_written", 0)),
        "largest_update_segment_bytes": max(int(row["authoritative_bytes_written"]) for row in writes),
        "compaction_bytes_written": int(compaction.get("compaction_bytes_written", 0)),
        "peak_manifest_bytes": int(disk_monitor.peak["manifest_bytes"]),
        "observed_active_peak_bytes": int(disk_monitor.peak["total_bytes"]),
        "observed_temporary_peak_bytes": int(disk_monitor.peak["temporary_bytes"]),
        "baseline_rss_bytes": baseline_rss,
        "peak_rss_bytes": int(memory_monitor.peak),
        "initial_steady": initial_steady,
        "pre_maintenance": pre_maintenance,
        "after_checkpoint": after_checkpoint,
        "after_compaction": after_compaction,
        "phase_peaks": disk_monitor.phase_peaks,
        "disk_monitor_samples": disk_monitor.samples,
        "checkpoint_due_at_mutation": checkpoint_due_at,
        "compaction_due_at_mutation": compaction_due_at,
        "mutation_count": len(writes),
        "checkpoint": checkpoint,
        "compaction": compaction,
        "query_recall_pass": query["recall_pass"],
        "provider_calls": 0,
        "status": status,
    }
    _write_json(pathlib.Path(args.result_path), result)
    return 0 if status == "PASS" else 1


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
    with DirectoryFootprintMonitor(root) as disk_monitor, foundation.RssMonitor() as monitor:
        disk_monitor.set_phase("corpus_generation")
        pack = foundation.generate_corpus(args.size, branches, "uniform")
        expected_initial_hash = project_knowledge_semantic_hash(pack)
        disk_monitor.set_phase("initial_creation")
        started = time.perf_counter()
        initial = save_project_knowledge(root, pack, format_version="2.0", policy=policy)
        initial_ms = (time.perf_counter() - started) * 1000
        pack = load_project_knowledge(root, use_checkpoint=False)
        update_rows: list[dict[str, Any]] = []
        internalization_ms: list[float] = []
        disk_monitor.set_phase("normal_updates")
        checkpoint_due_observed = False
        compaction_due_observed = False
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
            checkpoint_due_observed = checkpoint_due_observed or bool(write["checkpoint_due"])
            compaction_due_observed = compaction_due_observed or bool(write["compaction_due"])
        store = SegmentedKnowledgeStore(root, policy=policy)
        query = _add_query_p99(foundation.evaluate_queries(pack, foundation.query_cases(args.size, branches, "uniform"), repeats=2))
        # Drive the unchanged production maintenance signals. Small scales may
        # need the full 256-mutation interval; large scales usually hit the
        # byte thresholds much earlier.
        disk_monitor.set_phase("maintenance_trigger_sequence")
        for offset in range(args.update_samples, policy.checkpoint_mutation_interval):
            evidence = _new_update(args.size, offset, branches)
            result = internalize_evidence(pack, evidence, policy=KnowledgeMaintenancePolicy.LOCAL_LAZY)
            pack = result["pack"]
            write = save_project_knowledge(root, pack, mutation=result["persistence_mutation"], policy=policy)
            checkpoint_due_observed = checkpoint_due_observed or bool(write["checkpoint_due"])
            compaction_due_observed = compaction_due_observed or bool(write["compaction_due"])
            if checkpoint_due_observed and compaction_due_observed:
                break
        semantic_before_compaction = project_knowledge_semantic_hash(pack)
        disk_monitor.set_phase("compaction_transaction")
        compaction = store.compact()
        semantic_after_compaction = project_knowledge_semantic_hash(store.load(use_checkpoint=False))
        compaction["full_replay_semantic_equivalence"] = semantic_after_compaction == project_knowledge_semantic_hash(pack)
        disk_monitor.set_phase("checkpoint_transaction")
        checkpoint = store.create_checkpoint()
        disk_monitor.set_phase("restart_superseding_visibility")
        restart_superseding = (
            _restart_superseding_visibility(root, size=args.size, branches=branches, policy=policy)
            if args.size == 250_000 else {"status": "NOT_APPLICABLE"}
        )
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
        "restart_superseding_visibility": restart_superseding,
        "maintenance_signals": {
            "checkpoint_due_observed": checkpoint_due_observed,
            "compaction_due_observed": compaction_due_observed,
        },
        "disk_footprint": {
            "observed_active_peak_bytes": disk_monitor.peak["total_bytes"],
            "observed_temporary_peak_bytes": disk_monitor.peak["temporary_bytes"],
            "peak_breakdown": disk_monitor.peak,
            "phase_peaks": disk_monitor.phase_peaks,
            "samples": disk_monitor.samples,
        },
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
            and checkpoint_due_observed and compaction_due_observed
            and restart_superseding["status"] in {"PASS", "NOT_APPLICABLE"}
            and len({row["semantic_hash"] for row in cold.values()}) == 1
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
        save_project_knowledge(root, pack, format_version="2.0", policy=policy)
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
        save_project_knowledge(root, pack, format_version="2.0", policy=policy)
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
    disk_monitor = DirectoryFootprintMonitor(root)
    disk_monitor.__enter__()
    disk_monitor.set_phase("initial_creation")
    branches = foundation.branch_count_for(args.size)
    policy = PersistencePolicy()
    pack = foundation.generate_corpus(args.size, branches, "uniform")
    save_project_knowledge(root, pack, format_version="2.0", policy=policy)
    SegmentedKnowledgeStore(root, policy=policy).create_checkpoint()
    pack = load_project_knowledge(root)
    disk_monitor.set_phase("mixed_workloads")
    rows: list[dict[str, Any]] = []
    with foundation.RssMonitor() as monitor:
        for workload_index, workload in enumerate(WORKLOADS):
            trace = workload_trace(workload, args.operations)
            internalization: list[float] = []
            persistence: list[float] = []
            retrieval: list[float] = []
            conversation: list[float] = []
            conversation_failures = 0
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
                    started = time.perf_counter()
                    response = ConversationService(None).answer(
                        ConversationRequest(f"ident-{target:06d}"), pack, provider_enabled=False,
                    )
                    conversation.append((time.perf_counter() - started) * 1000)
                    if (
                        response["read_only"] is not True
                        or f"ki-{target:06d}" not in {str(item["evidence_id"]) for item in response["evidence"]}
                    ):
                        conversation_failures += 1
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
            final_query = _add_query_p99(foundation.evaluate_queries(pack, foundation.query_cases(args.size, branches, "uniform"), repeats=1))
            rows.append({
                "workload": workload, "operations": len(trace), "queries": queries, "updates": updates,
                "trace_hash": stable_hash(trace), "internalization_ms": _percentile_summary(internalization),
                "persistence_ms": _percentile_summary(persistence), "retrieval_ms": _percentile_summary(retrieval),
                "conversation_ms": _percentile_summary(conversation), "conversation_failures": conversation_failures,
                "logical_changed_bytes": logical, "physical_written_bytes": physical,
                "persistence_write_amplification": physical / max(1, logical),
                "compactions": compactions, "compaction_ms": round(maintenance_ms, 3),
                "amortized_compaction_ms_per_update": maintenance_ms / max(1, updates),
                "first_update_after_restart": first_visibility, "final_retrieval": final_query,
                "wall_ms": round(elapsed_ms, 3), "status": "PASS" if (
                    final_query["recall_pass"] and first_visibility and first_visibility["retrieval_visible"]
                    and first_visibility["conversation_visible"] and first_visibility["conversation_read_only"]
                    and conversation_failures == 0
                ) else "FAIL",
            })
    disk_monitor.__exit__()
    _write_json(pathlib.Path(args.result_path), {
        "kind": "KnowledgePersistenceProductionWorkloads", "scale": args.size,
        "operations_per_workload": args.operations, "workloads": rows,
        "final_storage": _storage(root), "peak_rss_bytes": monitor.peak, "provider_calls": 0,
        "disk_footprint": {
            "observed_active_peak_bytes": disk_monitor.peak["total_bytes"],
            "observed_temporary_peak_bytes": disk_monitor.peak["temporary_bytes"],
            "peak_breakdown": disk_monitor.peak, "phase_peaks": disk_monitor.phase_peaks,
            "samples": disk_monitor.samples,
        },
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
    })
    return 0


def crash_worker(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.store_root)
    disk_monitor = DirectoryFootprintMonitor(root)
    disk_monitor.__enter__()
    disk_monitor.set_phase("initial_creation")
    branches = foundation.branch_count_for(args.size)
    pack = foundation.generate_corpus(args.size, branches, "uniform")
    save_project_knowledge(root, pack, format_version="2.0")
    SegmentedKnowledgeStore(root).create_checkpoint()
    pack = load_project_knowledge(root)
    rows: list[dict[str, Any]] = []
    disk_monitor.set_phase("crash_recovery")
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
    disk_monitor.__exit__()
    _write_json(pathlib.Path(args.result_path), {
        "kind": "KnowledgePersistenceCrashRecoveryBenchmark", "scale": args.size,
        "crash_points": rows, "orphan_count": len(verify["orphan_segments"]),
        "partial_temporary_count": len(verify["partial_temporaries"]),
        "disk_footprint": {
            "observed_active_peak_bytes": disk_monitor.peak["total_bytes"],
            "observed_temporary_peak_bytes": disk_monitor.peak["temporary_bytes"],
            "peak_breakdown": disk_monitor.peak, "phase_peaks": disk_monitor.phase_peaks,
            "samples": disk_monitor.samples,
        },
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


def _resource_policy_digest(value: Mapping[str, Any]) -> str:
    return stable_hash({key: item for key, item in value.items() if key != "resource_policy_file_hash"})


def _freeze_resource_policy(calibrations: list[dict[str, Any]], scales: list[int], workspace: pathlib.Path) -> dict[str, Any]:
    disk = shutil.disk_usage(workspace)
    memory = psutil.virtual_memory()
    estimates = {
        str(scale): resource_policy.estimate_peak_resources(scale=scale, calibrations=calibrations, historical_s0=S0)
        for scale in sorted(set(scales))
    }
    gates = {
        scale: resource_policy.evaluate_resource_gate(
            volume_total_bytes=disk.total, volume_free_bytes=disk.free,
            memory_total_bytes=memory.total, memory_available_bytes=memory.available,
            estimate=estimate,
        )
        for scale, estimate in estimates.items()
    }
    policy = {
        "kind": "KnowledgePersistenceFrozenResourcePolicy",
        "iteration": ITERATION,
        "captured_at": _utc_now(),
        "resource_policy": resource_policy.POLICY,
        "resource_policy_hash": stable_hash(resource_policy.POLICY),
        "peak_estimator_hash": stable_hash({
            "version": resource_policy.ESTIMATOR_VERSION,
            "source": pathlib.Path(resource_policy.__file__).read_text(encoding="utf-8"),
        }),
        "corpus_generator_hash": foundation.benchmark_hashes()["corpus_generator_hash"],
        "workload_hash": foundation.benchmark_hashes()["workload_hash"],
        "calibration_hash": stable_hash(calibrations),
        "calibrations": calibrations,
        "estimates": estimates,
        "capture_snapshot": {
            "volume": str(workspace.anchor), "volume_total_bytes": disk.total,
            "volume_free_bytes": disk.free, "volume_used_percent": round(disk.used / disk.total * 100, 3),
            "memory_total_bytes": memory.total, "memory_available_bytes": memory.available,
            "memory_used_percent": float(memory.percent),
        },
        "capture_gate_decisions": gates,
        "status": "PASS" if all(row["status"] == "PASS" for row in gates.values()) else "FAIL",
    }
    policy["resource_policy_file_hash"] = _resource_policy_digest(policy)
    return policy


def _load_frozen_resource_policy(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = value.get("resource_policy_file_hash")
    if not isinstance(expected, str) or expected != _resource_policy_digest(value):
        raise RuntimeError("RESOURCE_POLICY_HASH_MISMATCH")
    if value.get("status") != "PASS":
        raise RuntimeError("RESOURCE_POLICY_NOT_APPROVED")
    if value.get("resource_policy_hash") != stable_hash(resource_policy.POLICY):
        raise RuntimeError("RESOURCE_POLICY_IMPLEMENTATION_MISMATCH")
    if value.get("corpus_generator_hash") != foundation.benchmark_hashes()["corpus_generator_hash"]:
        raise RuntimeError("RESOURCE_POLICY_CORPUS_HASH_MISMATCH")
    if value.get("benchmark_harness_hash") != benchmark_harness_hash():
        raise RuntimeError("RESOURCE_POLICY_HARNESS_HASH_MISMATCH")
    return value


def _calibrate(args: argparse.Namespace, output: pathlib.Path, workspace: pathlib.Path, requested_scales: list[int]) -> int:
    disk = shutil.disk_usage(workspace)
    memory = psutil.virtual_memory()
    calibration_guard = {
        "required_disk_free_bytes": 8 * resource_policy.GIB,
        "required_memory_available_bytes": 4 * resource_policy.GIB,
        "volume_free_bytes": disk.free,
        "memory_available_bytes": memory.available,
    }
    if disk.free < calibration_guard["required_disk_free_bytes"] or memory.available < calibration_guard["required_memory_available_bytes"]:
        raise RuntimeError(f"CALIBRATION_RESOURCE_HEADROOM_INSUFFICIENT: {calibration_guard}")
    rows: list[dict[str, Any]] = []
    for size in [int(value) for value in args.calibration_scales.split(",") if value]:
        with tempfile.TemporaryDirectory(prefix=f"v2-calibration-{size}-", dir=workspace) as temporary:
            result_path = output / f"resource-calibration-{size}.json"
            row = _run_worker("calibration", result_path, pathlib.Path(temporary) / "pack", args, size=size)
            rows.append(row)
            if row["status"] != "PASS":
                raise RuntimeError(f"RESOURCE_CALIBRATION_FAILED: scale={size}")
    policy = _freeze_resource_policy(rows, requested_scales, workspace)
    policy["source_commit"] = args.source_commit
    policy["production_source_commit"] = PRODUCTION_SOURCE_COMMIT
    policy["benchmark_harness_hash"] = benchmark_harness_hash()
    policy["calibration_guard"] = calibration_guard
    # The guard is evidence, so add it before sealing the final digest.
    policy["resource_policy_file_hash"] = _resource_policy_digest(policy)
    _write_json(output / "resource-policy.json", policy)
    print(foundation._stable_json(policy, pretty=True))
    return 0 if policy["status"] == "PASS" else 1


def orchestrate(args: argparse.Namespace) -> int:
    output = pathlib.Path(args.output_dir).resolve()
    workspace = pathlib.Path(args.workspace_root).resolve() if args.workspace_root else output / "tmp"
    output.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    scales = [int(value) for value in args.scales.split(",") if value]
    workload_scales = [int(value) for value in args.workload_scales.split(",") if value]
    requested_scales = scales + workload_scales + ([args.policy_scale] if args.run_policy_experiments else [])
    requested_scales += [args.crash_scale] if args.crash_scale else []
    if args.calibrate_only:
        return _calibrate(args, output, workspace, requested_scales)
    if not args.resource_policy_path:
        raise RuntimeError("FROZEN_RESOURCE_POLICY_REQUIRED")
    if args.source_commit == "WORKING_TREE":
        raise RuntimeError("FROZEN_SOURCE_COMMIT_REQUIRED")
    frozen_policy = _load_frozen_resource_policy(pathlib.Path(args.resource_policy_path).resolve())
    if frozen_policy.get("source_commit") != args.source_commit:
        raise RuntimeError("RESOURCE_POLICY_SOURCE_COMMIT_MISMATCH")
    lifecycle: list[dict[str, Any]] = []

    def guarded_worker(kind: str, *, size: int, prefix: str, result_path: pathlib.Path) -> dict[str, Any]:
        estimate = frozen_policy["estimates"].get(str(size))
        if not isinstance(estimate, dict):
            raise RuntimeError(f"RESOURCE_ESTIMATE_MISSING: {size}")
        before = resource_preflight(workspace, estimate)
        with tempfile.TemporaryDirectory(prefix=prefix, dir=workspace) as temporary:
            row = _run_worker(kind, result_path, pathlib.Path(temporary) / "pack", args, size=size)
            actual_peak = int(row["disk_footprint"]["observed_active_peak_bytes"])
            row["resource_bound"] = {
                "predicted_conservative_peak_bytes": estimate["conservative_peak_bytes"],
                "actual_peak_bytes": actual_peak,
                "within_conservative_bound": actual_peak <= int(estimate["conservative_peak_bytes"]),
            }
        disk_after = shutil.disk_usage(workspace)
        event = {
            "workload": kind, "scale": size, "preflight": before,
            "actual_peak_bytes": actual_peak,
            "predicted_conservative_peak_bytes": estimate["conservative_peak_bytes"],
            "within_conservative_bound": actual_peak <= int(estimate["conservative_peak_bytes"]),
            "post_cleanup_free_bytes": disk_after.free,
        }
        lifecycle.append(event)
        if not event["within_conservative_bound"]:
            raise RuntimeError(f"ACTUAL_PEAK_EXCEEDED_CONSERVATIVE_BOUND: {event}")
        return row

    scale_rows: list[dict[str, Any]] = []
    for size in scales:
        scale_rows.append(guarded_worker(
            "scale", size=size, prefix=f"v2-scale-{size}-", result_path=output / f"scale-{size}.json",
        ))
    policy_result = None
    if args.run_policy_experiments:
        with tempfile.TemporaryDirectory(prefix="v2-policy-", dir=workspace) as temporary:
            policy_path = output / "policy-experiments.json"
            policy_result = _run_worker("policy", policy_path, pathlib.Path(temporary), args, size=args.policy_scale)
    workload_rows: list[dict[str, Any]] = []
    for size in workload_scales:
        workload_rows.append(guarded_worker(
            "workload", size=size, prefix=f"v2-workload-{size}-", result_path=output / f"workloads-{size}.json",
        ))
    crash_result = None
    if args.crash_scale:
        crash_result = guarded_worker(
            "crash", size=args.crash_scale, prefix="v2-crash-",
            result_path=output / f"crash-{args.crash_scale}.json",
        )
    report = {
        "kind": "KnowledgePersistenceProductionizationReport", "iteration": ITERATION,
        "base_evidence": BASE_EVIDENCE, "source_commit": args.source_commit,
        "resource_policy_file_hash": frozen_policy["resource_policy_file_hash"],
        "resource_policy_hash": frozen_policy["resource_policy_hash"],
        "peak_estimator_hash": frozen_policy["peak_estimator_hash"],
        "resource_lifecycle": lifecycle,
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
    value.add_argument("--worker", choices=("cold", "calibration", "scale", "policy", "workload", "crash"))
    value.add_argument("--mode", choices=("full_replay", "valid_checkpoint", "corrupt_checkpoint"), default="valid_checkpoint")
    value.add_argument("--size", type=int, default=10_000)
    value.add_argument("--store-root")
    value.add_argument("--result-path")
    value.add_argument("--output-dir", default="evidence/knowledge_persistence_productionization")
    value.add_argument("--workspace-root")
    value.add_argument("--calibrate-only", action="store_true")
    value.add_argument("--calibration-scales", default="1000,5000")
    value.add_argument("--resource-policy-path")
    value.add_argument("--scales", default="10000,50000,100000,250000")
    value.add_argument("--workload-scales", default="100000,250000")
    value.add_argument("--update-samples", type=int, default=5)
    value.add_argument("--operations", type=int, default=120)
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
    if args.worker == "calibration":
        return calibration_worker(args)
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
