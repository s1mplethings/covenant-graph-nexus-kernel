from __future__ import annotations

import pytest

from cgkn.application.requirements import CSV_DEPENDENCY_POLICY, compile_csv_cleaner
from cgkn.application.verification import ContractTestCompiler, ContractTestPlan, OraclePlanCompiler


def plan():
    compilation = compile_csv_cleaner()
    oracle = OraclePlanCompiler().compile_csv(compilation.obligations, CSV_DEPENDENCY_POLICY)
    return ContractTestCompiler().compile(compilation.obligations, oracle, CSV_DEPENDENCY_POLICY)


def test_contract_plan_round_trip_immutability_and_stable_hash() -> None:
    first, second = plan(), plan()
    assert first.plan_hash == second.plan_hash
    assert ContractTestPlan.from_dict(first.as_dict()).as_dict() == first.as_dict()
    with pytest.raises(Exception):
        first.tests[0].expected["new"] = True


def test_duplicate_test_identity_and_hash_tamper_are_rejected() -> None:
    current = plan()
    with pytest.raises(ValueError, match="duplicate"):
        ContractTestPlan(current.plan_id, current.source_obligation_set_hash, current.source_oracle_plan_hash, (current.tests[0], current.tests[0]))
    value = current.as_dict(); value["plan_hash"] = "sha256:bad"
    with pytest.raises(ValueError, match="hash mismatch"):
        ContractTestPlan.from_dict(value)
