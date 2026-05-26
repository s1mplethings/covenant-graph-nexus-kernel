from __future__ import annotations

import unittest

from cgnk_runtime_adapter import EvidenceBundle, ProviderCallLedger, RuntimeRequest, RuntimeResult, ValidationResult


class RuntimeAdapterContractTest(unittest.TestCase):
    def test_runtime_adapter_dataclasses_hold_compiled_bundle(self) -> None:
        request = RuntimeRequest(compiled_contract_bundle={"kind": "CompiledContractBundle"}, inputs={"goal": {}})
        result = RuntimeResult(
            ok=True,
            outputs={},
            evidence=EvidenceBundle(file_hashes={"a.py": "abc"}),
            provider_ledger=ProviderCallLedger(),
            validation=ValidationResult(ok=True),
        )
        self.assertEqual("CompiledContractBundle", request.compiled_contract_bundle["kind"])
        self.assertTrue(result.validation.ok)


if __name__ == "__main__":
    unittest.main()
