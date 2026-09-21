from __future__ import annotations

import pathlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.slow

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.canonical_evidence_hash as canonical_evidence_hash
import scripts.canonical_media_validation as canonical_media_validation
import scripts.codex_conversation as bridge


@contextmanager
def production_post_build_context(root: pathlib.Path, project: pathlib.Path):
    provenance = bridge.production_candidate_provenance
    original_root = provenance.PRODUCTION_CANDIDATE_ROOT
    causal_provenance = bridge.provider_causal_trace.production_candidate_provenance
    original_causal_root = causal_provenance.PRODUCTION_CANDIDATE_ROOT
    provenance.PRODUCTION_CANDIDATE_ROOT = root.resolve()
    causal_provenance.PRODUCTION_CANDIDATE_ROOT = root.resolve()
    run_dir = root / "production_run"
    run_dir.mkdir()
    provider_staging = root / "provider_staging"
    provider_staging.mkdir()
    generated_files = []
    for source in canonical_evidence_hash.iter_candidate_source_files(project):
        try:
            source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = source.relative_to(project)
        staged = provider_staging / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(source.read_bytes())
        source.unlink()
        generated_files.append(relative.as_posix())
    provider_result_path = run_dir / "provider_generation_result.json"
    provider_result_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "provider_semantic_review": {"status": "pass"},
                "generated_files": sorted(generated_files),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    identity = {
        "run_id": "production-post-build-run",
        "candidate_id": f"candidate-{project.name}",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
    }
    receipts = {}
    try:
        entry_started = bridge.now()
        receipts["production_entry"] = provenance.write_stage_receipt(
            run_dir,
            stage="production_entry",
            run_id=identity["run_id"],
            candidate_id=identity["candidate_id"],
            commit_sha=identity["commit_sha"],
            candidate_root=project,
            started_at=entry_started,
            finished_at=bridge.now(),
        )
        generation_started = bridge.now()
        request_capture = bridge.provider_causal_trace.begin_provider_request(
            candidate_dir=project,
            production_run_dir=run_dir,
            identity=identity,
            goal="provider post-build integration fixture",
            model="reproducible-provider",
            request_started_at=generation_started,
        )
        capture = bridge.provider_causal_trace.consume_provider_response(
            candidate_dir=project,
            provider_staging_dir=provider_staging,
            production_run_dir=run_dir,
            provider_result_path=provider_result_path,
            identity=identity,
            provider_request_capture=request_capture,
            response_received_at=bridge.now(),
        )
        provider_result = json.loads(provider_result_path.read_text(encoding="utf-8"))
        provider_result.update(
            {
                "project_dir": str(project.resolve()),
                "provider_staging_dir": str(provider_staging.resolve()),
                "provider_causal_artifacts": {
                    key: str(value) if isinstance(value, pathlib.Path) else value
                    for key, value in capture.items()
                },
            }
        )
        provider_result_path.write_text(
            json.dumps(provider_result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        provider_ref = {
            "role": "provider_generation_result",
            "ref": str(provider_result_path.resolve()),
            "hash": canonical_evidence_hash.sha256_file(provider_result_path),
        }
        causal_refs = [
            {
                "role": role,
                "ref": str(pathlib.Path(capture[key]).resolve()),
                "hash": canonical_evidence_hash.sha256_file(capture[key]),
            }
            for role, key in (
                ("provider_request", "request_ref"),
                ("provider_response", "response_ref"),
                ("implementation_decision", "decision_ref"),
                ("implementation_patch", "patch_ref"),
                ("patch_application", "application_ref"),
            )
        ]
        receipts["provider_generation"] = provenance.write_stage_receipt(
            run_dir,
            stage="provider_generation",
            run_id=identity["run_id"],
            candidate_id=identity["candidate_id"],
            commit_sha=identity["commit_sha"],
            candidate_root=project,
            started_at=generation_started,
            finished_at=bridge.now(),
            artifact_refs=[provider_ref, *causal_refs],
        )
        validation_started = bridge.now()
        receipts["provider_validation"] = provenance.write_stage_receipt(
            run_dir,
            stage="provider_validation",
            run_id=identity["run_id"],
            candidate_id=identity["candidate_id"],
            commit_sha=identity["commit_sha"],
            candidate_root=project,
            started_at=validation_started,
            finished_at=bridge.now(),
            artifact_refs=[provider_ref, *causal_refs],
        )
        yield {
            "production_identity": identity,
            "production_run_dir": run_dir,
            "stage_receipts": receipts,
            "provider_result_path": provider_result_path,
            "provider_causal_capture": capture,
        }
    finally:
        provenance.PRODUCTION_CANDIDATE_ROOT = original_root
        causal_provenance.PRODUCTION_CANDIDATE_ROOT = original_causal_root


class ProviderPostBuildFinalizeTests(unittest.TestCase):
    def test_canonical_playwright_visual_satisfies_screenshot_without_provider_ui_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "index.html").write_text(
                "<main><h1>Canonical browser capture</h1><button>Run</button></main>\n",
                encoding="utf-8",
            )
            (project / "README.md").write_text("# Browser capture\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            session_dir = root / "sessions"
            session = bridge.default_session("chat-canonical-browser-only")
            session["messages"].append(
                {
                    "role": "user",
                    "text": "做一个网页并交付真实界面截图",
                    "created_at": bridge.now(),
                }
            )
            session["whiteboard"]["delivery_requirements"] = ["界面截图"]

            with production_post_build_context(root, project) as production:
                result = bridge.post_build_finalize_provider_project(
                    project,
                    {"status": "PASS", "example_outputs": {}, "agent_usage": {"events": []}},
                    {"copied": {}},
                    session,
                    session_dir=session_dir,
                    conversation_id="chat-canonical-browser-only",
                    **production,
                )

            self.assertFalse(result["image_result"].get("ui_screenshot"))
            self.assertEqual([], result["image_result"]["missing"])
            self.assertEqual("PASS", result["visual_evidence_result"]["status"], result["visual_evidence_result"])
            self.assertEqual("PASS", result["manifest"]["status"], result["manifest"])
            self.assertTrue(result["manifest"]["visual_evidence_ref"])
            self.assertEqual(
                canonical_evidence_hash.sha256_file(result["manifest"]["visual_evidence_ref"]),
                result["manifest"]["visual_evidence_hash"],
            )
            self.assertEqual("PASS", result["gate"]["canonical_package_inspection"]["status"], result["gate"])

    def test_customer_semantic_repairs_are_not_kernel_bridge_authority(self) -> None:
        bridge_source = (ROOT / "scripts" / "codex_conversation.py").read_text(encoding="utf-8")
        for retired in (
            "ensure_provider_root_launcher",
            "repair_pydantic_basesettings",
            "repair_pillow_requirement",
            "repair_missing_test_import_requirements",
            "repair_common_provider_project_interfaces",
            "materialize_provider_test_artifacts",
            "deterministic_post_build_repair",
        ):
            self.assertNotIn(f"def {retired}", bridge_source)
        post_build = bridge_source.split("def post_build_finalize_provider_project", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("provider_repair_required", post_build)
        self.assertIn("CGKN does not repair customer-project behavior", post_build)

    def test_provider_pytest_env_supports_src_and_top_level_backend_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            (project / "src" / "backend").mkdir(parents=True)
            (project / "src" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "backend" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "backend" / "timeline_manager.py").write_text(
                "class TimelineManager:\n    pass\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "project_api.py").write_text(
                "from backend.timeline_manager import TimelineManager\n\nclass ProjectAPI:\n    manager = TimelineManager\n",
                encoding="utf-8",
            )
            (project / "tests").mkdir()
            (project / "tests" / "test_imports.py").write_text(
                "from src.backend.project_api import ProjectAPI\n\ndef test_imports():\n    assert ProjectAPI.manager\n",
                encoding="utf-8",
            )

            result = bridge.run_provider_project_tests(project)

            self.assertTrue(result["ok"], result)

    def test_post_build_finalize_runs_tests_images_package_and_gate(self) -> None:
        try:
            import PIL  # noqa: F401
        except Exception:
            self.skipTest("Pillow is required for image evidence fixture")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("# VN Assistant\n\nRun `python app.py`.\n", encoding="utf-8")
            (project / "app.py").write_text("print('vn assistant')\n", encoding="utf-8")
            (project / "index.html").write_text("<main><h1>VN Assistant</h1><button>Export</button></main>\n", encoding="utf-8")
            (project / "requirements.txt").write_text("pytest\nPillow\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            (project / "models").mkdir()
            (project / "models" / "__init__.py").write_text("", encoding="utf-8")
            (project / "models" / "image_generator.py").write_text(
                "\n".join(
                    [
                        "import pathlib",
                        "from PIL import Image, ImageDraw",
                        "",
                        "class LocalImageGenerator:",
                        "    def __init__(self, assets_dir='assets/generated'):",
                        "        self.assets_dir = pathlib.Path(assets_dir)",
                        "        self.assets_dir.mkdir(parents=True, exist_ok=True)",
                        "    def generate_background(self, scene_name):",
                        "        path = self.assets_dir / f'background_{scene_name}.png'",
                        "        img = Image.new('RGB', (640, 360), (20, 30, 80))",
                        "        draw = ImageDraw.Draw(img)",
                        "        for x in range(0, 640, 20):",
                        "            draw.line((x, 0, 640-x, 360), fill=(40 + x % 180, 120, 200))",
                        "        draw.text((40, 150), 'generated background', fill=(255, 255, 255))",
                        "        img.save(path)",
                        "        return str(path)",
                        "    def generate_character_sprite(self, character_name):",
                        "        path = self.assets_dir / f'sprite_{character_name}.png'",
                        "        img = Image.new('RGBA', (320, 480), (0, 0, 0, 0))",
                        "        draw = ImageDraw.Draw(img)",
                        "        draw.ellipse((90, 30, 230, 170), fill=(250, 220, 180, 255))",
                        "        draw.rectangle((120, 170, 200, 420), fill=(120, 70, 180, 255))",
                        "        draw.text((50, 430), 'generated sprite', fill=(255, 255, 255, 255))",
                        "        img.save(path)",
                        "        return str(path)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            session_dir = root / "sessions"
            session = bridge.default_session("chat-vn-post")
            session["messages"].append(
                {
                    "role": "user",
                    "text": "帮我做一个本地可运行的 VN 项目助手，可以生成背景，立绘，本地模型，桌面界面，文件导出",
                    "created_at": bridge.now(),
                }
            )
            session["whiteboard"]["local_image_model_discovery"] = {"checked": True, "available": True}
            screenshot = project / "runtime_ui_screenshot.png"
            background = project / "runtime_generated_background.png"
            sprite = project / "runtime_generated_sprite.png"
            bridge.write_rgb_png(
                screenshot,
                640,
                360,
                lambda x, y: ((x * 3 + y) % 255, (x + y * 2) % 255, (x * 2 + y * 3) % 255),
            )
            bridge.write_rgb_png(
                background,
                640,
                360,
                lambda x, y: ((x * 5 + y) % 255, (x + y * 3) % 255, (x * 2 + y) % 255),
            )
            bridge.write_rgb_png(
                sprite,
                320,
                480,
                lambda x, y: ((x + y * 4) % 255, (x * 4 + y) % 255, (x * 2 + y * 2) % 255),
            )
            (project / "generated").mkdir()
            (project / "generated" / "fake_background.png").write_bytes(b"real-background")

            with production_post_build_context(root, project) as production:
                result = bridge.post_build_finalize_provider_project(
                    project,
                    {"status": "PASS", "example_outputs": {}, "agent_usage": {"events": []}},
                    {"copied": {"ui_screenshot": str(screenshot), "background": str(background), "sprite": str(sprite)}},
                    session,
                    session_dir=session_dir,
                    conversation_id="chat-vn-post",
                    **production,
                )

            self.assertTrue(result["test_result"]["ok"])
            self.assertTrue(result["image_result"]["ok"])
            self.assertTrue(result["gate"]["delivery_allowed"], result["gate"])
            self.assertEqual("PASS", result["gate"]["canonical_evidence_gate"]["status"])
            self.assertTrue(result["gate"]["canonical_evidence_gate"]["identity_consistent"])
            for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
                self.assertTrue(result["test_result"].get(field), field)
                self.assertEqual(result["test_result"].get(field), result["runtime_result"].get(field), field)
                self.assertEqual(result["test_result"].get(field), result["visual_evidence_result"].get(field), field)
            runtime_result = result["runtime_result"]
            self.assertTrue(runtime_result["execution_root_isolated"], runtime_result)
            self.assertNotEqual(pathlib.Path(runtime_result["cwd"]).resolve(), project.resolve())
            self.assertEqual(runtime_result["source_candidate_hash"], runtime_result["candidate_hash"])
            self.assertEqual(runtime_result["copied_candidate_hash"], runtime_result["candidate_hash"])
            self.assertTrue(runtime_result["cleanup_result"]["removed"])
            self.assertFalse(pathlib.Path(runtime_result["execution_root"]).exists())
            visual_result = result["visual_evidence_result"]
            self.assertEqual(runtime_result["pid"], visual_result["runtime_pid"])
            self.assertEqual(runtime_result["url"], visual_result["runtime_url"])
            self.assertEqual(runtime_result["port"], visual_result["runtime_port"])
            self.assertEqual(runtime_result["execution_root"], visual_result["runtime_execution_root"])
            self.assertEqual(runtime_result["browser_capture_id"], visual_result["browser_capture_id"])
            self.assertEqual(runtime_result["browser_capture_hash"], visual_result["browser_capture_hash"])
            self.assertTrue(visual_result["runtime_alive_before_capture"])
            self.assertTrue(visual_result["runtime_alive_after_capture"])
            self.assertEqual(canonical_evidence_hash.sha256_file(visual_result["screenshot_path"]), visual_result["screenshot_hash"])
            self.assertEqual(
                canonical_evidence_hash.sha256_file(visual_result["customer_runtime_ref"]),
                visual_result["customer_runtime_hash"],
            )
            image_manifest = result["image_result"]["manifest"]
            for item in image_manifest["images"]:
                if item["path"]:
                    self.assertEqual("PASS", item["audit"]["validation"]["status"], item)
                    self.assertTrue(item["audit"]["validation"]["sha256"].startswith("sha256:"), item)
            self.assertTrue(result["gate"]["media_validation"]["validated_assets"])
            rejected_paths = {
                pathlib.Path(item["path"]).name
                for item in result["gate"]["media_validation"]["rejected_assets"]
                if item.get("path")
            }
            self.assertIn("fake_background.png", rejected_paths)
            self.assertEqual(
                "PASS",
                canonical_media_validation.validate_media(
                    result["image_result"]["background"],
                    project,
                    requested_role="background",
                )["status"],
            )
            first_attempt = result["test_result"].get("first_attempt", {})
            if first_attempt:
                self.assertNotEqual(first_attempt.get("candidate_hash"), result["runtime_result"].get("candidate_hash"))
            self.assertTrue((project / "TEST_REPORT.md").exists())
            self.assertIn("exit_code: 0", (project / "TEST_REPORT.md").read_text(encoding="utf-8"))
            self.assertTrue((project / "screenshots" / "provider_ui_screenshot.png").exists())
            self.assertTrue(list((project / "assets" / "generated").glob("background_*.png")))
            self.assertTrue(list((project / "assets" / "generated").glob("sprite_*.png")))
            self.assertTrue((project / "generated_image_manifest.json").exists())
            self.assertTrue((project / "final_project_bundle.zip").exists())

    def test_post_build_finalize_generates_or_blocks_video_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("# Task Board\n\nRun `python app.py`.\n", encoding="utf-8")
            (project / "app.py").write_text("print('task board')\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            session_dir = root / "sessions"
            session = bridge.default_session("chat-video-blocked")
            session["messages"].append(
                {
                    "role": "user",
                    "text": "做一个任务看板网页应用，必须包含界面截图和30秒以内演示视频",
                    "created_at": bridge.now(),
                }
            )
            session["whiteboard"]["delivery_requirements"] = ["界面截图", "演示视频"]

            with production_post_build_context(root, project) as production:
                result = bridge.post_build_finalize_provider_project(
                    project,
                    {"status": "PASS", "example_outputs": {}, "agent_usage": {"events": []}},
                    {"copied": {}},
                    session,
                    session_dir=session_dir,
                    conversation_id="chat-video-blocked",
                    **production,
                )

            self.assertTrue((project / "video_blocked.json").exists())
            self.assertTrue(result["video_result"]["blocked"])
            self.assertFalse(list(project.rglob("*.mp4")))
            self.assertFalse(list(project.rglob("*.webm")))
            self.assertTrue(any("video_blocked" in item for item in result["manifest"]["known_limits"]))

    def test_post_build_finalize_repair_uses_final_candidate_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "project"
            (project / "src").mkdir(parents=True)
            (project / "src" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
            (project / "index.html").write_text("<main><h1>Repair App</h1></main>\n", encoding="utf-8")
            (project / "README.md").write_text("# Repair App\n", encoding="utf-8")
            (project / "requirements.txt").write_text("pytest\nfastapi>=0.115,<1\nflask>=3,<4\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_repair.py").write_text(
                "from src.main import create_app\n\n"
                "def test_create_app_repair():\n"
                "    assert create_app() is not None\n",
                encoding="utf-8",
            )
            screenshot = project / "runtime_ui_screenshot.png"
            bridge.write_rgb_png(screenshot, 320, 180, lambda x, y: ((x + y) % 255, (x * 2) % 255, (y * 3) % 255))
            session_dir = root / "sessions"
            session = bridge.default_session("chat-repair-post")
            session["messages"].append({"role": "user", "text": "做一个本地网页应用，需要界面截图", "created_at": bridge.now()})

            with production_post_build_context(root, project) as production:
                result = bridge.post_build_finalize_provider_project(
                    project,
                    {"status": "PASS", "example_outputs": {}, "agent_usage": {"events": []}},
                    {"copied": {"ui_screenshot": str(screenshot)}},
                    session,
                    session_dir=session_dir,
                    conversation_id="chat-repair-post",
                    **production,
                )

            first_attempt = result["preseal_test_result"]
            self.assertFalse(first_attempt.get("ok"), first_attempt)
            self.assertNotEqual(first_attempt.get("candidate_hash"), result["test_result"].get("candidate_hash"))
            for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
                self.assertEqual(result["test_result"].get(field), result["runtime_result"].get(field), field)
                self.assertEqual(result["test_result"].get(field), result["visual_evidence_result"].get(field), field)
            self.assertEqual("PASS", result["gate"]["canonical_evidence_gate"]["status"])
            self.assertTrue(result["gate"]["canonical_evidence_gate"]["identity_consistent"])


if __name__ == "__main__":
    unittest.main()
