from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
