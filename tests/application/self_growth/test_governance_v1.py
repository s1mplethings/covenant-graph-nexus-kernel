from __future__ import annotations

import json
from dataclasses import replace

import pytest

from cgkn.application.capability_routing.benchmarks import real_product_registry
from cgkn.application.self_growth import (
    CapabilityExperienceLedger,
    CapabilityProposal,
    EffectTier,
    ExperimentalRegistryClone,
    GapClass,
    GrowthGovernance,
    GrowthGroup,
    GrowthTaskNeed,
    QualificationLevel,
    StrongDecisionPacket,
    canonical_hash,
    policy_hashes,
    proposal_for_need,
    qualification_receipt,
)


pytestmark = [pytest.mark.boundary, pytest.mark.security, pytest.mark.roundtrip]


def need(**overrides):
    values = {
        "task_id": "task-1",
        "goal": "Normalize text using a reusable bounded transform",
        "family": "text.normalize",
        "input_semantics": "text.transform.request@1",
        "output_semantics": "text.transform.result@1",
        "required_observable": "normalized text",
        "abstraction_choices": ("general family capability", "task-specific capability"),
    }
    values.update(overrides)
    return GrowthTaskNeed(**values)


def qualified(proposal: CapabilityProposal, *, hidden=(True, True, True)):
    return qualification_receipt(
        proposal,
        source_hash="sha256:" + "1" * 64,
        hidden_results=hidden,
        builder_passed=True,
        scope_passed=True,
        security_passed=True,
    )


def admit(clone: ExperimentalRegistryClone, task: GrowthTaskNeed):
    classification = GrowthGovernance().classify(task, clone, GrowthGroup.G2).classification
    proposal = proposal_for_need(task, classification, generalized=True)
    clone.admit(
        proposal,
        qualified(proposal),
        executor_ref=f"generated.{proposal.capability_id}@1",
        source_hash="sha256:" + "1" * 64,
    )
    return proposal


def test_experimental_registry_clone_preserves_production_authority() -> None:
    production = real_product_registry()
    before = canonical_hash([item.as_dict() for item in production.query()])
    clone = ExperimentalRegistryClone(production)
    assert clone.production_size == 10
    assert clone.size == 10
    assert canonical_hash([item.as_dict() for item in production.query()]) == before
    assert clone.registry is not production


def test_production_authority_hash_is_stable_across_fresh_registry_instances() -> None:
    first = ExperimentalRegistryClone(real_product_registry())
    second = ExperimentalRegistryClone(real_product_registry())

    assert first.production_authority_hash == second.production_authority_hash


def test_exact_reuse_is_resolved_before_growth() -> None:
    clone = ExperimentalRegistryClone(real_product_registry())
    result = GrowthGovernance().classify(
        need(
            family="workspace.inspect",
            goal="Inspect the bounded workspace",
            input_semantics="artifact.project_request@1",
            output_semantics="artifact.project_result@1",
            requested_capability_ref="workspace.inspect@1",
        ),
        clone,
        GrowthGroup.G3,
    ).classification
    assert result.gap_class is GapClass.NO_GAP_EXISTING_CAPABILITY
    assert result.selected_ref == "workspace.inspect@1"


@pytest.mark.parametrize(
    ("signal", "expected"),
    (
        ("KNOWLEDGE", GapClass.KNOWLEDGE_GAP),
        ("EVIDENCE", GapClass.EVIDENCE_GAP),
        ("PERMISSION", GapClass.PERMISSION_GAP),
        ("STATE", GapClass.STATE_GAP),
        ("PROVIDER_FAILURE", GapClass.PROVIDER_FAILURE),
        ("EXISTING_CAPABILITY_BUG", GapClass.EXISTING_CAPABILITY_BUG),
        ("PRODUCT_DIRECTION", GapClass.PRODUCT_DIRECTION_GAP),
        ("CORE_EXTENSION", GapClass.CORE_EXTENSION_REQUIRED),
    ),
)
def test_non_capability_failures_never_become_new_capabilities(signal, expected) -> None:
    result = GrowthGovernance().classify(
        need(failure_signal=signal), ExperimentalRegistryClone(real_product_registry()), GrowthGroup.G3
    ).classification
    assert result.gap_class is expected


@pytest.mark.parametrize(
    "boundary",
    ("KERNEL_AUTHORITY", "SECURITY_GUARD", "PRODUCTION_REGISTRY", "MULTI_AGENT_RUNTIME"),
)
def test_critical_authority_changes_stop(boundary) -> None:
    result = GrowthGovernance().classify(
        need(critical_boundary=boundary), ExperimentalRegistryClone(real_product_registry()), GrowthGroup.G3
    ).classification
    assert result.gap_class is GapClass.AUTHORITY_CHANGE_REQUIRED


def test_parameterization_precedes_new_capability_in_g2_and_g3() -> None:
    clone = ExperimentalRegistryClone(real_product_registry())
    admit(clone, need())
    variant = need(task_id="task-2", parameter_variant="collapse-whitespace")
    assert GrowthGovernance().classify(variant, clone, GrowthGroup.G2).classification.gap_class is GapClass.PARAMETERIZATION_GAP
    assert GrowthGovernance().classify(variant, clone, GrowthGroup.G3).classification.gap_class is GapClass.PARAMETERIZATION_GAP
    assert GrowthGovernance().classify(variant, clone, GrowthGroup.G1).classification.gap_class is GapClass.CAPABILITY_GAP


def test_bounded_composition_is_ephemeral_and_precedes_creation() -> None:
    clone = ExperimentalRegistryClone(real_product_registry())
    first = admit(clone, need(family="text.normalize", output_semantics="text.normalized@1"))
    second = admit(clone, need(task_id="task-2", family="text.slug", input_semantics="text.normalized@1", output_semantics="text.slug@1"))
    composite = need(
        task_id="task-3",
        family="report.anchor",
        output_semantics="text.slug@1",
        composition_goal=(first.abstraction_boundary, second.abstraction_boundary),
    )
    result = GrowthGovernance(max_composition_depth=3).classify(composite, clone, GrowthGroup.G3).classification
    assert result.gap_class is GapClass.COMPOSITION_GAP
    assert result.composition and result.composition.depth == 2
    assert result.composition.as_dict()["authority"] == "ephemeral_execution_plan"


def test_composition_depth_is_bounded() -> None:
    clone = ExperimentalRegistryClone(real_product_registry())
    families = []
    for index in range(4):
        family = f"fixture.family{index}"
        families.append(family)
        admit(clone, need(
            task_id=f"task-{index}",
            family=family,
            goal=f"Perform bounded fixture operation {index}",
            input_semantics=f"fixture.input.{index}@1",
            output_semantics=f"fixture.output.{index}@1",
        ))
    result = GrowthGovernance(max_composition_depth=3).classify(
        need(task_id="task-c", composition_goal=tuple(families)), clone, GrowthGroup.G3
    ).classification
    assert result.gap_class is GapClass.CAPABILITY_GAP


def test_proposal_contains_complete_contract_and_stable_signature() -> None:
    task = need()
    classification = GrowthGovernance().classify(task, ExperimentalRegistryClone(real_product_registry()), GrowthGroup.G3).classification
    proposal = proposal_for_need(task, classification, generalized=True)
    doc = proposal.as_dict()
    assert doc["semantic_signature"] == proposal.semantic_signature
    assert doc["why_composition_is_insufficient"]
    assert set(doc["security_constraints"]) >= {"stdlib_only", "no_network", "no_secret_access"}
    assert proposal.semantic_signature == replace(proposal).semantic_signature


def test_duplicate_semantic_signature_and_identity_are_rejected() -> None:
    clone = ExperimentalRegistryClone(real_product_registry())
    proposal = admit(clone, need())
    with pytest.raises(ValueError, match="duplicate semantic responsibility"):
        clone.admit(
            replace(proposal, candidate_id="candidate.other", capability_id="text.normalize.alias"),
            qualified(replace(proposal, candidate_id="candidate.other", capability_id="text.normalize.alias")),
            executor_ref="generated.alias@1",
            source_hash="sha256:" + "2" * 64,
        )


def test_unsafe_effect_and_path_traversal_fail_closed() -> None:
    classification = GrowthGovernance().classify(need(), ExperimentalRegistryClone(real_product_registry()), GrowthGroup.G3).classification
    base = proposal_for_need(need(), classification, generalized=True)
    with pytest.raises(ValueError, match="effect"):
        replace(base, effect_class=EffectTier.EXTERNAL_WRITE)
    with pytest.raises(ValueError, match="traversal"):
        replace(base, allowed_paths=("../cgkn/runtime.py",))
    with pytest.raises(ValueError, match="canonical"):
        replace(base, capability_id="../spoof")
    with pytest.raises(ValueError, match="version"):
        replace(base, version="latest")


def test_hidden_qualification_is_required_for_admission() -> None:
    clone = ExperimentalRegistryClone(real_product_registry())
    classification = GrowthGovernance().classify(need(), clone, GrowthGroup.G3).classification
    proposal = proposal_for_need(need(), classification, generalized=True)
    receipt = qualified(proposal, hidden=(True, False, True))
    assert receipt.level is QualificationLevel.PROVISIONAL
    assert receipt.status == "FAIL"
    with pytest.raises(ValueError, match="QUALIFIED"):
        clone.admit(proposal, receipt, executor_ref="generated.text.normalize@1", source_hash=receipt.source_hash)


def test_experience_ledger_is_derived_atomic_and_rebuildable(tmp_path) -> None:
    path = tmp_path / "experience.json"
    ledger = CapabilityExperienceLedger(path)
    ledger.append({"task_id": "t1", "result": "PASS", "tokens": None, "usage_status": "UNKNOWN"})
    ledger.append({"task_id": "t2", "result": "FAIL", "tokens": 12, "usage_status": "REPORTED"})
    loaded = CapabilityExperienceLedger(path)
    assert len(loaded.events) == 2
    assert loaded.events[0]["tokens"] is None
    rebuilt = CapabilityExperienceLedger.rebuild(path, loaded.events)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert len(rebuilt.events) == 2
    assert doc["authority"] == "DERIVED_EXECUTION_EVIDENCE"
    assert doc["registry_authority"] is False


def test_strong_decision_packet_is_bounded_and_measures_compression() -> None:
    packet = StrongDecisionPacket(
        task_need={"goal": "normalize"},
        gap_classification_evidence={"gap": "CAPABILITY_GAP"},
        top_k_capabilities=({"ref": "a@1"}, {"ref": "b@1"}),
        failed_composition_attempts=({"reason": "contract mismatch"},),
        required_observable_result="normalized text",
        impact_risk="LOW",
        candidate_abstraction_choices=("general", "specific"),
        public_constraints=("stdlib", "sandbox"),
        full_possible_context_chars=10_000,
    )
    assert packet.actual_context_chars < 2_000
    assert packet.reduction_ratio > 0.8
    assert len(packet.top_k_capabilities) == 2


def test_policy_hashes_cover_every_frozen_policy_surface() -> None:
    hashes = policy_hashes()
    assert set(hashes) == {
        "growth_policy_hash",
        "composition_policy_hash",
        "candidate_contract_schema_hash",
        "experience_schema_hash",
        "admission_policy_hash",
        "sandbox_policy_hash",
    }
    assert all(value.startswith("sha256:") and len(value) == 71 for value in hashes.values())
