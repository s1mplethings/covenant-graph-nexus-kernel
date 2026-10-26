import pytest

from cgkn.artifacts.models import ArtifactRef
from cgkn.component import ComponentExecution, ComponentExecutionStatus


REF = ArtifactRef("ai.goal.001", "artifact.goal@1", "sha256:" + "1" * 64)
pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


@pytest.mark.roundtrip
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


def test_bypass_checkpoint_and_effect_metadata() -> None:
    execution = ComponentExecution("module.x@1", "n1", "run1", effects_summary={"fs": 1}, execution_fingerprint="fp").bypass([REF])
    checkpoint = execution.as_checkpoint()
    assert checkpoint["status"] == "bypassed" and checkpoint["durationMs"] == 0
    assert checkpoint["effectsSummary"] == {"fs": 1} and checkpoint["executionFingerprint"] == "fp"


@pytest.mark.parametrize("terminal", ["pass", "fail"])
@pytest.mark.negative
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


@pytest.mark.negative
def test_execution_rejects_missing_identity_and_non_ref_values() -> None:
    with pytest.raises(ValueError, match="required"):
        ComponentExecution("", "n", "r")
    with pytest.raises(TypeError, match="ArtifactRef"):
        ComponentExecution("m@1", "n", "r", input_artifact_refs=("bad",))
    with pytest.raises(TypeError, match="ArtifactRef"):
        ComponentExecution("m@1", "n", "r").start(["bad"])
