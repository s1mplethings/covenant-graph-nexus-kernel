from __future__ import annotations

import pathlib
import tempfile
import unittest

from tests.helpers import ROOT, codes
from cgnk_core import ContractRegistry
from cgnk_modules.project_snapshot import (
    MODULE_REF,
    OUTPUT_ARTIFACT_REF,
    check_contract_conformance,
    collect_project_snapshot,
)


class Phase19ProjectSnapshotModuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)

    def make_project(self) -> tempfile.TemporaryDirectory:
        td = tempfile.TemporaryDirectory()
        root = pathlib.Path(td.name)
        files = {
            "README.md": "# Fixture\n",
            "src/app.py": "print('hello')\n",
            "tests/test_app.py": "def test_app():\n    assert True\n",
            ".git/config": "[core]\n",
            "__pycache__/app.pyc": "bytecode",
            ".pytest_cache/v/cache/nodeids": "[]",
            "node_modules/pkg/index.js": "module.exports = {}",
            "final_output/result.txt": "forbidden",
            "project_output/result.txt": "forbidden",
            "data/app.sqlite": "sqlite",
            "archive/delivery.zip": "zip",
        }
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return td

    def test_contract_conformance_for_project_snapshot(self) -> None:
        contract = self.registry.resolve_module(MODULE_REF)
        self.assertIsNotNone(contract)
        self.assertEqual([], check_contract_conformance(contract))

    def test_snapshot_is_deterministic_and_matches_contract_output(self) -> None:
        with self.make_project() as td:
            first = collect_project_snapshot(td)
            second = collect_project_snapshot(td)
        self.assertTrue(first["ok"], first["diagnostics"])
        self.assertEqual(first["snapshot"], second["snapshot"])
        self.assertEqual("ProjectSnapshot", first["snapshot"]["kind"])
        self.assertEqual(OUTPUT_ARTIFACT_REF, first["snapshot"]["artifact_ref"])
        self.assertEqual(MODULE_REF, first["snapshot"]["module_ref"])
        self.assertEqual(["README.md", "src/app.py", "tests/test_app.py"], [row["path"] for row in first["snapshot"]["files"]])
        self.assertTrue(all("sha256" in row for row in first["snapshot"]["files"]))

    def test_snapshot_excludes_generated_archive_and_database_paths(self) -> None:
        with self.make_project() as td:
            result = collect_project_snapshot(td)
        paths = {row["path"] for row in result["snapshot"]["files"]}
        self.assertNotIn("final_output/result.txt", paths)
        self.assertNotIn("project_output/result.txt", paths)
        self.assertNotIn("data/app.sqlite", paths)
        self.assertNotIn("archive/delivery.zip", paths)
        self.assertIn("CGNK_PROJECT_SNAPSHOT_FORBIDDEN_PATH", codes(result["diagnostics"]))

    def test_missing_root_returns_stable_diagnostic(self) -> None:
        result = collect_project_snapshot(ROOT / "missing-project-root-for-snapshot")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["snapshot"])
        self.assertIn("CGNK_PROJECT_SNAPSHOT_ROOT_MISSING", codes(result["diagnostics"]))

    def test_snapshot_does_not_write_workspace_files(self) -> None:
        with self.make_project() as td:
            root = pathlib.Path(td)
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
            collect_project_snapshot(root)
            after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
