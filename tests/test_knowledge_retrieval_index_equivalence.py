from __future__ import annotations

import copy

from benchmarks.knowledge_persistence_scaling.runner import (
    branch_count_for,
    generate_corpus,
    query_cases,
    run_query,
)
from cgnk_knowledge.retrieve import retrieve_relevant_knowledge
from cgkn.application.conversation import ConversationRequest, ConversationService


def test_indexed_relevance_preserves_frozen_scaling_cases() -> None:
    pack = generate_corpus(10_000, branch_count_for(10_000), "uniform")
    expected = {
        "simple_local_fact": ["ki-000010"],
        "bottom_up_raw_detail": ["ki-000006", "ki-000007"],
        "two_node_composition": ["ki-000008", "ki-000006", "ki-000007"],
        "superseded_fact": ["ki-000001"],
        "contradiction": ["ki-000002", "ki-000003"],
        "cross_domain_isolation": [
            "ki-000012", "ki-000312", "ki-000612", "ki-000912",
            "ki-001212", "ki-001512", "ki-001812", "ki-002112",
        ],
        "stale_summary_raw_fallback": ["ki-000006", "ki-000007"],
        "no_evidence": [],
        "synonym_wording": [
            "ki-000213", "ki-000513", "ki-000813", "ki-001113",
            "ki-001413", "ki-001713", "ki-002013", "ki-002313",
        ],
        "ambiguous_similar_names": [
            "ki-000114", "ki-000414", "ki-000714", "ki-001014",
            "ki-001314", "ki-001614", "ki-001914", "ki-002214",
        ],
        "version_query": [
            "ki-000001", "ki-000201", "ki-000501", "ki-000801",
            "ki-001101", "ki-001401", "ki-001701", "ki-002001",
        ],
        "historical_query": ["ki-000016"],
    }
    for case in query_cases(10_000, branch_count_for(10_000), "uniform"):
        if case["name"] not in expected:
            continue
        result = run_query(pack, case)
        assert [row["id"] for row in result["selected_items"]] == expected[case["name"]]


def test_indexed_and_fallback_paths_have_identical_semantics() -> None:
    pack = generate_corpus(1_000, branch_count_for(1_000), "hot_branch_skew")
    queries = [
        {"goal": "shared-name branch-0000", "selected_modules": []},
        {"goal": "", "selected_modules": ["domain-alpha"]},
        {"goal": "conflict-block-000000", "selected_modules": [], "include_uncertain": True},
        {"goal": "historical-block-000000", "selected_modules": [], "include_archived": True},
    ]
    for query in queries:
        request = {
            "kind": "KnowledgeRetrievalQuery", "needed_types": [],
            "include_reference": False, "require_relevance": True, "max_items": 8,
            **query,
        }
        indexed = retrieve_relevant_knowledge(pack, request)
        stale = copy.deepcopy(pack)
        stale["knowledge_index"]["pack_revision"] = -1
        fallback = retrieve_relevant_knowledge(stale, request)
        assert [row["id"] for row in indexed["selected_items"]] == [
            row["id"] for row in fallback["selected_items"]
        ]
        assert indexed["metrics"]["selected_items"] == fallback["metrics"]["selected_items"]


def test_indexed_path_does_not_retokenize_candidate_content(monkeypatch) -> None:
    import cgnk_knowledge.retrieve as retrieval

    pack = generate_corpus(10_000, branch_count_for(10_000), "uniform")
    calls: list[str] = []
    original = retrieval._terms

    def observed(value):
        calls.append(str(value))
        return original(value)

    monkeypatch.setattr(retrieval, "_terms", observed)
    result = retrieval.retrieve_relevant_knowledge(
        pack,
        {
            "goal": "shared-name branch-0000", "require_relevance": True,
            "include_uncertain": True, "max_items": 8,
        },
    )
    assert result["metrics"]["candidates_evaluated"] > 100
    assert calls == ["shared-name branch-0000"]


def test_conversation_detail_expansion_reuses_index_without_full_item_scan() -> None:
    class ObservedItems(list):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    pack = generate_corpus(10_000, branch_count_for(10_000), "uniform")
    observed = ObservedItems(pack["all_items"])
    pack["all_items"] = observed
    selected, receipt = ConversationService(None)._retrieve(
        ConversationRequest("exact compose-block-000000"), pack
    )
    assert [row["id"] for row in selected] == ["ki-000008", "ki-000006", "ki-000007"]
    assert receipt["raw_expansion_count"] == 2
    assert observed.iterations == 0
