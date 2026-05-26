from __future__ import annotations

import pathlib
import tempfile
import unittest

from cgnk_modules.migration_proof import build_migration_proof
from cgnk_modules.patch_emit import emit_patch_manifest
from cgnk_modules.patch_validate import validate_patch_manifest
from cgnk_modules.plan_generate_contract_only import generate_contract_plan
from cgnk_modules.project_build_graph import build_project_graph
from cgnk_modules.project_snapshot import collect_project_snapshot
from cgnk_modules.repair_plan import build_repair_plan


class CleanRoomModuleChainTest(unittest.TestCase):
    def test_contract_only_chain_does_not_write_or_execute(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as ctcp_dir:
            project_root = pathlib.Path(project_dir)
            (project_root / "src").mkdir()
            (project_root / "tests").mkdir()
            (project_root / "README.md").write_text("# Fixture\n", encoding="utf-8")
            (project_root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (project_root / "tests" / "test_app.py").write_text("def test_app():\n    assert True\n", encoding="utf-8")
            before = _files(project_root)

            snapshot_result = collect_project_snapshot(project_root)
            self.assertTrue(snapshot_result["ok"], snapshot_result["diagnostics"])
            graph_result = build_project_graph(snapshot_result["snapshot"])
            self.assertTrue(graph_result["ok"], graph_result["diagnostics"])

            plan_result = generate_contract_plan(
                "add deterministic docs note",
                snapshot=snapshot_result["snapshot"],
                graph=graph_result["graph"],
                constraints={"proposed_changes": [{"action": "create", "path": "docs/notes.md", "content_ref": "goal:docs-note", "reason": "requested documentation"}]},
            )
            self.assertTrue(plan_result["ok"], plan_result["diagnostics"])

            patch_manifest = emit_patch_manifest(plan_result["plan"], snapshot=snapshot_result["snapshot"], graph=graph_result["graph"])
            validation = validate_patch_manifest(patch_manifest, snapshot=snapshot_result["snapshot"], graph=graph_result["graph"])
            self.assertTrue(validation["ok"], validation["diagnostics"])

            repair = build_repair_plan(validation["diagnostics"], compiled_flow={"flow_ref": "flow.project_refactor@1"})
            self.assertEqual("RepairPlan", repair["kind"])
            self.assertTrue(repair["requires_recompile"])

            ctcp_root = pathlib.Path(ctcp_dir)
            legacy_file = ctcp_root / "tools" / "legacy.py"
            legacy_file.parent.mkdir(parents=True)
            legacy_file.write_text("def main():\n    return 0\n", encoding="utf-8")
            proof = build_migration_proof(_migration_spec(), ctcp_root=ctcp_root)
            self.assertTrue(proof["ok"], proof["diagnostics"])

            after = _files(project_root)
        self.assertEqual(before, after)


def _files(root: pathlib.Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def _migration_spec() -> dict:
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
