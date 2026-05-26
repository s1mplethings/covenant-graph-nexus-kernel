from __future__ import annotations

from copy import deepcopy
import unittest

from tests.helpers import ROOT, codes
from cgnk_core import SchemaLoader
from cgnk_core.schema_loader import load_json
from cgnk_runtime_adapter import validate_runtime_adapter_contract


class Phase14RuntimeAdapterContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = SchemaLoader(ROOT)
        self.contract = load_json(ROOT / "examples" / "runtime" / "contract_only_adapter.runtime.json")

    def test_contract_only_adapter_validates(self) -> None:
        diagnostics = validate_runtime_adapter_contract(self.contract, self.loader)
        self.assertEqual([], diagnostics)
        self.assertEqual([], self.loader.validate(self.contract, "runtime_adapter_contract.schema.json"))

    def test_execution_claims_are_rejected(self) -> None:
        contract = deepcopy(self.contract)
        contract["can_execute"] = True
        contract["can_apply_patch"] = True
        contract["can_call_provider"] = True
        contract["can_write_workspace"] = True
        found = codes(validate_runtime_adapter_contract(contract, self.loader))
        self.assertIn("CGNK_RUNTIME_EXECUTION_FORBIDDEN", found)
        self.assertIn("CGNK_RUNTIME_PATCH_APPLY_FORBIDDEN", found)
        self.assertIn("CGNK_RUNTIME_PROVIDER_FORBIDDEN", found)
        self.assertIn("CGNK_RUNTIME_WORKSPACE_WRITE_FORBIDDEN", found)


if __name__ == "__main__":
    unittest.main()
