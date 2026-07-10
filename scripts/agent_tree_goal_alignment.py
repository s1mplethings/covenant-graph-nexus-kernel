from __future__ import annotations

from typing import Any

try:
    from agent_tree_contracts import contains_forbidden_terms
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import contains_forbidden_terms


REQUIRED_ALIGNMENT_TERMS = [
    "document import",
    "knowledge base",
    "search",
    "reports",
    "tasks",
    "local model adapter",
]


def evaluate_goal_alignment(shared_context: dict[str, Any], agent_plan: str) -> dict[str, Any]:
    lowered = agent_plan.lower()
    forbidden_hits = contains_forbidden_terms(agent_plan, list(shared_context.get("forbidden_context_terms") or []))
    missing_terms = [term for term in REQUIRED_ALIGNMENT_TERMS if term not in lowered]
    verdict = "PASS" if not forbidden_hits and not missing_terms else "FAIL"
    return {
        "kind": "AgentTreeGoalAlignmentResult",
        "project_name": shared_context.get("project_name", ""),
        "verdict": verdict,
        "can_continue": verdict == "PASS",
        "required_terms": list(REQUIRED_ALIGNMENT_TERMS),
        "missing_terms": missing_terms,
        "forbidden_terms_found": forbidden_hits,
        "agent_plan": agent_plan,
    }
