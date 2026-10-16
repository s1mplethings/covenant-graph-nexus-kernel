from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping

from cgkn.application.requirements.obligation import FrozenMapping, canonical_hash, thaw
from cgkn.application.requirements.policy import DependencyPolicy

from .contracts import OracleEvidence, OracleStatus


class PublicTestStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    HARNESS_FAILURE = "HARNESS_FAILURE"


class FailureClass(str, Enum):
    CONSISTENT_PASS = "CONSISTENT_PASS"
    TEST_DEFECT = "TEST_DEFECT"
    SOURCE_DEFECT = "SOURCE_DEFECT"
    MIXED = "MIXED"
    DEPENDENCY_POLICY_DEFECT = "DEPENDENCY_POLICY_DEFECT"
    HARNESS_FAILURE = "HARNESS_FAILURE"
    CONTRACT_GAP = "CONTRACT_GAP"


@dataclass(frozen=True)
class PublicTestEvidence:
    evidence_id: str
    status: PublicTestStatus
    obligation_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    return_code: int | None = None
    stdout_summary: str = ""
    stderr_summary: str = ""
    setup_status: str = "PASS"
    first_project_frame: str | None = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "obligation_ids", tuple(sorted(set(str(item) for item in self.obligation_ids))))
        object.__setattr__(self, "test_ids", tuple(sorted(set(str(item) for item in self.test_ids))))
        if not self.evidence_id or not self.obligation_ids or not self.test_ids:
            raise ValueError("PublicTestEvidence requires stable identity, tests, and obligations")
        if self.setup_status not in {"PASS", "FAIL"}:
            raise ValueError("public test setup_status must be PASS or FAIL")

    def as_dict(self) -> dict[str, Any]:
        value = {
            "evidence_id": self.evidence_id, "status": self.status.value,
            "obligation_ids": list(self.obligation_ids), "test_ids": list(self.test_ids),
            "return_code": self.return_code, "stdout_summary": self.stdout_summary,
            "stderr_summary": self.stderr_summary, "setup_status": self.setup_status,
            "first_project_frame": self.first_project_frame, "schema_version": self.schema_version,
        }
        return value | {"evidence_hash": canonical_hash(value)}


@dataclass(frozen=True)
class FailureEvidence:
    failure_class: FailureClass
    owner_work_unit: str | None
    owner_file: str | None
    obligation_ids: tuple[str, ...]
    oracle_status: OracleStatus
    public_test_status: PublicTestStatus
    first_project_frame: str | None
    expected: FrozenMapping
    observed: FrozenMapping
    allowed_repair_scope: tuple[str, ...]
    confidence_basis: tuple[str, ...]
    public_test_coverage_gap: bool = False
    owner_override: str | None = None
    override_reason: str | None = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "obligation_ids", tuple(sorted(set(str(item) for item in self.obligation_ids))))
        object.__setattr__(self, "allowed_repair_scope", tuple(sorted(set(str(item) for item in self.allowed_repair_scope))))
        object.__setattr__(self, "confidence_basis", tuple(str(item) for item in self.confidence_basis))
        object.__setattr__(self, "expected", self.expected if isinstance(self.expected, FrozenMapping) else FrozenMapping(self.expected))
        object.__setattr__(self, "observed", self.observed if isinstance(self.observed, FrozenMapping) else FrozenMapping(self.observed))
        if self.owner_override and not self.override_reason:
            raise ValueError("owner override requires a recorded reason")
        if self.failure_class in {FailureClass.HARNESS_FAILURE, FailureClass.CONTRACT_GAP, FailureClass.CONSISTENT_PASS} and self.owner_work_unit is not None:
            raise ValueError("non-project failure cannot own a project WorkUnit")

    @property
    def effective_owner(self) -> str | None:
        return self.owner_override or self.owner_work_unit

    def with_owner_override(self, owner: str, reason: str) -> "FailureEvidence":
        if not owner.strip() or not reason.strip():
            raise ValueError("owner override requires owner and reason")
        return replace(self, owner_override=owner, override_reason=reason)

    def as_dict(self) -> dict[str, Any]:
        value = {
            "failure_class": self.failure_class.value, "owner_work_unit": self.owner_work_unit,
            "owner_file": self.owner_file, "obligation_ids": list(self.obligation_ids),
            "oracle_status": self.oracle_status.value, "public_test_status": self.public_test_status.value,
            "first_project_frame": self.first_project_frame, "expected": thaw(self.expected),
            "observed": thaw(self.observed), "allowed_repair_scope": list(self.allowed_repair_scope),
            "confidence_basis": list(self.confidence_basis), "public_test_coverage_gap": self.public_test_coverage_gap,
            "owner_override": self.owner_override, "override_reason": self.override_reason,
            "schema_version": self.schema_version,
        }
        return value | {"failure_hash": canonical_hash(value)}


@dataclass(frozen=True)
class EvidenceComparator:
    work_unit_scopes: FrozenMapping = field(default_factory=lambda: FrozenMapping({
        "WU-CORE": ["csv_cleaner/**"],
        "WU-TESTS": ["tests/**"],
        "WU-DOCS": ["README.md"],
    }))

    def compare(
        self,
        oracle: OracleEvidence,
        public: PublicTestEvidence,
        *,
        interface_manifest: Mapping[str, Any] | None = None,
        dependency_policy: DependencyPolicy | None = None,
    ) -> FailureEvidence:
        manifest = FrozenMapping(interface_manifest or {})
        common = set(oracle.obligation_ids) & set(public.obligation_ids)
        dependency_failure = any("DEPS" in item or "RUNTIME-STDLIB" in item or "TEST-PYTEST" in item or "NETWORK" in item for item in oracle.obligation_ids)
        if oracle.status in {OracleStatus.HARNESS_FAILURE, OracleStatus.BLOCKED_ENVIRONMENT}:
            failure_class = FailureClass.HARNESS_FAILURE
            owner = None
            gap = False
            basis = (f"oracle_status={oracle.status.value}", "project mutation forbidden")
        elif oracle.status is OracleStatus.PASS and public.status is PublicTestStatus.PASS:
            failure_class = FailureClass.CONSISTENT_PASS
            owner = None
            gap = False
            basis = ("oracle=PASS", "public_test=PASS")
        elif oracle.status is OracleStatus.PASS and public.status is not PublicTestStatus.PASS:
            failure_class = FailureClass.TEST_DEFECT
            owner = "WU-TESTS"
            gap = False
            basis = ("oracle=PASS", f"public_test={public.status.value}", "implementation satisfies independent Oracle")
        elif oracle.status is OracleStatus.FAIL and public.status is PublicTestStatus.PASS:
            failure_class = FailureClass.DEPENDENCY_POLICY_DEFECT if dependency_failure else FailureClass.SOURCE_DEFECT
            owner = "WU-TESTS" if dependency_failure and all("TEST-" in item for item in oracle.obligation_ids) else "WU-CORE"
            gap = True
            basis = ("oracle=FAIL", "public_test=PASS", "PUBLIC_TEST_COVERAGE_GAP")
        elif public.setup_status == "FAIL":
            failure_class = FailureClass.MIXED
            owner = "WU-TESTS"
            gap = True
            basis = ("oracle=FAIL", "public_test_setup=FAIL", "source and test setup require separate resolution")
        elif common:
            failure_class = FailureClass.DEPENDENCY_POLICY_DEFECT if dependency_failure else FailureClass.SOURCE_DEFECT
            owner = "WU-TESTS" if dependency_failure and all("TEST-" in item for item in oracle.obligation_ids) else "WU-CORE"
            gap = False
            basis = ("oracle=FAIL", "public_test=FAIL", "matching obligation failure")
        else:
            failure_class = FailureClass.CONTRACT_GAP
            owner = None
            gap = True
            basis = ("oracle=FAIL", "public_test=FAIL", "no shared obligation mapping", "project mutation forbidden")
        owner_file = public.first_project_frame
        if owner_file is None and owner == "WU-CORE":
            modules = manifest.get("modules", ())
            if modules:
                first = modules[0]
                owner_file = str(first.get("path")) if isinstance(first, Mapping) and first.get("path") else None
        allowed = tuple(self.work_unit_scopes.get(owner, ())) if owner else ()
        policy_basis = (f"dependency_policy={dependency_policy.policy_id}",) if dependency_policy else ()
        return FailureEvidence(
            failure_class=failure_class,
            owner_work_unit=owner,
            owner_file=owner_file,
            obligation_ids=tuple(sorted(set(oracle.obligation_ids) | set(public.obligation_ids))),
            oracle_status=oracle.status,
            public_test_status=public.status,
            first_project_frame=public.first_project_frame,
            expected=oracle.expected,
            observed={"oracle": thaw(oracle.observed), "public_test": public.as_dict()},
            allowed_repair_scope=allowed,
            confidence_basis=basis + policy_basis,
            public_test_coverage_gap=gap,
        )
