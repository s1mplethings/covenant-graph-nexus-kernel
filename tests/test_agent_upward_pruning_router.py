from __future__ import annotations

import pathlib

from scripts.agent_upward_pruning_router import route_pruning_event


def test_router_blocks_branch_merge_integration_and_delivery(tmp_path: pathlib.Path) -> None:
    signal = route_pruning_event(
        out_dir=tmp_path,
        event={
            "event_id": "P0001",
            "leaf_id": "task_service_leaf",
            "parent_agent": "backend_branch_agent",
            "failure_type": "test_failed",
        },
    )

    assert signal["from_leaf"] == "task_service_leaf"
    assert signal["to_parent"] == "backend_branch_agent"
    assert "backend_branch_agent_merge" in signal["blocked_downstream"]
    assert "integration" in signal["blocked_downstream"]
    assert "delivery" in signal["blocked_downstream"]
