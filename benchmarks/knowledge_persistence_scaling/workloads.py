from __future__ import annotations

import argparse
import gc
import json
import pathlib
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

import psutil


ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from benchmarks.knowledge_persistence_scaling import alternatives, runner as base  # noqa: E402
from cgkn.application.conversation.service import ConversationRequest, ConversationService  # noqa: E402
from cgnk_knowledge.internalization import KnowledgeMaintenancePolicy, internalize_evidence  # noqa: E402


STRATEGIES = ("S0_CURRENT", "S2_APPEND_LOG")
WORKLOADS = ("read_heavy", "balanced", "write_heavy")


def workload_trace(name: str, operations: int = 1_000) -> list[str]:
    if name == "read_heavy":
        return ["UPDATE" if index % 11 == 10 else "QUERY" for index in range(operations)]
    if name == "balanced":
        return ["UPDATE" if index % 2 else "QUERY" for index in range(operations)]
    if name == "write_heavy":
        return ["QUERY" if index % 11 == 10 else "UPDATE" for index in range(operations)]
    raise ValueError(name)


def workload_hashes() -> dict[str, str]:
    return {name: base.stable_hash(workload_trace(name)) for name in WORKLOADS}


def prepare_worker(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.store_root)
    pack = base.generate_corpus(args.size, args.branches, "uniform")
    expected_hash = base.stable_hash(base.authoritative_projection(pack))
    if args.strategy == "S0_CURRENT":
        pack, metrics = base.measure_save(pack, root / "project_knowledge.json")
    else:
        metrics = alternatives.AppendLogStore(root).initialize(pack)
    result = {"expected_authority_hash": expected_hash, "initial_write": metrics}
    pathlib.Path(args.result_path).write_text(base._stable_json(result, pretty=True) + "\n", encoding="utf-8")
    return 0


def _load(strategy: str, root: pathlib.Path) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    if strategy == "S0_CURRENT":
        pack, detail = base._load_components(root / "project_knowledge.json")
    else:
        pack = alternatives.AppendLogStore(root).load()
        detail = {"total_cold_load_ms": (time.perf_counter() - started) * 1000}
    detail["measured_wall_ms"] = (time.perf_counter() - started) * 1000
    return pack, detail


def workload_worker(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.store_root)
    trace = workload_trace(args.workload, args.operations)
    with base.RssMonitor() as monitor:
        pack, load_metrics = _load(args.strategy, root)
        authority_at_start = base.stable_hash(base.authoritative_projection(pack))
        if authority_at_start != args.expected_authority_hash:
            raise ValueError("prepared authority hash mismatch")
        store = alternatives.AppendLogStore(root) if args.strategy == "S2_APPEND_LOG" else None
        internalization_ms: list[float] = []
        retrieval_ms: list[float] = []
        persistence_ms: list[float] = []
        rebuild_ms: list[float] = []
        serialization_ms: list[float] = []
        disk_ms: list[float] = []
        physical_bytes = 0
        logical_bytes = 0
        first_visibility: dict[str, Any] | None = None
        started_all = time.perf_counter()
        updates = 0
        queries = 0
        for operation_index, operation in enumerate(trace):
            if operation == "QUERY":
                queries += 1
                block_count = max(1, args.size // 100)
                target = (operation_index % block_count) * 100 + 20
                started = time.perf_counter()
                result = base.run_query(pack, {"goal": f"ident-{target:06d}"})
                retrieval_ms.append((time.perf_counter() - started) * 1000)
                if f"ki-{target:06d}" not in {str(row["id"]) for row in result["selected_items"]}:
                    raise ValueError("mixed workload retrieval recall failure")
                continue
            updates += 1
            branch = f"branch-{operation_index % args.branches:04d}"
            evidence = base._update_evidence(args.size * 10 + operation_index, branch)
            logical_bytes += len(base._stable_json(evidence).encode("utf-8"))
            started = time.perf_counter()
            result = internalize_evidence(pack, evidence, policy=KnowledgeMaintenancePolicy.LOCAL_LAZY)
            internalization_ms.append((time.perf_counter() - started) * 1000)
            pack = result["pack"]
            changed = [str(result["receipt"]["evidence_id"]), *map(str, result["receipt"]["nodes_invalidated"])]
            if args.strategy == "S0_CURRENT":
                pack, persistence = base.measure_save(pack, root / "project_knowledge.json")
                persistence_ms.append(float(persistence["total_save_ms"]))
                rebuild_ms.append(float(persistence["derived_index_rebuild_ms"]))
                serialization_ms.append(float(persistence["serialization_ms"]))
                disk_ms.append(float(persistence["disk_write_close_ms"]))
                physical_bytes += int(persistence["physical_written_bytes"])
            else:
                assert store is not None
                persistence = store.persist(pack, branch, sorted(set(changed)))
                persistence_ms.append(float(persistence["elapsed_ms"]))
                physical_bytes += int(persistence["bytes_written"])
            if first_visibility is None:
                query = base.run_query(pack, {"goal": evidence["content"]})
                response = ConversationService().answer(
                    ConversationRequest(evidence["content"]), pack, provider_enabled=False,
                )
                first_visibility = {
                    "relation": result["receipt"]["relation"],
                    "invalidated_nodes": result["receipt"]["nodes_invalidated"],
                    "recomputed_nodes": result["receipt"]["nodes_recomputed"],
                    "unrelated_nodes_touched": result["receipt"]["unrelated_nodes_touched"],
                    "retrieval_visible": str(result["receipt"]["evidence_id"]) in {str(row["id"]) for row in query["selected_items"]},
                    "conversation_visible": str(result["receipt"]["evidence_id"]) in {str(row["evidence_id"]) for row in response["evidence"]},
                    "conversation_status": response["status"],
                    "conversation_read_only": response["read_only"],
                }
        elapsed_ms = (time.perf_counter() - started_all) * 1000
        final_query = base.evaluate_queries(pack, base.query_cases(args.size, args.branches, "uniform"), repeats=2)
        steady = psutil.Process().memory_info().rss
    result = {
        "strategy": args.strategy, "scale": args.size, "branches": args.branches,
        "workload": args.workload, "operations": len(trace), "queries": queries, "updates": updates,
        "trace_hash": base.stable_hash(trace), "cold_load": load_metrics,
        "internalization_ms": base.summary(internalization_ms),
        "retrieval_ms": base.summary(retrieval_ms),
        "persistence_ms": base.summary(persistence_ms),
        "index_rebuild_ms": base.summary(rebuild_ms),
        "serialization_ms": base.summary(serialization_ms),
        "disk_io_ms": base.summary(disk_ms),
        "logical_changed_bytes": logical_bytes, "physical_written_bytes": physical_bytes,
        "persistence_write_amplification": physical_bytes / max(1, logical_bytes),
        "provider_calls": 0, "conversation_provider_ms": 0,
        "first_update_after_restart": first_visibility,
        "final_retrieval": final_query,
        "wall_ms": round(elapsed_ms, 3), "steady_rss_bytes": steady, "peak_rss_bytes": monitor.peak,
        "status": "PASS" if (
            len(trace) == args.operations and final_query["recall_pass"]
            and first_visibility is not None and first_visibility["retrieval_visible"]
            and first_visibility["conversation_visible"] and first_visibility["conversation_read_only"]
        ) else "FAIL",
    }
    pathlib.Path(args.result_path).write_text(base._stable_json(result, pretty=True) + "\n", encoding="utf-8")
    return 0


def _estimate_seconds(strategy: str, scale: int, workload: str, baseline: Mapping[str, Any], alternatives_report: Mapping[str, Any]) -> float:
    trace = workload_trace(workload)
    updates = trace.count("UPDATE")
    queries = trace.count("QUERY")
    if strategy == "S0_CURRENT":
        row = next(value for value in baseline["baseline_results"] if value["scale"] == scale and value["shape"] == "uniform")
        per_update = row["single_update"]["total_save_ms"]["p50"] + row["single_update"]["internalization_cpu_ms"]["p50"]
        per_query = row["retrieval_after_updates"]["latency_ms"]["p50"]
    else:
        row = next(value for value in alternatives_report["results"] if value["scale"] == scale and value["strategy"] == "S2_APPEND_LOG")
        per_update = row["single_update"]["persistence_ms"]["p50"] + row["single_update"]["internalization_ms"]["p50"]
        per_query = row["cold_restart"]["query"]["latency_ms"]["p50"]
    return (updates * per_update + queries * per_query) / 1000


def orchestrate(args: argparse.Namespace) -> int:
    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = pathlib.Path(args.workspace_root).resolve() if args.workspace_root else output_dir / "tmp"
    workspace_root.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(pathlib.Path(args.baseline_report).read_text(encoding="utf-8"))
    alternatives_report = json.loads(pathlib.Path(args.alternatives_report).read_text(encoding="utf-8"))
    sizes = [int(value) for value in args.scales.split(",") if value]
    plan: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        for size in sizes:
            for workload in WORKLOADS:
                projected = _estimate_seconds(strategy, size, workload, baseline, alternatives_report)
                admitted = strategy == "S2_APPEND_LOG" or projected <= args.current_max_projected_seconds
                entry = {
                    "strategy": strategy, "scale": size, "workload": workload,
                    "projected_seconds": round(projected, 3), "admitted": admitted,
                    "reason": "ADMITTED" if admitted else "RESOURCE_GUARD_PROJECTED_RUNTIME",
                }
                plan.append(entry)
                if not admitted:
                    continue
                with tempfile.TemporaryDirectory(prefix=f"mixed-{strategy.lower()}-{size}-{workload}-", dir=workspace_root) as tmp:
                    prepare_path = pathlib.Path(tmp) / "prepare.json"
                    prepare = [
                        sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "prepare",
                        "--strategy", strategy, "--store-root", tmp, "--result-path", str(prepare_path),
                        "--size", str(size), "--branches", str(base.branch_count_for(size)),
                    ]
                    completed = subprocess.run(prepare, cwd=ROOT, capture_output=True, text=True, timeout=args.worker_timeout)
                    if completed.returncode:
                        raise RuntimeError(completed.stderr[-3000:])
                    prepared = json.loads(prepare_path.read_text(encoding="utf-8"))
                    result_path = output_dir / f"{strategy.lower()}-{size}-{workload}.json"
                    command = [
                        sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "workload",
                        "--strategy", strategy, "--store-root", tmp, "--result-path", str(result_path),
                        "--size", str(size), "--branches", str(base.branch_count_for(size)),
                        "--workload", workload, "--operations", str(args.operations),
                        "--expected-authority-hash", prepared["expected_authority_hash"],
                    ]
                    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.worker_timeout)
                    if completed.returncode:
                        raise RuntimeError(completed.stderr[-4000:])
                    value = json.loads(result_path.read_text(encoding="utf-8"))
                    value["initial_write"] = prepared["initial_write"]
                    result_path.write_text(base._stable_json(value, pretty=True) + "\n", encoding="utf-8")
                    results.append(value)
    report = {
        "kind": "KnowledgePersistenceMixedWorkloads", "version": "1.0",
        "base_source": base.BASE_SOURCE, "workload_hashes": workload_hashes(),
        "operations_per_workload": args.operations,
        "current_runtime_guard_seconds": args.current_max_projected_seconds,
        "plan": plan, "results": results,
        "resource_guard_note": "Skipped S0 combinations use measured P50 costs; they are resource-bound projections, not product correctness failures.",
    }
    report_path = output_dir / "mixed-workloads-report.json"
    report_path.write_text(base._stable_json(report, pretty=True) + "\n", encoding="utf-8")
    print(base._stable_json({"report": str(report_path), "admitted": len(results), "planned": len(plan)}, pretty=True))
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--profile", default="workloads", choices=("workloads",))
    value.add_argument("--worker", choices=("prepare", "workload"))
    value.add_argument("--strategy", choices=STRATEGIES)
    value.add_argument("--workload", choices=WORKLOADS)
    value.add_argument("--operations", type=int, default=1_000)
    value.add_argument("--scales", default="10000,50000,100000")
    value.add_argument("--size", type=int)
    value.add_argument("--branches", type=int)
    value.add_argument("--store-root")
    value.add_argument("--result-path")
    value.add_argument("--output-dir", default=str(ROOT / "evidence" / "knowledge_persistence_workloads"))
    value.add_argument("--workspace-root")
    value.add_argument("--baseline-report", required=False)
    value.add_argument("--alternatives-report", required=False)
    value.add_argument("--expected-authority-hash", default="")
    value.add_argument("--current-max-projected-seconds", type=float, default=600.0)
    value.add_argument("--worker-timeout", type=int, default=1800)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.worker == "prepare":
        return prepare_worker(args)
    if args.worker == "workload":
        return workload_worker(args)
    if not args.baseline_report or not args.alternatives_report:
        raise ValueError("workload orchestration requires baseline and alternatives reports")
    return orchestrate(args)


if __name__ == "__main__":
    raise SystemExit(main())

