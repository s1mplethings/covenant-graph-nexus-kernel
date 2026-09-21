from __future__ import annotations

from typing import Any

try:
    from agent_tree_contracts import contains_forbidden_terms
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import contains_forbidden_terms


def _required_terms(shared_context: dict[str, Any]) -> list[str]:
    goal_spec = shared_context.get("goal_spec", {})
    if not isinstance(goal_spec, dict) or goal_spec.get("status") != "PASS":
        return []
    terms: list[str] = []
    for capability in goal_spec.get("capabilities", []):
        words = str(capability).lower().replace("_", " ").replace("-", " ").split()
        if words and words[0] in {"configure"}:
            words = words[1:]
        term = " ".join(words).strip()
        if term:
            terms.append(term)
    return terms


def evaluate_goal_alignment(shared_context: dict[str, Any], agent_plan: str) -> dict[str, Any]:
    lowered = agent_plan.lower().replace("_", " ").replace("-", " ")
    forbidden_hits = contains_forbidden_terms(agent_plan, list(shared_context.get("forbidden_context_terms") or []))
    required_terms = _required_terms(shared_context)
    missing_terms = [term for term in required_terms if term not in lowered]
    verdict = "PASS" if required_terms and not forbidden_hits and not missing_terms else "FAIL"
    return {
        "kind": "AgentTreeGoalAlignmentResult",
        "project_name": shared_context.get("project_name", ""),
        "verdict": verdict,
        "can_continue": verdict == "PASS",
        "required_terms": required_terms,
        "missing_terms": missing_terms,
        "forbidden_terms_found": forbidden_hits,
        "agent_plan": agent_plan,
    }
