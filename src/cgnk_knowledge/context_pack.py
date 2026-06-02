from __future__ import annotations

import hashlib
from typing import Any

from .retrieve import retrieve_relevant_knowledge


TYPE_BUCKETS = {
    "constraint": "critical_constraints",
    "decision": "active_decisions",
    "requirement": "current_requirements",
    "risk": "risks",
    "next_step": "next_steps",
    "artifact_ref": "artifact_refs",
    "module_mapping": "module_mappings",
    "agent_mapping": "agent_mappings",
    "research_finding": "research_findings",
}


def _pack_id(goal_spec: dict[str, Any]) -> str:
    seed = str(goal_spec.get("id") or goal_spec.get("goal") or goal_spec)
    return "acp_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def build_agent_context_pack(pack: dict[str, Any], goal_spec: dict[str, Any], agent_profile: dict[str, Any] | None = None, max_items: int = 20) -> dict[str, Any]:
    agent = agent_profile or {}
    query = {
        "kind": "KnowledgeRetrievalQuery",
        "goal": goal_spec.get("goal") or goal_spec.get("title") or "",
        "agent_role": agent.get("role"),
        "selected_modules": agent.get("selected_modules", goal_spec.get("selected_modules", [])),
        "needed_types": ["constraint", "decision", "requirement", "risk", "next_step", "module_mapping", "agent_mapping", "artifact_ref"],
        "scope": goal_spec.get("scope"),
        "include_reference": True,
        "max_items": max_items,
    }
    result = retrieve_relevant_knowledge(pack, query)
    out = {
        "kind": "AgentContextPack",
        "id": _pack_id(goal_spec),
        "goal_ref": goal_spec.get("id") or goal_spec.get("goal") or "",
        "agent_ref": agent.get("id"),
        "context_budget": {"max_items": max_items, "selected_items": len(result["selected_items"])},
        "critical_constraints": [],
        "active_decisions": [],
        "current_requirements": [],
        "needed_now": [],
        "needed_later": [],
        "reference_only": [],
        "risks": [],
        "next_steps": [],
        "artifact_refs": [],
        "module_mappings": [],
        "agent_mappings": [],
        "research_findings": [],
        "excluded_knowledge": result["excluded_items"],
        "discard_candidates": [],
        "diagnostics": list(result.get("diagnostics", [])),
    }
    for item in result["selected_items"]:
        bucket = TYPE_BUCKETS.get(item.get("type"))
        if bucket == "critical_constraints":
            if item.get("importance") == "critical":
                out[bucket].append(item)
        elif bucket:
            out[bucket].append(item)
        need_bucket = item.get("need_state")
        if need_bucket in {"needed_now", "needed_later", "reference_only"}:
            out[need_bucket].append(item)
    for item in pack.get("all_items", []):
        if item.get("retention") == "discard" or item.get("importance") == "noise":
            out["discard_candidates"].append(item)
    out["diagnostics"].append(
        {
            "code": "CGNK_CONTEXT_PACK_BUILT" if result["selected_items"] else "CGNK_CONTEXT_PACK_EMPTY",
            "severity": "info" if result["selected_items"] else "warning",
            "message": "AgentContextPack built",
        }
    )
    return out
