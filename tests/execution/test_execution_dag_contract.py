from __future__ import annotations

import pytest

from cgkn.orchestration.execution_dag import ExecutionDAG, ExecutionNode


def test_dag_round_trip_and_deep_immutability() -> None:
    source = {"nested": {"values": [1]}}
    dag = ExecutionDAG("goal", (ExecutionNode("a", "cap.a@1", (), source), ExecutionNode("b", "cap.b@1", ("a",), {})))
    source["nested"]["values"].append(2)
    assert dag.by_id["a"].config["nested"]["values"] == (1,)
    assert ExecutionDAG.from_dict(dag.as_dict()).as_dict() == dag.as_dict()


def test_dag_rejects_duplicate_unknown_cycle_and_serialized_order_mismatch() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ExecutionDAG("goal", (ExecutionNode("a", "cap.a@1", (), {}), ExecutionNode("a", "cap.b@1", (), {})))
    with pytest.raises(ValueError, match="unknown_dependency"):
        ExecutionDAG("goal", (ExecutionNode("a", "cap.a@1", ("missing",), {}),)).topological_order()
    with pytest.raises(ValueError, match="cycle"):
        ExecutionDAG("goal", (ExecutionNode("a", "cap.a@1", ("b",), {}), ExecutionNode("b", "cap.b@1", ("a",), {}))).topological_order()
    value = ExecutionDAG("goal", (ExecutionNode("a", "cap.a@1", (), {}), ExecutionNode("b", "cap.b@1", ("a",), {}))).as_dict()
    value["topological_order"] = ["b", "a"]
    with pytest.raises(ValueError, match="mismatch"):
        ExecutionDAG.from_dict(value)
