from __future__ import annotations

import pathlib
import tempfile
import unittest

from tests.helpers import ROOT, codes
from cgnk_core import ContractRegistry
from cgnk_modules.project_build_graph import (
    MODULE_REF,
    OUTPUT_ARTIFACT_REF,
    build_project_graph,
    check_contract_conformance,
)
from cgnk_modules.project_snapshot import collect_project_snapshot


class Phase20ProjectBuildGraphModuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)

    def make_project(self, bad_python: bool = False) -> tempfile.TemporaryDirectory:
        td = tempfile.TemporaryDirectory()
        root = pathlib.Path(td.name)
        files = {
            "README.md": "# Fixture\n",
            "pyproject.toml": "[project]\nname='fixture'\n",
            "requirements.txt": "pytest\n",
            "src/pkg/__init__.py": "",
            "src/pkg/app.py": "import json\nfrom pathlib import Path\nfrom .local import value\n",
            "src/pkg/local.py": "value = 1\n",
            "tests/test_app.py": "from src.pkg import app\n\ndef test_app():\n    assert app\n",
            "data/sample.json": "{\"ok\": true}\n",
            ".git/config": "[core]\n",
            "__pycache__/app.pyc": "bytecode",
            "node_modules/pkg/index.js": "module.exports = {}",
            "final_output/result.txt": "forbidden",
            "project_output/result.txt": "forbidden",
            "data/app.sqlite": "sqlite",
            "archive/delivery.zip": "zip",
        }
        if bad_python:
            files["src/pkg/bad.py"] = "def broken(:\n"
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return td

    def test_contract_conformance_for_project_build_graph(self) -> None:
        contract = self.registry.resolve_module(MODULE_REF)
        self.assertIsNotNone(contract)
        self.assertEqual([], check_contract_conformance(contract))

    def test_build_graph_from_project_snapshot_is_deterministic(self) -> None:
        with self.make_project() as td:
            snapshot = collect_project_snapshot(td).snapshot
            first = build_project_graph(snapshot)
            second = build_project_graph(snapshot)
        self.assertTrue(first.ok, first.diagnostics)
        self.assertEqual(first.graph, second.graph)
        self.assertEqual("ProjectGraph", first.graph["kind"])
        self.assertEqual(OUTPUT_ARTIFACT_REF, first.graph["artifact_ref"])
        self.assertEqual(MODULE_REF, first.graph["module_ref"])

    def test_graph_contains_file_directory_package_nodes_and_parent_edges(self) -> None:
        with self.make_project() as td:
            graph = build_project_graph(collect_project_snapshot(td).snapshot).graph
        nodes = {row["id"]: row for row in graph["nodes"]}
        edges = {(row["source"], row["target"], row["type"]) for row in graph["edges"]}
        self.assertIn("dir:.", nodes)
        self.assertIn("dir:src", nodes)
        self.assertIn("dir:src/pkg", nodes)
        self.assertTrue(nodes["dir:src/pkg"]["package"])
        self.assertIn("file:src/pkg/app.py", nodes)
        self.assertIn(("dir:src/pkg", "file:src/pkg/app.py", "contains"), edges)

    def test_file_classification_and_project_markers(self) -> None:
        with self.make_project() as td:
            graph = build_project_graph(collect_project_snapshot(td).snapshot).graph
        nodes = {row["path"]: row for row in graph["nodes"] if row["kind"] == "file"}
        self.assertEqual("documentation", nodes["README.md"]["classification"])
        self.assertEqual("config", nodes["pyproject.toml"]["classification"])
        self.assertEqual("source", nodes["src/pkg/app.py"]["classification"])
        self.assertEqual("test", nodes["tests/test_app.py"]["classification"])
        self.assertEqual("data", nodes["data/sample.json"]["classification"])
        markers = graph["metadata"]["project_markers"]
        self.assertTrue(markers["README.md"])
        self.assertTrue(markers["pyproject.toml"])
        self.assertTrue(markers["requirements.txt"])
        self.assertTrue(markers["tests/"])

    def test_python_import_edges_are_ast_only_and_no_execution(self) -> None:
        with self.make_project() as td:
            root = pathlib.Path(td)
            marker = root / "EXECUTED_MARKER"
            graph = build_project_graph(collect_project_snapshot(root).snapshot).graph
        self.assertFalse(marker.exists())
        edges = {(row["source"], row["target"], row["type"]) for row in graph["edges"]}
        self.assertIn(("file:src/pkg/app.py", "import:json", "imports"), edges)
        self.assertIn(("file:src/pkg/app.py", "import:pathlib", "imports"), edges)

    def test_invalid_snapshot_and_ast_parse_diagnostics(self) -> None:
        invalid = build_project_graph({"kind": "NotSnapshot"})
        self.assertFalse(invalid.ok)
        self.assertIn("CGNK_PROJECT_GRAPH_INVALID_SNAPSHOT", codes(invalid.diagnostics))
        with self.make_project(bad_python=True) as td:
            result = build_project_graph(collect_project_snapshot(td).snapshot)
        self.assertTrue(result.ok)
        self.assertIn("CGNK_PROJECT_GRAPH_AST_PARSE_FAILED", codes(result.diagnostics))

    def test_snapshot_forbidden_paths_are_not_in_graph(self) -> None:
        with self.make_project() as td:
            snapshot = collect_project_snapshot(td).snapshot
            snapshot["files"].append({"path": "final_output/forced.txt", "size_bytes": 1})
            result = build_project_graph(snapshot)
        paths = {row.get("path") for row in result.graph["nodes"]}
        self.assertNotIn("final_output/forced.txt", paths)
        self.assertIn("CGNK_PROJECT_GRAPH_FORBIDDEN_PATH", codes(result.diagnostics))


if __name__ == "__main__":
    unittest.main()
