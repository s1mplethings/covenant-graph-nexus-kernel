from __future__ import annotations

import unittest

from tests.helpers import ROOT, cloned_flow, codes
from cgnk_core import ContractRegistry, SchemaLoader, compile_flow


class CompileFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)

    def test_baseline_flows_compile_ok(self) -> None:
        for ref in ("flow.project_generation@1", "flow.project_refactor@1"):
            result = compile_flow(ref, self.registry)
            self.assertTrue(result["ok"], result["diagnostics"])
            self.assertEqual(ref, result["flow_ref"])
            self.assertTrue(result["compiled_contract_bundle"])
            self.assertEqual([], SchemaLoader(ROOT).validate(result, "compile_result.schema.json"))
            self.assertEqual([], SchemaLoader(ROOT).validate(result["compiled_contract_bundle"], "compiled_contract_bundle.schema.json"))

    def test_policy_denies_provider_under_refactor_policy(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        for node in flow["nodes"]:
            if node["id"] == "n_plan":
                node["uses"] = "module.plan.generate.provider@1"
        result = compile_flow("flow.project_refactor@1", self.registry, flow_doc=flow)
        self.assertFalse(result["ok"])
        self.assertIn("CGNK_POLICY_EFFECT_DENIED", codes(result))

    def test_required_inputs_and_outputs(self) -> None:
        result = compile_flow("flow.project_refactor@1", self.registry)
        self.assertEqual({"goal": "artifact.goal@1"}, result["required_inputs"])
        self.assertEqual({"validation_report": "artifact.validation_report@1"}, result["produced_outputs"])


if __name__ == "__main__":
    unittest.main()
