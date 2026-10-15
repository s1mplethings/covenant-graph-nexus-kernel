from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import append_jsonl, now, read_jsonl
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import append_jsonl, now, read_jsonl


def record_pruning_event(
    *,
    out_dir: str | pathlib.Path,
    leaf_id: str,
    parent_agent: str,
    classification: dict[str, Any],
    policy: dict[str, Any],
    evidence_refs: list[str] | None = None,
    replacement_required: bool | None = None,
) -> dict[str, Any]:
    path = pathlib.Path(out_dir) / "pruning_events.jsonl"
    event = {
        "event_id": f"P{len(read_jsonl(path)) + 1:04d}",
        "leaf_id": leaf_id,
        "parent_agent": parent_agent,
        "failure_type": classification["failure_type"],
        "decision": policy["decision"],
        "reason": policy["reason"],
        "evidence_refs": list(evidence_refs or []),
        "replacement_required": (
            policy.get("next_action") not in {"resume_later", "stop_branch"}
            if replacement_required is None
            else replacement_required
        ),
        "created_at": now(),
    }
    append_jsonl(path, event)
    return event


create_pruning_event = record_pruning_event
