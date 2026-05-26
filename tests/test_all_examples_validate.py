from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry, SchemaLoader, compile_flow


class AllExamplesValidateTest(unittest.TestCase):
    def test_examples_schema_and_semantic_validate(self) -> None:
        self.assertEqual([], [d.as_dict() for d in SchemaLoader(ROOT).validate_examples()])
        registry = ContractRegistry(ROOT, validate_schema=True)
        for ref in sorted(registry.flows):
            result = compile_flow(ref, registry)
            self.assertTrue(result["ok"], (ref, result["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
