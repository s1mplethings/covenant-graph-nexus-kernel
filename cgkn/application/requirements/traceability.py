from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, Mapping

from .compiler import NormalizedRequirements
from .obligation import FrozenMapping, ObligationSet, thaw


@dataclass(frozen=True)
class TestBinding:
    __test__: ClassVar[bool] = False
    test_id: str
    obligation_ids: tuple[str, ...]
    hidden: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "obligation_ids", tuple(sorted(set(self.obligation_ids))))
        if not self.test_id or not self.obligation_ids:
            raise ValueError("test binding requires test_id and obligation_ids")


@dataclass(frozen=True)
class TraceabilityGraph:
    requirement_to_obligations: FrozenMapping
    obligation_to_work_units: FrozenMapping
    obligation_to_tests: FrozenMapping
    test_to_obligation: FrozenMapping
    acceptance_to_obligation: FrozenMapping
    evidence_to_obligation: FrozenMapping
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        for name in (
            "requirement_to_obligations", "obligation_to_work_units", "obligation_to_tests",
            "test_to_obligation", "acceptance_to_obligation", "evidence_to_obligation",
        ):
            object.__setattr__(self, name, FrozenMapping(getattr(self, name)))

    def as_dict(self) -> dict[str, Any]:
        return {name: thaw(getattr(self, name)) for name in (
            "requirement_to_obligations", "obligation_to_work_units", "obligation_to_tests",
            "test_to_obligation", "acceptance_to_obligation", "evidence_to_obligation",
        )} | {"schema_version": self.schema_version}


@dataclass(frozen=True)
class TraceabilityResult:
    status: str
    errors: tuple[str, ...]
    public_test_coverage: float
    hidden_acceptance_coverage: float

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "errors": list(self.errors), "public_test_coverage": self.public_test_coverage, "hidden_acceptance_coverage": self.hidden_acceptance_coverage}


def build_traceability(requirements: NormalizedRequirements, obligations: ObligationSet, work_units: Mapping[str, Iterable[str]] = {}, tests: Iterable[TestBinding] = (), evidence: Mapping[str, Iterable[str]] = {}) -> TraceabilityGraph:
    ids = {item.obligation_id for item in obligations.obligations}
    bindings = tuple(tests)
    requirement_map = {source.source_id: [item.obligation_id for item in obligations.obligations if source.source_id in item.source_requirement_refs] for source in requirements.sources}
    test_map = {item.test_id: list(item.obligation_ids) for item in bindings if not item.hidden}
    acceptance_map = {item.test_id: list(item.obligation_ids) for item in bindings if item.hidden}
    inverse = {identifier: sorted(test_id for test_id, refs in {**test_map, **acceptance_map}.items() if identifier in refs) for identifier in ids}
    return TraceabilityGraph(
        FrozenMapping(requirement_map), FrozenMapping({key: list(value) for key, value in work_units.items()}),
        FrozenMapping(inverse), FrozenMapping(test_map), FrozenMapping(acceptance_map),
        FrozenMapping({key: list(value) for key, value in evidence.items()}),
    )


def validate_traceability(requirements: NormalizedRequirements, obligations: ObligationSet, graph: TraceabilityGraph) -> TraceabilityResult:
    ids = {item.obligation_id for item in obligations.obligations}
    errors: list[str] = []
    for source_id in requirements.public_acceptance_refs:
        if not graph.requirement_to_obligations.get(source_id, ()):
            errors.append(f"PUBLIC_ACCEPTANCE_UNMAPPED:{source_id}")
    public = dict(graph.test_to_obligation)
    hidden = dict(graph.acceptance_to_obligation)
    for prefix, bindings in (("PUBLIC_TEST", public), ("HIDDEN_ACCEPTANCE", hidden)):
        for test_id, refs in bindings.items():
            if not refs:
                errors.append(f"{prefix}_MISSING_OBLIGATION:{test_id}")
            for identifier in refs:
                if identifier not in ids:
                    errors.append(f"{prefix}_ORPHAN_OBLIGATION:{test_id}:{identifier}")
    covered_public = sum(bool(refs) and set(refs) <= ids for refs in public.values())
    covered_hidden = sum(bool(refs) and set(refs) <= ids for refs in hidden.values())
    public_rate = 1.0 if not public else covered_public / len(public)
    hidden_rate = 1.0 if not hidden else covered_hidden / len(hidden)
    harness_gap = any(item.startswith(("HIDDEN_ACCEPTANCE_", "PUBLIC_TEST_")) for item in errors)
    status = "HARNESS_CONTRACT_GAP" if harness_gap else ("REQUIREMENT_INCOMPLETE" if errors else "PASS")
    return TraceabilityResult(status, tuple(sorted(errors)), public_rate, hidden_rate)
