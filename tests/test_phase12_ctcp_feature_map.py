from __future__ import annotations

from copy import deepcopy
import pathlib
import tempfile
import unittest

from tests.helpers import ROOT, codes
from cgnk_core import ContractRegistry, SchemaLoader
from cgnk_core.schema_loader import load_json
from cgnk_ctcp.feature_map import check_feature_map


class Phase12CTCPFeatureMapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)
        self.spec = load_json(ROOT / "examples" / "ctcp" / "ctcp_feature_map.json")

    def make_ctcp_fixture(self, missing_file: str | None = None, omit_entrypoint: str | None = None) -> tempfile.TemporaryDirectory:
        td = tempfile.TemporaryDirectory()
        root = pathlib.Path(td.name)
        texts = {
            "tools/providers/project_generation_contracts.py": "\n".join([
                "provider_call_semantics",
                "package_split",
                "patch_manifest_validation",
                "convergence_guard",
                "repair_loop",
                "summary_json_schema",
                "benchmark_report_format",
            ]),
            "tests/concrete_project_benchmark/run_concrete_project_benchmark.py": "def run_concrete_project_benchmark():\n    pass\n",
            "tests/concrete_project_benchmark/benchmark_report.md": "benchmark_report_format\n",
            "tests/concrete_project_benchmark/generated/issue_tracker_api/benchmark_summary.json": "{\"summary_json_schema\": true}\n",
        }
        for rel, text in texts.items():
            if rel == missing_file:
                continue
            if omit_entrypoint:
                text = text.replace(omit_entrypoint, "")
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return td

    def test_feature_map_schema_and_valid_targets(self) -> None:
        self.assertEqual([], SchemaLoader(ROOT).validate(self.spec, "ctcp_feature_map.schema.json"))
        report = check_feature_map(self.spec, self.registry)
        self.assertTrue(report["ok"], report["diagnostics"])
        self.assertEqual(8, report["features_total"])
        self.assertEqual(8, report["features_with_valid_targets"])

    def test_feature_map_validates_legacy_fixture(self) -> None:
        with self.make_ctcp_fixture() as td:
            report = check_feature_map(self.spec, self.registry, pathlib.Path(td))
        self.assertTrue(report["ok"], report["diagnostics"])

    def test_feature_map_reports_duplicate_and_missing_refs(self) -> None:
        spec = deepcopy(self.spec)
        spec["features"].append(deepcopy(spec["features"][0]))
        spec["features"][0]["target"]["flow"] = "flow.missing@1"
        spec["features"][0]["target"]["modules"] = ["module.missing@1"]
        spec["features"][0]["target"]["artifacts"] = ["artifact.missing@1"]
        spec["features"][0]["migration"] = "migration.missing@1"
        found = codes(check_feature_map(spec, self.registry))
        self.assertIn("CGNK_FEATURE_DUPLICATE", found)
        self.assertIn("CGNK_FEATURE_TARGET_FLOW_MISSING", found)
        self.assertIn("CGNK_FEATURE_TARGET_MODULE_MISSING", found)
        self.assertIn("CGNK_FEATURE_TARGET_ARTIFACT_MISSING", found)
        self.assertIn("CGNK_FEATURE_MIGRATION_SPEC_MISSING", found)

    def test_feature_map_reports_legacy_file_and_entrypoint_missing(self) -> None:
        with self.make_ctcp_fixture(missing_file="tools/providers/project_generation_contracts.py", omit_entrypoint="run_concrete_project_benchmark") as td:
            found = codes(check_feature_map(self.spec, self.registry, pathlib.Path(td)))
        self.assertIn("CGNK_FEATURE_LEGACY_FILE_MISSING", found)
        self.assertIn("CGNK_FEATURE_ENTRYPOINT_MISSING", found)


if __name__ == "__main__":
    unittest.main()
