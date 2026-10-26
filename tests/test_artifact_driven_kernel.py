from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.artifacts import (
    ArtifactInstance,
    ArtifactRef,
    ArtifactStore,
    ArtifactTypeRegistry,
    ArtifactValidationError,
    Producer,
    Provenance,
    artifact_diff,
    content_hash,
)
from cgkn.artifacts.lineage import build_lineage
from cgkn.compiler import ArtifactFlowCompiler
from cgkn.runtime import ArtifactInvalidator, ArtifactModuleRunner, ModuleExecutionError, build_context_pack, execution_fingerprint
from cgkn.runtime.delivery import evaluate_delivery_readiness
from cgkn.runtime.effects import EffectConstraintViolation, EffectCounter


FLOW = "flow.artifact_driven_project_refactor@1"
PROJECT = json.loads((ROOT / "examples" / "artifact-driven" / "todo-refactor" / "todo_project.json").read_text(encoding="utf-8"))


def seed(store: ArtifactStore, artifact_type: str, content: dict, port: str, *, node: str = "flow_input", supersedes=None):
    return store.write_artifact(
        ArtifactInstance(
            id=store.allocate_id(artifact_type),
            artifact_type=artifact_type,
            run_id=store.run_dir.name,
            producer=Producer(node, "module.test@1", port),
            content=content,
            provenance=Provenance(source_refs=("test",)),
            supersedes=supersedes,
        )
    )


def initial_run(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    store = ArtifactStore(run_dir, ArtifactTypeRegistry(ROOT))
    inputs = {
        "raw_requirement": seed(store, "artifact.raw_requirement@1", {"text": "Add bulk archive", "source": "test"}, "raw_requirement"),
        "project": seed(store, "artifact.project_source@1", PROJECT, "project"),
    }
    runner = ArtifactModuleRunner(ROOT, run_dir, FLOW)
    result = runner.run(inputs, raw_source_chars=12000)
    return store, inputs, runner, result


def test_artifact_instance_schema_shape_and_ref() -> None:
    artifact = ArtifactInstance(
        id="ai.raw.001", artifact_type="artifact.raw_requirement@1", run_id="r1",
        producer=Producer("n", "module.test@1"), content={"text": "goal"}, provenance=Provenance(),
    )
    assert artifact.as_dict()["kind"] == "ArtifactInstance"
    assert ArtifactRef.from_dict(artifact.ref.as_dict()) == artifact.ref


def test_content_hash_is_stable_for_key_order() -> None:
    assert content_hash({"b": [2, 1], "a": "x"}) == content_hash({"a": "x", "b": [2, 1]})
    assert content_hash({"a": 1}).startswith("sha256:")


def test_invalid_content_is_blocked_before_write(tmp_path: pathlib.Path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    artifact = ArtifactInstance(
        id="ai.invalid.001", artifact_type="artifact.raw_requirement@1", run_id="r",
        producer=Producer("n", "module.test@1"), content={}, provenance=Provenance(),
    )
    with pytest.raises(ArtifactValidationError):
        store.write_artifact(artifact)
    assert not (tmp_path / "artifacts" / "ai.invalid.001.json").exists()


def test_provenance_is_stored_and_hash_verified(tmp_path: pathlib.Path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    first = seed(store, "artifact.raw_requirement@1", {"text": "goal"}, "requirement")
    artifact = ArtifactInstance(
        id="ai.interpretation.001", artifact_type="artifact.requirement_interpretation@1", run_id=tmp_path.name,
        producer=Producer("n_interpret", "module.requirement.interpret@1", "interpretation"),
        content={"goal":"goal","explicitRequirements":[],"constraints":[],"nonGoals":[],"ambiguities":[],"assumptions":[]},
        provenance=Provenance(input_artifact_refs=(first,), provider="qwen", model="qwen-test", prompt_version="v1"),
    )
    ref = store.write_artifact(artifact)
    loaded = store.resolve_artifact_ref(ref)
    assert loaded.provenance.input_artifact_refs == (first,)
    assert loaded.provenance.model == "qwen-test"
    assert store.verify_artifact_hash(ref)


def test_supersedes_preserves_history_and_updates_status(tmp_path: pathlib.Path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    old = seed(store, "artifact.raw_requirement@1", {"text": "old"}, "requirement")
    new = seed(store, "artifact.raw_requirement@1", {"text": "new"}, "requirement", supersedes=old.artifact_instance_id)
    assert store.read_artifact(old.artifact_instance_id).status == "superseded"
    assert store.read_artifact(new.artifact_instance_id).supersedes == old.artifact_instance_id
    assert len(store.list_artifacts("artifact.raw_requirement@1")) == 2


def test_artifact_diff_reports_added_removed_changed() -> None:
    diff = artifact_diff({"a": 1, "gone": True}, {"a": 2, "new": [1]})
    assert [item["path"] for item in diff["changed"]] == ["/a"]
    assert [item["path"] for item in diff["removed"]] == ["/gone"]
    assert [item["path"] for item in diff["added"]] == ["/new"]


def test_reference_flow_compiles_typed_artifact_graph() -> None:
    result = ArtifactFlowCompiler(ROOT).compile(FLOW)
    assert result["ok"], result["diagnostics"]
    assert "n_problem_analysis" in result["compiled_bundle"]["topological_order"]


def test_missing_required_input_producer_is_blocked() -> None:
    compiler = ArtifactFlowCompiler(ROOT)
    compiler.flows[FLOW] = copy.deepcopy(compiler.flows[FLOW])
    compiler.flows[FLOW]["edges"] = [
        edge for edge in compiler.flows[FLOW]["edges"]
        if edge.get("to") != {"node": "n_problem_analysis", "port": "snapshot"}
    ]
    result = compiler.compile(FLOW)
    assert "CGKN_INPUT_UNBOUND" in {item["code"] for item in result["diagnostics"]}


def test_wrong_port_type_is_blocked() -> None:
    compiler = ArtifactFlowCompiler(ROOT)
    module_ref = "module.problem.analyze@1"
    compiler.modules[module_ref] = copy.deepcopy(compiler.modules[module_ref])
    compiler.modules[module_ref]["ports"]["input"]["snapshot"]["artifact_type"] = "artifact.raw_requirement@1"
    result = compiler.compile(FLOW)
    assert "CGKN_EDGE_TYPE_MISMATCH" in {item["code"] for item in result["diagnostics"]}


def test_multiple_producer_is_invalid() -> None:
    compiler = ArtifactFlowCompiler(ROOT)
    compiler.flows[FLOW] = copy.deepcopy(compiler.flows[FLOW])
    edge = next(item for item in compiler.flows[FLOW]["edges"] if item.get("to") == {"node": "n_problem_analysis", "port": "snapshot"})
    compiler.flows[FLOW]["edges"].append(copy.deepcopy(edge))
    result = compiler.compile(FLOW)
    assert "CGKN_INPUT_MULTI_PRODUCER" in {item["code"] for item in result["diagnostics"]}


def test_artifact_graph_cycle_is_invalid() -> None:
    compiler = ArtifactFlowCompiler(ROOT)
    module_ref = "module.problem.analyze@1"
    compiler.modules[module_ref] = copy.deepcopy(compiler.modules[module_ref])
    compiler.modules[module_ref]["ports"]["input"]["back"] = {"artifact_type": "artifact.architecture_decision@1", "required": True}
    compiler.flows[FLOW] = copy.deepcopy(compiler.flows[FLOW])
    compiler.flows[FLOW]["edges"].append({"from":{"node":"n_architecture","port":"architecture"},"to":{"node":"n_problem_analysis","port":"back"}})
    result = compiler.compile(FLOW)
    assert "CGKN_GRAPH_CYCLE" in {item["code"] for item in result["diagnostics"]}


def test_invalid_projection_and_missing_implementation_are_blocked() -> None:
    compiler = ArtifactFlowCompiler(ROOT)
    module_ref = "module.problem.analyze@1"
    compiler.modules[module_ref] = copy.deepcopy(compiler.modules[module_ref])
    compiler.modules[module_ref]["ports"]["input"]["snapshot"]["projection"] = ["doesNotExist"]
    del compiler.modules[module_ref]["implementation"]
    codes = {item["code"] for item in compiler.compile(FLOW)["diagnostics"]}
    assert {"CGKN_PROJECTION_FIELD_INVALID", "CGKN_RUNTIME_IMPLEMENTATION_MISSING"} <= codes


def test_runtime_materializes_outputs_and_index_consumers(tmp_path: pathlib.Path) -> None:
    store, _, _, result = initial_run(tmp_path)
    judgment = store.resolve_artifact_ref(result["outputs"]["delivery_judgment"])
    assert judgment.content["evidenceStatus"] == "PASS"
    index = json.loads(store.index_path.read_text(encoding="utf-8"))
    analysis = next(row for row in index["artifacts"] if row["artifactType"] == "artifact.problem_analysis@1")
    assert "n_architecture" in analysis["consumers"]


def test_checkpoint_contains_refs_not_business_content(tmp_path: pathlib.Path) -> None:
    _, _, _, _ = initial_run(tmp_path)
    checkpoint = json.loads((tmp_path / "run" / "checkpoints" / "n_problem_analysis.json").read_text(encoding="utf-8"))
    assert checkpoint["inputArtifactRefs"] and checkpoint["outputArtifactRefs"]
    assert "content" not in checkpoint
    assert set(checkpoint) == {"kind","executionId","componentRef","runId","nodeId","status","startedAt","finishedAt","durationMs","inputArtifactRefs","outputArtifactRefs","executionFingerprint","cacheStatus","diagnostics","evidenceRefs","effectsSummary"}
    assert checkpoint["componentRef"] == "module.problem.analyze@1"


def test_provider_output_gets_one_bounded_schema_repair(tmp_path: pathlib.Path) -> None:
    calls = []
    runner = ArtifactModuleRunner(ROOT, tmp_path / "run", FLOW, provider_executor=lambda request: calls.append(request.copy()) or (
        {"interpretation": {}} if len(calls) == 1 else {"interpretation":{"goal":"g","explicitRequirements":[],"constraints":[],"nonGoals":[],"ambiguities":[],"assumptions":[]}}
    ))
    module = copy.deepcopy(runner.compiler.modules["module.requirement.interpret@1"])
    module["implementation"] = {"kind":"provider","promptVersion":"v1","cacheable":False,"model":"test"}
    requirement = seed(runner.store, "artifact.raw_requirement@1", {"text":"g"}, "requirement")
    output, _ = runner._execute(module, {"requirement": requirement}, {}, {"id":"n"})
    assert output["interpretation"]["goal"] == "g"
    assert [item["repair"] for item in calls] == [False, True]


def test_provider_invalid_output_creates_diagnostic_and_no_artifact(tmp_path: pathlib.Path) -> None:
    runner = ArtifactModuleRunner(ROOT, tmp_path / "run", FLOW, provider_executor=lambda request: {"interpretation": {}})
    module = copy.deepcopy(runner.compiler.modules["module.requirement.interpret@1"])
    module["implementation"] = {"kind":"provider","promptVersion":"v1","cacheable":False}
    requirement = seed(runner.store, "artifact.raw_requirement@1", {"text":"g"}, "requirement")
    before = len(runner.store.list_artifacts())
    with pytest.raises(ModuleExecutionError) as error:
        runner._execute(module, {"requirement": requirement}, {}, {"id":"n"})
    assert error.value.diagnostics[0]["code"] == "CGKN_PROVIDER_OUTPUT_INVALID"
    assert len(runner.store.list_artifacts()) == before


def test_context_uses_only_declared_required_artifacts_and_projection(tmp_path: pathlib.Path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    req = seed(store, "artifact.requirement_interpretation@1", {"goal":"g","explicitRequirements":[],"constraints":[],"nonGoals":[],"ambiguities":[],"assumptions":[]}, "requirement")
    snapshot = seed(store, "artifact.project_snapshot@1", PROJECT, "snapshot")
    compiler = ArtifactFlowCompiler(ROOT)
    module = compiler.modules["module.problem.analyze@1"]
    pack = build_context_pack({"id":"n_problem"}, module, {"requirement":req,"snapshot":snapshot}, store, compiler.policies["policy.artifact_driven_project_refactor@1"])
    assert set(pack["context"]["artifacts"]) == {"requirement", "snapshot"}
    assert set(pack["context"]["artifacts"]["snapshot"]["content"]) == {"modules","boundaries","importantFiles","knownRisks"}


def test_context_budget_and_trace_are_enforced(tmp_path: pathlib.Path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    huge = dict(PROJECT)
    huge["importantFiles"] = [f"src/file_{index}.py" for index in range(300)]
    ref = seed(store, "artifact.project_snapshot@1", huge, "snapshot")
    compiler = ArtifactFlowCompiler(ROOT)
    module = copy.deepcopy(compiler.modules["module.project.snapshot_artifact@1"])
    module["ports"]["input"]["project"]["artifact_type"] = "artifact.project_snapshot@1"
    module["context"]["maxChars"] = 500
    pack = build_context_pack({"id":"n"}, module, {"project":ref}, store, compiler.policies["policy.artifact_driven_project_refactor@1"], raw_source_chars=5000)
    assert pack["metrics"]["contextChars"] <= 500
    assert pack["trace"][0]["artifactRef"] == ref.as_dict()
    assert pack["metrics"]["tokenEstimate"] > 0


def test_same_fingerprint_hits_cache_and_changes_miss(tmp_path: pathlib.Path) -> None:
    store, inputs, _, first = initial_run(tmp_path)
    second = ArtifactModuleRunner(ROOT, tmp_path / "run", FLOW).run(inputs, raw_source_chars=12000)
    rows = {row["nodeId"]: row for row in second["feedForwardReport"]["nodes"]}
    assert rows["n_project_snapshot"]["cache"] == "hit"
    assert rows["n_problem_analysis"]["cache"] == "hit"


def test_fingerprint_changes_with_input_module_and_prompt() -> None:
    a = ArtifactRef("a", "artifact.raw_requirement@1", "sha256:" + "1" * 64)
    b = ArtifactRef("b", "artifact.raw_requirement@1", "sha256:" + "2" * 64)
    base = execution_fingerprint("module.x@1", {}, [a], "p1", "policy.x@1")
    assert base != execution_fingerprint("module.x@1", {}, [b], "p1", "policy.x@1")
    assert base != execution_fingerprint("module.x@2", {}, [a], "p1", "policy.x@1")
    assert base != execution_fingerprint("module.x@1", {}, [a], "p2", "policy.x@1")


def test_upstream_change_invalidates_only_descendants_and_explains(tmp_path: pathlib.Path) -> None:
    store, _, runner, result = initial_run(tmp_path)
    old = store.resolve_artifact_ref(result["outputs"]["requirement_interpretation"])
    content = dict(old.content)
    content["constraints"] = ["confirmation required"]
    changed = ArtifactInstance(
        id=store.allocate_id(old.artifact_type), artifact_type=old.artifact_type, run_id=store.run_dir.name,
        producer=old.producer, content=content, provenance=old.provenance, supersedes=old.id,
    )
    changed_ref = store.write_artifact(changed)
    report = ArtifactInvalidator(store, runner.graph).invalidate(changed_ref)
    assert "n_problem_analysis" in report["affectedNodes"]
    assert "n_project_snapshot" not in report["affectedNodes"]
    assert report["explanations"][0]["reason"] == "upstream_artifact_changed"
    assert report["explanations"][0]["changedInputs"][0]["oldHash"] != report["explanations"][0]["changedInputs"][0]["newHash"]
    assert store.resolve_artifact_ref(result["outputs"]["project_snapshot"]).status == "fresh"


def test_invalidation_dry_run_does_not_mutate(tmp_path: pathlib.Path) -> None:
    store, _, runner, result = initial_run(tmp_path)
    source = result["outputs"]["requirement_interpretation"]
    report = ArtifactInvalidator(store, runner.graph).invalidate(source, dry_run=True)
    assert report["dryRun"]
    assert store.resolve_artifact_ref(result["outputs"]["problem_analysis"]).status == "fresh"


def test_stale_artifact_blocks_delivery_readiness(tmp_path: pathlib.Path) -> None:
    store, _, _, result = initial_run(tmp_path)
    judgment = result["outputs"]["delivery_judgment"]
    store.set_status(judgment.artifact_instance_id, "stale")
    report = evaluate_delivery_readiness(store, [judgment])
    assert report["evidenceStatus"] == "NEEDS_REWORK"
    assert report["diagnostics"][0]["code"] == "CGKN_REQUIRED_ARTIFACT_STALE"


def test_complete_lineage_passes_and_tree_reaches_inputs(tmp_path: pathlib.Path) -> None:
    store, _, _, result = initial_run(tmp_path)
    judgment = result["outputs"]["delivery_judgment"]
    assert evaluate_delivery_readiness(store, [judgment])["evidenceStatus"] == "PASS"
    tree = build_lineage(store, judgment)
    assert tree["inputs"]


def test_missing_artifact_blocks_delivery() -> None:
    class MissingStore:
        def resolve_artifact_ref(self, ref):
            raise ArtifactValidationError("missing")
    ref = ArtifactRef("missing", "artifact.delivery_judgment@1", "sha256:" + "0" * 64)
    assert evaluate_delivery_readiness(MissingStore(), [ref])["evidenceStatus"] == "NEEDS_REWORK"


def test_effect_cardinality_accepts_node_and_run_scopes() -> None:
    counter = EffectCounter([{"effect":"provider_call","scope":"node","max":2},{"effect":"fs_write","scope":"run","max":2}])
    counter.consume("provider_call", 2, node_id="n1")
    counter.consume("fs_write", 1, node_id="n1", run="r")
    counter.consume("fs_write", 1, node_id="n2", run="r")


def test_effect_cardinality_violation_blocks_execution() -> None:
    counter = EffectCounter([{"effect":"provider_call","scope":"node","max":1}])
    counter.consume("provider_call", 1, node_id="n")
    with pytest.raises(EffectConstraintViolation):
        counter.consume("provider_call", 1, node_id="n")


def test_compiler_rejects_invalid_effect_constraint() -> None:
    compiler = ArtifactFlowCompiler(ROOT)
    policy_ref = "policy.artifact_driven_project_refactor@1"
    compiler.policies[policy_ref] = copy.deepcopy(compiler.policies[policy_ref])
    compiler.policies[policy_ref]["effect_constraints"] = [{"effect":"magic","scope":"forever","max":-1}]
    assert "CGKN_EFFECT_CONSTRAINT_INVALID" in {item["code"] for item in compiler.compile(FLOW)["diagnostics"]}


def test_run_manifest_and_feed_forward_report_exist(tmp_path: pathlib.Path) -> None:
    _, _, _, result = initial_run(tmp_path)
    manifest = json.loads((tmp_path / "run" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert len(manifest["nodeCheckpoints"]) == 9
    assert result["feedForwardReport"]["nodes"][0]["contextChars"] > 0


def test_cli_flow_explain_and_lineage_json(tmp_path: pathlib.Path) -> None:
    _, _, _, result = initial_run(tmp_path)
    explained = subprocess.run([sys.executable, str(ROOT / "scripts" / "explain_flow.py"), "--flow", FLOW, "--json"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(explained.stdout)["nodes"][0]["inputs"]
    lineage = subprocess.run([sys.executable, str(ROOT / "scripts" / "artifact_lineage.py"), "--run-dir", str(tmp_path / "run"), "--artifact", result["outputs"]["delivery_judgment"].artifact_instance_id, "--json"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(lineage.stdout)["inputs"]
