from __future__ import annotations

import unittest

from tests.helpers import codes
from cgnk_modules.patch_validate import validate_patch_manifest


class PatchValidateModuleApiTest(unittest.TestCase):
    def test_returns_plain_dictionary_validation_report(self) -> None:
        result = validate_patch_manifest({"file_changes": [{"action": "create", "path": "src/new.py"}]})
        self.assertIsInstance(result, dict)
        self.assertTrue(result["ok"])
        self.assertEqual("ValidationReport", result["validation_report"]["kind"])
        self.assertEqual([], result["diagnostics"])

    def test_rejects_forbidden_generated_outputs(self) -> None:
        result = validate_patch_manifest({"file_changes": [{"action": "create", "path": "final_output/result.txt"}]})
        self.assertFalse(result["ok"])
        self.assertIn("CGNK_PATCH_VALIDATE_FORBIDDEN_PATH", codes(result["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
