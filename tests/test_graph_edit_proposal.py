from __future__ import annotations

import unittest

from tests.helpers import ROOT, codes
from cgnk_core import ContractRegistry, apply_graph_edit_proposal
from cgnk_core.schema_loader import load_json


class GraphEditProposalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)

    def proposal(self, name: str) -> dict:
        return load_json(ROOT / "examples" / "proposals" / name)

    def test_ok_proposals_preview(self) -> None:
        for name in ("insert_patch_validation_ok.proposal.json", "replace_plan_provider_with_contract_only_ok.proposal.json"):
            result = apply_graph_edit_proposal(self.proposal(name), self.registry)
            self.assertTrue(result["ok"], result["diagnostics"])
            self.assertIsNotNone(result["preview_flow"])

    def test_denied_proposals_return_specific_codes(self) -> None:
        cases = {
            "replace_contract_only_with_provider_denied.proposal.json": "CGNK_POLICY_EFFECT_DENIED",
            "connect_wrong_type_denied.proposal.json": "CGNK_EDGE_TYPE_MISMATCH",
            "add_unbound_required_input_denied.proposal.json": "CGNK_INPUT_UNBOUND",
        }
        for name, code in cases.items():
            result = apply_graph_edit_proposal(self.proposal(name), self.registry)
            self.assertFalse(result["ok"])
            self.assertIn(code, codes(result))


if __name__ == "__main__":
    unittest.main()
