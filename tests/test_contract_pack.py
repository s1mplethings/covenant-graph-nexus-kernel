from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry, SchemaLoader, compile_flow


class ContractPackTest(unittest.TestCase):
    def test_contract_pack_passes_schema(self) -> None:
        registry = ContractRegistry(ROOT, validate_schema=False)
        result = compile_flow("flow.project_generation@1", registry)
        self.assertTrue(result["ok"], result["diagnostics"])
        pack = result["contract_pack"]
        self.assertIsNotNone(pack)
        self.assertEqual([], SchemaLoader(ROOT).validate(pack, "contract_pack.schema.json"))
        self.assertIn("module.plan.generate.provider@1", pack["required_modules"])


if __name__ == "__main__":
    unittest.main()
