from __future__ import annotations

from cgkn.application.requirements.obligation import ObligationSet
from cgkn.application.requirements.policy import DependencyPolicy

from .contracts import OraclePlan
from .contract_test import ContractTestPlan, ContractTestSpec


class ContractTestCompiler:
    def compile(self, obligations: ObligationSet, oracle_plan: OraclePlan, policy: DependencyPolicy) -> ContractTestPlan:
        obligation_ids = {item.obligation_id for item in obligations.obligations}
        if oracle_plan.obligation_set_hash != obligations.as_dict()["obligation_set_hash"]:
            raise ValueError("OraclePlan does not belong to ObligationSet")
        specs: list[ContractTestSpec] = []
        for oracle in oracle_plan.specs:
            if not set(oracle.obligation_ids) <= obligation_ids:
                raise ValueError("unknown obligation in OraclePlan")
            if oracle.dependency_policy_refs and oracle.dependency_policy_refs != (policy.policy_id,):
                raise ValueError("Oracle dependency policy mismatch")
            slug = oracle.oracle_id.removeprefix("ORACLE-").lower().replace("-", "_")
            specs.append(ContractTestSpec(
                test_id="TEST-CONTRACT-" + oracle.oracle_id.removeprefix("ORACLE-"),
                obligation_ids=oracle.obligation_ids, oracle_ids=(oracle.oracle_id,), test_kind=oracle.oracle_kind.value,
                target_path="tests/test_contract_csv_cleaner.py", test_name="test_contract_" + slug,
                setup=oracle.setup, operation=oracle.operation, expected=oracle.expected,
                dependency_policy_refs=oracle.dependency_policy_refs,
                provenance={"authority": "canonical_oracle_plan", "oracle_hash": oracle.oracle_hash},
            ))
        covered = {item for spec in specs for item in spec.obligation_ids}
        if covered != obligation_ids:
            raise ValueError("every obligation requires a canonical contract test")
        return ContractTestPlan("PLAN-CSV-CONTRACT-TEST-001", obligations.as_dict()["obligation_set_hash"], oracle_plan.plan_hash, tuple(specs))
