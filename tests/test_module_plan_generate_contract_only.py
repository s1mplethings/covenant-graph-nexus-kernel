from __future__ import annotations

import unittest

from cgnk_core import ContractRegistry
from cgnk_modules.plan_generate_contract_only import MODULE_REF, check_contract_conformance, generate_contract_plan
from tests.helpers import ROOT, codes


class PlanGenerateContractOnlyModuleTest(unittest.TestCase):
    def test_contract_conformance(self) -> None:
        contract = ContractRegistry(ROOT, validate_schema=True).resolve_module(MODULE_REF)
        self.assertIsNotNone(contract)
        result = check_contract_conformance(contract)
        self.assertTrue(result["ok"], result["diagnostics"])

    def test_generates_conservative_plan_from_constraints(self) -> None:
        snapshot = {"kind": "ProjectSnapshot", "files": [{"path": "README.md"}]}
        result = generate_contract_plan("update docs", snapshot=snapshot, constraints={"proposed_changes": [{"action": "modify", "path": "README.md", "reason": "requested"}]})
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual("ImplementationPlan", result["plan"]["kind"])
        self.assertEqual("README.md", result["plan"]["proposed_changes"][0]["path"])

    def test_blocks_ambiguous_goal_without_context(self) -> None:
        result = generate_contract_plan("refactor everything")
        self.assertFalse(result["ok"])
        self.assertIn("CGNK_PLAN_CONTRACT_ONLY_INSUFFICIENT_CONTEXT", codes(result["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
