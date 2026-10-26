from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .obligation import ObligationSet


@dataclass(frozen=True)
class TestCasePlan:
    test_id: str
    obligation_ids: tuple[str, ...]
    test_kind: str
    setup: tuple[str, ...]
    operation: tuple[str, ...]
    expected: tuple[str, ...]
    negative: bool
    required_dependency_policy: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id, "obligation_ids": list(self.obligation_ids), "test_kind": self.test_kind,
            "setup": list(self.setup), "operation": list(self.operation), "expected": list(self.expected),
            "negative": self.negative, "required_dependency_policy": self.required_dependency_policy,
        }


@dataclass(frozen=True)
class TestPlan:
    cases: tuple[TestCasePlan, ...]
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "CGKNTestPlan", "schema_version": self.schema_version, "cases": [item.as_dict() for item in self.cases]}


class TestPlanCompiler:
    """Compiles test facts; a test worker may implement but cannot expand them."""

    def compile(self, obligations: ObligationSet) -> TestPlan:
        cases: list[TestCasePlan] = []
        for obligation in obligations.obligations:
            routes = tuple(obligation.verification_method)
            if not routes:
                continue
            policy_id = obligation.dependency_policy.policy_id if obligation.dependency_policy else None
            cases.append(TestCasePlan(
                test_id=f"PLAN-{obligation.obligation_id.removeprefix('OBL-')}",
                obligation_ids=(obligation.obligation_id,),
                test_kind=routes[0],
                setup=tuple(f"{key}={value}" for key, value in obligation.preconditions.items()),
                operation=tuple(f"{key}={value}" for key, value in obligation.operation.items()),
                expected=tuple(f"{key}={value}" for key, value in obligation.expected.items()),
                negative=obligation.kind.value == "ERROR_SEMANTICS",
                required_dependency_policy=policy_id,
            ))
        return TestPlan(tuple(cases))
