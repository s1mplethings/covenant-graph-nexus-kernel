from __future__ import annotations

import ast
from dataclasses import dataclass

from cgkn.application.requirements.obligation import ObligationSet
from cgkn.application.requirements.policy import DependencyPolicy

from .contracts import OraclePlan
from .contract_test import ContractTestPlan
from .contract_test_manifest import ContractTestManifest
from .contract_test_renderer import ContractTestRenderer


@dataclass(frozen=True)
class ContractTestValidation:
    status: str
    errors: tuple[str, ...]


class ContractTestValidator:
    def validate(self, plan: ContractTestPlan, manifest: ContractTestManifest, source: str,
                 obligations: ObligationSet, oracle_plan: OraclePlan, policy: DependencyPolicy) -> ContractTestValidation:
        errors: list[str] = []
        expected = ContractTestRenderer().render(plan, policy)
        if source != expected.source:
            errors.append("unprovenanced_or_extra_assertion")
        if manifest.as_dict() != expected.manifest.as_dict():
            errors.append("manifest_or_source_tamper")
        if plan.source_obligation_set_hash != obligations.as_dict()["obligation_set_hash"]:
            errors.append("obligation_set_hash_mismatch")
        if plan.source_oracle_plan_hash != oracle_plan.plan_hash:
            errors.append("oracle_plan_hash_mismatch")
        covered = {item for test in plan.tests for item in test.obligation_ids}
        required = {item.obligation_id for item in obligations.obligations}
        if covered != required:
            errors.append("incomplete_obligation_trace")
        known_oracles = {item.oracle_id for item in oracle_plan.specs}
        if any(set(test.oracle_ids) - known_oracles for test in plan.tests):
            errors.append("unknown_oracle")
        if "cgkn" in source or "hidden acceptance" in source.lower() or "benchmarks" in source:
            errors.append("forbidden_internal_reference")
        try:
            tree = ast.parse(source)
            imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
            imports |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            if any(name not in {"__future__", "ast", "csv", "io", "json", "os", "pathlib", "subprocess", "sys", "pytest"} for name in imports):
                errors.append("dependency_policy_violation")
        except SyntaxError:
            errors.append("invalid_python")
        return ContractTestValidation("PASS" if not errors else "FAIL", tuple(sorted(set(errors))))
