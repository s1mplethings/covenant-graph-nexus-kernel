from __future__ import annotations

import unittest

from cgnk_core import ContractRegistry, SchemaLoader
from cgnk_core.diagnostics import CGNK_INPUT_UNBOUND
from cgnk_modules.repair_plan import MODULE_REF, build_repair_plan, check_contract_conformance
from tests.helpers import ROOT, codes


class RepairPlanModuleTest(unittest.TestCase):
    def test_contract_conformance(self) -> None:
        contract = ContractRegistry(ROOT, validate_schema=True).resolve_module(MODULE_REF)
        self.assertIsNotNone(contract)
        result = check_contract_conformance(contract)
        self.assertTrue(result["ok"], result["diagnostics"])

    def test_builds_schema_valid_repair_plan_without_mutation(self) -> None:
        diagnostics = [{"code": CGNK_INPUT_UNBOUND, "severity": "error", "path": "$.nodes[0].input", "message": "missing", "target": {"node": "n1", "port": "goal"}}]
        proposal = {"kind": "GraphEditProposal", "id": "proposal.test", "version": "1", "target_flow": "flow.project_refactor@1", "edits": []}
        plan = build_repair_plan(diagnostics, proposal=proposal)
        self.assertEqual([], SchemaLoader(ROOT).validate(plan, "repair_plan.schema.json"))
        self.assertEqual("RepairPlan", plan["kind"])
        self.assertTrue(plan["requires_recompile"])
        self.assertEqual("deterministic", plan["confidence"])
        self.assertEqual([], plan["blocked_reasons"])
        self.assertEqual({"node": "n1", "port": "goal"}, plan["suggested_edits"][0]["target"])
        self.assertEqual([], proposal["edits"])

    def test_unsupported_diagnostic_is_blocked(self) -> None:
        plan = build_repair_plan([{"code": "CGNK_UNKNOWN", "severity": "error", "path": "$", "message": "unknown"}])
        self.assertEqual("none", plan["confidence"])
        self.assertIn("CGNK_REPAIR_UNSUPPORTED_DIAGNOSTIC", codes(plan["blocked_reasons"]))


if __name__ == "__main__":
    unittest.main()
