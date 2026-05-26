from __future__ import annotations

import pathlib
import tempfile
import unittest

from tests.helpers import ROOT, codes
from cgnk_core import ContractRegistry
from cgnk_modules.patch_validate import MODULE_REF, OUTPUT_ARTIFACT_REF, check_contract_conformance, validate_patch_manifest
from cgnk_modules.project_build_graph import build_project_graph
from cgnk_modules.project_snapshot import collect_project_snapshot


class Phase21PatchValidateModuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)

    def make_project(self) -> tempfile.TemporaryDirectory:
        td = tempfile.TemporaryDirectory()
        root = pathlib.Path(td.name)
        files = {
            "README.md": "# Fixture\n",
            "src/app.py": "print('hello')\n",
            "tests/test_app.py": "def test_app():\n    assert True\n",
        }
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return td

    def context(self, root: pathlib.Path) -> tuple[dict, dict]:
        snapshot = collect_project_snapshot(root).snapshot
        graph = build_project_graph(snapshot).graph
        return snapshot, graph

    def test_contract_conformance_for_patch_validate(self) -> None:
        contract = self.registry.resolve_module(MODULE_REF)
        self.assertIsNotNone(contract)
        self.assertEqual([], check_contract_conformance(contract))

    def test_valid_manifest_produces_validation_report(self) -> None:
        with self.make_project() as td:
            snapshot, graph = self.context(pathlib.Path(td))
            result = validate_patch_manifest(
                {
                    "kind": "PatchManifest",
                    "file_changes": [
                        {"action": "modify", "path": "src/app.py"},
                        {"action": "create", "path": "src/new_module.py"},
                        {"action": "rename", "path": "tests/test_app.py", "to_path": "tests/test_cli.py"},
                    ],
                },
                snapshot=snapshot,
                project_graph=graph,
            )
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual("ValidationReport", result.validation_report["kind"])
        self.assertEqual(OUTPUT_ARTIFACT_REF, result.validation_report["artifact_ref"])
        self.assertEqual("deterministic", result.validation_report["checked_at"])
        self.assertEqual(3, result.validation_report["manifest_summary"]["change_count"])
        self.assertEqual("review", result.validation_report["risk_summary"]["severity"])

    def test_invalid_manifest_shape_and_missing_fields(self) -> None:
        result = validate_patch_manifest(["not", "a", "dict"])
        self.assertFalse(result.ok)
        self.assertIn("CGNK_PATCH_VALIDATE_INVALID_MANIFEST", codes(result.diagnostics))

        result = validate_patch_manifest({"kind": "PatchManifest", "file_changes": [{"path": "src/app.py"}]})
        self.assertFalse(result.ok)
        self.assertIn("CGNK_PATCH_VALIDATE_MISSING_FIELD", codes(result.diagnostics))

    def test_invalid_action_path_escape_and_forbidden_paths(self) -> None:
        result = validate_patch_manifest(
            {
                "file_changes": [
                    {"action": "chmod", "path": "src/app.py"},
                    {"action": "modify", "path": "../outside.py"},
                    {"action": "create", "path": ".git/config"},
                    {"action": "create", "path": ".env"},
                    {"action": "create", "path": "secrets/token.txt"},
                    {"action": "create", "path": "final_output/result.txt"},
                    {"action": "create", "path": "project_output/result.txt"},
                    {"action": "create", "path": "data/app.sqlite"},
                    {"action": "create", "path": "archive/delivery.zip"},
                ]
            }
        )
        found = codes(result.diagnostics)
        self.assertFalse(result.ok)
        self.assertIn("CGNK_PATCH_VALIDATE_INVALID_ACTION", found)
        self.assertIn("CGNK_PATCH_VALIDATE_PATH_ESCAPE", found)
        self.assertIn("CGNK_PATCH_VALIDATE_FORBIDDEN_PATH", found)

    def test_duplicate_targets_are_detected(self) -> None:
        result = validate_patch_manifest(
            {
                "file_changes": [
                    {"action": "modify", "path": "src/app.py"},
                    {"action": "delete", "path": "src/app.py"},
                ]
            }
        )
        self.assertFalse(result.ok)
        self.assertIn("CGNK_PATCH_VALIDATE_DUPLICATE_TARGET", codes(result.diagnostics))

    def test_snapshot_context_mismatches_are_detected(self) -> None:
        with self.make_project() as td:
            snapshot, _ = self.context(pathlib.Path(td))
            result = validate_patch_manifest(
                {
                    "file_changes": [
                        {"action": "modify", "path": "src/missing.py"},
                        {"action": "delete", "path": "tests/missing_test.py"},
                        {"action": "create", "path": "README.md"},
                    ]
                },
                snapshot=snapshot,
            )
        found = codes(result.diagnostics)
        self.assertFalse(result.ok)
        self.assertIn("CGNK_PATCH_VALIDATE_CONTEXT_MISMATCH", found)
        self.assertEqual("blocked", result.validation_report["risk_summary"]["severity"])

    def test_move_or_rename_requires_destination(self) -> None:
        result = validate_patch_manifest({"file_changes": [{"action": "move", "path": "src/app.py"}]})
        self.assertFalse(result.ok)
        self.assertIn("CGNK_PATCH_VALIDATE_MISSING_FIELD", codes(result.diagnostics))

    def test_validation_does_not_write_workspace_files(self) -> None:
        with self.make_project() as td:
            root = pathlib.Path(td)
            snapshot, graph = self.context(root)
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
            validate_patch_manifest({"file_changes": [{"action": "modify", "path": "src/app.py"}]}, snapshot=snapshot, project_graph=graph)
            after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
