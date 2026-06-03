from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.check_product_studio_contract as checker


def copy_checker_inputs(temp_root: pathlib.Path) -> None:
    rel_paths = checker.REQUIRED_DOCS + [
        checker.PRODUCT_STUDIO_RUN_SCHEMA,
        checker.PRODUCT_STUDIO_RUN_EXAMPLE,
    ]
    for rel_path in rel_paths:
        source = ROOT / rel_path
        target = temp_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


class ProductStudioContractCheckerTests(unittest.TestCase):
    def test_checker_passes_current_repository(self) -> None:
        result = checker.check_root(ROOT)
        self.assertTrue(result["ok"], result["issues"])

    def test_missing_keyword_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = pathlib.Path(temp_dir)
            copy_checker_inputs(temp_root)

            readme = temp_root / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8").replace("agent-led", "agent led"), encoding="utf-8")

            result = checker.check_root(temp_root)
            self.assertFalse(result["ok"])
            self.assertIn("missing_phrase", {issue["type"] for issue in result["issues"]})
            self.assertIn("agent-led", {issue["item"] for issue in result["issues"]})

    def test_json_output_is_parseable(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_product_studio_contract.py"), "--json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertTrue(result["ok"], result["issues"])
        self.assertEqual(checker.REQUIRED_DOCS, result["checked_files"])
        self.assertEqual(checker.PRODUCT_STUDIO_RUN_SCHEMA, result["product_studio_schema_checked"])
        self.assertEqual(checker.PRODUCT_STUDIO_RUN_EXAMPLE, result["product_studio_example_checked"])
        self.assertIn("product_studio_cross_checks", result)

    def test_required_docs_list_is_complete(self) -> None:
        self.assertEqual(
            [
                "README.md",
                "PRODUCT_GOAL.md",
                "docs/00_product_studio_contract.md",
                "docs/01_virtual_team_contract.md",
                "docs/02_product_story_contract.md",
                "docs/03_execution_flow.md",
                "docs/04_acceptance_and_evidence.md",
                "docs/05_agent_operating_contract.md",
                "docs/06_agent_led_layered_architecture.md",
            ],
            checker.REQUIRED_DOCS,
        )

    def test_product_studio_run_schema_exists(self) -> None:
        self.assertTrue((ROOT / checker.PRODUCT_STUDIO_RUN_SCHEMA).exists())

    def test_product_studio_run_example_exists(self) -> None:
        self.assertTrue((ROOT / checker.PRODUCT_STUDIO_RUN_EXAMPLE).exists())

    def test_missing_product_story_acceptance_implications_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = pathlib.Path(temp_dir)
            copy_checker_inputs(temp_root)
            run_path = temp_root / checker.PRODUCT_STUDIO_RUN_EXAMPLE
            run_doc = json.loads(run_path.read_text(encoding="utf-8"))
            run_doc["product_story"]["acceptance_implications"] = []
            run_path.write_text(json.dumps(run_doc, ensure_ascii=False, indent=2), encoding="utf-8")

            result = checker.check_root(temp_root)
            self.assertFalse(result["ok"])
            self.assertIn(
                "product_story_acceptance_implications_non_empty",
                {issue["item"] for issue in result["issues"]},
            )

    def test_missing_delivery_included_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = pathlib.Path(temp_dir)
            copy_checker_inputs(temp_root)
            run_path = temp_root / checker.PRODUCT_STUDIO_RUN_EXAMPLE
            run_doc = json.loads(run_path.read_text(encoding="utf-8"))
            run_doc["delivery_bundle"]["included_evidence"] = []
            run_path.write_text(json.dumps(run_doc, ensure_ascii=False, indent=2), encoding="utf-8")

            result = checker.check_root(temp_root)
            self.assertFalse(result["ok"])
            self.assertIn(
                "delivery_bundle_included_evidence_non_empty",
                {issue["item"] for issue in result["issues"]},
            )


if __name__ == "__main__":
    unittest.main()
