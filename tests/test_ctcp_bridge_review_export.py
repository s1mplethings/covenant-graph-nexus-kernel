from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from scripts.cgnk_export_ctcp_bridge_review_package import export_bridge_review_package


class CTCPBridgeReviewExportTest(unittest.TestCase):
    def test_export_package_contains_expected_files_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as ctcp_dir, tempfile.TemporaryDirectory() as output_dir:
            ctcp_root = pathlib.Path(ctcp_dir)
            _write_ctcp_fixture(ctcp_root)
            before = _files(ctcp_root)
            result = export_bridge_review_package(ctcp_root=ctcp_root, output_dir=pathlib.Path(output_dir))
            after = _files(ctcp_root)

            self.assertTrue(result["ok"], result)
            self.assertEqual(before, after)
            output_root = pathlib.Path(output_dir)
            expected = {
                "project_generation_bridge.proposal.json",
                "project_generation_contract_bridge.patch_manifest.json",
                "project_generation_next_steps.migration.json",
                "ctcp_bridge_review.json",
                "all_chain_readiness.json",
                "slice_readiness.project_generation.json",
                "REVIEW_SUMMARY.md",
            }
            self.assertEqual(expected, {path.name for path in output_root.iterdir() if path.is_file()})
            summary = (output_root / "REVIEW_SUMMARY.md").read_text(encoding="utf-8")
            self.assertIn("Approval status: `approvable`", summary)
            self.assertIn("CTCP was not modified", summary)
            review = json.loads((output_root / "ctcp_bridge_review.json").read_text(encoding="utf-8"))
            self.assertEqual("approvable", review["approval_status"])

    def test_export_rejects_output_inside_ctcp_root(self) -> None:
        with tempfile.TemporaryDirectory() as ctcp_dir:
            ctcp_root = pathlib.Path(ctcp_dir)
            _write_ctcp_fixture(ctcp_root)
            with self.assertRaises(ValueError):
                export_bridge_review_package(ctcp_root=ctcp_root, output_dir=ctcp_root / "review_package")

    def test_export_creates_no_forbidden_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as ctcp_dir, tempfile.TemporaryDirectory() as output_dir:
            ctcp_root = pathlib.Path(ctcp_dir)
            _write_ctcp_fixture(ctcp_root)
            output_root = pathlib.Path(output_dir)
            export_bridge_review_package(ctcp_root=ctcp_root, output_dir=output_root)
            forbidden = [
                path
                for path in output_root.rglob("*")
                if path.suffix.lower() in {".db", ".sqlite", ".zip"} or path.name in {"final_output", "project_output"}
            ]
            self.assertEqual([], forbidden)


def _write_ctcp_fixture(root: pathlib.Path) -> None:
    files = {
        "tools/providers/project_generation_contracts.py": "CLI args\nprovider_call_semantics\ntimeout_guard_semantics\nfile_hash_cache_evidence\nsupport decision flow\nrepo hygiene guard\nsummary_json_schema\nbenchmark_report_format\n",
        "tests/concrete_project_benchmark/run_concrete_project_benchmark.py": "def run_concrete_project_benchmark():\n    pass\n",
        "tests/concrete_project_benchmark/benchmark_report.md": "benchmark_report_format\n",
        "tests/concrete_project_benchmark/generated/issue_tracker_api/benchmark_summary.json": "{\"summary_json_schema\": true}\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _files(root: pathlib.Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in sorted(root.rglob("*")) if path.is_file()}


if __name__ == "__main__":
    unittest.main()
