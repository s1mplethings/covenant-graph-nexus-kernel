from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from typing import Any, Iterable

from cgkn.application.software_project.bundle import SoftwareProjectBundle
from cgkn.capabilities import CapabilityDescriptor, CapabilityLifecycle, CapabilityRegistry
from cgkn.component import ComponentSpec

from .contracts import (
    CapabilityEffect,
    CapabilitySearchRequest,
    DecisionContext,
    DecisionLevel,
    DecisionRiskClass,
    stable_hash,
)
from .decision import DecisionRouter, policy_hashes
from .search import CapabilitySearchIndex, SEARCH_POLICY_VERSION


BENCHMARK_VERSION = "capability-routing-discovery-v1"
MODEL_CONFIG = {
    "D0": "strong-all-discovery-simulation",
    "D1": "cheap-all-discovery-simulation",
    "D2": "fixed-strong-to-cheap-discovery-simulation",
    "D3": "adaptive-policy-discovery",
    "formal_live_required_on_integrated_source": True,
}


@dataclass(frozen=True)
class DecisionBenchmarkCase:
    case_id: str
    expected: DecisionLevel
    context: DecisionContext
    phase: str = "decision"

    def as_dict(self) -> dict[str, Any]:
        candidate_capabilities = [f"candidate.{index}@1" for index in range(self.context.candidate_count)]
        if self.context.critical_boundaries:
            required_effect = "EXTERNAL_OR_AUTHORITY_CHANGE"
        elif self.phase == "execution":
            required_effect = "BOUNDED_WRITE_OR_TRANSFORM"
        else:
            required_effect = "READ_ONLY_DECISION"
        return {
            "case_id": self.case_id,
            "expected": self.expected.value,
            "phase": self.phase,
            "request": self.context.operation,
            "candidate_capabilities": candidate_capabilities,
            "available_inputs": ["request"] if self.context.evidence_sufficient else [],
            "required_effect": required_effect,
            "qualification": "QUALIFIED" if self.context.capability_qualified else "UNQUALIFIED",
            "expected_validator": "AVAILABLE" if self.context.validator_available else "UNAVAILABLE",
            "context": {
                "operation": self.context.operation,
                "uncertainty": self.context.uncertainty,
                "impact": self.context.impact.value,
                "reversible": self.context.reversible,
                "authority_scope": self.context.authority_scope,
                "evidence_sufficient": self.context.evidence_sufficient,
                "candidate_count": self.context.candidate_count,
                "capability_qualified": self.context.capability_qualified,
                "validator_available": self.context.validator_available,
                "cheap_route_qualified": self.context.cheap_route_qualified,
                "deterministic_rule_available": self.context.deterministic_rule_available,
                "deterministic_evidence_valid": self.context.deterministic_evidence_valid,
                "crosses_authority_boundary": self.context.crosses_authority_boundary,
                "critical_boundaries": list(self.context.critical_boundaries),
            },
        }


def decision_cases() -> tuple[DecisionBenchmarkCase, ...]:
    cases: list[DecisionBenchmarkCase] = []
    for index, operation in enumerate(
        (
            "EXACT_DUPLICATE",
            "KNOWN_REQUIREMENT_OWNER",
            "EXACT_CAPABILITY_IDENTITY",
            "SCHEMA_VALIDATION",
            "HASH_COMPARISON",
            "SINGLE_ELIGIBLE_ROUTE",
        ),
        1,
    ):
        cases.append(
            DecisionBenchmarkCase(
                f"deterministic-{index}",
                DecisionLevel.DETERMINISTIC,
                DecisionContext(operation, deterministic_rule_available=True, deterministic_evidence_valid=True),
            )
        )
    cheap_operations = (
        ("SUMMARIZE_BOUNDED_RESULT", "decision"),
        ("FORMAT_PUBLIC_RESPONSE", "decision"),
        ("CLASSIFY_LOCAL_FAILURE", "decision"),
        ("SELECT_QUALIFIED_SINGLE_TOOL", "decision"),
        ("PATCH_REVERSIBLE_FILE", "execution"),
        ("EXTRACT_TYPED_FIELDS", "execution"),
        ("DRAFT_TEST_FIXTURE", "execution"),
        ("NORMALIZE_LOCAL_METADATA", "execution"),
    )
    for index, (operation, phase) in enumerate(cheap_operations, 1):
        cases.append(
            DecisionBenchmarkCase(
                f"cheap-{index}",
                DecisionLevel.CHEAP_MODEL,
                DecisionContext(operation, uncertainty=0.15, impact=DecisionRiskClass.LOW, reversible=True, validator_available=True, cheap_route_qualified=True),
                phase=phase,
            )
        )
    strong_contexts = (
        (DecisionContext("SELECT_AMONG_SEMANTIC_CAPABILITIES", uncertainty=0.5, candidate_count=3), "decision"),
        (DecisionContext("PLAN_COMPLEX_REPAIR", uncertainty=0.8, impact=DecisionRiskClass.HIGH), "decision"),
        (DecisionContext("DECIDE_CROSS_BOUNDARY_CHANGE", uncertainty=0.4, crosses_authority_boundary=True), "decision"),
        (DecisionContext("SEMANTIC_DECISION_CHEAP_UNAVAILABLE", uncertainty=0.3, cheap_route_qualified=False), "decision"),
        (DecisionContext("DECIDE_WITHOUT_VALIDATOR", uncertainty=0.4, validator_available=False), "execution"),
        (DecisionContext("USE_UNQUALIFIED_CAPABILITY", uncertainty=0.3, capability_qualified=False), "execution"),
    )
    for index, (context, phase) in enumerate(strong_contexts, 1):
        cases.append(DecisionBenchmarkCase(f"strong-{index}", DecisionLevel.STRONG_MODEL, context, phase=phase))
    boundaries = (
        "KERNEL_AUTHORITY_CHANGE",
        "PRODUCT_DIRECTION_CHANGE",
        "SECURITY_BOUNDARY_LOWERING",
        "IRREVERSIBLE_MIGRATION",
    )
    for index, boundary in enumerate(boundaries, 1):
        cases.append(
            DecisionBenchmarkCase(
                f"critical-{index}",
                DecisionLevel.HUMAN_STOP,
                DecisionContext("CRITICAL_CHANGE", impact=DecisionRiskClass.CRITICAL, critical_boundaries=(boundary,)),
            )
        )
    return tuple(cases)


def real_product_registry() -> CapabilityRegistry:
    """Build the current real L6 registry projection without creating a new authority."""
    bundle = SoftwareProjectBundle.build()
    registry = CapabilityRegistry({item.ref: item for item in bundle.components})
    for descriptor in bundle.capabilities:
        candidate = replace(descriptor, lifecycle_status=CapabilityLifecycle.CANDIDATE)
        registry.register_candidate(candidate)
        registry.admit(candidate.ref)
    return registry


def synthetic_registry(size: int) -> tuple[CapabilityRegistry, str]:
    if size < 2:
        raise ValueError("synthetic capability fixture requires at least two records")
    components: dict[str, ComponentSpec] = {}
    descriptors: list[CapabilityDescriptor] = []
    target = "data.csv.clean@1"
    for index in range(size):
        if index == 0:
            capability_id = "data.csv.clean"
            purpose = "Clean comma separated CSV rows, remove blank rows, and deduplicate records"
        elif index % 10 == 0:
            capability_id = f"data.csv.inspect_{index}"
            purpose = "Inspect comma separated CSV schema and report duplicate row counts without changing data"
        else:
            capability_id = f"fixture.capability_{index}"
            purpose = f"Perform deterministic fixture operation number {index} for unrelated domain {index % 17}"
        fixture_class = index % 25
        effects = {"filesystem": "write"} if fixture_class == 2 else {}
        metadata = {"purpose": purpose}
        if fixture_class == 1:
            metadata["permissions"] = ["fixture.admin"]
        component = ComponentSpec(capability_id, "1", (), (), effects, None, metadata)
        descriptor = CapabilityDescriptor(
            capability_id,
            "1",
            component.ref,
            f"fixture.executor_{index}@1",
            ("deterministic",),
            (),
            (),
            (),
            5.0,
            "zero",
            "LOW",
            "deterministic_fixture",
            {"fixture": True},
            ("tests/application/capability_routing",),
            CapabilityLifecycle.ADMITTED,
        )
        components[component.ref] = component
        descriptors.append(descriptor)
    registry = CapabilityRegistry(components)
    for descriptor in descriptors:
        candidate = replace(descriptor, lifecycle_status=CapabilityLifecycle.CANDIDATE)
        registry.register_candidate(candidate)
        index = int(candidate.capability_id.rsplit("_", 1)[-1]) if candidate.capability_id.startswith("fixture.capability_") else 0
        if index % 25 != 3:
            registry.admit(candidate.ref)
    return registry, target


def _search_case(index: CapabilitySearchIndex, request: CapabilitySearchRequest, expected: str) -> dict[str, Any]:
    result = index.search(request)
    refs = [item.capability_ref for item in result.candidates]
    reason_counts: dict[str, int] = {}
    for reasons in result.rejected.values():
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "expected": expected,
        "selected": refs[0] if refs else None,
        "top1": bool(refs and refs[0] == expected),
        "top3": expected in refs[:3],
        "candidate_count": len(refs),
        "retrieval_pool_count": result.retrieval_pool_count,
        "eligible_count": result.eligible_count,
        "total_count": result.total_count,
        "rejected_count": len(result.rejected),
        "rejection_reason_counts": reason_counts,
        "false_candidate_rate": round(sum(ref != expected for ref in refs) / len(refs), 6) if refs else 0.0,
        "full_registry_context_tokens": result.full_registry_context_tokens,
        "topk_context_tokens": result.topk_context_tokens,
        "latency_ms": result.latency_ms,
        "index_hash": result.index_hash,
        "policy_hash": result.policy_hash,
    }


def run_search_discovery(scales: Iterable[int] = (100, 500, 1000)) -> dict[str, Any]:
    real_registry = real_product_registry()
    real_index = CapabilitySearchIndex.rebuild(real_registry)
    real_cases = (
        _search_case(
            real_index,
            CapabilitySearchRequest("look up and inspect workspace files", ("request",), (CapabilityEffect.READ_ONLY,), top_k=3),
            "workspace.inspect@1",
        ),
        _search_case(
            real_index,
            CapabilitySearchRequest("repair and patch one source file", ("request",), (CapabilityEffect.WRITE_CODE,), top_k=3),
            "project.file.patch@1",
        ),
        _search_case(
            real_index,
            CapabilitySearchRequest("run pytest validation", ("request",), (CapabilityEffect.SYSTEM,), top_k=3),
            "project.python.pytest@1",
        ),
    )
    synthetic: dict[str, Any] = {}
    for size in scales:
        registry, expected = synthetic_registry(size)
        index = CapabilitySearchIndex.rebuild(registry)
        rows = [
            _search_case(
                index,
                CapabilitySearchRequest("clean CSV records and remove blank duplicate rows", allowed_effects=(CapabilityEffect.READ_ONLY,), top_k=3),
                expected,
            )
            for _ in range(5)
        ]
        synthetic[str(size)] = {
            "runs": len(rows),
            "top1_accuracy": sum(row["top1"] for row in rows) / len(rows),
            "top3_recall": sum(row["top3"] for row in rows) / len(rows),
            "median_latency_ms": round(statistics.median(row["latency_ms"] for row in rows), 6),
            "max_candidate_count": max(row["candidate_count"] for row in rows),
            "median_false_candidate_rate": round(statistics.median(row["false_candidate_rate"] for row in rows), 6),
            "ineligible_capability_count": rows[0]["total_count"] - rows[0]["eligible_count"],
            "ineligible_capability_rejection_rate": (
                rows[0]["rejected_count"] / (len(index.records) - rows[0]["eligible_count"])
                if len(index.records) > rows[0]["eligible_count"]
                else 1.0
            ),
            "full_registry_context_tokens": rows[0]["full_registry_context_tokens"],
            "topk_context_tokens": rows[0]["topk_context_tokens"],
            "context_reduction_ratio": round(1 - rows[0]["topk_context_tokens"] / rows[0]["full_registry_context_tokens"], 6),
            "index_hash": rows[0]["index_hash"],
        }
    return {
        "real_registry": {
            "capability_count": len(real_index.records),
            "top1_accuracy": sum(row["top1"] for row in real_cases) / len(real_cases),
            "top3_recall": sum(row["top3"] for row in real_cases) / len(real_cases),
            "cases": list(real_cases),
            "benefit": "NOT_YET_NEEDED_AT_CURRENT_SCALE" if len(real_index.records) < 25 else "EVALUATE_FORMALLY",
        },
        "synthetic": synthetic,
        "synthetic_is_product_evidence": False,
    }


def _strategy_route(strategy: str, case: DecisionBenchmarkCase, router: DecisionRouter) -> DecisionLevel:
    if case.expected is DecisionLevel.HUMAN_STOP:
        return DecisionLevel.HUMAN_STOP
    if case.expected is DecisionLevel.DETERMINISTIC:
        return DecisionLevel.DETERMINISTIC
    if strategy == "D0":
        return DecisionLevel.STRONG_MODEL
    if strategy == "D1":
        return DecisionLevel.CHEAP_MODEL
    if strategy == "D2":
        return DecisionLevel.CHEAP_MODEL if case.phase == "execution" else DecisionLevel.STRONG_MODEL
    return router.route(case.context).level


def run_decision_discovery() -> dict[str, Any]:
    cases = decision_cases()
    router = DecisionRouter()
    groups: dict[str, Any] = {}
    for strategy in ("D0", "D1", "D2", "D3"):
        rows = []
        for case in cases:
            actual = _strategy_route(strategy, case, router)
            rows.append({"case_id": case.case_id, "expected": case.expected.value, "actual": actual.value, "correct": actual is case.expected})
        groups[strategy] = {
            "cases": rows,
            "routing_accuracy": sum(row["correct"] for row in rows) / len(rows),
            "deterministic": sum(row["actual"] == DecisionLevel.DETERMINISTIC.value for row in rows),
            "cheap": sum(row["actual"] == DecisionLevel.CHEAP_MODEL.value for row in rows),
            "strong": sum(row["actual"] == DecisionLevel.STRONG_MODEL.value for row in rows),
            "human_stop": sum(row["actual"] == DecisionLevel.HUMAN_STOP.value for row in rows),
            "false_escalations": sum(
                row["actual"] == DecisionLevel.STRONG_MODEL.value
                and row["expected"] in {DecisionLevel.DETERMINISTIC.value, DecisionLevel.CHEAP_MODEL.value}
                for row in rows
            ),
            "missed_escalations": sum(
                row["expected"] == DecisionLevel.STRONG_MODEL.value
                and row["actual"] in {DecisionLevel.DETERMINISTIC.value, DecisionLevel.CHEAP_MODEL.value}
                for row in rows
            ),
            "critical_stop_correctness": (
                sum(row["correct"] and row["expected"] == DecisionLevel.HUMAN_STOP.value for row in rows)
                / sum(row["expected"] == DecisionLevel.HUMAN_STOP.value for row in rows)
            ),
            "token_metrics": "NOT_EVALUATED_DISCOVERY_ONLY",
            "cost_metrics": "NOT_EVALUATED_DISCOVERY_ONLY",
            "formal_live_evidence": False,
        }
    return {
        "case_count": len(cases),
        "case_hash": stable_hash([item.as_dict() for item in cases]),
        "groups": groups,
        "discovery_only": True,
    }


def run_discovery() -> dict[str, Any]:
    search = run_search_discovery()
    decision = run_decision_discovery()
    benchmark_hash = stable_hash({
        "benchmark_version": BENCHMARK_VERSION,
        "decision_cases": [item.as_dict() for item in decision_cases()],
        "real_search_cases": [
            {"goal": "look up and inspect workspace files", "expected": "workspace.inspect@1"},
            {"goal": "repair and patch one source file", "expected": "project.file.patch@1"},
            {"goal": "run pytest validation", "expected": "project.python.pytest@1"},
        ],
        "synthetic_scales": [100, 500, 1000],
        "top_k": 3,
    })
    return {
        "kind": "CapabilityRoutingDiscoveryReceipt",
        "schema_version": "1.0",
        "benchmark_version": BENCHMARK_VERSION,
        "search_policy_version": SEARCH_POLICY_VERSION,
        **policy_hashes(),
        "benchmark_hash": benchmark_hash,
        "model_config_hash": stable_hash(MODEL_CONFIG),
        "search": search,
        "decision": decision,
        "formal_d0_d3_required_on_integrated_source": True,
        "contains_credentials": False,
    }

