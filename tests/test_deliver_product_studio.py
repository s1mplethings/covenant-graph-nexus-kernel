from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.deliver_product_studio as delivery

pytestmark = pytest.mark.slow


RUN_FILE = ROOT / "examples" / "product_studio" / "runs" / "minimal_gui_tool_run" / "product_studio_run.json"


class ProductStudioDeliveryTests(unittest.TestCase):
    def deliver_to_temp(self, use_boundary_guard: bool = False) -> tuple[tempfile.TemporaryDirectory, pathlib.Path, dict]:
        temp_dir = tempfile.TemporaryDirectory()
        out_dir = pathlib.Path(temp_dir.name) / "delivery"
        result = delivery.deliver(RUN_FILE, out_dir, use_boundary_guard=use_boundary_guard)
        return temp_dir, out_dir, result

    def test_deliver_generates_delivery_directory(self) -> None:
        temp_dir, out_dir, result = self.deliver_to_temp()
        with temp_dir:
            self.assertEqual("PASS_WITH_LIMITS", result["status"])
            self.assertTrue((out_dir / "product_studio_run.json").exists())
            self.assertTrue((out_dir / "delivery_bundle.json").exists())

    def test_generated_project_files_exist(self) -> None:
        temp_dir, out_dir, _ = self.deliver_to_temp()
        with temp_dir:
            project_dir = out_dir / "generated_project"
            for name in ["index.html", "styles.css", "app.js", "README.md"]:
                self.assertTrue((project_dir / name).exists(), name)

    def test_test_data_manifest_and_svgs_exist(self) -> None:
        temp_dir, out_dir, _ = self.deliver_to_temp()
        with temp_dir:
            test_data_dir = out_dir / "test_data"
            self.assertTrue((test_data_dir / "sample_images_manifest.json").exists())
            for name in ["sample_001.svg", "sample_002.svg", "sample_003.svg"]:
                self.assertTrue((test_data_dir / name).exists(), name)

    def test_runtime_check_is_local_only(self) -> None:
        temp_dir, out_dir, _ = self.deliver_to_temp()
        with temp_dir:
            runtime_check = json.loads((out_dir / "runtime_check.json").read_text(encoding="utf-8"))
            self.assertTrue(runtime_check["no_network"])
            self.assertFalse(runtime_check["provider_used"])
            self.assertEqual([], runtime_check["missing_files"])

    def test_test_report_exists(self) -> None:
        temp_dir, out_dir, _ = self.deliver_to_temp()
        with temp_dir:
            report = json.loads((out_dir / "test_report.json").read_text(encoding="utf-8"))
            self.assertEqual("ProductStudioTestReport", report["kind"])
            self.assertEqual("PASS_WITH_LIMITS", report["status"])

    def test_visual_evidence_is_static_preview(self) -> None:
        temp_dir, out_dir, _ = self.deliver_to_temp()
        with temp_dir:
            evidence_path = out_dir / "visual_evidence" / "visual_evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual("static_svg_preview", evidence["evidence_type"])
            self.assertEqual("PASS_WITH_LIMITS", evidence["status"])

    def test_delivery_bundle_is_partial(self) -> None:
        temp_dir, out_dir, _ = self.deliver_to_temp()
        with temp_dir:
            bundle = json.loads((out_dir / "delivery_bundle.json").read_text(encoding="utf-8"))
            self.assertEqual("ProductStudioDeliveryBundle", bundle["kind"])
            self.assertEqual("PASS_WITH_LIMITS", bundle["status"])

    def test_delivery_zip_contains_required_files(self) -> None:
        temp_dir, out_dir, _ = self.deliver_to_temp()
        with temp_dir:
            zip_path = out_dir / "delivery_bundle.zip"
            self.assertTrue(zip_path.exists())
            with zipfile.ZipFile(zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn("generated_project/index.html", names)
            self.assertIn("test_report.json", names)
            self.assertIn("visual_evidence/visual_evidence.json", names)

    def test_known_limits_and_revision_entry_exist(self) -> None:
        temp_dir, out_dir, _ = self.deliver_to_temp()
        with temp_dir:
            known_limits = (out_dir / "known_limits.md").read_text(encoding="utf-8")
            self.assertIn("尚未做真实浏览器截图", known_limits)
            revision = json.loads((out_dir / "revision_entry.json").read_text(encoding="utf-8"))
            self.assertIn("ui_change", revision["allowed_revision_types"])

    def test_checker_detects_delivery_bundle(self) -> None:
        temp_dir, out_dir, _ = self.deliver_to_temp()
        with temp_dir:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "check_product_studio_contract.py"),
                    "--run-file",
                    str(out_dir / "product_studio_run.json"),
                    "--json",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(proc.stdout)
            self.assertTrue(result["ok"], result["issues"])
            self.assertTrue(result["delivery_detected"])
            self.assertTrue(result["delivery_bundle_checked"])
            self.assertTrue(result["delivery_zip_checked"])
            self.assertTrue(result["visual_evidence_checked"])

    def test_no_network_or_provider_direct_calls(self) -> None:
        source = (ROOT / "scripts" / "deliver_product_studio.py").read_text(encoding="utf-8")
        for snippet in ["requests.post", "httpx.post", "urllib.request.urlopen", "openai"]:
            self.assertNotIn(snippet, source)

    def test_use_boundary_guard_allows_build_agent_generated_write(self) -> None:
        temp_dir, out_dir, result = self.deliver_to_temp(use_boundary_guard=True)
        with temp_dir:
            self.assertEqual("PASS_WITH_LIMITS", result["status"])
            bundle = json.loads((out_dir / "delivery_bundle.json").read_text(encoding="utf-8"))
            self.assertTrue(bundle["boundary_guard_used"])
            self.assertEqual("allow", bundle["boundary_guard_decision"]["status"])


if __name__ == "__main__":
    unittest.main()
