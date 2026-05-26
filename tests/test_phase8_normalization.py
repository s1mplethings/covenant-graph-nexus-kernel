from __future__ import annotations

import json
import unittest

from tests.helpers import ROOT, cloned_flow, codes
from cgnk_core import ContractRegistry, SemanticValidator, apply_graph_edit_proposal, compile_flow


class Phase8NormalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)

    def test_compile_result_has_canonical_normalized_outputs(self) -> None:
        result = compile_flow("flow.project_refactor@1", self.registry)
        self.assertTrue(result["ok"], result["diagnostics"])
        for key in ("normalized_bundle", "compiled_flow", "symbol_table", "diagnostics"):
            self.assertIn(key, result)
        bundle = result["compiled_contract_bundle"]
        self.assertIn("normalized_bundle", bundle)
        self.assertIn("compiled_flow", bundle)
        self.assertIn("symbol_table", bundle)
        self.assertEqual("flow.project_refactor@1", result["normalized_bundle"]["flow_ref"])
        self.assertEqual("flow.project_refactor@1", result["compiled_flow"]["flow_ref"])
        self.assertIn("n_plan", result["symbol_table"]["nodes"])

    def test_normalized_output_does_not_expose_schema_alias_names(self) -> None:
        result = compile_flow("flow.project_refactor@1", self.registry)
        rendered = json.dumps(result["normalized_bundle"], sort_keys=True)
        for alias in ("artifact.schema.json", "module.schema.json", "flow.schema.json", "policy.schema.json"):
            self.assertNotIn(alias, rendered)

    def test_diagnostics_include_structured_context_and_repair_hints(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["edges"].append({"from": {"node": "n_plan", "port": "plan"}, "to": {"node": "n_validate_patch", "port": "patch_manifest"}})
        result = compile_flow("flow.project_refactor@1", self.registry, flow_doc=flow)
        mismatch = next(d for d in result["diagnostics"] if d["code"] == "CGNK_EDGE_TYPE_MISMATCH")
        self.assertEqual("error", mismatch["severity"])
        self.assertEqual("$.edges[8]", mismatch["path"])
        self.assertEqual("artifact.patch_manifest@1", mismatch["expected"])
        self.assertEqual("artifact.implementation_plan@1", mismatch["actual"])
        self.assertIn("source", mismatch)
        self.assertIn("target", mismatch)
        self.assertIn("repair_hints", mismatch)

    def test_duplicate_input_and_cycle_invariants(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["edges"].append({"from": {"flow_input": "goal"}, "to": {"node": "n_plan", "port": "goal"}})
        self.assertIn("CGNK_INPUT_MULTI_PRODUCER", codes(SemanticValidator(self.registry).validate_flow(flow)))

        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["edges"].append({"from": {"node": "n_validate_patch", "port": "patch_manifest"}, "to": {"node": "n_emit_patch", "port": "plan"}})
        self.assertIn("CGNK_GRAPH_CYCLE", codes(SemanticValidator(self.registry).validate_flow(flow)))

    def test_split_edge_proposal_applies_to_copy_and_rejects_invalid_preview(self) -> None:
        original = cloned_flow(self.registry, "flow.project_refactor@1")
        proposal = {
            "kind": "GraphEditProposal",
            "id": "proposal.phase8_split_edge",
            "target_flow": "flow.project_refactor@1",
            "edits": [
                {
                    "op": "split_edge",
                    "edge": {
                        "from": {"node": "n_emit_patch", "port": "patch_manifest"},
                        "to": {"node": "n_validate_patch", "port": "patch_manifest"},
                    },
                    "inserted_node": {"id": "n_validate_patch_extra", "uses": "module.patch.validate@1"},
                }
            ],
        }
        result = apply_graph_edit_proposal(proposal, self.registry)
        self.assertFalse(result["ok"])
        self.assertIn("CGNK_INPUT_UNBOUND", codes(result))
        self.assertEqual(original, self.registry.resolve_flow("flow.project_refactor@1"))
        self.assertFalse(result["compile_result"]["ok"])


if __name__ == "__main__":
    unittest.main()
