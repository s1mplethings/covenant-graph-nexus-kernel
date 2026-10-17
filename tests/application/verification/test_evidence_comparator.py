from __future__ import annotations

import pytest

from cgkn.application.requirements import CSV_DEPENDENCY_POLICY
from cgkn.application.verification import (
    EvidenceComparator,
    FailureClass,
    OracleEvidence,
    OracleStatus,
    PublicTestEvidence,
    PublicTestStatus,
)


def oracle(status: OracleStatus, obligation: str = "OBL-CSV-FILL-EMPTY") -> OracleEvidence:
    return OracleEvidence(
        evidence_id="EVIDENCE-ORACLE-COMPARE",
        oracle_id="ORACLE-CSV-COMPARE",
        obligation_ids=(obligation,),
        status=status,
        expected={"fill": "UNKNOWN"},
        observed={"fill": "" if status is OracleStatus.FAIL else "UNKNOWN"},
        failure_class=None if status is OracleStatus.PASS else "ASSERTION_MISMATCH",
    )


def public(
    status: PublicTestStatus,
    obligation: str = "OBL-CSV-FILL-EMPTY",
    *,
    setup_status: str = "PASS",
) -> PublicTestEvidence:
    return PublicTestEvidence(
        "EVIDENCE-PUBLIC-TESTS", status, (obligation,), ("TEST-FILL",),
        return_code=0 if status is PublicTestStatus.PASS else 1,
        setup_status=setup_status,
        first_project_frame="tests/test_csv_cleaner.py",
    )


def test_case_a_oracle_pass_test_pass_is_consistent() -> None:
    result = EvidenceComparator().compare(oracle(OracleStatus.PASS), public(PublicTestStatus.PASS))
    assert result.failure_class is FailureClass.CONSISTENT_PASS
    assert result.owner_work_unit is None
    assert result.allowed_repair_scope == ()


def test_case_b_oracle_pass_test_fail_routes_only_tests() -> None:
    result = EvidenceComparator().compare(oracle(OracleStatus.PASS), public(PublicTestStatus.FAIL))
    assert result.failure_class is FailureClass.TEST_DEFECT
    assert result.owner_work_unit == "WU-TESTS"
    assert result.allowed_repair_scope == ("tests/**",)
    assert result.public_test_coverage_gap is False


def test_case_c_oracle_fail_test_pass_routes_core_and_marks_coverage_gap() -> None:
    result = EvidenceComparator().compare(
        oracle(OracleStatus.FAIL), public(PublicTestStatus.PASS),
        interface_manifest={"modules": [{"path": "csv_cleaner/core.py"}]},
        dependency_policy=CSV_DEPENDENCY_POLICY,
    )
    assert result.failure_class is FailureClass.SOURCE_DEFECT
    assert result.owner_work_unit == "WU-CORE"
    assert result.owner_file == "tests/test_csv_cleaner.py"
    assert result.public_test_coverage_gap is True
    assert "dependency_policy=POLICY-CSV-DEPS-001" in result.confidence_basis


def test_case_d_both_fail_same_obligation_routes_source() -> None:
    result = EvidenceComparator().compare(oracle(OracleStatus.FAIL), public(PublicTestStatus.FAIL))
    assert result.failure_class is FailureClass.SOURCE_DEFECT
    assert result.owner_work_unit == "WU-CORE"
    assert result.public_test_coverage_gap is False


def test_broken_public_setup_with_oracle_failure_is_mixed_and_test_owned() -> None:
    result = EvidenceComparator().compare(
        oracle(OracleStatus.FAIL), public(PublicTestStatus.HARNESS_FAILURE, setup_status="FAIL")
    )
    assert result.failure_class is FailureClass.MIXED
    assert result.owner_work_unit == "WU-TESTS"
    assert result.public_test_coverage_gap is True


def test_harness_and_contract_gaps_never_mutate_project() -> None:
    harness = EvidenceComparator().compare(
        oracle(OracleStatus.HARNESS_FAILURE), public(PublicTestStatus.FAIL)
    )
    assert harness.failure_class is FailureClass.HARNESS_FAILURE
    assert harness.owner_work_unit is None
    contract = EvidenceComparator().compare(
        oracle(OracleStatus.FAIL), public(PublicTestStatus.FAIL, "OBL-CSV-README")
    )
    assert contract.failure_class is FailureClass.CONTRACT_GAP
    assert contract.owner_work_unit is None


def test_dependency_policy_failure_routes_corresponding_work_unit() -> None:
    runtime = EvidenceComparator().compare(
        oracle(OracleStatus.FAIL, "OBL-CSV-RUNTIME-STDLIB"),
        public(PublicTestStatus.PASS, "OBL-CSV-RUNTIME-STDLIB"),
    )
    assert runtime.failure_class is FailureClass.DEPENDENCY_POLICY_DEFECT
    assert runtime.owner_work_unit == "WU-CORE"
    tests = EvidenceComparator().compare(
        oracle(OracleStatus.FAIL, "OBL-CSV-TEST-PYTEST"),
        public(PublicTestStatus.PASS, "OBL-CSV-TEST-PYTEST"),
    )
    assert tests.owner_work_unit == "WU-TESTS"


def test_owner_override_requires_reason_and_is_recorded() -> None:
    result = EvidenceComparator().compare(oracle(OracleStatus.FAIL), public(PublicTestStatus.FAIL))
    with pytest.raises(ValueError, match="reason"):
        result.with_owner_override("WU-DOCS", "")
    overridden = result.with_owner_override("WU-DOCS", "first project frame points to README generation")
    assert overridden.effective_owner == "WU-DOCS"
    assert overridden.as_dict()["override_reason"]


def test_documentation_oracle_failure_routes_to_docs_work_unit() -> None:
    result = EvidenceComparator().compare(
        oracle(OracleStatus.FAIL, "OBL-CSV-README"),
        public(PublicTestStatus.PASS, "OBL-CSV-README"),
    )
    assert result.failure_class is FailureClass.SOURCE_DEFECT
    assert result.owner_work_unit == "WU-DOCS"
    assert result.allowed_repair_scope == ("README.md",)


def test_canonical_test_disagreement_is_framework_owned_and_cannot_mutate_project() -> None:
    compiler_defect = EvidenceComparator().compare(
        oracle(OracleStatus.PASS),
        PublicTestEvidence(
            "EVIDENCE-CANONICAL-FAIL", PublicTestStatus.FAIL,
            ("OBL-CSV-FILL-EMPTY",), ("TEST-CONTRACT-FILL",),
            evidence_authority="CANONICAL_CONTRACT",
        ),
    )
    assert compiler_defect.failure_class is FailureClass.FRAMEWORK_TEST_COMPILER_DEFECT
    assert compiler_defect.owner_work_unit is None
    coverage_defect = EvidenceComparator().compare(
        oracle(OracleStatus.FAIL),
        PublicTestEvidence(
            "EVIDENCE-CANONICAL-PASS", PublicTestStatus.PASS,
            ("OBL-CSV-FILL-EMPTY",), ("TEST-CONTRACT-FILL",),
            evidence_authority="CANONICAL_CONTRACT",
        ),
    )
    assert coverage_defect.failure_class is FailureClass.FRAMEWORK_TEST_COVERAGE_DEFECT
    assert coverage_defect.owner_work_unit is None
