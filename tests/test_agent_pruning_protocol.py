from __future__ import annotations

import pathlib

from scripts.agent_pruning_protocol import record_pruning_event
from scripts.agent_tree_contracts import read_jsonl


def test_pruning_protocol_preserves_evidence_and_monotonic_ids(tmp_path: pathlib.Path) -> None:
    classification = {"leaf_id": "task_leaf", "failure_type": "test_failed"}
    policy = {"decision": "PRUNE", "reason": "failed twice", "next_action": "spawn_replacement_leaf"}

    first = record_pruning_event(
        out_dir=tmp_path,
        leaf_id="task_leaf",
        parent_agent="backend_branch_agent",
        classification=classification,
        policy=policy,
        evidence_refs=["checkpoints/task_leaf.json", "test_execution/task_leaf.json"],
    )
    second = record_pruning_event(
        out_dir=tmp_path,
        leaf_id="other_leaf",
        parent_agent="backend_branch_agent",
        classification={**classification, "leaf_id": "other_leaf"},
        policy=policy,
    )

    assert first["event_id"] == "P0001"
    assert second["event_id"] == "P0002"
    assert first["evidence_refs"] == ["checkpoints/task_leaf.json", "test_execution/task_leaf.json"]
    assert len(read_jsonl(tmp_path / "pruning_events.jsonl")) == 2
