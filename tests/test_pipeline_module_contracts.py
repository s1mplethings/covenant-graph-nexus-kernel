from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import zipfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.artifact_integrity as artifact_integrity
import scripts.candidate_materializer as candidate_materializer
import scripts.candidate_review_delivery as candidate_review_delivery
import scripts.candidate_sanitizer as candidate_sanitizer
import scripts.final_delivery_truth as final_delivery_truth
import scripts.pipeline_contracts as pipeline_contracts
import scripts.post_build_finalize as post_build_finalize
import scripts.post_build_repair as post_build_repair
import scripts.provider_generation as provider_generation
import scripts.run_local_pipeline as run_local_pipeline
import scripts.visual_evidence as visual_evidence


class PipelineModuleContractTests(unittest.TestCase):
    def test_run_local_pipeline_is_thin_orchestrator(self) -> None:
        source = (ROOT / "scripts" / "run_local_pipeline.py").read_text(encoding="utf-8", errors="replace")

        self.assertIn("api_provider_for_delivery_simulator_for_preflight_only", source)
        self.assertNotIn("telegram_live_bridge", source)
        self.assertNotIn("send_delivery_from_manifest", source)

    def test_provider_generation_module_contract(self) -> None:
        contract = provider_generation.contract()

        self.assertEqual("pass", contract["status"])
        self.assertEqual("replaceable_module", contract["verdict"])
        self.assertIn("provider model routing", contract["metadata"]["responsibilities"])
        self.assertIn("delivery manifest", contract["metadata"]["forbidden"])

    def test_candidate_materializer_contract(self) -> None:
        contract = candidate_materializer.contract()

        self.assertEqual("pass", contract["status"])
        self.assertIn("candidate marker", contract["metadata"]["responsibilities"])
        self.assertIn("final_project_bundle.zip", contract["metadata"]["forbidden"])

    def test_post_build_finalize_contract(self) -> None:
        contract = post_build_finalize.contract()

        self.assertEqual("pass", contract["status"])
        self.assertIn("npm test", contract["metadata"]["responsibilities"])
        self.assertIn("fake PASS", contract["metadata"]["forbidden"])

    def test_post_build_repair_contract(self) -> None:
        contract = post_build_repair.contract()

        self.assertEqual("replaceable_module", contract["verdict"])
        self.assertIn("Windows ESM pathToFileURL repair", contract["metadata"]["responsibilities"])
        self.assertIn("whole-project regeneration", contract["metadata"]["forbidden"])

    def test_visual_evidence_contract(self) -> None:
        contract = visual_evidence.contract()

        self.assertEqual("replaceable_module", contract["verdict"])
        self.assertIn("blank image rejection", contract["metadata"]["responsibilities"])
        self.assertIn("provider-faked screenshots", contract["metadata"]["forbidden"])

    def test_candidate_review_delivery_contract(self) -> None:
        contract = candidate_review_delivery.contract()

        self.assertEqual("replaceable_module", contract["verdict"])
        self.assertIn("ASK_USER_REVIEW candidate delivery", contract["metadata"]["responsibilities"])
        self.assertIn("PASS_FINAL", contract["metadata"]["forbidden"])

    def test_final_delivery_truth_cannot_be_bypassed_by_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            (project / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json").write_text("{}", encoding="utf-8")
            (project / "final_project_bundle.zip").write_bytes(b"PK fake")
            (project / "delivery_manifest.json").write_text("{}", encoding="utf-8")

            result = final_delivery_truth.evaluate(project, {}, {}, phase="final")

        self.assertEqual("fail", result["status"])
        self.assertIn("candidate project cannot pass final delivery", result["blockers"])
        self.assertFalse(result["metadata"]["delivery_allowed"])

    def test_artifact_integrity_rejects_fake_final_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bundle = root / "candidate_diagnostic_bundle.zip"
            with zipfile.ZipFile(bundle, "w") as zf:
                zf.writestr("delivery_manifest.json", "{}")

            result = artifact_integrity.validate_candidate_bundle(bundle)

        self.assertEqual("fail", result["status"])
        self.assertIn("candidate bundle contains delivery_manifest.json", result["blockers"])

    def test_visual_evidence_stub_fake_screenshot_is_rejected_by_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            fake = project / "artifacts" / "screenshots" / "candidate_home.png"
            fake.parent.mkdir(parents=True)
            fake.write_text("not a png", encoding="utf-8")

            result = artifact_integrity.validate_visual_evidence(project, {"screenshots": [str(fake)], "fake": True})

        self.assertEqual("fail", result["status"])
        self.assertTrue(any("not a real image" in item for item in result["blockers"]))
        self.assertTrue(any("fake evidence" in item for item in result["blockers"]))

    def test_artifact_integrity_rejects_header_only_png(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            shot = project / "artifacts" / "screenshots" / "candidate_home.png"
            shot.parent.mkdir(parents=True)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n")

            result = artifact_integrity.validate_visual_evidence(project, {"screenshots": [str(shot)]})

        self.assertEqual("fail", result["status"])
        self.assertTrue(any("blank_or_invalid_screenshot" in item for item in result["blockers"]))

    def test_artifact_integrity_uses_visual_evidence_real_image_file(self) -> None:
        original = artifact_integrity.visual_evidence.real_image_file
        calls: list[pathlib.Path] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            shot = project / "artifacts" / "screenshots" / "candidate_home.png"
            shot.parent.mkdir(parents=True)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)

            def fake_real_image_file(path):
                calls.append(pathlib.Path(path))
                return False

            artifact_integrity.visual_evidence.real_image_file = fake_real_image_file
            try:
                result = artifact_integrity.validate_visual_evidence(project, {"screenshots": [str(shot)]})
            finally:
                artifact_integrity.visual_evidence.real_image_file = original

        self.assertEqual("fail", result["status"])
        self.assertEqual([shot], calls)

    def test_candidate_bundle_rejects_invalid_visual_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bundle = root / "candidate_diagnostic_bundle.zip"
            with zipfile.ZipFile(bundle, "w") as zf:
                zf.writestr("candidate_review_summary.json", "{}")
                zf.writestr("TEST_REPORT.md", "commands_run:\n- npm test\n")
                zf.writestr("known_limits.json", "{}")
                zf.writestr("repair_plan.json", "{}")
                zf.writestr("video_blocked.json", "{}")
                zf.writestr("artifacts/screenshots/candidate_home.png", b"\x89PNG\r\n\x1a\n")

            result = artifact_integrity.validate_candidate_bundle(bundle)

        self.assertEqual("fail", result["status"])
        self.assertTrue(any("corrupt_image" in item for item in result["blockers"]))

    def test_final_gate_rejects_corrupt_screenshot_even_with_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            (project / "artifacts" / "screenshots").mkdir(parents=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n", encoding="utf-8")
            (project / "DELIVERY_NOTES.md").write_text("# Delivery\n", encoding="utf-8")
            (project / "index.html").write_text("<!doctype html><title>Task Board</title><body>Task Board Todo Doing Done</body>\n", encoding="utf-8")
            (project / "artifacts" / "screenshots" / "candidate_home.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            final_bundle = project / "final_project_bundle.zip"
            with zipfile.ZipFile(final_bundle, "w") as zf:
                for path in project.rglob("*"):
                    if path.is_file() and path.name not in {"final_project_bundle.zip", "delivery_manifest.json"}:
                        zf.write(path, path.relative_to(project).as_posix())
            manifest = {
                "package_path": str(final_bundle),
                "quality_evidence": {
                    "test_report_found": True,
                    "test_report_has_commands": True,
                    "test_report_has_no_test_executed": False,
                },
            }
            (project / "delivery_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = final_delivery_truth.evaluate(project, manifest, {"messages": [{"role": "user", "text": "需要截图"}]}, phase="final")

        self.assertEqual("fail", result["status"])
        self.assertTrue(any("corrupt_image" in item for item in result["blockers"]))

    def test_pipeline_modules_can_be_replaced_with_contract_stub(self) -> None:
        class StubProviderGeneration:
            @staticmethod
            def contract() -> dict[str, object]:
                return pipeline_contracts.base_result(status="pass", verdict="replaceable_module", metadata={"stub": True})

            @staticmethod
            def run() -> dict[str, object]:
                return {"status": "pass", "files": [{"path": "README.md", "content": "# Stub\n"}]}

        project = ROOT / "generated" / "test_pipeline_module_contract_candidate"
        if project.exists():
            shutil.rmtree(project)
        try:
            generation = StubProviderGeneration.run()
            materialized = candidate_materializer.run(candidate_dir=project, files=generation["files"])

            self.assertEqual("pass", StubProviderGeneration.contract()["status"])
            self.assertEqual("pass", materialized["status"])
            self.assertTrue((project / "README.md").exists())
            self.assertTrue((project / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json").exists())
        finally:
            if project.exists():
                shutil.rmtree(project)

    def test_module_mutation_contract_is_documented(self) -> None:
        doc = (ROOT / "docs" / "00_kernel_contract.md").read_text(encoding="utf-8")

        self.assertIn("Pipeline Module Mutation Contract", doc)
        self.assertIn("directly modifying, generating, or deleting bounded modules", doc)
        self.assertIn("truth modules", doc)
        self.assertIn("candidate bundle", doc)
        self.assertIn("MODULE_MUTATION_CONTRACT", dir(pipeline_contracts))


if __name__ == "__main__":
    unittest.main()
