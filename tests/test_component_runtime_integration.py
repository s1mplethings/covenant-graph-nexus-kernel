import json
import pathlib

import pytest

from cgkn.artifacts import ArtifactInstance, ArtifactRef, ArtifactStore, ArtifactTypeRegistry, Producer, Provenance
from cgkn.component import ComponentExecutionStatus
from cgkn.runtime import ArtifactModuleRunner, ModuleExecutionError
from cgkn.runtime.effects import EffectCounter


ROOT = pathlib.Path(__file__).resolve().parents[1]
FLOW = "flow.artifact_driven_project_refactor@1"
PROJECT = json.loads((ROOT / "examples/artifact-driven/todo-refactor/todo_project.json").read_text(encoding="utf-8"))


def _seed(store, artifact_type, content, port):
    return store.write_artifact(ArtifactInstance(store.allocate_id(artifact_type), artifact_type, store.run_dir.name, Producer("flow_input", "module.test@1", port), content, Provenance()))


def _runner(tmp_path):
    run_dir = tmp_path / "run"
    store = ArtifactStore(run_dir, ArtifactTypeRegistry(ROOT))
    inputs = {"raw_requirement": _seed(store, "artifact.raw_requirement@1", {"text":"goal"}, "raw_requirement"), "project": _seed(store, "artifact.project_source@1", PROJECT, "project")}
    return ArtifactModuleRunner(ROOT, run_dir, FLOW), inputs


def test_runtime_records_component_execution_and_cache_hit(tmp_path) -> None:
    runner, inputs = _runner(tmp_path)
    first = runner.run(inputs)
    assert all(item.status is ComponentExecutionStatus.PASS for item in first["componentExecutions"])
    assert first["outputs"]["delivery_judgment"]
    second = ArtifactModuleRunner(ROOT, tmp_path / "run", FLOW).run(inputs)
    statuses = {item.node_id: item.status for item in second["componentExecutions"]}
    assert statuses["n_project_snapshot"] is ComponentExecutionStatus.CACHED
    assert ComponentExecutionStatus.CACHED in statuses.values()
    checkpoint = json.loads((tmp_path / "run/checkpoints/n_problem_analysis.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "cached" and checkpoint["executionId"]


def test_runtime_missing_required_input_creates_failed_execution(tmp_path) -> None:
    runner, inputs = _runner(tmp_path)
    runner.flow["edges"] = [edge for edge in runner.flow["edges"] if edge.get("to") != {"node":"n_requirement_interpretation","port":"requirement"}]
    with pytest.raises(ModuleExecutionError) as error:
        runner.run(inputs)
    assert error.value.diagnostics[0]["code"] == "CGKN_RUNTIME_REQUIRED_INPUT_MISSING"
    assert runner.component_executions[-1].status is ComponentExecutionStatus.FAIL


def test_unbound_flow_input_creates_failed_execution(tmp_path) -> None:
    runner, inputs = _runner(tmp_path)
    del inputs["raw_requirement"]
    with pytest.raises(ModuleExecutionError):
        runner.run(inputs)
    assert runner.component_executions[-1].status is ComponentExecutionStatus.FAIL


def test_component_exception_creates_failed_execution(tmp_path) -> None:
    runner, inputs = _runner(tmp_path)
    runner.local_functions["cgkn.runtime.reference_modules:interpret_requirement"] = lambda *_: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(ModuleExecutionError):
        runner.run(inputs)
    assert runner.component_executions[-1].status is ComponentExecutionStatus.FAIL
    assert runner.component_executions[-1].diagnostics


@pytest.mark.parametrize("failure", ["wrong_type", "bad_hash", "stale"])
def test_runtime_rejects_invalid_input_and_records_failure(tmp_path, failure) -> None:
    runner, inputs = _runner(tmp_path)
    if failure == "wrong_type":
        inputs["raw_requirement"] = inputs["project"]
    elif failure == "bad_hash":
        ref = inputs["raw_requirement"]
        inputs["raw_requirement"] = ArtifactRef(ref.artifact_instance_id, ref.artifact_type, "sha256:" + "0" * 64)
    else:
        runner.store.set_status(inputs["raw_requirement"].artifact_instance_id, "stale")
    with pytest.raises(ModuleExecutionError):
        runner.run(inputs)
    assert runner.component_executions[-1].status is ComponentExecutionStatus.FAIL
    if failure == "bad_hash":
        assert runner.component_executions[-1].diagnostics[0]["code"] == "CGKN_INPUT_HASH_INVALID"


def test_invalid_output_schema_records_failed_execution(tmp_path) -> None:
    runner, inputs = _runner(tmp_path)
    runner.local_functions["cgkn.runtime.reference_modules:interpret_requirement"] = lambda *_: {"interpretation": {}}
    with pytest.raises(ModuleExecutionError):
        runner.run(inputs)
    assert runner.component_executions[-1].status is ComponentExecutionStatus.FAIL
    assert "invalid artifact.requirement_interpretation@1 content" in runner.component_executions[-1].diagnostics[0]["message"]


def test_effect_violation_records_failed_execution(tmp_path) -> None:
    runner, inputs = _runner(tmp_path)
    runner.effects = EffectCounter([{"effect":"fs_read", "scope":"run", "max":0}])
    with pytest.raises(ModuleExecutionError):
        runner.run(inputs)
    assert runner.component_executions[-1].node_id == "n_project_snapshot"
    assert runner.component_executions[-1].status is ComponentExecutionStatus.FAIL
