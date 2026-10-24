from __future__ import annotations

import json
import os
import pathlib
import tempfile
import time
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from cgkn.application.capability_routing import CapabilityEffect, CapabilitySearchIndex, CapabilitySearchRequest
from cgkn.capabilities import CapabilityDescriptor, CapabilityLifecycle, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec

from .contracts_v1 import (
    CapabilityProposal,
    CompositionPlan,
    EffectTier,
    GapClass,
    GrowthClassification,
    GrowthGroup,
    GrowthTaskNeed,
    QualificationLevel,
    QualificationReceipt,
    canonical_hash,
)


GROWTH_POLICY_VERSION = "self-growth-v1.0"
ADMISSION_POLICY_VERSION = "experimental-admission-v1.0"
SANDBOX_POLICY_VERSION = "candidate-sandbox-v1.0"
MAX_COMPOSITION_DEPTH = 3
AUTO_ADMIT_EFFECTS = {EffectTier.PURE, EffectTier.READ_LOCAL, EffectTier.WRITE_LOCAL_SANDBOX}
CRITICAL_BOUNDARIES = {
    "KERNEL_AUTHORITY", "CAPABILITY_REGISTRY_AUTHORITY", "RUNTIME_AUTHORITY",
    "DAG_AUTHORITY", "STATE_AUTHORITY", "SECURITY_GUARD", "IRREVERSIBLE_MIGRATION",
    "UNAPPROVED_DEPENDENCY", "EXTERNAL_HIGH_IMPACT", "PRODUCTION_REGISTRY",
    "KNOWLEDGE_ADMISSION", "MULTI_AGENT_RUNTIME",
}


def _effect_for_search(effect: EffectTier) -> CapabilityEffect:
    return {
        EffectTier.PURE: CapabilityEffect.READ_ONLY,
        EffectTier.READ_LOCAL: CapabilityEffect.READ_ONLY,
        EffectTier.WRITE_LOCAL_SANDBOX: CapabilityEffect.MAINTENANCE,
        EffectTier.WRITE_PROJECT_SCOPED: CapabilityEffect.WRITE_CODE,
        EffectTier.WRITE_KNOWLEDGE: CapabilityEffect.WRITE_KNOWLEDGE,
        EffectTier.EXTERNAL_READ: CapabilityEffect.READ_ONLY,
        EffectTier.EXTERNAL_WRITE: CapabilityEffect.EXTERNAL_ACTION,
        EffectTier.SYSTEM: CapabilityEffect.SYSTEM,
    }[effect]


def _component_semantics(component: ComponentSpec) -> tuple[str, str, str]:
    metadata = dict(component.metadata)
    input_semantics = str(metadata.get("input_semantics") or (component.input_ports[0].artifact_type if component.input_ports else "none"))
    output_semantics = str(metadata.get("output_semantics") or (component.output_ports[0].artifact_type if component.output_ports else "none"))
    family = str(metadata.get("capability_family") or component.component_id)
    return input_semantics, output_semantics, family


class ExperimentalRegistryClone:
    """An isolated CapabilityRegistry instance; never a second production authority."""

    def __init__(self, production: CapabilityRegistry) -> None:
        self.production_authority_hash = canonical_hash({"capabilities": [item.as_dict() for item in production.query()]})
        self.production_size = len(production.query())
        self.registry = CapabilityRegistry(dict(production.components))
        self._signatures: dict[str, str] = {}
        for item in production.query():
            copied = replace(item, lifecycle_status=CapabilityLifecycle.CANDIDATE)
            self.registry.register_candidate(copied)
            if item.lifecycle_status is CapabilityLifecycle.ADMITTED:
                self.registry.admit(copied.ref)
            component = production.components[item.component_ref]
            signature = str(component.metadata.get("semantic_signature") or "")
            if signature:
                self._signatures[signature] = copied.ref
        self.admitted_from_growth: set[str] = set()

    @property
    def size(self) -> int:
        return len(self.registry.query())

    @property
    def authority_hash(self) -> str:
        return canonical_hash({"capabilities": [item.as_dict() for item in self.registry.query()]})

    def semantic_duplicate(self, signature: str) -> str | None:
        return self._signatures.get(signature)

    def admit(self, proposal: CapabilityProposal, receipt: QualificationReceipt, *, executor_ref: str, source_hash: str) -> CapabilityDescriptor:
        if receipt.status != "PASS" or receipt.level is not QualificationLevel.QUALIFIED:
            raise ValueError("experimental admission requires QUALIFIED evidence")
        if proposal.effect_class not in AUTO_ADMIT_EFFECTS:
            raise ValueError("effect requires proposal-only or human review")
        duplicate = self.semantic_duplicate(proposal.semantic_signature)
        if duplicate:
            raise ValueError(f"duplicate semantic responsibility: {duplicate}")
        if proposal.ref in {item.ref for item in self.registry.query()}:
            raise ValueError(f"duplicate capability identity: {proposal.ref}")
        component = ComponentSpec(
            proposal.capability_id,
            proposal.version,
            (PortSpec("value", str(proposal.input_contract.get("artifact_type", "artifact.capability.value@1"))),),
            (PortSpec("result", str(proposal.output_contract.get("artifact_type", "artifact.capability.result@1"))),),
            {},
            "policy.self_growth.experimental@1",
            {
                "purpose": proposal.purpose,
                "capability_family": proposal.abstraction_boundary,
                "input_semantics": str(proposal.input_contract.get("semantic_type", "value")),
                "output_semantics": str(proposal.output_contract.get("semantic_type", "result")),
                "scope": list(proposal.scope),
                "permissions": list(proposal.required_permissions),
                "required_state": list(proposal.required_state),
                "semantic_signature": proposal.semantic_signature,
                "experimental": True,
            },
        )
        self.registry.components[component.ref] = component
        descriptor = CapabilityDescriptor(
            proposal.capability_id,
            proposal.version,
            component.ref,
            executor_ref,
            ("generated_python",),
            ("value",),
            ("result",),
            tuple(proposal.side_effects),
            10.0,
            "experimental",
            "LOW",
            "self_growth_v1_experimental",
            {
                "source_hash": source_hash,
                "qualification_receipt_hash": receipt.receipt_hash,
                "semantic_signature": proposal.semantic_signature,
                "production_registry_modified": False,
            },
            ("hidden_qualification",),
        )
        self.registry.register_candidate(descriptor)
        self.registry.admit(descriptor.ref)
        self._signatures[proposal.semantic_signature] = descriptor.ref
        self.admitted_from_growth.add(descriptor.ref)
        return descriptor


@dataclass(frozen=True)
class SearchAndClassifyResult:
    classification: GrowthClassification
    full_registry_context_chars: int
    top_k_context_chars: int
    search_latency_ms: float


class GrowthGovernance:
    def __init__(self, *, max_composition_depth: int = MAX_COMPOSITION_DEPTH, top_k: int = 5) -> None:
        if not 1 <= max_composition_depth <= 4:
            raise ValueError("max composition depth must be between one and four")
        self.max_composition_depth = max_composition_depth
        self.top_k = top_k

    def classify(self, need: GrowthTaskNeed, clone: ExperimentalRegistryClone, group: GrowthGroup) -> SearchAndClassifyResult:
        index = CapabilitySearchIndex.rebuild(clone.registry)
        request = CapabilitySearchRequest(
            goal=need.goal,
            available_inputs=("request", "value"),
            allowed_effects=tuple(CapabilityEffect),
            permissions=need.permissions,
            available_state=need.available_state,
            allowed_scope=need.scope,
            exact_ref=need.requested_capability_ref,
            top_k=self.top_k,
        )
        result = index.search(request)
        top_k_refs = tuple(item.capability_ref for item in result.candidates)
        evidence = result.as_dict()
        full_chars = len(json.dumps([item.as_dict() for item in index.records], ensure_ascii=False, sort_keys=True))
        top_chars = len(json.dumps([item.as_dict() for item in result.candidates], ensure_ascii=False, sort_keys=True))

        fixed = self._fixed_classification(need, top_k_refs, evidence)
        if fixed is not None:
            return SearchAndClassifyResult(fixed, full_chars, top_chars, result.latency_ms)

        exact = self._exact_match(need, clone, top_k_refs)
        if exact:
            classification = GrowthClassification(
                GapClass.NO_GAP_EXISTING_CAPABILITY,
                ("EXACT_CONTRACT_MATCH",), True, top_k_refs, exact, None, evidence,
            )
            return SearchAndClassifyResult(classification, full_chars, top_chars, result.latency_ms)

        if group in {GrowthGroup.G2, GrowthGroup.G3}:
            parameterized = self._parameterized_match(need, clone)
            if parameterized:
                classification = GrowthClassification(
                    GapClass.PARAMETERIZATION_GAP,
                    ("EXISTING_FAMILY_SUPPORTS_PARAMETER_VARIANT",), True, top_k_refs,
                    parameterized, None, evidence,
                )
                return SearchAndClassifyResult(classification, full_chars, top_chars, result.latency_ms)
            composition = self._compose(need, clone)
            if composition:
                classification = GrowthClassification(
                    GapClass.COMPOSITION_GAP,
                    ("BOUNDED_COMPATIBLE_COMPOSITION",), True, top_k_refs, None,
                    composition, evidence,
                )
                return SearchAndClassifyResult(classification, full_chars, top_chars, result.latency_ms)

        classification = GrowthClassification(
            GapClass.CAPABILITY_GAP,
            ("NO_EXACT_PARAMETERIZED_OR_BOUNDED_COMPOSITION",), True, top_k_refs,
            None, None, evidence,
        )
        return SearchAndClassifyResult(classification, full_chars, top_chars, result.latency_ms)

    @staticmethod
    def _fixed_classification(need: GrowthTaskNeed, top_k_refs: tuple[str, ...], evidence: Mapping[str, Any]) -> GrowthClassification | None:
        signal = need.failure_signal.upper()
        if need.critical_boundary.upper() in CRITICAL_BOUNDARIES:
            return GrowthClassification(GapClass.AUTHORITY_CHANGE_REQUIRED, (need.critical_boundary.upper(),), True, top_k_refs, None, None, evidence)
        mapping = {
            "KNOWLEDGE": GapClass.KNOWLEDGE_GAP,
            "EVIDENCE": GapClass.EVIDENCE_GAP,
            "PERMISSION": GapClass.PERMISSION_GAP,
            "STATE": GapClass.STATE_GAP,
            "PROVIDER_FAILURE": GapClass.PROVIDER_FAILURE,
            "EXISTING_CAPABILITY_BUG": GapClass.EXISTING_CAPABILITY_BUG,
            "PRODUCT_DIRECTION": GapClass.PRODUCT_DIRECTION_GAP,
            "CORE_EXTENSION": GapClass.CORE_EXTENSION_REQUIRED,
        }
        if signal in mapping:
            return GrowthClassification(mapping[signal], (f"DECLARED_{signal}",), True, top_k_refs, None, None, evidence)
        return None

    @staticmethod
    def _exact_match(need: GrowthTaskNeed, clone: ExperimentalRegistryClone, top_k_refs: tuple[str, ...]) -> str | None:
        if need.requested_capability_ref and need.requested_capability_ref in top_k_refs:
            return need.requested_capability_ref
        for descriptor in clone.registry.query():
            component = clone.registry.components[descriptor.component_ref]
            input_semantics, output_semantics, family = _component_semantics(component)
            if family == need.family and input_semantics == need.input_semantics and output_semantics == need.output_semantics and not need.parameter_variant:
                return descriptor.ref
        return None

    @staticmethod
    def _parameterized_match(need: GrowthTaskNeed, clone: ExperimentalRegistryClone) -> str | None:
        if not need.parameter_variant:
            return None
        for descriptor in clone.registry.query():
            component = clone.registry.components[descriptor.component_ref]
            input_semantics, output_semantics, family = _component_semantics(component)
            if family == need.family and input_semantics == need.input_semantics and output_semantics == need.output_semantics:
                return descriptor.ref
        return None

    def _compose(self, need: GrowthTaskNeed, clone: ExperimentalRegistryClone) -> CompositionPlan | None:
        if not need.composition_goal:
            return None
        requested_families = tuple(need.composition_goal)
        selected: list[str] = []
        for family in requested_families:
            match = None
            for descriptor in clone.registry.query():
                component = clone.registry.components[descriptor.component_ref]
                if _component_semantics(component)[2] == family:
                    match = descriptor.ref
                    break
            if match is None:
                return None
            selected.append(match)
        if not selected or len(selected) > self.max_composition_depth:
            return None
        return CompositionPlan(tuple(selected), len(selected), need.input_semantics, need.output_semantics, len(selected))


class CapabilityExperienceLedger:
    """Derived execution evidence. Registry truth does not depend on this file."""

    def __init__(self, path: pathlib.Path | str) -> None:
        self.path = pathlib.Path(path)
        self.events: list[dict[str, Any]] = []
        if self.path.is_file():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("kind") != "CGKNCapabilityExperienceLedger" or value.get("schema_version") != "1.0":
                raise ValueError("unsupported capability experience ledger")
            self.events = [dict(item) for item in value.get("events", [])]

    def append(self, event: Mapping[str, Any]) -> None:
        row = dict(event)
        row["event_hash"] = canonical_hash({key: value for key, value in row.items() if key != "event_hash"})
        self.events.append(row)
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "kind": "CGKNCapabilityExperienceLedger",
            "schema_version": "1.0",
            "authority": "DERIVED_EXECUTION_EVIDENCE",
            "registry_authority": False,
            "events": self.events,
            "contains_credentials": False,
        }
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            pathlib.Path(temporary).unlink(missing_ok=True)

    @classmethod
    def rebuild(cls, path: pathlib.Path | str, receipts: Iterable[Mapping[str, Any]]) -> "CapabilityExperienceLedger":
        target = pathlib.Path(path)
        if target.exists():
            target.unlink()
        ledger = cls(target)
        for receipt in receipts:
            ledger.append(receipt)
        return ledger


def proposal_for_need(need: GrowthTaskNeed, classification: GrowthClassification, *, generalized: bool) -> CapabilityProposal:
    identity = need.family if generalized else f"{need.family}.{need.task_id.lower().replace('-', '_')}"
    identity = identity.lower().replace(" ", ".").replace("/", ".")
    return CapabilityProposal(
        candidate_id=f"candidate.{need.task_id.lower()}",
        capability_id=identity,
        version="1",
        purpose=need.goal,
        abstraction_boundary=need.family if generalized else need.task_id,
        input_contract={"type": "object", "semantic_type": need.input_semantics, "artifact_type": "artifact.capability.value@1"},
        output_contract={"semantic_type": need.output_semantics, "artifact_type": "artifact.capability.result@1"},
        effect_class=need.effect,
        required_permissions=need.permissions,
        required_state=need.required_state,
        side_effects=(),
        failure_semantics=("INVALID_INPUT", "EXECUTION_FAILED"),
        scope=need.scope,
        existing_overlapping_capabilities=classification.top_k_refs,
        why_composition_is_insufficient="No bounded compatible composition satisfied the observable contract.",
        expected_reuse_scope=(need.family,),
        qualification_plan=("schema", "scope", "security", "contract", "integration", "hidden_variants"),
        security_constraints=("stdlib_only", "no_network", "no_secret_access", "sandbox_only", "no_authority_change"),
        forbidden_paths=("cgkn/", "governance/", ".git/", "production_registry.json"),
    )


def qualification_receipt(
    proposal: CapabilityProposal,
    *,
    source_hash: str,
    hidden_results: Iterable[bool],
    builder_passed: bool,
    scope_passed: bool,
    security_passed: bool,
) -> QualificationReceipt:
    hidden = tuple(bool(item) for item in hidden_results)
    checks = {
        "schema_validation": True,
        "scope_validation": scope_passed,
        "security_validation": security_passed,
        "contract_tests": builder_passed,
        "integration_tests": builder_passed,
        "effect_guard": proposal.effect_class in AUTO_ADMIT_EFFECTS,
        "error_semantics": bool(proposal.failure_semantics),
        "hidden_qualification": bool(hidden) and all(hidden),
        "no_authority_change": True,
        "no_unapproved_dependency": proposal.dependency_policy == "stdlib_or_existing_only",
    }
    passed = all(checks.values())
    return QualificationReceipt(
        proposal.candidate_id,
        proposal.ref,
        QualificationLevel.QUALIFIED if passed else QualificationLevel.PROVISIONAL,
        "PASS" if passed else "FAIL",
        checks,
        len(hidden),
        sum(hidden),
        source_hash,
        canonical_hash(proposal.as_dict()),
    )


def policy_hashes() -> dict[str, str]:
    return {
        "growth_policy_hash": canonical_hash({
            "version": GROWTH_POLICY_VERSION,
            "reuse_before_compose_before_create": True,
            "gap_classes": [item.value for item in GapClass],
            "max_composition_depth": MAX_COMPOSITION_DEPTH,
        }),
        "candidate_contract_schema_hash": canonical_hash({"fields": list(CapabilityProposal.__dataclass_fields__)}),
        "experience_schema_hash": canonical_hash({"kind": "CGKNCapabilityExperienceLedger", "schema_version": "1.0"}),
        "admission_policy_hash": canonical_hash({"version": ADMISSION_POLICY_VERSION, "effects": sorted(item.value for item in AUTO_ADMIT_EFFECTS)}),
        "sandbox_policy_hash": canonical_hash({"version": SANDBOX_POLICY_VERSION, "network": False, "secrets": False, "production_write": False}),
    }

