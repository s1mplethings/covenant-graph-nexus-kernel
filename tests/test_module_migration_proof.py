from __future__ import annotations

import pathlib
import tempfile
import unittest

from cgnk_core import ContractRegistry, SchemaLoader
from cgnk_modules.migration_proof import MODULE_REF, build_migration_proof, check_contract_conformance
from tests.helpers import ROOT, codes


class MigrationProofModuleTest(unittest.TestCase):
    def test_contract_conformance(self) -> None:
        contract = ContractRegistry(ROOT, validate_schema=True).resolve_module(MODULE_REF)
        self.assertIsNotNone(contract)
        result = check_contract_conformance(contract)
        self.assertTrue(result["ok"], result["diagnostics"])

    def test_valid_proof_with_temp_ctcp_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            legacy_file = root / "tools" / "legacy.py"
            legacy_file.parent.mkdir(parents=True)
            legacy_file.write_text("def main():\n    return 0\n", encoding="utf-8")
            proof = build_migration_proof(_spec(), ctcp_root=root)
        self.assertTrue(proof["ok"], proof["diagnostics"])
        self.assertEqual([], SchemaLoader(ROOT).validate(proof, "migration_proof.schema.json"))
        self.assertEqual("migration.project_generation@1", proof["migration_ref"])

    def test_missing_legacy_file_and_entrypoint_are_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proof = build_migration_proof(_spec(), ctcp_root=td)
        found = codes(proof["diagnostics"])
        self.assertIn("CGNK_MIGRATION_LEGACY_FILE_MISSING", found)
        self.assertIn("CGNK_MIGRATION_ENTRYPOINT_MISSING", found)


def _spec() -> dict:
    return {
        "kind": "MigrationSpec",
        "id": "migration.project_generation",
        "version": "1",
        "legacy": {"files": ["tools/legacy.py"], "public_entrypoints": ["main"]},
        "target": {
            "flow": "flow.project_refactor@1",
            "modules": ["module.project.snapshot@1"],
            "artifacts": ["artifact.project_snapshot@1"],
        },
        "preserve": {
            "cli_args": True,
            "summary_json_schema": True,
            "benchmark_report_format": True,
            "provider_call_semantics": True,
        },
        "proof": {
            "required_tests": ["tests/test_legacy.py"],
            "required_artifacts": ["artifact.project_snapshot@1"],
            "required_schemas": ["schemas/summary.schema.json"],
        },
    }


if __name__ == "__main__":
    unittest.main()
