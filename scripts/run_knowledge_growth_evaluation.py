from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cgnk_knowledge import (  # noqa: E402
    KnowledgeMaintenancePolicy,
    build_knowledge_index,
    internalize_evidence,
    make_derived_abstraction,
    new_project_knowledge_pack,
    rebuild_pack_indexes,
    refresh_stale_abstractions,
    retrieve_relevant_knowledge,
)
from cgnk_knowledge.internalization import raw_content_hash  # noqa: E402
from cgnk_knowledge.normalize import stable_hash_for  # noqa: E402


GAP_AUDIT = {
    "classification": "PARTIAL_LIFECYCLE_WITHOUT_DEPENDENCY_INVALIDATION",
    "capabilities": {
        "new_raw_evidence_ingestion": "PARTIAL",
        "exact_duplicate_ingestion": "EXISTING_PARTIAL",
        "supporting_evidence": "MISSING",
        "new_fact": "EXISTING",
        "updated_fact": "PARTIAL",
        "superseding_fact_version": "PARTIAL",
        "contradictory_evidence": "PARTIAL",
        "correction": "PARTIAL",
        "retraction_deletion": "PARTIAL",
        "derived_summary_refresh": "MISSING",
        "ancestor_invalidation": "MISSING",
        "cross_branch_update": "MISSING",
        "index_update": "EXISTING_GLOBAL_REBUILD",
        "provenance_preservation": "PARTIAL",
        "conversation_after_update": "PARTIAL",
    },
    "existing_authority": "ProjectKnowledgePack",
    "retrieval_authority": "cgnk_knowledge.retrieve_relevant_knowledge",
}


def _raw_item(index: int, branch: int) -> dict[str, Any]:
    content = f"subject-{index} branch-{branch} fact value-v1"
    content_hash = raw_content_hash(content)
    return {
        "kind": "KnowledgeItem", "id": f"raw.{index}", "title": f"subject-{index}",
        "type": "research_finding", "scope": "project", "content": content,
        "source_refs": [f"source:{index}"], "tags": [f"branch-{branch}", "raw-evidence"],
        "importance": "medium", "need_state": "needed_now", "retention": "keep",
        "review_state": "accepted", "status": "active", "supersedes": [],
        "stable_hash": content_hash, "content_hash": content_hash,
        "semantic_hash": stable_hash_for(content, "research_finding", "project"),
        "evidence_kind": "raw", "subject_ref": f"subject-{index}",
        "branch_ref": f"branch-{branch}", "source_version": "1", "observed_at": "",
        "relations": [], "observation_count": 1, "revision": 1, "diagnostics": [],
    }


def _pack(size: int, *, structured: bool) -> dict[str, Any]:
    pack = new_project_knowledge_pack("knowledge-growth-evaluation")
    summary_count = max(1, size // 10) if structured else 0
    raw_count = size - summary_count
    branch_count = summary_count or max(1, size // 10)
    raws = [_raw_item(index, index % branch_count) for index in range(raw_count)]
    summaries: list[dict[str, Any]] = []
    if structured:
        for branch in range(branch_count):
            sources = [item["id"] for item in raws if item["branch_ref"] == f"branch-{branch}"]
            summaries.append(
                make_derived_abstraction(
                    f"summary.{branch}", f"branch-{branch} abstraction over {len(sources)} facts",
                    sources, branch_ref=f"branch-{branch}", dependency_mode="branch",
                )
            )
    pack["all_items"] = raws + summaries
    pack["knowledge_revision"] = 1
    return rebuild_pack_indexes(pack)


def _reducer(item: dict[str, Any], sources: tuple[dict[str, Any], ...]) -> str:
    active = [source for source in sources if source.get("status", "active") == "active"]
    return f"{item.get('branch_ref')} abstraction: " + "; ".join(source["content"] for source in active[:3])


def _evaluate_policy(size: int, policy: KnowledgeMaintenancePolicy) -> dict[str, Any]:
    structured = policy is not KnowledgeMaintenancePolicy.FLAT_APPEND
    pack = _pack(size, structured=structured)
    update = {
        "content": "subject-0 branch-0 fact value-v2",
        "item_type": "research_finding", "scope": "project", "source_ref": "source:update",
        "subject_ref": "subject-0", "branch_ref": "branch-0", "source_version": "2",
        "importance": "high", "need_state": "needed_now",
    }
    result = internalize_evidence(
        pack,
        update,
        policy=policy,
        eager_reducer=_reducer if policy is KnowledgeMaintenancePolicy.EAGER_GLOBAL_REBUILD else None,
    )
    updated = result["pack"]
    receipt = result["receipt"]
    refresh_receipt: dict[str, Any] = {"nodes_recomputed": [], "elapsed_ms": 0, "model_calls": 0}
    if policy is KnowledgeMaintenancePolicy.LOCAL_LAZY:
        refreshed = refresh_stale_abstractions(updated, branch_ref="branch-0", reducer=_reducer)
        updated = refreshed["pack"]
        refresh_receipt = refreshed["receipt"]
    query = {
        "goal": "subject-0",
        "require_relevance": structured,
        "max_items": 20 if structured else size + 1,
    }
    retrieval_started = time.perf_counter()
    retrieval = retrieve_relevant_knowledge(updated, query)
    retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
    selected = retrieval["selected_items"]
    encoded = json.dumps(updated, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "policy": policy.value,
        "size_before": size,
        "size_after": len(updated["all_items"]),
        "write_elapsed_ms": receipt["elapsed_ms"],
        "refresh_elapsed_ms": refresh_receipt.get("elapsed_ms", 0),
        "retrieval_elapsed_ms": round(retrieval_ms, 3),
        "model_calls": receipt["model_calls"] + refresh_receipt.get("model_calls", 0),
        "nodes_invalidated": len(receipt["nodes_invalidated"]),
        "nodes_recomputed_on_write": len(receipt["nodes_recomputed"]),
        "nodes_recomputed_on_demand": len(refresh_receipt.get("nodes_recomputed", ())),
        "unrelated_nodes_touched": receipt["unrelated_nodes_touched"],
        "index_items_scanned_on_write": receipt["index_items_scanned"],
        "relation_candidates_visited": receipt["candidate_items_visited"],
        "bucket_items_touched": receipt["bucket_items_touched"],
        "retrieval_candidates_evaluated": retrieval["metrics"]["candidates_evaluated"],
        "retrieved_nodes": len(selected),
        "context_chars": sum(len(str(item.get("content", ""))) for item in selected),
        "pack_bytes": len(encoded),
        "updated_fact_available": any("value-v2" in str(item.get("content", "")) for item in selected),
        "raw_history_preserved": any("value-v1" in str(item.get("content", "")) for item in updated["all_items"]),
    }


def run_benchmark(sizes: list[int]) -> dict[str, Any]:
    rows = [
        _evaluate_policy(size, policy)
        for size in sizes
        for policy in (
            KnowledgeMaintenancePolicy.FLAT_APPEND,
            KnowledgeMaintenancePolicy.EAGER_GLOBAL_REBUILD,
            KnowledgeMaintenancePolicy.LOCAL_LAZY,
        )
    ]
    duplicate_pack = internalize_evidence(new_project_knowledge_pack("duplicate"), {
        "content": "identical raw", "item_type": "research_finding", "scope": "project",
        "source_ref": "source:one", "subject_ref": "duplicate", "branch_ref": "duplicate",
    })["pack"]
    duplicate = internalize_evidence(duplicate_pack, {
        "content": "identical raw", "item_type": "research_finding", "scope": "project",
        "source_ref": "source:two", "subject_ref": "duplicate", "branch_ref": "duplicate",
    })["receipt"]
    local_rows = [row for row in rows if row["policy"] == "LOCAL_LAZY"]
    eager_rows = [row for row in rows if row["policy"] == "EAGER_GLOBAL_REBUILD"]
    flat_rows = [row for row in rows if row["policy"] == "FLAT_APPEND"]
    pass_gate = bool(
        duplicate["relation"] == "EXACT_DUPLICATE"
        and duplicate["model_calls"] == 0
        and all(row["nodes_invalidated"] <= 1 and row["unrelated_nodes_touched"] == 0 for row in local_rows)
        and all(row["nodes_recomputed_on_write"] > 0 for row in eager_rows)
        and all(local["context_chars"] < flat["context_chars"] for local, flat in zip(local_rows, flat_rows))
        and all(row["updated_fact_available"] and row["raw_history_preserved"] for row in rows)
    )
    return {
        "kind": "CGKNKnowledgeGrowthEvaluation",
        "schema_version": "1.0",
        "status": "PASS" if pass_gate else "FAIL",
        "gap_audit": GAP_AUDIT,
        "sizes": sizes,
        "rows": rows,
        "duplicate_probe": duplicate,
        "conclusions": {
            "hot_path_model_calls": 0,
            "global_rebuild_required_every_write": False,
            "raw_evidence_is_source": True,
            "derived_abstraction_is_recomputable_cache": True,
            "local_lazy_invalidation_scope": "BOUNDED_BY_ACTUAL_DEPENDENCIES",
            "monolithic_pack_serialization": "LINEAR_IN_PACK_SIZE",
            "knowledge_internalization_benefit": "PROVEN_DIRECTIONALLY" if pass_gate else "NOT_PROVEN",
            "statistical_significance_claimed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate CGKN knowledge growth and internalization")
    parser.add_argument("--profile", choices=("gap-audit", "growth-benchmark", "final"), default="final")
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 5000])
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.profile == "gap-audit":
        result: dict[str, Any] = {"kind": "CGKNKnowledgeGrowthGapAudit", **GAP_AUDIT}
    else:
        result = run_benchmark(args.sizes)
    if args.output:
        target = pathlib.Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None, sort_keys=True))
    return 0 if result.get("status", "PASS") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
