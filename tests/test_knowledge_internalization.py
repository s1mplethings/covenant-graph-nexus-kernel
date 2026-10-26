from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgkn.application.knowledge_growth import (  # noqa: E402
    KNOWLEDGE_INTERNALIZATION_COMPONENT_SPEC,
    KnowledgeInternalizationExecutor,
)
from cgkn.execution import BlockExecutionRequest, BlockStatus, TaskContext  # noqa: E402
from cgnk_knowledge import (  # noqa: E402
    KnowledgeMaintenancePolicy,
    internalize_evidence,
    make_derived_abstraction,
    new_project_knowledge_pack,
    raw_content_hash,
    refresh_stale_abstractions,
    retrieve_relevant_knowledge,
    upsert_knowledge_items,
)


def evidence(content: str, **overrides) -> dict:
    value = {
        "content": content,
        "item_type": "research_finding",
        "scope": "project",
        "source_ref": "source:1",
        "subject_ref": "payments.retry",
        "branch_ref": "payments",
        "source_version": "1",
        "importance": "high",
        "need_state": "needed_now",
    }
    value.update(overrides)
    return value


def first(pack: dict) -> dict:
    return pack["all_items"][0]


def test_novel_raw_evidence_runs_hot_lifecycle_without_model() -> None:
    result = internalize_evidence(new_project_knowledge_pack("p"), evidence("Retry HTTP 503 twice."))
    receipt = result["receipt"]
    assert receipt["relation"] == "NOVEL"
    assert receipt["model_calls"] == receipt["provider_calls"] == 0
    assert receipt["raw_committed"] is True
    assert receipt["lifecycle"] == [
        "OBSERVED", "IDENTIFIED", "LOCATED", "RAW_COMMITTED", "RELATION_CLASSIFIED",
        "DEPENDENTS_INVALIDATED", "DERIVED_STALE", "INTERNALIZED", "AVAILABLE",
    ]
    assert first(result["pack"])["content"] == "Retry HTTP 503 twice."


def test_exact_duplicate_is_zero_call_no_rebuild_and_merges_provenance() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Retry twice."))["pack"]
    result = internalize_evidence(original, evidence("Retry twice.", source_ref="source:2"))
    assert result["receipt"]["relation"] == "EXACT_DUPLICATE"
    assert result["receipt"]["model_calls"] == 0
    assert result["receipt"]["nodes_invalidated"] == []
    assert result["receipt"]["nodes_recomputed"] == []
    assert len(result["pack"]["all_items"]) == 1
    assert first(result["pack"])["source_refs"] == ["source:1", "source:2"]


def test_exact_duplicate_recognizes_legacy_item_without_content_hash() -> None:
    legacy = {
        "kind": "KnowledgeItem", "id": "legacy", "title": "legacy", "type": "research_finding",
        "scope": "project", "content": "Legacy exact raw.", "source_refs": ["source:old"],
        "tags": [], "importance": "medium", "need_state": "needed_now", "retention": "keep",
        "review_state": "accepted", "status": "active", "supersedes": [], "stable_hash": "legacy-hash",
        "diagnostics": [],
    }
    knowledge = upsert_knowledge_items(new_project_knowledge_pack("p"), [legacy])
    result = internalize_evidence(
        knowledge,
        evidence("Legacy exact raw.", source_ref="source:new", subject_ref="", branch_ref="project", source_version=""),
    )
    assert result["receipt"]["relation"] == "EXACT_DUPLICATE"
    assert len(result["pack"]["all_items"]) == 1
    assert result["pack"]["all_items"][0]["content_hash"] == raw_content_hash("Legacy exact raw.")


def test_same_semantics_with_distinct_raw_bytes_is_supporting_not_duplicate() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Retry twice."))["pack"]
    result = internalize_evidence(original, evidence("  retry   twice. ", source_ref="source:2"))
    assert result["receipt"]["relation"] == "SUPPORTING"
    assert len(result["pack"]["all_items"]) == 2


def test_same_bytes_in_another_scope_is_not_cross_domain_duplicate() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Shared text."))["pack"]
    result = internalize_evidence(
        original,
        evidence("Shared text.", scope="module", branch_ref="media", subject_ref="media.codec"),
    )
    assert result["receipt"]["relation"] == "NOVEL"
    assert len(result["pack"]["all_items"]) == 2


def test_newer_version_supersedes_and_preserves_old_raw_evidence() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Port 8000.", subject_ref="service.port"))["pack"]
    old_id = first(original)["id"]
    result = internalize_evidence(
        original,
        evidence("Port 9000.", subject_ref="service.port", source_ref="source:2", source_version="2"),
    )
    by_id = {item["id"]: item for item in result["pack"]["all_items"]}
    assert result["receipt"]["relation"] == "SUPERSEDING"
    assert by_id[old_id]["status"] == "superseded"
    assert by_id[old_id]["content"] == "Port 8000."


def test_explicit_contradiction_is_bidirectional_and_requires_review() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Workers write owned paths."))["pack"]
    target = first(original)["id"]
    result = internalize_evidence(
        original,
        evidence("Workers write any path.", source_ref="source:2", relation="CONTRADICTING", target_id=target),
    )
    rows = {item["id"]: item for item in result["pack"]["all_items"]}
    assert result["receipt"]["relation"] == "CONTRADICTING"
    assert rows[target]["review_state"] == "conflict"
    assert any(edge["type"] == "CONTRADICTED_BY" for edge in rows[target]["relations"])


def test_correction_and_retraction_keep_raw_history() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Limit is 3."))["pack"]
    target = first(original)["id"]
    corrected = internalize_evidence(
        original,
        evidence("Correction: limit is 4.", source_ref="source:2", relation="CORRECTION", target_id=target),
    )
    assert corrected["receipt"]["relation"] == "CORRECTION"
    corrected_id = corrected["receipt"]["evidence_id"]
    retracted = internalize_evidence(
        corrected["pack"],
        evidence("Retract the corrected limit.", source_ref="source:3", source_version="3", relation="RETRACTION", target_id=corrected_id),
    )
    rows = {item["id"]: item for item in retracted["pack"]["all_items"]}
    assert rows[target]["content"] == "Limit is 3."
    assert rows[corrected_id]["status"] == "retracted"
    assert rows[retracted["receipt"]["evidence_id"]]["evidence_kind"] == "tombstone"


def test_ambiguous_relation_remains_unresolved_without_model_authority() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Retry twice.", source_version=""))["pack"]
    result = internalize_evidence(
        original,
        evidence("Retry on 503.", source_ref="source:2", source_version=""),
    )
    assert result["receipt"]["relation"] == "UNRESOLVED_RELATION"
    assert result["receipt"]["model_calls"] == 0
    assert result["pack"]["all_items"][-1]["review_state"] == "candidate"


def test_optional_warm_classifier_is_counted_and_target_validated() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Retry twice.", source_version=""))["pack"]
    target = first(original)["id"]
    result = internalize_evidence(
        original,
        evidence("Never retry.", source_ref="source:2", source_version=""),
        classifier=lambda incoming, candidates: {"relation": "CONTRADICTING", "target_id": target},
    )
    assert result["receipt"]["relation"] == "CONTRADICTING"
    assert result["receipt"]["model_calls"] == 1

    try:
        internalize_evidence(
            result["pack"],
            evidence("Maybe retry.", source_ref="source:3", source_version=""),
            classifier=lambda incoming, candidates: {"relation": "SUPPORTING", "target_id": "invented"},
        )
    except ValueError as exc:
        assert "existing target_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unvalidated classifier target was accepted")


def test_leaf_change_invalidates_only_actual_ancestor_closure_without_recompute() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Port 8000.", subject_ref="service.port"))["pack"]
    leaf_id = first(original)["id"]
    parent = make_derived_abstraction("summary.service", "Service uses port 8000.", [leaf_id], branch_ref="service")
    root = make_derived_abstraction("summary.root", "System summary.", ["summary.service"], branch_ref="root")
    unrelated = make_derived_abstraction("summary.media", "Media uses H.264.", [leaf_id], branch_ref="media")
    # The unrelated node is deliberately indexed against a different leaf so
    # its branch is independent of the changed service chain.
    unrelated["source_refs"] = ["media.raw"]
    knowledge = upsert_knowledge_items(original, [parent, root, unrelated])
    result = internalize_evidence(
        knowledge,
        evidence("Port 9000.", subject_ref="service.port", branch_ref="service", source_ref="source:2", source_version="2"),
    )
    assert result["receipt"]["nodes_invalidated"] == ["summary.root", "summary.service"]
    assert result["receipt"]["nodes_recomputed"] == []
    rows = {item["id"]: item for item in result["pack"]["all_items"]}
    assert rows["summary.service"]["derived_state"] == "stale"
    assert rows["summary.root"]["derived_state"] == "stale"
    assert rows["summary.media"]["derived_state"] == "fresh"


def test_on_demand_refresh_recomputes_only_requested_stale_chain() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Port 8000.", subject_ref="service.port"))["pack"]
    leaf_id = first(original)["id"]
    knowledge = upsert_knowledge_items(
        original,
        [
            make_derived_abstraction("summary.service", "old service", [leaf_id], branch_ref="service"),
            make_derived_abstraction("summary.root", "old root", ["summary.service"], branch_ref="root"),
        ],
    )
    updated = internalize_evidence(
        knowledge,
        evidence("Port 9000.", subject_ref="service.port", branch_ref="service", source_ref="source:2", source_version="2"),
    )["pack"]
    pending = refresh_stale_abstractions(updated, node_ids=["summary.service", "summary.root"])
    assert pending["receipt"]["status"] == "PENDING_REDUCER"
    refreshed = refresh_stale_abstractions(
        updated,
        node_ids=["summary.service", "summary.root"],
        reducer=lambda item, sources: f"{item['id']}:" + "|".join(source["content"] for source in sources),
    )
    assert refreshed["receipt"]["nodes_recomputed"] == ["summary.service", "summary.root"]
    assert all(item.get("derived_state", "fresh") == "fresh" for item in refreshed["pack"]["all_items"])


def test_retrieval_excludes_stale_summary_and_finds_updated_raw_evidence() -> None:
    original = internalize_evidence(new_project_knowledge_pack("p"), evidence("Port 8000.", subject_ref="service.port"))["pack"]
    leaf_id = first(original)["id"]
    knowledge = upsert_knowledge_items(
        original,
        [make_derived_abstraction("summary.service", "Service port 8000.", [leaf_id], branch_ref="service", dependency_mode="branch")],
    )
    updated = internalize_evidence(
        knowledge,
        evidence("Service port 9000.", subject_ref="service.port", branch_ref="service", source_ref="source:2", source_version="2"),
    )["pack"]
    result = retrieve_relevant_knowledge(updated, {"goal": "What is service port 9000?", "require_relevance": True, "max_items": 5})
    ids = [item["id"] for item in result["selected_items"]]
    assert "summary.service" not in ids
    assert any("9000" in item["content"] for item in result["selected_items"])
    assert result["metrics"]["index_used"] is True


def test_raw_content_fidelity_preserves_crlf_and_distinguishes_lf() -> None:
    crlf = "first\r\nsecond\r\n"
    lf = "first\nsecond\n"
    result = internalize_evidence(new_project_knowledge_pack("p"), evidence(crlf))
    assert first(result["pack"])["content"] == crlf
    assert raw_content_hash(crlf) != raw_content_hash(lf)


def test_component_uses_common_block_boundary() -> None:
    executor = KnowledgeInternalizationExecutor()
    request = BlockExecutionRequest(
        "p", "r", "a", "knowledge", KNOWLEDGE_INTERNALIZATION_COMPONENT_SPEC.ref,
        executor.descriptor.executor_ref, TaskContext("Internalize evidence"),
        input_values={"knowledge_pack": new_project_knowledge_pack("p"), "evidence": evidence("Retry twice.")},
        declared_effects=("knowledge.write",),
    )
    result = executor.execute(request)
    assert result.status is BlockStatus.SUCCEEDED
    assert result.outputs["receipt"]["relation"] == "NOVEL"
    assert result.usage["provider_calls"] == 0


def test_pack_round_trip_shape_is_json_serializable() -> None:
    result = internalize_evidence(new_project_knowledge_pack("p"), evidence("Retry twice."))
    assert json.loads(json.dumps(result["pack"]))["knowledge_index"]["kind"] == "KnowledgeIndex"


def test_local_lazy_and_flat_do_not_recompute_but_eager_does() -> None:
    base = internalize_evidence(new_project_knowledge_pack("p"), evidence("Port 8000.", subject_ref="service.port"))["pack"]
    leaf_id = first(base)["id"]
    base = upsert_knowledge_items(
        base,
        [make_derived_abstraction("summary.service", "old", [leaf_id], branch_ref="service", dependency_mode="branch")],
    )
    update = evidence("Port 9000.", subject_ref="service.port", branch_ref="service", source_ref="source:2", source_version="2")
    flat = internalize_evidence(json.loads(json.dumps(base)), update, policy=KnowledgeMaintenancePolicy.FLAT_APPEND)
    local = internalize_evidence(json.loads(json.dumps(base)), update, policy=KnowledgeMaintenancePolicy.LOCAL_LAZY)
    eager = internalize_evidence(
        json.loads(json.dumps(base)), update, policy=KnowledgeMaintenancePolicy.EAGER_GLOBAL_REBUILD,
        eager_reducer=lambda item, sources: " | ".join(source["content"] for source in sources),
    )
    assert flat["receipt"]["nodes_recomputed"] == []
    assert local["receipt"]["nodes_invalidated"] == ["summary.service"]
    assert local["receipt"]["nodes_recomputed"] == []
    assert eager["receipt"]["nodes_recomputed"] == ["summary.service"]
