from __future__ import annotations

import pathlib
import tempfile
import unittest

from tests.helpers import ROOT, codes
from cgnk_core import SchemaLoader
from cgnk_core.schema_loader import load_json
from cgnk_ctcp.module_discovery import discover_module_inventory


class Phase16CTCPModuleDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = SchemaLoader(ROOT)

    def make_ctcp_fixture(self) -> tempfile.TemporaryDirectory:
        td = tempfile.TemporaryDirectory()
        root = pathlib.Path(td.name)
        files = {
            "tools/project_analysis.py": """
def collect_project_snapshot(root):
    return {"snapshot": root}

def build_file_index(snapshot):
    return []

def build_project_graph(file_index):
    return {"graph": file_index}
""",
            "tools/planning.py": """
REQUIREMENT_SCHEMA = "requirement"

def extract_requirements(goal):
    return goal

def generate_plan(requirements, project_graph):
    return {"plan": requirements}

def emit_patch_manifest(plan):
    return {"patch_manifest": plan}
""",
            "tools/validation.py": """
def validate_patch_manifest(patch_manifest):
    return True

def validate_schema(payload, schema):
    return True

def contract_validation(contract):
    return []
""",
            "tools/reporting.py": """
def parse_benchmark_summary(path):
    return {"summary_json": path}

def generate_benchmark_report(summary):
    return "benchmark_report"

def trace_summary(trace):
    return trace

def diagnostics_summary(diagnostics):
    return diagnostics
""",
            "tools/guards.py": """
def provider_call_guard(provider_call):
    return provider_call

def convergence_guard(state):
    return state

def timeout_guard(seconds):
    return seconds
""",
            "tools/migration_contracts.py": """
def build_migration_proof(evidence):
    return evidence

def repair_plan(diagnostics):
    return diagnostics
""",
            "legacy/orchestrator.py": """
def old_orchestrator_runner():
    final_output = "legacy"
    project_output = "legacy"
    telegram_bot = "legacy"
    support_progress_fallback = "legacy"
    sqlite_db = "legacy"
    return final_output
""",
            "tools/no_execute.py": f"""
import pathlib
pathlib.Path(r"{(root / 'EXECUTED_MARKER').as_posix()}").write_text("executed")

def snapshot_marker():
    return "snapshot"
""",
        }
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return td

    def test_seed_inventory_and_transfer_plan_schema(self) -> None:
        inventory = load_json(ROOT / "examples" / "ctcp" / "ctcp_module_inventory.seed.json")
        transfer = load_json(ROOT / "examples" / "ctcp" / "ctcp_transfer_plan.seed.json")
        self.assertEqual([], self.loader.validate(inventory, "ctcp_module_inventory.schema.json"))
        self.assertEqual([], self.loader.validate(transfer, "ctcp_transfer_plan.schema.json"))

    def test_temp_ctcp_fixture_detects_reusable_middle_modules(self) -> None:
        with self.make_ctcp_fixture() as td:
            inventory, transfer = discover_module_inventory(pathlib.Path(td), self.loader)
        self.assertTrue(inventory["ok"], inventory["diagnostics"])
        self.assertTrue(transfer["ok"], transfer["diagnostics"])
        self.assertEqual([], self.loader.validate(inventory, "ctcp_module_inventory.schema.json"))
        self.assertEqual([], self.loader.validate(transfer, "ctcp_transfer_plan.schema.json"))
        candidate_ids = {row["id"] for row in inventory["candidates"]}
        self.assertIn("candidate.project_snapshot", candidate_ids)
        self.assertIn("candidate.project_graph", candidate_ids)
        self.assertIn("candidate.requirement_extraction", candidate_ids)
        self.assertIn("candidate.planning", candidate_ids)
        self.assertIn("candidate.patch_manifest_generation", candidate_ids)
        self.assertIn("candidate.patch_validation", candidate_ids)
        self.assertIn("candidate.benchmark_summary_parsing", candidate_ids)
        self.assertIn("candidate.provider_call_guard", candidate_ids)
        self.assertIn("candidate.repair_planning", candidate_ids)

    def test_fixed_glue_is_not_reusable_middle_capability(self) -> None:
        with self.make_ctcp_fixture() as td:
            inventory, _ = discover_module_inventory(pathlib.Path(td), self.loader)
        glue = next(row for row in inventory["candidates"] if row["id"] == "candidate.legacy_glue")
        self.assertIn(glue["classification"]["role"], {"fixed_pipeline_glue", "legacy_only"})
        self.assertEqual("reject", glue["classification"]["migration_value"])
        self.assertFalse(glue["transfer"]["recommended"])

    def test_discovery_does_not_execute_ctcp_code(self) -> None:
        with self.make_ctcp_fixture() as td:
            root = pathlib.Path(td)
            discover_module_inventory(root, self.loader)
            self.assertFalse((root / "EXECUTED_MARKER").exists())

    def test_missing_ctcp_root_diagnostic(self) -> None:
        inventory, transfer = discover_module_inventory(ROOT / "does-not-exist-ctcp", self.loader)
        self.assertFalse(inventory["ok"])
        self.assertIn("CGNK_CTCP_ROOT_MISSING", codes(inventory))
        self.assertEqual([], self.loader.validate(transfer, "ctcp_transfer_plan.schema.json"))

    def test_transfer_plan_never_sets_copy_old_code_true(self) -> None:
        with self.make_ctcp_fixture() as td:
            _, transfer = discover_module_inventory(pathlib.Path(td), self.loader)
        self.assertTrue(transfer["modules"])
        self.assertTrue(all(row["copy_old_code"] is False for row in transfer["modules"]))


if __name__ == "__main__":
    unittest.main()
