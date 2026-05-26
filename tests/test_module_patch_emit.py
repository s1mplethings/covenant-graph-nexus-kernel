from __future__ import annotations

import unittest

from cgnk_core import ContractRegistry
from cgnk_modules.patch_emit import MODULE_REF, check_contract_conformance, emit_patch_manifest
from tests.helpers import ROOT, codes


class PatchEmitModuleTest(unittest.TestCase):
    def test_contract_conformance(self) -> None:
        contract = ContractRegistry(ROOT, validate_schema=True).resolve_module(MODULE_REF)
        self.assertIsNotNone(contract)
        result = check_contract_conformance(contract)
        self.assertTrue(result["ok"], result["diagnostics"])

    def test_emits_manifest_without_workspace_write(self) -> None:
        manifest = emit_patch_manifest({"proposed_changes": [{"action": "create", "path": "docs/notes.md", "content_ref": "goal:note", "reason": "document behavior"}]})
        self.assertEqual("PatchManifest", manifest["kind"])
        self.assertEqual(1, manifest["summary"]["change_count"])
        self.assertEqual(False, manifest["changes"][0]["safety"]["workspace_write"])
        self.assertEqual([], manifest["diagnostics"])

    def test_rejects_forbidden_patch_targets(self) -> None:
        manifest = emit_patch_manifest({"proposed_changes": [{"action": "create", "path": "project_output/out.txt"}]})
        self.assertIn("CGNK_PATCH_EMIT_FORBIDDEN_PATH", codes(manifest["diagnostics"]))
        self.assertEqual("blocked", manifest["risk_summary"]["severity"])


if __name__ == "__main__":
    unittest.main()
