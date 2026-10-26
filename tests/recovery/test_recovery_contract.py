from __future__ import annotations

import pytest

from cgkn.orchestration.execution_dag import ExecutionDAG, ExecutionNode
from cgkn.orchestration.invalidation import downstream_closure


pytestmark = [pytest.mark.recovery, pytest.mark.boundary, pytest.mark.determinism]


def test_recovery_uses_deterministic_graph_downstream_closure() -> None:
    dag = ExecutionDAG(
        goal="recover only the affected subgraph",
        nodes=(
            ExecutionNode(id="source", capability_ref="cap.source@1", depends_on=(), config={}),
            ExecutionNode(id="affected", capability_ref="cap.affected@1", depends_on=("source",), config={}),
            ExecutionNode(id="unrelated", capability_ref="cap.unrelated@1", depends_on=(), config={}),
        )
    )

    assert downstream_closure(dag, {"source"}) == ("source", "affected")


@pytest.mark.negative
def test_recovery_rejects_unknown_changed_node() -> None:
    dag = ExecutionDAG(
        goal="reject unknown invalidation input",
        nodes=(ExecutionNode(id="known", capability_ref="cap.known@1", depends_on=(), config={}),),
    )

    with pytest.raises(ValueError, match="unknown invalidation nodes: missing"):
        downstream_closure(dag, {"missing"})
