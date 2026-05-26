from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry


class DecisionGateModuleContractTest(unittest.TestCase):
    def test_decision_gate_is_deterministic_first(self) -> None:
        module = ContractRegistry(ROOT).modules["module.decision.gate@1"]
        self.assertEqual("deterministic_first", module["metadata"]["truth_rule"])
        self.assertFalse(module["effects"]["provider_call"])


if __name__ == "__main__":
    unittest.main()
