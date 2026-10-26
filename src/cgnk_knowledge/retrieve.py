from __future__ import annotations

import re
from typing import Any

from .store import IMPORTANCE_RANK, NEED_RANK, knowledge_index_is_current


REVIEW_RANK = {"accepted": 0, "auto_extracted": 1, "candidate": 2, "conflict": 3, "rejected": 9}
SCOPE_RANK = {"project.cgkn": 0, "project": 1, "project.cgnk": 1, "global": 2, "module": 3, "agent": 3, "session": 4}
_TOKEN = re.compile(r"[A-Za-z0-9_.+-]+|[\u3400-\u9fff]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "how", "in",
    "is", "it", "of", "on", "or", "the", "to", "what", "when", "which", "with",
}


def _terms(value: Any) -> set[str]:
    terms: set[str] = set()
    for token in _TOKEN.findall(str(value or "")):
        folded = token.casefold()
        normalized = folded.strip(".+-")
        for candidate in (folded, normalized):
            if len(candidate) > 1 and candidate not in _STOPWORDS:
                terms.add(candidate)
    return terms


def relevance_terms(item: dict[str, Any], query: dict[str, Any]) -> tuple[set[str], set[str]]:
    query_terms = _terms(query.get("goal"))
    item_terms = _terms(" ".join((
        str(item.get("id", "")), str(item.get("title", "")), str(item.get("content", "")),
        " ".join(str(row) for row in item.get("tags", ())),
    )))
    return query_terms, item_terms


def item_relevance(item: dict[str, Any], query: dict[str, Any]) -> int:
    query_terms, item_terms = relevance_terms(item, query)
    selected_modules = {str(row).casefold() for row in query.get("selected_modules", ())}
    tags = {str(row).casefold() for row in item.get("tags", ())}
    return len(query_terms & item_terms) + (2 if selected_modules & tags else 0)


def _exclude_reason(item: dict[str, Any], query: dict[str, Any]) -> str | None:
    if item.get("derived_state") == "stale":
        return "derived_stale"
    status = item.get("status", "active")
    retention = item.get("retention", "keep")
    if status == "superseded" and not query.get("include_superseded"):
        return "superseded"
    if status == "retracted":
        return "retracted"
    if item.get("review_state") == "rejected" and not (
        status == "superseded" and query.get("include_superseded")
    ):
        return "rejected"
    if retention == "discard":
        return "discard"
    if retention == "archive" or status == "archived":
        return None if query.get("include_archived") else "archived"
    if item.get("need_state") == "reference_only" and not query.get("include_reference", False) and item.get("type") not in {"artifact_ref", "test_result"}:
        return "reference_not_requested"
    if item.get("status") == "uncertain" and not query.get("include_uncertain"):
        return "low_relevance"
    return None


def _score(
    item: dict[str, Any], query: dict[str, Any], relevance: int | None = None,
) -> tuple[Any, ...]:
    needed_types = set(query.get("needed_types", []))
    selected_modules = {str(row).lower() for row in query.get("selected_modules", [])}
    tags = {str(row).lower() for row in item.get("tags", [])}
    scope = query.get("scope")
    exact_scope = 0 if scope and item.get("scope") == scope else 1
    type_rank = 0 if item.get("type") in needed_types else 1
    tag_rank = 0 if selected_modules and selected_modules.intersection(tags) else 1
    lexical_rank = -(item_relevance(item, query) if relevance is None else relevance)
    return (
        REVIEW_RANK.get(item.get("review_state"), 8),
        lexical_rank,
        IMPORTANCE_RANK.get(item.get("importance"), 9),
        NEED_RANK.get(item.get("need_state"), 9),
        exact_scope,
        SCOPE_RANK.get(item.get("scope"), 8),
        type_rank,
        tag_rank,
        str(item.get("id", "")),
    )


def retrieve_relevant_knowledge(pack: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    effective_query = {
        "kind": "KnowledgeRetrievalQuery",
        "selected_modules": [],
        "needed_types": [],
        "include_reference": False,
        "include_archived": False,
        "include_uncertain": False,
        "require_relevance": False,
        "max_items": 20,
        **(query or {}),
    }
    all_items = pack.get("all_items", [])
    index_used = False
    candidate_pool = all_items
    indexed_relevance: dict[str, int] = {}
    if effective_query.get("require_relevance") and knowledge_index_is_current(pack):
        index = pack["knowledge_index"]
        goal_terms = _terms(effective_query.get("goal"))
        selected_modules = {
            str(value).casefold() for value in effective_query.get("selected_modules", ()) if str(value)
        }
        query_terms = goal_terms | selected_modules
        # This is an indexed implementation of the existing any-term lexical
        # relevance rule, so candidate acceleration does not change selection
        # semantics or lose multi-fact evidence.
        indexed_ids = {
            item_id
            for term in query_terms
            for item_id in index.get("by_term", {}).get(term, ())
        }
        candidate_pool = [
            all_items[int(index["by_id"][item_id])]
            for item_id in sorted(indexed_ids)
            if item_id in index.get("by_id", {})
        ]
        # The inverted index already proves lexical membership. Count the
        # matching goal postings once and add the existing exact tag boost;
        # this is identical to item_relevance without re-tokenizing every
        # candidate's content once for filtering and again for sorting.
        for term in goal_terms:
            for item_id in index.get("by_term", {}).get(term, ()):
                indexed_relevance[str(item_id)] = indexed_relevance.get(str(item_id), 0) + 1
        if selected_modules:
            for item in candidate_pool:
                item_id = str(item.get("id", ""))
                tags = {str(row).casefold() for row in item.get("tags", ())}
                if selected_modules & tags:
                    indexed_relevance[item_id] = indexed_relevance.get(item_id, 0) + 2
        index_used = True
    candidates: list[tuple[dict[str, Any], int]] = []
    excluded: list[dict[str, Any]] = []
    for item in candidate_pool:
        relevance = (
            indexed_relevance.get(str(item.get("id", "")), 0)
            if index_used else item_relevance(item, effective_query)
        )
        reason = _exclude_reason(item, effective_query)
        if reason:
            excluded.append({"item": item, "reason": reason})
        elif effective_query.get("require_relevance") and relevance <= 0:
            excluded.append({"item": item, "reason": "low_relevance"})
        else:
            candidates.append((item, relevance))
    ranked = sorted(candidates, key=lambda row: _score(row[0], effective_query, row[1]))
    max_items = int(effective_query.get("max_items") or 20)
    selected = [item for item, _ in ranked[:max_items]]
    for item, _ in ranked[max_items:]:
        excluded.append({"item": item, "reason": "over_budget"})
    diagnostics = []
    if not selected:
        diagnostics.append({"code": "CGNK_KNOWLEDGE_RETRIEVAL_EMPTY", "severity": "warning", "message": "no relevant knowledge selected"})
    if excluded:
        diagnostics.append({"code": "CGNK_KNOWLEDGE_RETRIEVAL_EXCLUDED", "severity": "info", "message": f"{len(excluded)} knowledge items excluded"})
    return {
        "kind": "KnowledgeRetrievalResult",
        "query": effective_query,
        "selected_items": selected,
        "excluded_items": excluded,
        "ranking_reasons": [
            {"item_id": item.get("id"), "reason": "ranked by review_state, lexical relevance, importance, need_state, scope, type, tags"}
            for item in selected
        ],
        "metrics": {
            "index_used": index_used,
            "pack_items": len(all_items),
            "candidates_evaluated": len(candidate_pool),
            "selected_items": len(selected),
        },
        "diagnostics": diagnostics,
    }
