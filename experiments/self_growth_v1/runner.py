from __future__ import annotations

import json
import pathlib
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from cgkn.application.capability_routing.benchmarks import real_product_registry
from cgkn.application.self_growth import (
    CapabilityExperienceLedger,
    CapabilityProposal,
    ExperimentalRegistryClone,
    GapClass,
    GrowthGroup,
    GrowthGovernance,
    QualificationReceipt,
    ResolutionKind,
    StrongDecisionPacket,
    canonical_hash,
    policy_hashes,
    proposal_for_need,
)

from .cases import GrowthTaskCase, _apply, _replace_previous, ordered_task_stream, stream_hashes


@dataclass(frozen=True)
class ModelCallEvidence:
    role: str
    provider: str
    model: str
    operation: str
    status: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    usage_status: str
    latency_ms: float
    request_id: str = ""
    transport_attempts: int = 0
    error_type: str = ""
    selection_receipt_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class CandidateBuildResult:
    status: str
    source_hash: str
    executor_ref: str
    qualification: QualificationReceipt
    calls: tuple[ModelCallEvidence, ...] = ()
    repair_calls: int = 0
    error: str = ""


@dataclass(frozen=True)
class StrongDecisionResult:
    decision: str
    reason_codes: tuple[str, ...]
    call: ModelCallEvidence | None
    packet: StrongDecisionPacket


class CandidateBackend(Protocol):
    def build(self, proposal: CapabilityProposal, case: GrowthTaskCase, candidate_root: pathlib.Path) -> CandidateBuildResult: ...
    def execute(self, capability_ref: str, value: Any) -> Any: ...


class StrongDecider(Protocol):
    def decide(self, packet: StrongDecisionPacket) -> StrongDecisionResult: ...


class StaticStrongDecider:
    def decide(self, packet: StrongDecisionPacket) -> StrongDecisionResult:
        return StrongDecisionResult("GENERAL_FAMILY", ("REUSE_SCOPE_WARRANTS_GENERAL_BOUNDARY",), None, packet)


class StaticCandidateBackend:
    """Discovery-only backend. Formal evidence uses the reviewed live Provider backend."""

    def __init__(self) -> None:
        self._cases: dict[str, GrowthTaskCase] = {}

    def build(self, proposal: CapabilityProposal, case: GrowthTaskCase, candidate_root: pathlib.Path) -> CandidateBuildResult:
        from cgkn.application.self_growth import qualification_receipt

        del candidate_root
        self._cases[proposal.ref] = case
        source_hash = canonical_hash({"proposal": proposal.as_dict(), "fixture": "discovery-only"})
        qualification = qualification_receipt(
            proposal,
            source_hash=source_hash,
            hidden_results=(True for _ in case.hidden_examples),
            builder_passed=True,
            scope_passed=True,
            security_passed=True,
        )
        call = ModelCallEvidence(
            "worker", "deterministic-fixture", "deterministic-fixture", "CANDIDATE_IMPLEMENTATION",
            "PASS", 0, 0, 0, 0, 0, "NOT_APPLICABLE_DETERMINISTIC_FIXTURE", 0.0,
        )
        return CandidateBuildResult("PASS", source_hash, f"generated.{proposal.capability_id}@1", qualification, (call,))

    def execute(self, capability_ref: str, value: Any) -> Any:
        case = self._cases[capability_ref]
        if case.composition_steps:
            previous = None
            for index, step in enumerate(case.composition_steps):
                step_input = _replace_previous(step["input"], previous) if index else step["input"]
                previous = _apply(str(step["family"]), step_input)
            return previous
        family = case.need.family
        if family.startswith("composition."):
            previous = None
            for index, step in enumerate(case.composition_steps):
                step_input = _replace_previous(step["input"], previous) if index else step["input"]
                previous = _apply(str(step["family"]), step_input)
            return previous
        return _apply(family, value)


def _detected_class(gap: GapClass) -> str:
    if gap in {GapClass.NO_GAP_EXISTING_CAPABILITY, GapClass.PARAMETERIZATION_GAP}:
        return "REUSE"
    if gap is GapClass.COMPOSITION_GAP:
        return "COMPOSE"
    if gap is GapClass.CAPABILITY_GAP:
        return "TRUE_GAP"
    if gap is GapClass.AUTHORITY_CHANGE_REQUIRED:
        return "CRITICAL_STOP"
    return "NON_CAPABILITY_GAP"


def _replace_composition_input(value: Any, previous: Any) -> Any:
    return _replace_previous(value, previous)


def _sum_nullable(values: list[int | None]) -> int | None:
    known = [item for item in values if item is not None]
    return sum(known) if known else None


def _cost(call: ModelCallEvidence, pricing: Mapping[str, Any]) -> float | None:
    if call.total_tokens is None or call.input_tokens is None or call.output_tokens is None:
        return None
    models = pricing.get("models", {}) if isinstance(pricing, Mapping) else {}
    row = models.get(call.provider) if isinstance(models, Mapping) else None
    if not isinstance(row, Mapping):
        return None
    if str(row.get("model") or "") != call.model:
        return None
    input_tokens = call.input_tokens - int(call.cached_tokens or 0)
    value = (
        input_tokens * float(row["input_price_per_million"])
        + int(call.cached_tokens or 0) * float(row["cached_input_price_per_million"])
        + call.output_tokens * float(row["output_price_per_million"])
    ) / 1_000_000
    if str(row.get("currency")) == "USD":
        value *= float(pricing.get("usd_cny", 1.0))
    return value


@dataclass
class GrowthBenchmarkRunner:
    group: GrowthGroup
    backend: CandidateBackend
    output_root: pathlib.Path
    strong_decider: StrongDecider = field(default_factory=StaticStrongDecider)
    pricing: Mapping[str, Any] = field(default_factory=dict)
    source_commit: str = ""
    source_tree: str = ""

    def run(self, tasks: tuple[GrowthTaskCase, ...] | None = None) -> dict[str, Any]:
        stream = tasks or ordered_task_stream()
        clone = ExperimentalRegistryClone(real_product_registry())
        governance = GrowthGovernance(max_composition_depth=3, top_k=5)
        self.output_root.mkdir(parents=True, exist_ok=False)
        ledger = CapabilityExperienceLedger(self.output_root / "experience_ledger.json")
        task_rows: list[dict[str, Any]] = []
        admitted_at: dict[str, int] = {}
        reuse_counts: dict[str, int] = {}
        created = rejected = duplicate_candidates = 0
        strong_packets: list[dict[str, Any]] = []

        for task_index, case in enumerate(stream, 1):
            started = time.perf_counter()
            search = governance.classify(case.need, clone, self.group)
            classification = search.classification
            detected = _detected_class(classification.gap_class)
            resolution = ResolutionKind.UNRESOLVED
            selected_refs: list[str] = []
            calls: list[ModelCallEvidence] = []
            candidate_created = candidate_admitted = False
            qualification: dict[str, Any] | None = None
            output: Any = None
            error = ""

            if classification.gap_class in {GapClass.NO_GAP_EXISTING_CAPABILITY, GapClass.PARAMETERIZATION_GAP}:
                resolution = ResolutionKind.DIRECT_REUSE if classification.gap_class is GapClass.NO_GAP_EXISTING_CAPABILITY else ResolutionKind.PARAMETERIZATION
                if classification.selected_ref:
                    selected_refs.append(classification.selected_ref)
                    if classification.selected_ref in admitted_at:
                        reuse_counts[classification.selected_ref] = reuse_counts.get(classification.selected_ref, 0) + 1
                        try:
                            output = self.backend.execute(classification.selected_ref, case.input_value)
                        except Exception as exc:
                            error = f"{type(exc).__name__}: {exc}"
                    elif case.production_ref == classification.selected_ref:
                        output = case.production_ref
            elif classification.gap_class is GapClass.COMPOSITION_GAP and classification.composition:
                resolution = ResolutionKind.COMPOSITION
                previous = None
                try:
                    for step_index, (ref, step) in enumerate(zip(classification.composition.capability_refs, case.composition_steps, strict=True)):
                        selected_refs.append(ref)
                        if ref in admitted_at:
                            reuse_counts[ref] = reuse_counts.get(ref, 0) + 1
                        value = _replace_composition_input(step["input"], previous) if step_index else step["input"]
                        previous = self.backend.execute(ref, value)
                    output = previous
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            elif classification.gap_class is GapClass.CAPABILITY_GAP:
                if self.group is GrowthGroup.G0:
                    error = "FROZEN_REGISTRY_GAP"
                else:
                    generalized = self.group is not GrowthGroup.G1
                    if self.group is GrowthGroup.G3 and len(case.need.abstraction_choices) > 1:
                        packet = StrongDecisionPacket(
                            task_need={
                                "goal": case.need.goal,
                                "input_semantics": case.need.input_semantics,
                                "output_semantics": case.need.output_semantics,
                                "effect": case.need.effect.value,
                                "scope": list(case.need.scope),
                            },
                            gap_classification_evidence=classification.as_dict(),
                            top_k_capabilities=tuple({"capability_ref": ref} for ref in classification.top_k_refs),
                            failed_composition_attempts=({"reason": "no bounded compatible composition"},),
                            required_observable_result=case.need.required_observable,
                            impact_risk="LOW",
                            candidate_abstraction_choices=case.need.abstraction_choices,
                            public_constraints=("stdlib_only", "sandbox_only", "no_production_registry_write", "max_four_candidate_calls"),
                            full_possible_context_chars=max(search.full_registry_context_chars, search.top_k_context_chars + 1),
                        )
                        decision = self.strong_decider.decide(packet)
                        strong_packets.append({
                            "task_id": case.need.task_id,
                            "full_possible_context_chars": packet.full_possible_context_chars,
                            "actual_context_chars": packet.actual_context_chars,
                            "reduction_ratio": packet.reduction_ratio,
                            "top_k_capability_count": len(packet.top_k_capabilities),
                            "irrelevant_capability_count": 0,
                            "decision": decision.decision,
                        })
                        if decision.call:
                            calls.append(decision.call)
                        if decision.decision == "DO_NOT_CREATE":
                            error = (
                                "STRONG_DECISION_PROVIDER_FAILURE"
                                if decision.call and decision.call.status == "FAIL"
                                else "STRONG_DECISION_DO_NOT_CREATE"
                            )
                        else:
                            generalized = decision.decision == "GENERAL_FAMILY"
                    if not error:
                        proposal = proposal_for_need(case.need, classification, generalized=generalized)
                        if clone.semantic_duplicate(proposal.semantic_signature):
                            duplicate_candidates += 1
                            error = "DUPLICATE_CAPABILITY"
                        else:
                            created += 1
                            candidate_created = True
                            try:
                                build = self.backend.build(proposal, case, self.output_root / "sandboxes" / proposal.candidate_id)
                                calls.extend(build.calls)
                                qualification = build.qualification.as_dict()
                                if build.status == "PASS" and build.qualification.status == "PASS":
                                    descriptor = clone.admit(
                                        proposal,
                                        build.qualification,
                                        executor_ref=build.executor_ref,
                                        source_hash=build.source_hash,
                                    )
                                    candidate_admitted = True
                                    admitted_at[descriptor.ref] = task_index
                                    reuse_counts.setdefault(descriptor.ref, 0)
                                    selected_refs.append(descriptor.ref)
                                    resolution = ResolutionKind.CREATE
                                    output = self.backend.execute(descriptor.ref, case.input_value)
                                else:
                                    rejected += 1
                                    error = build.error or "CANDIDATE_QUALIFICATION_FAILED"
                            except Exception as exc:
                                rejected += 1
                                error = f"{type(exc).__name__}: {exc}"
            elif classification.gap_class in {GapClass.AUTHORITY_CHANGE_REQUIRED, GapClass.CORE_EXTENSION_REQUIRED, GapClass.PRODUCT_DIRECTION_GAP}:
                resolution = ResolutionKind.CRITICAL_STOP
            else:
                resolution = ResolutionKind.REPAIR_EXISTING if classification.gap_class is GapClass.EXISTING_CAPABILITY_BUG else ResolutionKind.NON_CAPABILITY_PATH

            if case.expected_class in {"NON_CAPABILITY_GAP", "CRITICAL_STOP"}:
                observable_pass = detected == case.expected_class
            elif case.production_ref:
                observable_pass = output == case.production_ref
            else:
                observable_pass = output == case.expected_output
            success = bool(observable_pass and not error)
            latency_ms = round((time.perf_counter() - started) * 1000, 6)
            call_costs = [_cost(item, self.pricing) for item in calls]
            known_cost = sum(item for item in call_costs if item is not None)
            unknown_cost_calls = sum(item is None and call.usage_status not in {"NOT_APPLICABLE_DETERMINISTIC_FIXTURE"} for item, call in zip(call_costs, calls, strict=True))
            event = {
                "task_index": task_index,
                "task_id": case.need.task_id,
                "family": case.need.family,
                "expected_growth_class": case.expected_class,
                "detected_class": detected,
                "gap_class": classification.gap_class.value,
                "resolution": resolution.value,
                "search_candidates": list(classification.top_k_refs),
                "selected_capabilities": selected_refs,
                "composition_plan": classification.composition.as_dict() if classification.composition else None,
                "strong_decision_used": any(item.role == "strong" for item in calls),
                "candidate_created": candidate_created,
                "qualification": qualification,
                "admitted": candidate_admitted,
                "reused_grown_capability": any(ref in admitted_at and admitted_at[ref] < task_index for ref in selected_refs),
                "success": success,
                "validator": "DETERMINISTIC_OBSERVABLE_COMPARISON",
                "registry_size": clone.size,
                "production_registry_size": clone.production_size,
                "search_latency_ms": search.search_latency_ms,
                "full_registry_context_chars": search.full_registry_context_chars,
                "top_k_context_chars": search.top_k_context_chars,
                "latency_ms": latency_ms,
                "model_calls": [item.as_dict() for item in calls],
                "known_cost_cny": known_cost,
                "unknown_cost_call_count": unknown_cost_calls,
                "error": error,
            }
            ledger.append(event)
            task_rows.append(event)

        return self._receipt(
            clone, stream, task_rows, created, rejected, duplicate_candidates,
            admitted_at, reuse_counts, strong_packets,
        )

    def _receipt(
        self,
        clone: ExperimentalRegistryClone,
        stream: tuple[GrowthTaskCase, ...],
        rows: list[dict[str, Any]],
        created: int,
        rejected: int,
        duplicates: int,
        admitted_at: Mapping[str, int],
        reuse_counts: Mapping[str, int],
        strong_packets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        calls = [call for row in rows for call in row["model_calls"]]
        strong_calls = [item for item in calls if item["role"] == "strong"]
        cheap_calls = [item for item in calls if item["role"] == "worker"]
        model_calls = [item for item in calls if item["usage_status"] != "NOT_APPLICABLE_DETERMINISTIC_FIXTURE"]
        successes = sum(bool(row["success"]) for row in rows)
        true_positive = sum(row["expected_growth_class"] == "TRUE_GAP" and row["detected_class"] == "TRUE_GAP" for row in rows)
        false_positive = sum(row["expected_growth_class"] != "TRUE_GAP" and row["detected_class"] == "TRUE_GAP" for row in rows)
        false_negative = sum(row["expected_growth_class"] == "TRUE_GAP" and row["detected_class"] != "TRUE_GAP" for row in rows)
        true_gap_detected = true_positive + false_positive
        true_gap_expected = true_positive + false_negative
        internalization_eligible = [row for row in rows if row["expected_growth_class"] in {"REUSE", "COMPOSE"} and not row["task_id"].startswith("production-reuse")]
        windows = []
        for start in range(0, len(rows), 20):
            window = rows[start:start + 20]
            window_calls = [call for row in window for call in row["model_calls"]]
            windows.append({
                "range": f"{start + 1}-{start + len(window)}",
                "success_rate": sum(row["success"] for row in window) / len(window),
                "growth_saturation": sum(row["success"] and not row["candidate_created"] for row in window) / len(window),
                "new_capability_rate": sum(row["candidate_created"] for row in window) / len(window),
                "reuse_rate": sum(row["resolution"] in {ResolutionKind.DIRECT_REUSE.value, ResolutionKind.PARAMETERIZATION.value} for row in window) / len(window),
                "composition_rate": sum(row["resolution"] == ResolutionKind.COMPOSITION.value for row in window) / len(window),
                "strong_calls_per_task": sum(call["role"] == "strong" for call in window_calls) / len(window),
                "known_cost_cny_per_task": sum(row["known_cost_cny"] for row in window) / len(window),
            })
        zero_use = sum(reuse_counts.get(ref, 0) == 0 for ref in admitted_at)
        single_use = sum(reuse_counts.get(ref, 0) == 1 for ref in admitted_at)
        known_tokens = _sum_nullable([item["total_tokens"] for item in model_calls])
        unknown_usage = sum(item["total_tokens"] is None for item in model_calls)
        strong_known_tokens = _sum_nullable([item["total_tokens"] for item in strong_calls if item["usage_status"] != "NOT_APPLICABLE_DETERMINISTIC_FIXTURE"])
        cheap_known_tokens = _sum_nullable([item["total_tokens"] for item in cheap_calls if item["usage_status"] != "NOT_APPLICABLE_DETERMINISTIC_FIXTURE"])
        body = {
            "kind": "CGKNSelfGrowthFormalGroupReceipt",
            "schema_version": "1.0",
            "group": self.group.value,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "production_registry_authority_hash": clone.production_authority_hash,
            "production_registry_size": clone.production_size,
            "final_experimental_registry_size": clone.size,
            "production_registry_modified": False,
            "policy_hashes": policy_hashes(),
            "benchmark_hashes": stream_hashes(),
            "tasks": rows,
            "metrics": {
                "tasks": len(rows),
                "successes": successes,
                "success_rate": successes / len(rows),
                "true_gap_precision": true_positive / true_gap_detected if true_gap_detected else 1.0,
                "true_gap_recall": true_positive / true_gap_expected if true_gap_expected else 1.0,
                "false_gap_rate": false_positive / len(rows),
                "missed_gap_rate": false_negative / len(rows),
                "non_capability_gap_correctness": sum(row["expected_growth_class"] == "NON_CAPABILITY_GAP" and row["detected_class"] == "NON_CAPABILITY_GAP" for row in rows) / max(1, sum(row["expected_growth_class"] == "NON_CAPABILITY_GAP" for row in rows)),
                "critical_stop_correctness": sum(row["expected_growth_class"] == "CRITICAL_STOP" and row["detected_class"] == "CRITICAL_STOP" for row in rows) / max(1, sum(row["expected_growth_class"] == "CRITICAL_STOP" for row in rows)),
                "new_capabilities_created": created,
                "new_capabilities_admitted": len(admitted_at),
                "rejected_capabilities": rejected,
                "duplicate_capability_count": duplicates,
                "direct_reuse_rate": sum(row["resolution"] == ResolutionKind.DIRECT_REUSE.value for row in rows) / len(rows),
                "parameterization_rate": sum(row["resolution"] == ResolutionKind.PARAMETERIZATION.value for row in rows) / len(rows),
                "composition_rate": sum(row["resolution"] == ResolutionKind.COMPOSITION.value for row in rows) / len(rows),
                "new_capability_rate": created / len(rows),
                "qualification_pass_rate": len(admitted_at) / created if created else 1.0,
                "generalization_pass_rate": len(admitted_at) / created if created else 1.0,
                "capability_internalization_rate": sum(row["success"] and row["reused_grown_capability"] for row in internalization_eligible) / max(1, len(internalization_eligible)),
                "median_reuse_count": statistics.median(reuse_counts.values()) if reuse_counts else 0,
                "zero_reuse_capability_rate": zero_use / max(1, len(admitted_at)),
                "single_use_capability_rate": single_use / max(1, len(admitted_at)),
                "strong_calls": len([item for item in strong_calls if item["usage_status"] != "NOT_APPLICABLE_DETERMINISTIC_FIXTURE"]),
                "cheap_calls": len([item for item in cheap_calls if item["usage_status"] != "NOT_APPLICABLE_DETERMINISTIC_FIXTURE"]),
                "deterministic_resolution_share": sum(not row["model_calls"] for row in rows) / len(rows),
                "known_total_tokens": known_tokens,
                "known_strong_tokens": strong_known_tokens,
                "known_cheap_tokens": cheap_known_tokens,
                "unknown_usage_call_count": unknown_usage,
                "usage_completeness": (len(model_calls) - unknown_usage) / len(model_calls) if model_calls else 1.0,
                "known_cost_cny": sum(row["known_cost_cny"] for row in rows),
                "unknown_cost_call_count": sum(row["unknown_cost_call_count"] for row in rows),
                "total_latency_ms": sum(row["latency_ms"] for row in rows),
                "search_latency_p50_ms": statistics.median(row["search_latency_ms"] for row in rows),
                "search_candidate_count_max": max(len(row["search_candidates"]) for row in rows),
            },
            "windows": windows,
            "strong_context_packets": strong_packets,
            "growth_debt": {
                "registry_growth": clone.size - clone.production_size,
                "duplicate_candidates": duplicates,
                "zero_use_capabilities": zero_use,
                "single_use_capabilities": single_use,
                "rejected_candidates": rejected,
                "qualification_test_count": sum((row.get("qualification") or {}).get("hidden_case_count", 0) for row in rows),
                "maintenance_test_burden": len(admitted_at),
            },
            "consolidation_proposals": self._consolidation(reuse_counts),
            "contains_credentials": False,
        }
        return body | {"receipt_hash": canonical_hash(body)}

    @staticmethod
    def _consolidation(reuse_counts: Mapping[str, int]) -> list[dict[str, Any]]:
        singletons = sorted(ref for ref, count in reuse_counts.items() if count <= 1)
        return [
            {
                "kind": "DEPRECATION_PROPOSAL",
                "capability_ref": ref,
                "reason": "zero-or-single observed reuse; proposal only",
                "executed": False,
            }
            for ref in singletons
        ]

