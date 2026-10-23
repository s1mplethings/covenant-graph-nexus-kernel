from __future__ import annotations

import argparse
import gc
import hashlib
import inspect
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import psutil


ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cgkn.application.conversation.service import (  # noqa: E402
    CONTEXT_POLICY,
    MODEL_CONFIG,
    RETRIEVAL_POLICY,
    ConversationRequest,
    ConversationService,
)
from cgnk_knowledge.internalization import (  # noqa: E402
    KnowledgeMaintenancePolicy,
    internalize_evidence,
)
from cgnk_knowledge.retrieve import retrieve_relevant_knowledge  # noqa: E402
from cgnk_knowledge.store import (  # noqa: E402
    ACTIVE_BUCKETS,
    rebuild_pack_indexes,
)


BASE_SOURCE = "b1c6eb9673fd20a2631e6a8f3a9206495dd1fef2"
BENCHMARK_VERSION = "1.0"
SHAPE_SPEC = {
    "uniform": "round-robin branches",
    "hot_branch_skew": "70 percent of items in the hottest 10 percent of branches",
    "long_tail": "deterministic cubic rank distribution",
}
WORKLOAD_SPEC = {
    "read_heavy": {"queries": 10, "updates": 1},
    "balanced": {"queries": 1, "updates": 1},
    "write_heavy": {"queries": 1, "updates": 10},
    "operations": 1000,
    "persistence": "save after every committed update",
}
PERSISTENCE_POLICY = {
    "authority": "ProjectKnowledgePack",
    "format": "single pretty UTF-8 JSON",
    "save": "rebuild_pack_indexes -> json.dumps -> Path.write_text",
    "load": "Path.read_text -> json.loads -> rebuild_pack_indexes",
    "fsync": False,
    "atomic_rename": False,
}


def _stable_json(value: Any, *, pretty: bool = False) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )


def stable_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def source_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(inspect.getsource(value).encode("utf-8")).hexdigest()


def percentile(values: Iterable[float], quantile: float) -> float | None:
    rows = sorted(float(value) for value in values)
    if not rows:
        return None
    position = max(0, min(len(rows) - 1, math.ceil(quantile * len(rows)) - 1))
    return round(rows[position], 3)


def summary(values: Iterable[float]) -> dict[str, float | int | None]:
    rows = list(values)
    return {
        "count": len(rows),
        "min": round(min(rows), 3) if rows else None,
        "p50": percentile(rows, 0.50),
        "p95": percentile(rows, 0.95),
        "max": round(max(rows), 3) if rows else None,
    }


@dataclass
class RssMonitor:
    interval_seconds: float = 0.01

    def __post_init__(self) -> None:
        self._process = psutil.Process()
        self.baseline = self._process.memory_info().rss
        self.peak = self.baseline
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.peak = max(self.peak, self._process.memory_info().rss)
            except psutil.Error:
                return

    def __enter__(self) -> "RssMonitor":
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        try:
            self.peak = max(self.peak, self._process.memory_info().rss)
        except psutil.Error:
            pass


def branch_count_for(size: int) -> int:
    if size <= 1_000:
        return 20
    if size <= 10_000:
        return 100
    if size <= 50_000:
        return 500
    return 1_000


def branch_index(position: int, size: int, branches: int, shape: str) -> int:
    if shape == "uniform":
        return position % branches
    if shape == "hot_branch_skew":
        hot = max(1, branches // 10)
        if position % 10 < 7:
            return position % hot
        return hot + (position % max(1, branches - hot))
    if shape == "long_tail":
        fraction = ((position * 2_654_435_761) % max(1, size)) / max(1, size)
        return min(branches - 1, int((fraction**3) * branches))
    raise ValueError(f"unsupported shape: {shape}")


def _item(position: int, size: int, branches: int, shape: str) -> dict[str, Any]:
    item_id = f"ki-{position:06d}"
    block, role = divmod(position, 100)
    branch = f"branch-{branch_index(position, size, branches, shape):04d}"
    content = f"ident-{position:06d} {branch} component-{position % 200:03d} value-{position % 997:03d}"
    item_type = ("research_finding", "requirement", "decision", "constraint", "test_result")[position % 5]
    item: dict[str, Any] = {
        "kind": "KnowledgeItem",
        "id": item_id,
        "title": f"fact-{position:06d}",
        "type": item_type,
        "scope": "project.cgnk",
        "content": content,
        "source_refs": [f"source:{position:06d}"],
        "tags": [branch, f"component-{position % 200:03d}"],
        "importance": ("critical", "high", "medium", "low")[position % 4],
        "need_state": ("needed_now", "needed_later", "unknown")[position % 3],
        "retention": "keep",
        "review_state": "accepted",
        "status": "active",
        "supersedes": [],
        "stable_hash": "",
        "content_hash": "",
        "semantic_hash": "",
        "evidence_kind": "raw",
        "subject_ref": f"subject-{block:06d}-{role % 20:02d}",
        "branch_ref": branch,
        "source_version": "1",
        "relations": [],
        "observation_count": 1,
        "revision": 1,
        "diagnostics": [],
    }
    if role == 0:
        item.update(
            content=f"ident-{position:06d} versioned-block-{block:06d} old-value",
            subject_ref=f"versioned-{block:06d}", source_version="1", status="superseded",
            review_state="rejected", retention="archive", superseded_by=f"ki-{position + 1:06d}",
            relations=[{"type": "superseded_by", "target_id": f"ki-{position + 1:06d}"}],
        )
    elif role == 1:
        item.update(
            content=f"ident-{position:06d} versioned-block-{block:06d} current-value",
            subject_ref=f"versioned-{block:06d}", source_version="2",
            supersedes=[f"ki-{position - 1:06d}"],
            relations=[{"type": "supersedes", "target_id": f"ki-{position - 1:06d}"}],
        )
    elif role in {2, 3}:
        other = position + 1 if role == 2 else position - 1
        item.update(
            content=f"ident-{position:06d} conflict-block-{block:06d} alternative-{role}",
            subject_ref=f"conflict-{block:06d}", review_state="conflict",
            relations=[{"type": "contradicts", "target_id": f"ki-{other:06d}"}],
        )
    elif role == 4:
        item.update(
            content=f"ident-{position:06d} retracted-block-{block:06d} invalid-claim",
            subject_ref=f"retracted-{block:06d}", status="retracted", review_state="rejected",
            retention="archive", relations=[{"type": "retracted_by", "target_id": f"ki-{position + 1:06d}"}],
        )
    elif role == 5:
        item.update(
            content=f"ident-{position:06d} retraction-block-{block:06d} tombstone",
            subject_ref=f"retracted-{block:06d}", evidence_kind="tombstone",
            relations=[{"type": "retracts", "target_id": f"ki-{position - 1:06d}"}],
        )
    elif role in {6, 7}:
        item.update(
            content=(f"ident-{position:06d} compose-block-{block:06d} detail-block-{block:06d} "
                     f"stale-fallback-block-{block:06d} raw-part-{role}"),
            subject_ref=f"composition-{block:06d}",
        )
    elif role == 8:
        item.update(
            content=f"ident-{position:06d} summary-block-{block:06d} compose-block-{block:06d}",
            source_refs=[f"ki-{position - 2:06d}", f"ki-{position - 1:06d}"], tags=[branch, "summary"],
            retention="compress", evidence_kind="derived", dependency_mode="explicit",
            derived_state="fresh", stale_due_to=[], refresh_count=0,
        )
    elif role == 9:
        item.update(
            content=f"ident-{position:06d} stale-fallback-block-{block:06d} stale-summary",
            source_refs=[f"ki-{position - 3:06d}", f"ki-{position - 2:06d}"], tags=[branch, "summary"],
            retention="compress", evidence_kind="derived", dependency_mode="explicit",
            derived_state="stale", stale_due_to=[f"ki-{position - 3:06d}"], refresh_count=0,
        )
    elif role == 10:
        item.update(
            content=f"ident-{position:06d} duplicate-observation-block-{block:06d}",
            source_refs=[f"source:{position:06d}:a", f"source:{position:06d}:b"], observation_count=3,
        )
    elif role == 11:
        item.update(
            content=f"ident-{position:06d} supporting-block-{block:06d}",
            subject_ref=f"composition-{block:06d}",
            relations=[{"type": "supports", "target_id": f"ki-{position - 5:06d}"}],
        )
    elif role == 12:
        item.update(content=f"ident-{position:06d} domain-alpha-unique", tags=[branch, "domain-alpha"])
    elif role == 13:
        item.update(content=f"ident-{position:06d} durable persistence storage", tags=[branch, "durability"])
    elif role in {14, 15}:
        item.update(content=f"ident-{position:06d} similar-service shared-name {branch}")
    elif role == 16:
        item.update(
            content=f"ident-{position:06d} historical-block-{block:06d}", status="archived", retention="archive",
        )
    digest = "sha256:" + hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
    item["stable_hash"] = digest
    item["content_hash"] = digest
    item["semantic_hash"] = digest
    return item


def generate_corpus(size: int, branches: int, shape: str) -> dict[str, Any]:
    if size < 100 or branches < 1 or branches > size:
        raise ValueError("size must be >=100 and branches must be within the corpus")
    pack = {
        "kind": "ProjectKnowledgePack",
        "id": f"pkp_scaling_{size}_{shape}",
        "project": "CGKN persistence scaling",
        "version": "1",
        **{bucket: [] for bucket in ACTIVE_BUCKETS.values()},
        "archived_items": [],
        "discarded_items": [],
        "all_items": [_item(position, size, branches, shape) for position in range(size)],
        "diagnostics": [],
        "knowledge_revision": size,
        "knowledge_index": {},
    }
    return rebuild_pack_indexes(pack)


def authoritative_projection(pack: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": pack.get("kind"),
        "id": pack.get("id"),
        "project": pack.get("project"),
        "version": pack.get("version"),
        "knowledge_revision": pack.get("knowledge_revision"),
        "diagnostics": pack.get("diagnostics", []),
        "all_items": sorted((dict(row) for row in pack.get("all_items", [])), key=lambda row: str(row.get("id"))),
    }


def corpus_counts(pack: Mapping[str, Any]) -> dict[str, int]:
    rows = list(pack.get("all_items", []))
    derived = sum(row.get("evidence_kind") == "derived" for row in rows)
    return {
        "items": len(rows),
        "authoritative_items": len(rows) - derived,
        "derived_items": derived,
        "stale_items": sum(row.get("derived_state") == "stale" for row in rows),
        "superseded_items": sum(row.get("status") == "superseded" for row in rows),
        "retracted_items": sum(row.get("status") == "retracted" for row in rows),
        "contradiction_items": sum(row.get("review_state") == "conflict" for row in rows),
        "multi_source_items": sum(len(row.get("source_refs", [])) > 1 for row in rows),
    }


def query_cases(size: int, branches: int, shape: str) -> list[dict[str, Any]]:
    branch_14 = f"branch-{branch_index(14, size, branches, shape):04d}"
    synonym_equivalents = [f"ki-{position:06d}" for position in range(13, size, 100)]
    similar_in_branch = [
        f"ki-{position:06d}"
        for block in range((size + 99) // 100)
        for position in (block * 100 + 14, block * 100 + 15)
        if position < size and branch_index(position, size, branches, shape) == branch_index(14, size, branches, shape)
    ]
    return [
        {"name": "simple_local_fact", "goal": "ident-000010", "expected": ["ki-000010"]},
        {"name": "bottom_up_raw_detail", "goal": "detail-block-000000", "expected": ["ki-000006", "ki-000007"]},
        {"name": "two_node_composition", "goal": "compose-block-000000", "expected": ["ki-000006", "ki-000007"]},
        {"name": "superseded_fact", "goal": "versioned-block-000000", "expected": ["ki-000001"], "forbidden": ["ki-000000"]},
        {"name": "contradiction", "goal": "conflict-block-000000", "expected": ["ki-000002", "ki-000003"]},
        {"name": "cross_domain_isolation", "goal": "domain-alpha-unique", "expected": ["ki-000012"]},
        {"name": "stale_summary_raw_fallback", "goal": "stale-fallback-block-000000", "expected": ["ki-000006", "ki-000007"], "forbidden": ["ki-000009"]},
        {"name": "no_evidence", "goal": "utterly-absent-zebra", "expected_empty": True},
        {"name": "synonym_wording", "goal": "durable storage", "expected_any": synonym_equivalents},
        {"name": "ambiguous_similar_names", "goal": f"shared-name {branch_14}", "expected_any": similar_in_branch},
        {"name": "version_query", "goal": "versioned-block-000000 current-value", "expected": ["ki-000001"], "forbidden": ["ki-000000"]},
        {"name": "historical_query", "goal": "historical-block-000000", "expected": ["ki-000016"], "include_archived": True},
    ]


def run_query(pack: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    return retrieve_relevant_knowledge(
        dict(pack),
        {
            "kind": "KnowledgeRetrievalQuery",
            "goal": case["goal"],
            "selected_modules": [],
            "needed_types": [],
            "include_uncertain": True,
            "include_archived": bool(case.get("include_archived", False)),
            "require_relevance": True,
            "max_items": 8,
        },
    )


def evaluate_queries(pack: Mapping[str, Any], cases: list[dict[str, Any]], repeats: int = 7) -> dict[str, Any]:
    case_rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for case in cases:
        started = time.perf_counter()
        result = run_query(pack, case)
        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)
        selected = [str(row.get("id")) for row in result["selected_items"]]
        expected = set(map(str, case.get("expected", [])))
        expected_any = set(map(str, case.get("expected_any", [])))
        forbidden = set(map(str, case.get("forbidden", [])))
        correct = (
            (not case.get("expected_empty") or not selected)
            and expected.issubset(selected)
            and (not expected_any or bool(expected_any.intersection(selected)))
            and not forbidden.intersection(selected)
        )
        case_rows.append(
            {
                "name": case["name"],
                "selected_ids": selected,
                "expected_ids": sorted(expected),
                "expected_any_count": len(expected_any),
                "correct": correct,
                "candidate_count": result["metrics"]["candidates_evaluated"],
                "selected_count": result["metrics"]["selected_items"],
                "irrelevant_count": sum(row["reason"] == "low_relevance" for row in result["excluded_items"]),
                "excluded_count": len(result["excluded_items"]),
                "latency_ms": round(elapsed, 3),
            }
        )
    for _ in range(max(0, repeats - 1)):
        for case in cases:
            started = time.perf_counter()
            run_query(pack, case)
            latencies.append((time.perf_counter() - started) * 1000)
    return {
        "cases": case_rows,
        "accuracy": sum(row["correct"] for row in case_rows) / len(case_rows),
        "recall_pass": all(row["correct"] for row in case_rows),
        "latency_ms": summary(latencies),
        "candidate_p50": percentile([row["candidate_count"] for row in case_rows], 0.50),
        "candidate_p95": percentile([row["candidate_count"] for row in case_rows], 0.95),
        "candidate_max": max(row["candidate_count"] for row in case_rows),
        "locality_ratio_max": max(row["candidate_count"] for row in case_rows) / max(1, len(pack.get("all_items", []))),
        "result_hash": stable_hash([(row["name"], row["selected_ids"], row["correct"]) for row in case_rows]),
    }


def measure_save(pack: dict[str, Any], path: pathlib.Path) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    clean = rebuild_pack_indexes(dict(pack))
    rebuild_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    payload = _stable_json(clean, pretty=True) + "\n"
    serialization_ms = (time.perf_counter() - started) * 1000
    payload_bytes = len(payload.encode("utf-8"))
    started = time.perf_counter()
    path.write_text(payload, encoding="utf-8")
    disk_write_ms = (time.perf_counter() - started) * 1000
    return clean, {
        "derived_index_rebuild_ms": round(rebuild_ms, 3),
        "serialization_ms": round(serialization_ms, 3),
        "disk_write_close_ms": round(disk_write_ms, 3),
        "total_save_ms": round(rebuild_ms + serialization_ms + disk_write_ms, 3),
        "serialized_bytes": payload_bytes,
        "file_bytes": path.stat().st_size,
        "physical_written_bytes": path.stat().st_size,
        "file_count": 1,
        "temporary_disk_amplification": 0.0,
    }


def _update_evidence(position: int, branch: str) -> dict[str, Any]:
    return {
        "content": f"persistent local update {position:08d} for {branch}",
        "item_type": "research_finding",
        "scope": "project.cgnk",
        "source_ref": f"benchmark:update:{position:08d}",
        "subject_ref": f"benchmark-update-{position:08d}",
        "branch_ref": branch,
        "source_version": "1",
        "importance": "high",
        "need_state": "needed_now",
        "tags": [branch, "benchmark-update"],
    }


def _single_update_series(pack: dict[str, Any], path: pathlib.Path, count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    update_ms: list[float] = []
    rebuild_ms: list[float] = []
    serialization_ms: list[float] = []
    write_ms: list[float] = []
    save_ms: list[float] = []
    write_amplification: list[float] = []
    receipts: list[dict[str, Any]] = []
    for offset in range(count):
        evidence = _update_evidence(offset, f"branch-{offset:04d}")
        logical_bytes = len(_stable_json(evidence).encode("utf-8"))
        started = time.perf_counter()
        result = internalize_evidence(pack, evidence, policy=KnowledgeMaintenancePolicy.LOCAL_LAZY)
        update_ms.append((time.perf_counter() - started) * 1000)
        pack = result["pack"]
        pack, persistence = measure_save(pack, path)
        rebuild_ms.append(persistence["derived_index_rebuild_ms"])
        serialization_ms.append(persistence["serialization_ms"])
        write_ms.append(persistence["disk_write_close_ms"])
        save_ms.append(persistence["total_save_ms"])
        write_amplification.append(persistence["physical_written_bytes"] / max(1, logical_bytes))
        receipts.append(
            {
                "relation": result["receipt"]["relation"],
                "invalidated_nodes": len(result["receipt"]["nodes_invalidated"]),
                "recomputed_nodes": len(result["receipt"]["nodes_recomputed"]),
                "unrelated_nodes_touched": result["receipt"]["unrelated_nodes_touched"],
                "logical_changed_bytes": logical_bytes,
                "physical_written_bytes": persistence["physical_written_bytes"],
            }
        )
    return pack, {
        "count": count,
        "internalization_cpu_ms": summary(update_ms),
        "derived_index_rebuild_ms": summary(rebuild_ms),
        "serialization_ms": summary(serialization_ms),
        "disk_write_close_ms": summary(write_ms),
        "total_save_ms": summary(save_ms),
        "persistence_write_amplification": summary(write_amplification),
        "serialization_amplification": summary(write_amplification),
        "receipts": receipts,
    }


def _load_components(path: pathlib.Path) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    raw = path.read_bytes()
    read_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    text = raw.decode("utf-8")
    decode_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    data = json.loads(text)
    parse_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    pack = rebuild_pack_indexes(data)
    rebuild_ms = (time.perf_counter() - started) * 1000
    return pack, {
        "cold_read_ms": round(read_ms, 3),
        "utf8_decode_ms": round(decode_ms, 3),
        "json_parse_ms": round(parse_ms, 3),
        "derived_index_rebuild_ms": round(rebuild_ms, 3),
        "total_cold_load_ms": round(read_ms + decode_ms + parse_ms + rebuild_ms, 3),
    }


def cold_worker(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.pack_path)
    output = pathlib.Path(args.result_path)
    with RssMonitor() as monitor:
        pack, load = _load_components(path)
        after_load_rss = psutil.Process().memory_info().rss
        cases = query_cases(args.size, args.branches, args.shape)
        started = time.perf_counter()
        first_result = run_query(pack, cases[0])
        first_retrieval_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        response = ConversationService().answer(
            ConversationRequest(str(cases[0]["goal"])), pack, provider_enabled=False,
        )
        first_conversation_ms = (time.perf_counter() - started) * 1000
        query_metrics = evaluate_queries(pack, cases)
        authority_hash = stable_hash(authoritative_projection(pack))
        state = {
            "authority_hash": authority_hash,
            "authority_equivalent": authority_hash == args.expected_authority_hash,
            "query_equivalent": query_metrics["result_hash"] == args.expected_query_hash,
            "first_retrieval_selected": [row["id"] for row in first_result["selected_items"]],
            "conversation_status": response["status"],
            "conversation_evidence_ids": [row["evidence_id"] for row in response["evidence"]],
            "conversation_provenance_count": len(response["provenance"]),
            "conversation_read_only": response["read_only"],
        }
    value = {
        "process_id": os.getpid(),
        **load,
        "first_retrieval_ms": round(first_retrieval_ms, 3),
        "first_conversation_ms": round(first_conversation_ms, 3),
        "time_to_first_retrieval_ms": round(load["total_cold_load_ms"] + first_retrieval_ms, 3),
        "time_to_first_answer_ms": round(load["total_cold_load_ms"] + first_conversation_ms, 3),
        "steady_rss_bytes": after_load_rss,
        "peak_rss_bytes": monitor.peak,
        "query_after_load": query_metrics,
        "restart_correctness": state,
    }
    output.write_text(_stable_json(value, pretty=True) + "\n", encoding="utf-8")
    return 0


def scale_worker(args: argparse.Namespace) -> int:
    output = pathlib.Path(args.result_path)
    workspace_root = pathlib.Path(args.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    started_all = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix=f"pkp-{args.size}-{args.shape}-", dir=workspace_root) as tmp:
        pack_path = pathlib.Path(tmp) / "project_knowledge.json"
        with RssMonitor() as monitor:
            started = time.perf_counter()
            pack = generate_corpus(args.size, args.branches, args.shape)
            generation_ms = (time.perf_counter() - started) * 1000
            counts = corpus_counts(pack)
            cases = query_cases(args.size, args.branches, args.shape)
            pre_query = evaluate_queries(pack, cases)
            pack, initial_save = measure_save(pack, pack_path)
            authoritative_bytes = len(_stable_json(authoritative_projection(pack)).encode("utf-8"))
            index_bytes = len(_stable_json(pack["knowledge_index"]).encode("utf-8"))
            bucket_bytes = sum(len(_stable_json(pack[bucket]).encode("utf-8")) for bucket in (*ACTIVE_BUCKETS.values(), "archived_items", "discarded_items"))
            pack, updates = _single_update_series(pack, pack_path, args.update_samples)
            post_query = evaluate_queries(pack, cases)
            expected_authority_hash = stable_hash(authoritative_projection(pack))
            expected_query_hash = post_query["result_hash"]
            steady_rss = psutil.Process().memory_info().rss
            del pack
            gc.collect()
            cold_result_path = pathlib.Path(tmp) / "cold_result.json"
            command = [
                sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "cold",
                "--pack-path", str(pack_path), "--result-path", str(cold_result_path),
                "--size", str(args.size), "--branches", str(args.branches), "--shape", args.shape,
                "--expected-authority-hash", expected_authority_hash,
                "--expected-query-hash", expected_query_hash,
            ]
            cold_started = time.perf_counter()
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.worker_timeout)
            cold_process_wall_ms = (time.perf_counter() - cold_started) * 1000
            if completed.returncode != 0:
                raise RuntimeError(f"cold worker failed: {completed.stderr[-2000:]}")
            cold = json.loads(cold_result_path.read_text(encoding="utf-8"))
        result = {
            "benchmark_version": BENCHMARK_VERSION,
            "base_source": BASE_SOURCE,
            "scale": args.size,
            "branch_count": args.branches,
            "shape": args.shape,
            "generation_ms": round(generation_ms, 3),
            "counts": counts,
            "storage": {
                **initial_save,
                "authoritative_projection_bytes": authoritative_bytes,
                "derived_index_bytes": index_bytes,
                "compatibility_bucket_bytes": bucket_bytes,
                "serialized_to_authority_ratio": initial_save["serialized_bytes"] / max(1, authoritative_bytes),
            },
            "single_update": updates,
            "retrieval_before_save": pre_query,
            "retrieval_after_updates": post_query,
            "cold_restart": cold,
            "cold_worker_wall_ms": round(cold_process_wall_ms, 3),
            "parent_steady_rss_bytes_before_release": steady_rss,
            "parent_peak_rss_bytes": monitor.peak,
            "total_worker_wall_ms": round((time.perf_counter() - started_all) * 1000, 3),
            "status": "PASS" if (
                pre_query["recall_pass"] and post_query["recall_pass"]
                and cold["restart_correctness"]["authority_equivalent"]
                and cold["restart_correctness"]["query_equivalent"]
            ) else "FAIL",
        }
    output.write_text(_stable_json(result, pretty=True) + "\n", encoding="utf-8")
    return 0


def crash_safety_probe(workspace_root: pathlib.Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pkp-crash-", dir=workspace_root) as tmp:
        target = pathlib.Path(tmp) / "authority.json"
        pack = generate_corpus(100, 20, "uniform")
        pack, _ = measure_save(pack, target)
        original = target.read_bytes()
        partial = pathlib.Path(tmp) / "authority.partial.json"
        partial.write_bytes(original[: len(original) // 2])
        try:
            _load_components(partial)
            partial_detected = False
        except json.JSONDecodeError:
            partial_detected = True
        corrupt_index = json.loads(original.decode("utf-8"))
        corrupt_index["knowledge_index"] = {"kind": "KnowledgeIndex", "schema_version": "1.0", "pack_revision": -1}
        index_path = pathlib.Path(tmp) / "corrupt-index.json"
        index_path.write_text(_stable_json(corrupt_index, pretty=True), encoding="utf-8")
        rebuilt, _ = _load_components(index_path)
        derived_rebuilt = rebuilt["knowledge_index"]["item_count"] == 100
        tampered = json.loads(original.decode("utf-8"))
        tampered["all_items"][0]["content"] = "silently tampered but valid JSON"
        tampered_path = pathlib.Path(tmp) / "tampered.json"
        tampered_path.write_text(_stable_json(tampered, pretty=True), encoding="utf-8")
        loaded_tampered, _ = _load_components(tampered_path)
        checksum_detected = loaded_tampered["all_items"][0]["content"] != "silently tampered but valid JSON"
        return {
            "write_interrupted_before_commit": "UNSAFE_DIRECT_OVERWRITE",
            "partial_json_detected": partial_detected,
            "partial_write_recovery": False,
            "temporary_file_strategy": "NOT_IMPLEMENTED",
            "checksum_present": False,
            "valid_json_tamper_detected": checksum_detected,
            "corrupt_derived_index_rebuilt": derived_rebuilt,
            "stale_sidecar_behavior": "NOT_APPLICABLE_NO_SIDECAR",
            "authoritative_state_silent_corruption_guard": "FAIL",
        }


def benchmark_hashes() -> dict[str, str]:
    return {
        "corpus_generator_hash": source_hash(generate_corpus),
        "corpus_shape_hash": stable_hash(SHAPE_SPEC),
        "queryset_hash": source_hash(query_cases),
        "workload_hash": stable_hash(WORKLOAD_SPEC),
        "persistence_policy_hash": stable_hash(PERSISTENCE_POLICY),
        "retrieval_policy_hash": stable_hash(RETRIEVAL_POLICY),
        "context_policy_hash": stable_hash(CONTEXT_POLICY),
        "model_config_hash": stable_hash(MODEL_CONFIG),
    }


def _run_child(command: list[str], timeout: int) -> None:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError(f"benchmark worker failed ({completed.returncode}): {completed.stderr[-4000:]}")


def orchestrate(args: argparse.Namespace) -> int:
    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = pathlib.Path(args.workspace_root).resolve() if args.workspace_root else output_dir / "tmp"
    workspace_root.mkdir(parents=True, exist_ok=True)
    initial_memory = psutil.virtual_memory()
    initial_disk = shutil.disk_usage(workspace_root)
    sizes = [int(value) for value in args.scales.split(",") if value.strip()]
    matrix = [(size, "uniform") for size in sizes]
    if args.skew_scale in sizes:
        matrix.extend([(args.skew_scale, "hot_branch_skew"), (args.skew_scale, "long_tail")])
    results: list[dict[str, Any]] = []
    resource_events: list[dict[str, Any]] = []
    for size, shape in matrix:
        branches = branch_count_for(size)
        result_path = output_dir / f"scale-{size}-{shape}.json"
        command = [
            sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "scale",
            "--result-path", str(result_path), "--workspace-root", str(workspace_root),
            "--size", str(size), "--branches", str(branches), "--shape", shape,
            "--update-samples", str(args.update_samples), "--worker-timeout", str(args.worker_timeout),
        ]
        _run_child(command, args.worker_timeout + 60)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        results.append(result)
        if result["parent_peak_rss_bytes"] >= int(initial_memory.available * args.resource_fraction):
            resource_events.append({"scale": size, "shape": shape, "reason": "PEAK_RSS_GUARD"})
        if result["storage"]["file_bytes"] >= int(initial_disk.free * args.resource_fraction):
            resource_events.append({"scale": size, "shape": shape, "reason": "ARTIFACT_DISK_GUARD"})
    if args.try_250k and 100_000 in sizes:
        base = next(row for row in results if row["scale"] == 100_000 and row["shape"] == "uniform")
        projected_rss = base["parent_peak_rss_bytes"] * 2.5
        projected_file = base["storage"]["file_bytes"] * 2.5
        projected_save = base["single_update"]["total_save_ms"]["p95"] * 2.5
        safe = (
            projected_rss < initial_memory.available * args.resource_fraction
            and projected_file < initial_disk.free * 0.50
            and projected_save < 180_000
            and not resource_events
        )
        if safe:
            result_path = output_dir / "scale-250000-uniform.json"
            command = [
                sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "scale",
                "--result-path", str(result_path), "--workspace-root", str(workspace_root),
                "--size", "250000", "--branches", "1000", "--shape", "uniform",
                "--update-samples", str(max(3, args.update_samples // 2)), "--worker-timeout", str(args.worker_timeout),
            ]
            _run_child(command, args.worker_timeout + 60)
            results.append(json.loads(result_path.read_text(encoding="utf-8")))
        else:
            resource_events.append(
                {
                    "scale": 250_000,
                    "shape": "uniform",
                    "reason": "RESOURCE_BOUND_NOT_PRODUCT_FAILURE",
                    "projected_peak_rss_bytes": projected_rss,
                    "projected_file_bytes": projected_file,
                    "projected_save_p95_ms": projected_save,
                }
            )
    uniform = [row for row in results if row["shape"] == "uniform"]
    locality_gap = False
    if len(uniform) >= 3:
        first, last = uniform[0], uniform[-1]
        size_growth = last["scale"] / first["scale"]
        save_growth = last["single_update"]["total_save_ms"]["p50"] / max(0.001, first["single_update"]["total_save_ms"]["p50"])
        update_growth = last["single_update"]["internalization_cpu_ms"]["p50"] / max(0.001, first["single_update"]["internalization_cpu_ms"]["p50"])
        persistence_share = last["single_update"]["total_save_ms"]["p50"] / max(
            0.001,
            last["single_update"]["total_save_ms"]["p50"] + last["single_update"]["internalization_cpu_ms"]["p50"],
        )
        locality_gap = save_growth >= max(3.0, size_growth * 0.25) and persistence_share >= 0.80
        scaling = {
            "size_growth": size_growth,
            "save_p50_growth": save_growth,
            "internalization_p50_growth": update_growth,
            "largest_persistence_wall_share": persistence_share,
            "persistence_locality_gap": "PROVEN" if locality_gap else "NOT_PROVEN",
        }
    else:
        scaling = {"persistence_locality_gap": "NOT_EVALUATED"}
    report = {
        "kind": "KnowledgePersistenceScalingBenchmark",
        "benchmark_version": BENCHMARK_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_source": BASE_SOURCE,
        "hashes": benchmark_hashes(),
        "resource_guard": {
            "fraction": args.resource_fraction,
            "initial_available_ram_bytes": initial_memory.available,
            "initial_total_ram_bytes": initial_memory.total,
            "initial_disk_free_bytes": initial_disk.free,
            "events": resource_events,
        },
        "matrix": [{"scale": row["scale"], "shape": row["shape"], "status": row["status"]} for row in results],
        "scaling": scaling,
        "crash_safety": crash_safety_probe(workspace_root),
        "baseline_results": results,
        "production_source_modified": False,
        "storage_alternatives_started": locality_gap,
    }
    report_path = output_dir / "baseline-report.json"
    report_path.write_text(_stable_json(report, pretty=True) + "\n", encoding="utf-8")
    print(_stable_json({"report": str(report_path), "scaling": scaling, "matrix": report["matrix"]}, pretty=True))
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Benchmark ProjectKnowledgePack physical persistence and retrieval scaling")
    value.add_argument("--worker", choices=("scale", "cold"))
    value.add_argument("--profile", default="baseline", choices=("baseline",))
    value.add_argument("--output-dir", default=str(ROOT / "evidence" / "knowledge_persistence_scaling"))
    value.add_argument("--workspace-root")
    value.add_argument("--scales", default="1000,5000,10000,50000,100000")
    value.add_argument("--skew-scale", type=int, default=10000)
    value.add_argument("--try-250k", action="store_true")
    value.add_argument("--update-samples", type=int, default=5)
    value.add_argument("--resource-fraction", type=float, default=0.75)
    value.add_argument("--worker-timeout", type=int, default=1800)
    value.add_argument("--result-path")
    value.add_argument("--pack-path")
    value.add_argument("--size", type=int)
    value.add_argument("--branches", type=int)
    value.add_argument("--shape", choices=tuple(SHAPE_SPEC))
    value.add_argument("--expected-authority-hash", default="")
    value.add_argument("--expected-query-hash", default="")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.worker == "cold":
        return cold_worker(args)
    if args.worker == "scale":
        return scale_worker(args)
    return orchestrate(args)


if __name__ == "__main__":
    raise SystemExit(main())

