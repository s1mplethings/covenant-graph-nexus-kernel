import pytest

from cgkn.artifacts.models import ArtifactRef
from cgkn.component import ComponentExecution, ComponentExecutionStatus


REF = ArtifactRef("ai.goal.001", "artifact.goal@1", "sha256:" + "1" * 64)


def test_execution_pass_lifecycle_and_output_refs() -> None:
    execution = ComponentExecution("module.x@1", "n1", "run1")
    assert execution.status is ComponentExecutionStatus.PENDING and execution.execution_id
    execution.start([REF]).succeed([REF])
    assert execution.status is ComponentExecutionStatus.PASS
    assert execution.finished_at and execution.output_artifact_refs == (REF,)


def test_execution_fail_and_cache_lifecycles() -> None:
    failed = ComponentExecution("module.x@1", "n1", "run1").start().fail([{"code": "X"}])
    cached = ComponentExecution("module.x@1", "n1", "run1").start().cached([REF])
    assert failed.status is ComponentExecutionStatus.FAIL and failed.diagnostics
    assert cached.status is ComponentExecutionStatus.CACHED and cached.cache_status == "hit"


@pytest.mark.parametrize("terminal", ["pass", "fail"])
def test_terminal_execution_cannot_transition_again(terminal: str) -> None:
    execution = ComponentExecution("module.x@1", "n1", "run1").start()
    execution.succeed([]) if terminal == "pass" else execution.fail([{"code": "X"}])
    with pytest.raises(ValueError):
        execution.start()
    with pytest.raises(ValueError):
        execution.fail([{"code": "Y"}]) if terminal == "pass" else execution.succeed([])


def test_fail_requires_diagnostics_and_terminal_checkpoint_requires_finish() -> None:
    with pytest.raises(ValueError):
        ComponentExecution("module.x@1", "n1", "run1").start().fail([])
    execution = ComponentExecution("module.x@1", "n1", "run1")
    execution._status = ComponentExecutionStatus.PASS
    with pytest.raises(ValueError):
        execution.as_checkpoint()
