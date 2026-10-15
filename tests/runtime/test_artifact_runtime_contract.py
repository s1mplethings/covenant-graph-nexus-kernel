"""Current-path responsibility for the ArtifactModuleRunner compatibility adapter.

The original scenarios remain at their historical import location.  These aliases
bind the active runtime profile to the same executable functions without copying
or creating a second runtime implementation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from cgkn.artifacts import ArtifactInstance, ArtifactStore, ArtifactTypeRegistry, Producer, Provenance
from cgkn.runtime.cache import ArtifactCache
from cgkn.runtime.context import _shrink, build_context_pack
from cgkn.runtime.delivery import evaluate_delivery_readiness
from cgkn.runtime.invalidation import ArtifactInvalidator
from cgkn.runtime import reference_modules
from cgkn.compiler.artifact_graph import ArtifactGraph


_SOURCE = Path(__file__).resolve().parents[1] / "test_artifact_driven_kernel.py"
_SPEC = importlib.util.spec_from_file_location("cgkn_runtime_contract_scenarios", _SOURCE)
assert _SPEC and _SPEC.loader
_SCENARIOS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCENARIOS)


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary, pytest.mark.integration, pytest.mark.roundtrip, pytest.mark.determinism]


_NAMES = (
    "test_runtime_materializes_outputs_and_index_consumers",
    "test_checkpoint_contains_refs_not_business_content",
    "test_provider_output_gets_one_bounded_schema_repair",
    "test_provider_invalid_output_creates_diagnostic_and_no_artifact",
    "test_context_uses_only_declared_required_artifacts_and_projection",
    "test_context_budget_and_trace_are_enforced",
    "test_same_fingerprint_hits_cache_and_changes_miss",
    "test_fingerprint_changes_with_input_module_and_prompt",
    "test_upstream_change_invalidates_only_descendants_and_explains",
    "test_invalidation_dry_run_does_not_mutate",
    "test_stale_artifact_blocks_delivery_readiness",
    "test_complete_lineage_passes_and_tree_reaches_inputs",
    "test_missing_artifact_blocks_delivery",
    "test_effect_cardinality_accepts_node_and_run_scopes",
    "test_effect_cardinality_violation_blocks_execution",
    "test_run_manifest_and_feed_forward_report_exist",
)

for _name in _NAMES:
    globals()[_name] = getattr(_SCENARIOS, _name)
    globals()[_name].__module__ = __name__

test_provider_invalid_output_creates_diagnostic_and_no_artifact = pytest.mark.fault_injection(test_provider_invalid_output_creates_diagnostic_and_no_artifact)
test_effect_cardinality_violation_blocks_execution = pytest.mark.security(pytest.mark.fault_injection(test_effect_cardinality_violation_blocks_execution))
test_upstream_change_invalidates_only_descendants_and_explains = pytest.mark.recovery(test_upstream_change_invalidates_only_descendants_and_explains)
test_invalidation_dry_run_does_not_mutate = pytest.mark.recovery(test_invalidation_dry_run_does_not_mutate)


@pytest.mark.negative
@pytest.mark.fault_injection
def test_run_failure_marks_manifest_failed(tmp_path) -> None:
    run_dir = tmp_path / "run"
    store = ArtifactStore(run_dir, ArtifactTypeRegistry(_SCENARIOS.ROOT))
    project = _SCENARIOS.seed(store, "artifact.project_source@1", _SCENARIOS.PROJECT, "project")
    runner = _SCENARIOS.ArtifactModuleRunner(_SCENARIOS.ROOT, run_dir, _SCENARIOS.FLOW)
    with pytest.raises(_SCENARIOS.ModuleExecutionError, match="not bound"):
        runner.run({"project": project})
    assert runner._load_manifest()["status"] == "failed"


@pytest.mark.fault_injection
def test_cache_rejects_empty_missing_stale_and_tampered_entries(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path / "run", ArtifactTypeRegistry(_SCENARIOS.ROOT))
    cache = ArtifactCache(tmp_path / "run")
    assert cache.lookup("n", "sha256:none", store) is None
    path = cache._path("n", "sha256:empty"); path.parent.mkdir(parents=True); path.write_text('{"outputs": []}', encoding="utf-8")
    assert cache.lookup("n", "sha256:empty", store) is None
    ref = _SCENARIOS.seed(store, "artifact.raw_requirement@1", {"text": "x"}, "input")
    cache.record("n", "sha256:valid", [ref])
    assert cache.lookup("n", "sha256:valid", store) == [ref]
    monkeypatch.setattr(store, "verify_artifact_hash", lambda _ref: False)
    assert cache.lookup("n", "sha256:valid", store) is None
    missing = {**ref.as_dict(), "artifactInstanceId": "ai.missing.001"}
    cache._path("n", "sha256:missing").write_text(__import__("json").dumps({"outputs": [missing]}), encoding="utf-8")
    assert cache.lookup("n", "sha256:missing", store) is None


@pytest.mark.boundary
def test_context_shrink_decision_ledger_and_scalar_paths(tmp_path) -> None:
    assert _shrink("abcdef", 5) == "ab..."
    assert _shrink(["x" * 40], 20)[0].endswith("...")
    assert _shrink(3, 1) == 3
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(_SCENARIOS.ROOT))
    ref = _SCENARIOS.seed(store, "artifact.raw_requirement@1", {"text": "x" * 200}, "requirement")
    module = {"id": "m", "version": "1", "ports": {"input": {"required": {"required": True}, "optional": {"required": False}}}, "effects": {}, "context": {"includeDecisionLedger": True, "optionalArtifactPorts": ["optional"], "maxChars": 220}}
    pack = build_context_pack({"id": "n"}, module, {"required": ref, "optional": ref}, store, {}, {"decisions": [{"id": "d"}]})
    assert pack["context"].get("decisionLedger") == [{"id": "d"}]
    assert pack["metrics"]["contextChars"] <= 220


@pytest.mark.security
def test_delivery_detects_hash_tamper(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(_SCENARIOS.ROOT))
    ref = _SCENARIOS.seed(store, "artifact.raw_requirement@1", {"text": "x"}, "input")
    monkeypatch.setattr(store, "verify_artifact_hash", lambda _ref: False)
    report = evaluate_delivery_readiness(store, [ref])
    assert report["diagnostics"][0]["code"] == "CGKN_ARTIFACT_HASH_INVALID"


@pytest.mark.recovery
def test_artifact_invalidator_uses_direct_consumers_when_producer_is_external(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(_SCENARIOS.ROOT))
    ref = _SCENARIOS.seed(store, "artifact.raw_requirement@1", {"text": "x"}, "input", node="external")
    store.register_consumer(ref, "a")
    graph = ArtifactGraph("f", {"a": (), "b": ("a",)}, {"a": ("b",), "b": ()}, {})
    assert ArtifactInvalidator(store, graph).affected_nodes(ref) == ["a", "b"]


@pytest.mark.determinism
def test_reference_adapter_conditional_branches() -> None:
    interpreted = reference_modules.interpret_requirement({"requirement": {"text": "must not lose data; confirm first"}}, {})["interpretation"]
    assert len(interpreted["constraints"]) == 2
    snapshot = {"modules": ["m"], "boundaries": ["b"]}
    analysis = reference_modules.analyze_problem({"requirement": interpreted, "snapshot": snapshot}, {})["analysis"]
    assert "confirm before bulk archive" in analysis["requiredCapabilities"]
    architecture = reference_modules.decide_architecture({"analysis": analysis}, {})["architecture"]
    assert any("confirmation" in item for item in architecture["decisions"])
    plan = reference_modules.plan_refactor({"architecture": architecture, "snapshot": snapshot}, {})["plan"]
    assert any("confirmation" in item.lower() for item in plan["steps"])
