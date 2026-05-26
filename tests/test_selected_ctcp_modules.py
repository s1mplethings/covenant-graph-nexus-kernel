from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry, compile_flow


class SelectedCtcpModulesTest(unittest.TestCase):
    def test_selected_modules_exist_as_contracts(self) -> None:
        registry = ContractRegistry(ROOT, validate_schema=True)
        for ref in (
            "module.intent.expand@1",
            "module.decision.gate@1",
            "module.design.arena@1",
            "module.plan.generate.contract_only@1",
            "module.plan.generate.provider@1",
            "module.source.generate.project@1",
            "module.runtime.validate@1",
            "module.delivery.package@1",
            "module.support.reply.orchestrate@1",
            "module.public.send.guard@1",
        ):
            self.assertIn(ref, registry.modules)

    def test_selected_flows_compile(self) -> None:
        registry = ContractRegistry(ROOT, validate_schema=True)
        for ref in (
            "flow.project_generation.cgnk@1",
            "flow.project_refactor.cgnk@1",
            "flow.support_intake_decision.cgnk@1",
            "flow.delivery_guarded_support.cgnk@1",
        ):
            result = compile_flow(ref, registry)
            self.assertTrue(result["ok"], (ref, result["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
