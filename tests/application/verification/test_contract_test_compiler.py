from __future__ import annotations

import pytest

from cgkn.application.requirements import CSV_DEPENDENCY_POLICY, compile_csv_cleaner
from cgkn.application.verification import ContractTestCompiler, OraclePlan, OraclePlanCompiler


def test_compiler_is_deterministic_and_covers_every_obligation_and_oracle() -> None:
    compilation = compile_csv_cleaner(); oracle = OraclePlanCompiler().compile_csv(compilation.obligations, CSV_DEPENDENCY_POLICY)
    first = ContractTestCompiler().compile(compilation.obligations, oracle, CSV_DEPENDENCY_POLICY)
    second = ContractTestCompiler().compile(compilation.obligations, oracle, CSV_DEPENDENCY_POLICY)
    assert first.plan_hash == second.plan_hash
    assert {item for test in first.tests for item in test.obligation_ids} == {item.obligation_id for item in compilation.obligations.obligations}
    assert {item for test in first.tests for item in test.oracle_ids} == {item.oracle_id for item in oracle.specs}


def test_compiler_rejects_missing_or_unknown_semantic_sources() -> None:
    compilation = compile_csv_cleaner(); oracle = OraclePlanCompiler().compile_csv(compilation.obligations, CSV_DEPENDENCY_POLICY)
    broken = OraclePlan(oracle.plan_id, oracle.source_obligation_ids, oracle.obligation_set_hash, oracle.specs[:-1])
    with pytest.raises(ValueError, match="every obligation"):
        ContractTestCompiler().compile(compilation.obligations, broken, CSV_DEPENDENCY_POLICY)
