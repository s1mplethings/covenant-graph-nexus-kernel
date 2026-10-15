from __future__ import annotations

import json

from cgkn.capabilities import CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec
from cgkn.execution import BlockExecutionRequest, BlockStatus, TaskContext
from cgkn.executors import ExecutorRegistry
from cgkn.growth import CapabilityGap, GrowthLoop, LocalDiscoverySource, LocalSandbox, default_growth_executor_factories


def component() -> ComponentSpec:
    return ComponentSpec("json.parse", "1", (PortSpec("text", "artifact.text@1"),), (PortSpec("object", "artifact.json@1"),))


def gap(run_id: str) -> CapabilityGap:
    return CapabilityGap(f"gap-{run_id}", "project", run_id, "json.parse", ("text",), ("object",), (), "missing capability", "parse", "LOW")


def test_json_parse_growth_trial_admission_execution_and_persistent_reuse(tmp_path) -> None:
    spec = component()
    registry = CapabilityRegistry({spec.ref: spec})
    executors = ExecutorRegistry()
    registry_path = tmp_path / "registry.json"
    loop = GrowthLoop(registry, executors, LocalDiscoverySource(), LocalSandbox(), factories=default_growth_executor_factories(), registry_path=registry_path, evidence_root=tmp_path)
    try:
        registry.resolve("json.parse", "1")
        assert False, "capability must initially be missing"
    except KeyError:
        pass
    outcome = loop.ensure(gap("run-1"))
    assert outcome.growth_invoked and outcome.candidate_count == outcome.trial_count == 1
    assert outcome.receipt and outcome.receipt.verdict == "ADMITTED"
    assert all(outcome.receipt.checks.values())
    executor = executors.resolve("python.stdlib.json@1", "json.parse@1")
    request = BlockExecutionRequest(project_id="project", run_id="run-1", attempt_id="a1", node_id="parse", component_ref="json.parse@1", executor_ref="python.stdlib.json@1", task_context=TaskContext("parse JSON"), input_values={"text": '{"answer": 42}'})
    assert executor.execute(request).outputs == {"object": {"answer": 42}}
    invalid = type(request)(**{**request.__dict__, "attempt_id": "a2", "input_values": {"text": "{broken"}})
    assert executor.execute(invalid).status is BlockStatus.FAILED
    evidence = tmp_path / "project/run-1/growth_sandbox/gap-run-1"
    assert {item.name for item in evidence.iterdir()} == {"gap.json", "candidate.json", "trial.json", "admission_receipt.json"}
    trial = json.loads((evidence / "trial.json").read_text(encoding="utf-8"))
    assert trial["network_calls"] == 0 and trial["files_created"] == []
    loaded = CapabilityRegistry.load(registry_path, {spec.ref: spec})
    second_executors = ExecutorRegistry()
    second = GrowthLoop(loaded, second_executors, LocalDiscoverySource(), LocalSandbox(), factories=default_growth_executor_factories(), registry_path=registry_path, evidence_root=tmp_path)
    reuse = second.ensure(gap("run-2"))
    assert reuse.reused and not reuse.growth_invoked
    assert second.invoked_count == 0
    assert second_executors.resolve("python.stdlib.json@1", "json.parse@1")


def test_discovery_is_offline_and_bounded_to_supported_gap() -> None:
    assert LocalDiscoverySource().discover(gap("run"))[0].identity == "json.loads"
    missing = CapabilityGap("g", "p", "r", "unknown.capability", ("x",), ("y",), (), "missing", "n", "LOW")
    assert LocalDiscoverySource().discover(missing) == []
