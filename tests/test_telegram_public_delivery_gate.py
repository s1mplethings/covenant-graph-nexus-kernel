from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
import json
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.local_packager as local_packager
import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.videos: list[tuple[str, pathlib.Path, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))

    def send_photo(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.photos.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_video(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.videos.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return True


def vn_session(chat_id: str) -> dict:
    session = bridge.default_session(chat_id)
    session["whiteboard"]["project_summary"] = "本地可运行的 VN 项目助手，桌面界面，文件导出，能直接生成背景和立绘图片"
    session["whiteboard"]["delivery_requirements"] = ["交付项目包、界面截图、生成背景、生成立绘"]
    session["whiteboard"]["acceptance_criteria"] = ["NO TEST EXECUTED 不能公开交付"]
    session["active_run"] = {"id": f"run-{chat_id}-1", "status": "running", "created_at": bridge.now()}
    session["generation"] = {"status": "running"}
    return session


def make_candidate_review_fixture(root: pathlib.Path, *, bundle_name: str = "candidate_diagnostic_bundle.zip", extra_bundle_files: dict[str, str] | None = None) -> tuple[pathlib.Path, pathlib.Path]:
    project = root / "candidate"
    project.mkdir()
    (project / "README.md").write_text("# Candidate\n", encoding="utf-8")
    (project / "index.html").write_text("<!doctype html><title>Candidate</title>\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("# TEST_REPORT\n\ntest_status: pass\ncommands_run:\n- [\"npm\", \"test\"]\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("candidate_only: true\nnot_final_delivery: true\n", encoding="utf-8")
    (project / "known_limits.json").write_text(json.dumps({"known_limits": ["screenshot missing"]}), encoding="utf-8")
    (project / "repair_plan.json").write_text(json.dumps({"stage": "post_build_repair"}), encoding="utf-8")
    (project / "screenshot_blocked.json").write_text(json.dumps({"status": "blocked", "reason": "browser unavailable"}), encoding="utf-8")
    (project / "video_blocked.json").write_text(json.dumps({"status": "blocked", "reason": "video not produced"}), encoding="utf-8")
    (project / "candidate_review_summary.json").write_text(
        json.dumps(
            {
                "verdict": "ASK_USER_REVIEW",
                "candidate_project_dir": str(project),
                "test_status": "pass",
                "final_delivery": False,
                "warnings": ["final_project_bundle.zip not generated", "delivery_manifest.json not generated"],
            }
        ),
        encoding="utf-8",
    )
    bundle = root / bundle_name
    with zipfile.ZipFile(bundle, "w") as zf:
        for name in ("candidate_review_summary.json", "TEST_REPORT.md", "DELIVERY_NOTES.md", "known_limits.json", "repair_plan.json", "screenshot_blocked.json", "video_blocked.json"):
            zf.write(project / name, name)
        for name, content in (extra_bundle_files or {}).items():
            zf.writestr(name, content)
    return project, bundle


class TelegramPublicDeliveryGateTests(unittest.TestCase):
    def test_readme_only_no_test_executed_blocks_public_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("# VN helper\n", encoding="utf-8")
            session = vn_session("chat-block")
            bridge.save_session(session_dir, session)
            client = FakeTelegramClient()
            evidence = {
                "test_report_path": "TEST_REPORT.md",
                "test_commands": [],
                "sample_inputs": [],
                "screenshots": [],
                "generated_images": [],
                "videos": [],
                "preview_files": ["README.md", "delivery_manifest.json", "notes.txt"],
            }
            manifest = {
                "project_dir": str(project),
                "quality_evidence": {
                    "test_report_found": True,
                    "test_report_has_commands": False,
                    "test_report_has_no_test_executed": True,
                },
            }

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, evidence=evidence, phase="checkpoint")
            sent = bridge.send_evidence_checkpoint(client, "chat-block", session_dir, session, project, evidence)
            saved = bridge.load_session(session_dir, "chat-block")

        self.assertFalse(gate["delivery_allowed"])
        self.assertEqual([], sent)
        self.assertEqual([], client.documents)
        self.assertEqual("REWORK_BLOCKED", saved["generation"]["status"].upper())
        self.assertEqual("REWORK_BLOCKED", saved["active_run"]["status"].upper())
        joined_replies = "\n".join(text for _, text in client.messages)
        self.assertIn("生成没有通过交付检查", joined_replies)
        self.assertIn("不会把内部记录当成果发给你", joined_replies)
        self.assertNotIn("后台", joined_replies)
        self.assertNotIn("中间测试和预览证据已准备好", joined_replies)

    def test_runnable_visual_assets_and_zip_allow_public_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project = root / "project"
            (project / "screenshots").mkdir(parents=True)
            (project / "generated").mkdir(parents=True)
            (project / "README.md").write_text("# VN helper\n", encoding="utf-8")
            (project / "main.py").write_text("print('vn helper')\n", encoding="utf-8")
            (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            (project / "TEST_REPORT.md").write_text("# Tests\n\ncommands_run:\n- python main.py\n", encoding="utf-8")
            (project / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: PASS\n", encoding="utf-8")
            screenshot = project / "screenshots" / "desktop_ui_screenshot.png"
            background = project / "generated" / "background_scene.png"
            sprite = project / "generated" / "character_sprite.png"
            screenshot.write_bytes(b"png")
            background.write_bytes(b"png")
            sprite.write_bytes(b"png")
            manifest = local_packager.package_project(project, startup_command="python main.py", screenshot_path=screenshot)
            session = vn_session("chat-pass")
            bridge.save_session(session_dir, session)
            client = FakeTelegramClient()

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")
            sent = bridge.send_delivery_from_manifest(client, "chat-pass", session_dir, session, manifest)

        self.assertTrue(gate["delivery_allowed"])
        self.assertTrue(any(item["kind"] == "package" for item in sent))
        self.assertTrue(any(caption == "界面截图" for _, _, caption in client.photos))
        self.assertTrue(any(caption == "生成背景" for _, _, caption in client.photos))
        self.assertTrue(any(caption == "生成立绘" for _, _, caption in client.photos))
        self.assertEqual([".zip"], sorted({path.suffix.lower() for _, path, _ in client.documents}))
        self.assertFalse(any(path.suffix.lower() in {".md", ".json", ".txt", ".log"} for _, path, _ in client.documents))

    def test_candidate_review_delivery_allows_candidate_bundle_without_final_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, bundle = make_candidate_review_fixture(root)

            gate = bridge.evaluate_candidate_review_delivery(project, bundle)

        self.assertTrue(gate["delivery_allowed"])
        self.assertEqual("ASK_USER_REVIEW_READY", gate["status"])
        self.assertEqual([], gate["missing"])
        self.assertEqual([], gate["rejected"])

    def test_candidate_review_delivery_does_not_mark_final_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project, bundle = make_candidate_review_fixture(root)
            session = bridge.default_session("candidate-review")
            session["active_run"] = {"id": "run-candidate-review", "status": "ask_user_review"}
            session["generation"] = {"status": "ask_user_review"}
            bridge.save_session(session_dir, session)
            client = FakeTelegramClient()

            result = bridge.emit_candidate_review_delivery(client, "candidate-review", session_dir, session, project, bundle)
            saved = bridge.load_session(session_dir, "candidate-review")

        self.assertEqual("sent", result["status"])
        self.assertTrue(saved["generation"]["ask_user_review_sent"])
        self.assertTrue(saved["generation"]["candidate_review_sent"])
        self.assertTrue(saved["generation"]["review_artifacts_sent"])
        self.assertEqual("ask_user_review", saved["generation"]["status"])
        self.assertNotIn("delivered", saved["generation"])
        self.assertNotIn("final_delivered", saved["generation"])
        self.assertNotIn("delivery_manifest_sent", saved["generation"])
        self.assertNotIn("PASS_FINAL", json.dumps(saved, ensure_ascii=False))
        self.assertFalse(any(path.name == "final_project_bundle.zip" for _, path, _ in client.documents))
        self.assertFalse(any(path.name == "delivery_manifest.json" for _, path, _ in client.documents))

    def test_candidate_review_delivery_rejects_bundle_containing_final_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, bundle = make_candidate_review_fixture(root, extra_bundle_files={"delivery_manifest.json": "{}"})

            gate = bridge.evaluate_candidate_review_delivery(project, bundle)

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("bundle_contains_delivery_manifest", gate["rejected"])

    def test_candidate_review_delivery_rejects_bundle_named_final_project_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, bundle = make_candidate_review_fixture(root, bundle_name="final_project_bundle.zip")

            gate = bridge.evaluate_candidate_review_delivery(project, bundle)

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("candidate_bundle_named_final_project_bundle", gate["rejected"])

    def test_public_final_gate_still_rejects_candidate_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, bundle = make_candidate_review_fixture(root)
            session = vn_session("candidate-final-gate")
            session["whiteboard"]["delivery_requirements"].append("演示视频")
            manifest = {
                "project_dir": str(project),
                "package_path": str(bundle),
                "quality_evidence": {
                    "test_report_found": True,
                    "test_report_has_commands": True,
                    "test_report_has_no_test_executed": False,
                },
            }

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("screenshots", gate["missing"])
        self.assertIn("videos", gate["missing"])

    def test_public_final_gate_rejects_candidate_bundle_even_without_media_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, bundle = make_candidate_review_fixture(root)
            (project / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json").write_text("{}", encoding="utf-8")
            session = bridge.default_session("candidate-final-gate-no-media")
            manifest = {
                "project_dir": str(project),
                "package_path": str(bundle),
                "quality_evidence": {
                    "test_report_found": True,
                    "test_report_has_commands": True,
                    "test_report_has_no_test_executed": False,
                },
            }

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("candidate_project_cannot_be_final", gate["missing"])
        self.assertIn("candidate_bundle_cannot_be_final_package", gate["missing"])

    def test_user_visible_candidate_review_message_is_honest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project, bundle = make_candidate_review_fixture(root)
            session = bridge.default_session("candidate-message")
            session["active_run"] = {"id": "run-candidate-message", "status": "ask_user_review"}
            session["generation"] = {"status": "ask_user_review"}
            bridge.save_session(session_dir, session)
            client = FakeTelegramClient()

            result = bridge.emit_candidate_review_delivery(client, "candidate-message", session_dir, session, project, bundle)
            message = "\n".join(text for _, text in client.messages)

        self.assertEqual("sent", result["status"])
        self.assertIn("候选审核包", message)
        self.assertIn("不是最终交付", message)
        self.assertIn("npm test 已通过", message)
        self.assertIn("screenshot_blocked.json", message)
        self.assertIn("video_blocked.json", message)
        self.assertIn("final_project_bundle.zip 尚未生成", message)
        self.assertIn("delivery_manifest.json 尚未生成", message)
        self.assertNotIn("PASS_FINAL", message)
        self.assertNotIn("final delivered", message.lower())
        self.assertNotIn("已最终交付", message)
        self.assertNotIn("delivery complete", message.lower())
        self.assertNotIn("BLOCKED", message)
        self.assertNotIn("gate", message.lower())


if __name__ == "__main__":
    unittest.main()
