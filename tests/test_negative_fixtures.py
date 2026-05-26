from __future__ import annotations

import unittest

from tests.helpers import ROOT, cloned_flow, codes
from cgnk_core import ContractRegistry, SemanticValidator


class NegativeFixturesTest(unittest.TestCase):
    def test_invalid_fixtures_return_stable_codes(self) -> None:
        registry = ContractRegistry(ROOT)
        validator = SemanticValidator(registry)
        cases = []

        flow = cloned_flow(registry, "flow.project_refactor@1")
        flow["nodes"][0]["uses"] = "module.missing@1"
        cases.append((flow, "CGNK_MODULE_NOT_FOUND"))

        flow = cloned_flow(registry, "flow.project_refactor@1")
        flow["edges"].append({"from": {"node": "n_plan", "port": "plan"}, "to": {"node": "n_validate_patch", "port": "patch_manifest"}})
        cases.append((flow, "CGNK_EDGE_TYPE_MISMATCH"))

        flow = cloned_flow(registry, "flow.project_refactor@1")
        flow["gates"][0]["require"] = {"free": "stringly"}
        cases.append((flow, "CGNK_GATE_PREDICATE_INVALID"))

        for flow, expected in cases:
            self.assertIn(expected, codes(validator.validate_flow(flow)))


if __name__ == "__main__":
    unittest.main()
