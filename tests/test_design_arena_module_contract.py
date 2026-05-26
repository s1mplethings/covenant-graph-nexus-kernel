from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry


class DesignArenaModuleContractTest(unittest.TestCase):
    def test_arena_declares_expected_outputs(self) -> None:
        module = ContractRegistry(ROOT).modules["module.design.arena@1"]
        self.assertEqual(
            ["candidates", "scorecard", "winner", "context_digest"],
            module["metadata"]["outputs"],
        )


if __name__ == "__main__":
    unittest.main()
