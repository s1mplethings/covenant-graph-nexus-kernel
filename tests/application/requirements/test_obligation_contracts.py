from __future__ import annotations

import json

import pytest

from cgkn.application.requirements import (
    DependencyDomainPolicy,
    DependencyPolicy,
    NetworkPolicy,
    Obligation,
    ObligationCompletenessValidator,
    ObligationKind,
    ObligationPreflightReceipt,
    ObligationSet,
    RequirementCompiler,
    RequirementExplicitness,
    RequirementSource,
    RequirementSourceType,
    TestBinding,
    TraceabilityGraph,
    build_traceability,
    validate_traceability,
)
from cgkn.application.requirements.obligation import FrozenMapping


def source(source_id: str = "REQ-001", source_type: RequirementSourceType = RequirementSourceType.USER_EXPLICIT) -> RequirementSource:
    explicitness = RequirementExplicitness.INTERNAL if source_type is RequirementSourceType.HARNESS_INTERNAL else RequirementExplicitness.EXPLICIT
    return RequirementSource(source_id, "  invalid input   should fail clearly ", source_type, explicitness=explicitness)


def policy() -> DependencyPolicy:
    return DependencyPolicy(
        "POLICY-DEPS-001",
        runtime=DependencyDomainPolicy(stdlib_only=True),
        test=DependencyDomainPolicy(allowed_packages=("pytest",)),
        tooling=DependencyDomainPolicy(allowed_packages=("pytest",)),
        network=NetworkPolicy("FORBIDDEN"),
    )


def obligation(identifier: str = "OBL-ERR-001", **updates) -> Obligation:
    values = {
        "obligation_id": identifier,
        "kind": ObligationKind.ERROR_SEMANTICS,
        "subject": "invalid column",
        "source_requirement_refs": ("REQ-001",),
        "preconditions": {"column_missing": True},
        "operation": {"command": "clean"},
        "expected": {"exit_code": "nonzero", "stderr": "nonempty"},
        "forbidden": {"successful_output_commit": True},
        "dependency_policy": policy(),
        "verification_method": ("public_test", "hidden_acceptance"),
        "provenance": {"compiler": "deterministic"},
    }
    values.update(updates)
    return Obligation(**values)


def test_obligation_round_trip_is_immutable_hashable_and_deterministic() -> None:
    first = obligation()
    rendered = json.loads(json.dumps(first.as_dict()))
    second = Obligation.from_dict(rendered)
    assert second == first
    assert second.obligation_hash == first.obligation_hash
    assert hash(second) == hash(first)
    with pytest.raises(TypeError):
        first.expected["exit_code"] = "zero"  # type: ignore[index]


def test_obligation_set_rejects_duplicate_id_and_hash_tamper() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ObligationSet((obligation(), obligation()))
    document = ObligationSet((obligation(),)).as_dict()
    document["obligation_set_hash"] = "sha256:bad"
    with pytest.raises(ValueError, match="hash mismatch"):
        ObligationSet.from_dict(document)


def test_dependency_policy_separates_runtime_test_tooling_and_network() -> None:
    value = policy()
    assert value.runtime.stdlib_only is True
    assert value.allows("runtime", "pytest") is False
    assert value.allows("test", "pytest") is True
    assert value.allows("tooling", "pytest") is True
    assert value.network.outbound == "FORBIDDEN"
    assert DependencyPolicy.from_dict(value.as_dict()) == value
    with pytest.raises(ValueError):
        DependencyDomainPolicy(stdlib_only=True, allowed_packages=("pytest",))


def test_compiler_normalizes_and_stabilizes_generated_ids() -> None:
    compiler = RequirementCompiler()
    normalized = compiler.normalize((source(),), ("REQ-001",))
    spec = {
        "kind": "BEHAVIOR", "subject": "  stable   behavior ",
        "source_requirement_refs": ["REQ-001"], "expected": {"result": "stable"},
        "verification_method": ["public_test"],
    }
    first = compiler.compile(normalized, (spec,))
    second = compiler.compile(normalized, (spec,))
    assert first.as_dict() == second.as_dict()
    assert first.obligations[0].subject == "stable behavior"


def test_compiler_rejects_missing_internal_and_ungrounded_derived_sources() -> None:
    compiler = RequirementCompiler()
    normalized = compiler.normalize((source(),), ("REQ-001",))
    with pytest.raises(ValueError, match="missing or unknown"):
        compiler.compile(normalized, ({"kind": "BEHAVIOR", "subject": "x", "source_requirement_refs": ["REQ-404"]},))
    internal = compiler.normalize((source("REQ-HARNESS", RequirementSourceType.HARNESS_INTERNAL),), ())
    with pytest.raises(ValueError, match="HARNESS_INTERNAL"):
        compiler.compile(internal, ({"kind": "BEHAVIOR", "subject": "x", "source_requirement_refs": ["REQ-HARNESS"]},))
    derived = compiler.normalize((source("REQ-DERIVED", RequirementSourceType.DERIVED),), ())
    with pytest.raises(ValueError, match="non-derived"):
        compiler.compile(derived, ({"kind": "BEHAVIOR", "subject": "x", "source_requirement_refs": ["REQ-DERIVED"]},))


def test_completeness_rejects_unmapped_unverifiable_and_invalid_expected() -> None:
    requirements = RequirementCompiler().normalize((source(), source("REQ-002")), ("REQ-001", "REQ-002"))
    incomplete = obligation(verification_method=(), expected={})
    result = ObligationCompletenessValidator().validate(requirements, ObligationSet((incomplete,)))
    assert result.status == "REQUIREMENT_INCOMPLETE"
    assert "unmapped_public_acceptance:REQ-002" in result.errors
    assert "unverifiable_obligation:OBL-ERR-001" in result.errors
    assert "incomplete_error_semantics:OBL-ERR-001" in result.errors


def test_traceability_covers_requirement_public_hidden_and_evidence_routes() -> None:
    requirements = RequirementCompiler().normalize((source(),), ("REQ-001",))
    obligations = ObligationSet((obligation(),))
    graph = build_traceability(
        requirements, obligations, {"OBL-ERR-001": ("WU-CLI-CORE",)},
        (TestBinding("TEST-PUBLIC-ERROR", ("OBL-ERR-001",)), TestBinding("ACCEPT-HIDDEN-ERROR", ("OBL-ERR-001",), hidden=True)),
        {"EVIDENCE-001": ("OBL-ERR-001",)},
    )
    result = validate_traceability(requirements, obligations, graph)
    assert result.status == "PASS"
    assert result.public_test_coverage == result.hidden_acceptance_coverage == 1.0
    assert graph.requirement_to_obligations["REQ-001"] == ("OBL-ERR-001",)


@pytest.mark.parametrize("hidden", [False, True])
def test_orphan_test_obligation_is_harness_contract_gap(hidden: bool) -> None:
    requirements = RequirementCompiler().normalize((source(),), ("REQ-001",))
    obligations = ObligationSet((obligation(),))
    graph = build_traceability(requirements, obligations, tests=(TestBinding("TEST-ORPHAN", ("OBL-NOT-FOUND",), hidden=hidden),))
    result = validate_traceability(requirements, obligations, graph)
    assert result.status == "HARNESS_CONTRACT_GAP"
    assert "ORPHAN_OBLIGATION" in result.errors[0]


def test_missing_hidden_obligation_metadata_is_harness_contract_gap() -> None:
    requirements = RequirementCompiler().normalize((source(),), ("REQ-001",))
    obligations = ObligationSet((obligation(),))
    graph = TraceabilityGraph(
        FrozenMapping({"REQ-001": ["OBL-ERR-001"]}), FrozenMapping(), FrozenMapping(),
        FrozenMapping({"TEST-PUBLIC": ["OBL-ERR-001"]}), FrozenMapping({"ACCEPT-HIDDEN": []}), FrozenMapping(),
    )
    result = validate_traceability(requirements, obligations, graph)
    assert result.status == "HARNESS_CONTRACT_GAP"
    assert result.hidden_acceptance_coverage == 0.0


def test_preflight_only_completes_with_complete_obligations_and_traceability() -> None:
    requirements = RequirementCompiler().normalize((source(),), ("REQ-001",))
    obligations = ObligationSet((obligation(),))
    validation = ObligationCompletenessValidator().validate(requirements, obligations)
    traceability = validate_traceability(requirements, obligations, build_traceability(requirements, obligations))
    receipt = ObligationPreflightReceipt.build(requirements, obligations, validation, traceability).as_dict()
    assert receipt["status"] == "COMPLETE"
    assert receipt["receipt_hash"].startswith("sha256:")
