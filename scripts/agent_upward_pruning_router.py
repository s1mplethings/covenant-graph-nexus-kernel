from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import append_jsonl, now, read_jsonl
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import append_jsonl, now, read_jsonl


def route_pruning_event(
    *,
    out_dir: str | pathlib.Path,
    event: dict[str, Any],
    requested_parent_action: str = "replan_or_spawn_replacement",
) -> dict[str, Any]:
    path = pathlib.Path(out_dir) / "upward_signals.jsonl"
    signal = {
        "signal_id": f"U{len(read_jsonl(path)) + 1:04d}",
        "pruning_event_id": event["event_id"],
        "from_leaf": event["leaf_id"],
        "to_parent": event["parent_agent"],
        "failure_type": event["failure_type"],
        "requested_parent_action": requested_parent_action,
        "blocked_downstream": [
            f"{event['parent_agent']}_merge",
            "integration",
            "delivery",
        ],
        "created_at": now(),
    }
    append_jsonl(path, signal)
    return signal


route_upward_signal = route_pruning_event
