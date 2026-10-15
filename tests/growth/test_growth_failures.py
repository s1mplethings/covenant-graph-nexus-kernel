from __future__ import annotations

import pytest

from cgkn.capabilities import CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec
from cgkn.execution import BlockExecutionRequest, BlockStatus, TaskContext
from cgkn.executors import ExecutorRegistry
from cgkn.growth import CapabilityGap, GrowthLoop, LocalDiscoverySource, LocalSandbox, default_growth_executor_factories
from cgkn.growth.loop import StdlibJsonExecutor
from cgkn.growth.sandbox import SandboxTrialResult


pytestmark = [pytest.mark.negative, pytest.mark.fault_injection, pytest.mark.security]


def component():
    return ComponentSpec("json.parse", "1", (PortSpec("text", "artifact.text@1"),), (PortSpec("object", "artifact.json@1"),))


def gap(capability="json.parse"):
    return CapabilityGap("gap", "p", "r", capability, ("text",), ("object",), (), "missing", "node", "LOW")


def build(tmp_path, *, discovery=None, sandbox=None, executors=None):
    spec = component()
    return GrowthLoop(CapabilityRegistry({spec.ref: spec}), executors or ExecutorRegistry(), discovery or LocalDiscoverySource(), sandbox or LocalSandbox(), factories=default_growth_executor_factories(), registry_path=tmp_path / "registry.json", evidence_root=tmp_path)


def test_no_candidate_fails_closed(tmp_path) -> None:
    with pytest.raises(LookupError, match="no local"):
        build(tmp_path).ensure(gap("unknown"))


def test_rejected_trial_persists_evidence_but_does_not_admit(tmp_path) -> None:
    class RejectingSandbox:
        def trial(self, candidate):
            return SandboxTrialResult(candidate.candidate_id, False, {"identity_allowed": True, "kernel_files_unchanged": True}, "", "failed", candidate.identity, 0, ())
    loop = build(tmp_path, sandbox=RejectingSandbox())
    with pytest.raises(RuntimeError, match="not admitted"):
        loop.ensure(gap())
    assert (tmp_path / "p/r/growth_sandbox/gap/admission_receipt.json").is_file()
    with pytest.raises(KeyError):
        loop.registry.resolve("json.parse", "1")


def test_existing_executor_is_not_registered_twice_and_outcome_round_trips(tmp_path) -> None:
    executors = ExecutorRegistry(); executors.register(StdlibJsonExecutor())
    loop = build(tmp_path, executors=executors)
    first = loop.ensure(gap())
    second = loop.ensure(gap())
    assert first.as_dict()["receipt"]["verdict"] == "ADMITTED"
    assert second.as_dict()["receipt"] is None and second.reused
    assert len(executors.list()) == 1


def test_stdlib_executor_rejects_non_string_input() -> None:
    request = BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="n", component_ref="json.parse@1", executor_ref="python.stdlib.json@1", task_context=TaskContext("parse"), input_values={"text": 42})
    assert StdlibJsonExecutor().execute(request).status is BlockStatus.FAILED


def test_sandbox_rejects_non_allowlisted_candidate() -> None:
    candidate = LocalDiscoverySource().discover(gap())[0]
    object.__setattr__(candidate, "identity", "other")
    result = LocalSandbox().trial(candidate)
    assert not result.passed and result.checks == {"identity_allowed": False}
