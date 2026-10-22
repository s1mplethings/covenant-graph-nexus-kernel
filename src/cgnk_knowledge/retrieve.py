from __future__ import annotations

import re
from typing import Any

from .store import IMPORTANCE_RANK, NEED_RANK


REVIEW_RANK = {"accepted": 0, "auto_extracted": 1, "candidate": 2, "conflict": 3, "rejected": 9}
SCOPE_RANK = {"project.cgkn": 0, "project": 1, "project.cgnk": 1, "global": 2, "module": 3, "agent": 3, "session": 4}
_TOKEN = re.compile(r"[A-Za-z0-9_.+-]+|[\u3400-\u9fff]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "how", "in",
    "is", "it", "of", "on", "or", "the", "to", "what", "when", "which", "with",
}


def _terms(value: Any) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN.findall(str(value or ""))
        if len(token) > 1 and token.casefold() not in _STOPWORDS
    }


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
    status = item.get("status", "active")
    retention = item.get("retention", "keep")
    if status == "superseded":
        return "superseded"
    if status == "retracted":
        return "retracted"
    if item.get("review_state") == "rejected":
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


def _score(item: dict[str, Any], query: dict[str, Any]) -> tuple[Any, ...]:
    needed_types = set(query.get("needed_types", []))
    selected_modules = {str(row).lower() for row in query.get("selected_modules", [])}
    tags = {str(row).lower() for row in item.get("tags", [])}
    scope = query.get("scope")
    exact_scope = 0 if scope and item.get("scope") == scope else 1
    type_rank = 0 if item.get("type") in needed_types else 1
    tag_rank = 0 if selected_modules and selected_modules.intersection(tags) else 1
    lexical_rank = -item_relevance(item, query)
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
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in pack.get("all_items", []):
        reason = _exclude_reason(item, effective_query)
        if reason:
            excluded.append({"item": item, "reason": reason})
        elif effective_query.get("require_relevance") and item_relevance(item, effective_query) <= 0:
            excluded.append({"item": item, "reason": "low_relevance"})
        else:
            candidates.append(item)
    ranked = sorted(candidates, key=lambda item: _score(item, effective_query))
    max_items = int(effective_query.get("max_items") or 20)
    selected = ranked[:max_items]
    for item in ranked[max_items:]:
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
        "diagnostics": diagnostics,
    }
