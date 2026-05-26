from __future__ import annotations

import unittest

from tests.helpers import ROOT, cloned_flow, codes
from cgnk_core import ContractRegistry, SemanticValidator


class SemanticValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=False)
        self.validator = SemanticValidator(self.registry)

    def test_missing_module(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["nodes"][0]["uses"] = "module.missing@1"
        self.assertIn("CGNK_MODULE_NOT_FOUND", codes(self.validator.validate_flow(flow)))

    def test_wrong_edge_type(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["edges"].append({"from": {"node": "n_plan", "port": "plan"}, "to": {"node": "n_validate_patch", "port": "patch_manifest"}})
        self.assertIn("CGNK_EDGE_TYPE_MISMATCH", codes(self.validator.validate_flow(flow)))

    def test_invalid_endpoint_direction(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["edges"].append({"from": {"flow_output": "validation_report"}, "to": {"node": "n_plan", "port": "goal"}})
        self.assertIn("CGNK_ENDPOINT_DIRECTION_INVALID", codes(self.validator.validate_flow(flow)))

    def test_provider_module_under_no_provider_policy(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        for node in flow["nodes"]:
            if node["id"] == "n_plan":
                node["uses"] = "module.plan.generate.provider@1"
        found = codes(self.validator.validate_flow(flow))
        self.assertIn("CGNK_POLICY_EFFECT_DENIED", found)
        self.assertIn("CGNK_POLICY_CAPABILITY_DENIED", found)

    def test_unbound_input(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["edges"] = [e for e in flow["edges"] if not (e.get("to", {}).get("node") == "n_plan" and e["to"]["port"] == "goal")]
        self.assertIn("CGNK_INPUT_UNBOUND", codes(self.validator.validate_flow(flow)))

    def test_invalid_predicate(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["gates"][0]["require"] = {"node_passed": "missing_node"}
        self.assertIn("CGNK_GATE_PREDICATE_INVALID", codes(self.validator.validate_flow(flow)))

    def test_invalid_policy_and_artifact_refs(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["policy_ref"] = "policy.missing@1"
        flow["inputs"]["goal"] = "artifact.missing@1"
        found = codes(self.validator.validate_flow(flow))
        self.assertIn("CGNK_POLICY_NOT_FOUND", found)
        self.assertIn("CGNK_ARTIFACT_NOT_FOUND", found)


if __name__ == "__main__":
    unittest.main()
