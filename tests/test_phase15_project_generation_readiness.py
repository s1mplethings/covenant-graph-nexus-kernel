from __future__ import annotations

from copy import deepcopy
import pathlib
import tempfile
import unittest

from tests.helpers import ROOT, codes
from cgnk_core import ContractRegistry, SchemaLoader
from cgnk_core.schema_loader import load_json
from cgnk_ctcp.readiness import check_slice_readiness


class Phase15ProjectGenerationReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)
        self.feature_map = load_json(ROOT / "examples" / "ctcp" / "ctcp_feature_map.json")
        self.proposal_path = ROOT / "examples" / "proposals" / "replace_plan_provider_with_contract_only_ok.proposal.json"

    def make_ctcp_fixture(self, omit_entrypoint: bool = False) -> tempfile.TemporaryDirectory:
        td = tempfile.TemporaryDirectory()
        root = pathlib.Path(td.name)
        files = {
            "tools/providers/project_generation_contracts.py": "CLI args\nprovider_call_semantics\ntimeout_guard_semantics\nfile_hash_cache_evidence\nsupport decision flow\nrepo hygiene guard\nsummary_json_schema\nbenchmark_report_format\n",
            "tests/concrete_project_benchmark/run_concrete_project_benchmark.py": "" if omit_entrypoint else "def run_concrete_project_benchmark():\n    pass\n",
            "tests/concrete_project_benchmark/benchmark_report.md": "benchmark_report_format\n",
            "tests/concrete_project_benchmark/generated/issue_tracker_api/benchmark_summary.json": "{\"summary_json_schema\": true}\n",
        }
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return td

    def test_readiness_migration_schema_validates(self) -> None:
        spec = load_json(ROOT / "examples" / "migrations" / "project_generation_readiness.migration.json")
        self.assertEqual([], SchemaLoader(ROOT).validate(spec, "migration_spec.schema.json"))

    def test_project_generation_slice_ready_with_complete_fixture(self) -> None:
        with self.make_ctcp_fixture() as td:
            report = check_slice_readiness("feature.project_generation", self.feature_map, self.registry, pathlib.Path(td), self.proposal_path)
        self.assertTrue(report["ok"], report["diagnostics"])
        self.assertEqual("ready_for_refactor", report["readiness_status"])
        self.assertEqual([], report["missing_requirements"])

    def test_project_generation_slice_blocks_when_feature_missing(self) -> None:
        with self.make_ctcp_fixture() as td:
            report = check_slice_readiness("feature.missing", self.feature_map, self.registry, pathlib.Path(td), self.proposal_path)
        self.assertFalse(report["ok"])
        self.assertIn("CGNK_SLICE_FEATURE_MISSING", codes(report))

    def test_project_generation_slice_blocks_when_proof_incomplete(self) -> None:
        with self.make_ctcp_fixture(omit_entrypoint=True) as td:
            report = check_slice_readiness("feature.project_generation", self.feature_map, self.registry, pathlib.Path(td), self.proposal_path)
        self.assertFalse(report["ok"])
        self.assertIn("public entrypoint presence", report["missing_requirements"])
        self.assertIn("CGNK_SLICE_NOT_READY", codes(report))

    def test_project_generation_slice_blocks_when_migration_missing(self) -> None:
        feature_map = deepcopy(self.feature_map)
        feature_map["features"][0]["migration"] = "migration.missing@1"
        with self.make_ctcp_fixture() as td:
            report = check_slice_readiness("feature.project_generation", feature_map, self.registry, pathlib.Path(td), self.proposal_path)
        self.assertFalse(report["ok"])
        self.assertIn("CGNK_SLICE_MIGRATION_MISSING", codes(report))


if __name__ == "__main__":
    unittest.main()
