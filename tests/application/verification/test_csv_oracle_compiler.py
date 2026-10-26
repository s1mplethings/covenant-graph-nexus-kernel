from __future__ import annotations

import pytest

from cgkn.application.requirements import CSV_DEPENDENCY_POLICY, compile_csv_cleaner
from cgkn.application.verification import (
    CSV_OBLIGATION_IDS,
    OracleEvidence,
    OracleKind,
    OraclePlanCompiler,
    OracleStatus,
)
from scripts.obligation_traceability_gate import validate_oracle_traceability


def compile_plan():
    compiled = compile_csv_cleaner()
    return compiled, OraclePlanCompiler().compile_csv(compiled.obligations, CSV_DEPENDENCY_POLICY)


def passing_evidence(plan):
    return tuple(
        OracleEvidence(
            evidence_id=f"EVIDENCE-{index:03d}",
            oracle_id=spec.oracle_id,
            obligation_ids=spec.obligation_ids,
            status=OracleStatus.PASS,
            expected=spec.expected,
            observed=spec.expected,
        )
        for index, spec in enumerate(plan.specs, 1)
    )


def test_all_sixteen_csv_obligations_have_an_oracle_without_extra_behavior() -> None:
    compiled, plan = compile_plan()
    source_ids = {item.obligation_id for item in compiled.obligations.obligations}
    covered = {identifier for spec in plan.specs for identifier in spec.obligation_ids}
    assert source_ids == covered == CSV_OBLIGATION_IDS
    assert len(source_ids) == 16
    assert all(set(spec.obligation_ids) <= source_ids for spec in plan.specs)
    assert not any("MALFORMED" in identifier for identifier in covered)


def test_oracle_mapping_uses_required_kinds_and_dependency_domains() -> None:
    _, plan = compile_plan()
    mapping = {identifier: spec for spec in plan.specs for identifier in spec.obligation_ids}
    assert mapping["OBL-CSV-INPUT-OUTPUT"].oracle_kind is OracleKind.CSV
    assert mapping["OBL-CSV-PREVIEW"].oracle_kind is OracleKind.CLI
    assert mapping["OBL-CSV-README"].oracle_kind is OracleKind.DOCUMENTATION
    assert mapping["OBL-CSV-PUBLIC-TESTS"].oracle_kind is OracleKind.FILE
    assert mapping["OBL-CSV-RUNTIME-STDLIB"].operation["domain"] == "runtime"
    assert mapping["OBL-CSV-TEST-PYTEST"].operation["domain"] == "test"
    assert mapping["OBL-CSV-RUNTIME-STDLIB"].dependency_policy_refs == ("POLICY-CSV-DEPS-001",)


def test_plan_hash_is_deterministic_across_fresh_compilations() -> None:
    first_compiled = compile_csv_cleaner()
    second_compiled = compile_csv_cleaner()
    compiler = OraclePlanCompiler()
    first = compiler.compile_csv(first_compiled.obligations, CSV_DEPENDENCY_POLICY)
    second = compiler.compile_csv(second_compiled.obligations, CSV_DEPENDENCY_POLICY)
    assert first.as_dict() == second.as_dict()
    assert first.plan_hash == second.plan_hash


def test_malformed_csv_expansion_is_rejected_not_silently_oracled() -> None:
    expanded = compile_csv_cleaner(require_malformed_rejection=True)
    with pytest.raises(ValueError, match="extra=.*MALFORMED"):
        OraclePlanCompiler().compile_csv(expanded.obligations, CSV_DEPENDENCY_POLICY)


def test_traceability_requires_oracle_for_every_must_obligation() -> None:
    compiled, plan = compile_plan()
    result = validate_oracle_traceability(compiled.obligations, plan)
    assert result["status"] == "PASS"
    assert result["oracle_coverage"] == 1.0
    assert result["required_oracles"] == len(plan.specs)


def test_final_pass_requires_passing_evidence_for_every_required_oracle() -> None:
    compiled, plan = compile_plan()
    evidence = passing_evidence(plan)
    passed = validate_oracle_traceability(compiled.obligations, plan, evidence, final_project_status="PASS")
    assert passed["status"] == "PASS"
    failed = validate_oracle_traceability(compiled.obligations, plan, evidence[:-1], final_project_status="PASS")
    assert failed["status"] == "HARNESS_CONTRACT_GAP"
    assert any(item.startswith("FINAL_PASS_MISSING_ORACLE_EVIDENCE") for item in failed["errors"])
