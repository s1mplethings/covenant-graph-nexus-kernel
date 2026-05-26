from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry
from cgnk_core.refs import is_valid_ref


class NoStringlyTypedContractsTest(unittest.TestCase):
    def test_refs_are_canonical(self) -> None:
        registry = ContractRegistry(ROOT)
        for ref in registry.artifacts:
            self.assertTrue(is_valid_ref(ref, "artifact"))
        for module in registry.modules.values():
            for side in ("input", "output"):
                for spec in module["ports"][side].values():
                    self.assertTrue(is_valid_ref(spec["artifact_type"], "artifact"))
        for flow in registry.flows.values():
            self.assertTrue(is_valid_ref(f"{flow['id']}@{flow['version']}", "flow"))
            self.assertTrue(is_valid_ref(flow["policy_ref"], "policy"))
            for node in flow["nodes"]:
                self.assertTrue(is_valid_ref(node["uses"], "module"))


if __name__ == "__main__":
    unittest.main()
