from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry


class RegistryTest(unittest.TestCase):
    def test_load_and_resolve_baseline_refs(self) -> None:
        registry = ContractRegistry(ROOT, validate_schema=False)
        self.assertIn("artifact.goal@1", registry.artifacts)
        self.assertIn("module.plan.generate.contract_only@1", registry.modules)
        self.assertIn("flow.project_generation@1", registry.flows)
        self.assertIn("policy.safe_project_refactor@1", registry.policies)
        self.assertEqual([], registry.diagnostics)


if __name__ == "__main__":
    unittest.main()
