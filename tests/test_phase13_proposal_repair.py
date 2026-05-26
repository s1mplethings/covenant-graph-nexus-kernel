from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry, SchemaLoader
from cgnk_core.repair import build_repair_plan
from cgnk_core.schema_loader import load_json


class Phase13ProposalRepairTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)

    def test_repair_plan_for_unbound_input_suggests_deterministic_connect(self) -> None:
        proposal = load_json(ROOT / "examples" / "proposals" / "invalid" / "add_unbound_benchmark_input.proposal.json")
        plan = build_repair_plan(proposal, "flow.project_refactor@1", self.registry)
        self.assertEqual("RepairPlan", plan["kind"])
        self.assertEqual("deterministic", plan["confidence"])
        self.assertTrue(plan["requires_recompile"])
        self.assertEqual([], SchemaLoader(ROOT).validate(plan, "repair_plan.schema.json"))
        self.assertIn({"op": "connect", "from": {"node": "n_validate_patch", "port": "validation_report"}, "to": {"node": "n_extra_benchmark", "port": "validation_report"}}, plan["suggested_edits"])

    def test_repair_plan_preserves_original_proposal_and_diagnostics(self) -> None:
        proposal = load_json(ROOT / "examples" / "proposals" / "connect_wrong_type_denied.proposal.json")
        plan = build_repair_plan(proposal, "flow.project_refactor@1", self.registry)
        self.assertEqual(proposal, plan["original_proposal"])
        self.assertTrue(plan["source_diagnostics"])
        self.assertTrue(plan["suggested_edits"] or plan["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
