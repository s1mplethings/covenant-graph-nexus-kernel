from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import pytest

pytestmark = pytest.mark.e2e

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.local_packager as local_packager
import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self, *, fail_documents: bool = False, fail_photos: bool = False) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.fail_documents = fail_documents
        self.fail_photos = fail_photos

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))

    def send_photo(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        if self.fail_photos:
            return False
        self.photos.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        if self.fail_documents:
            return False
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return True


def make_session(chat_id: str) -> dict:
    session = bridge.default_session(chat_id)
    session["whiteboard"]["project_summary"] = "本地项目生成系统，带 GUI 状态展示，像项目团队一样交付"
    session["whiteboard"]["delivery_requirements"] = ["交付可运行项目包", "真实截图", "测试报告"]
    session["active_run"] = {"id": f"run-{chat_id}", "status": "running", "created_at": bridge.now()}
    session["generation"] = {"status": "running", "driver": "api_provider_project_generation"}
    return session


def make_project(root: pathlib.Path, *, screenshot: bool = True, solid_screenshot: bool = False, test_report: bool = True) -> pathlib.Path:
    project = root / "project"
    (project / "screenshots").mkdir(parents=True)
    (project / "tests").mkdir(parents=True)
    (project / "README.md").write_text("# Local Generator\n\nRun with `python main.py`.\n", encoding="utf-8")
    (project / "main.py").write_text("print('local generator ready')\n", encoding="utf-8")
    (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (project / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("# Delivery\n\n可运行项目、截图和测试报告已整理。\n", encoding="utf-8")
    if test_report:
        (project / "TEST_REPORT.md").write_text(
            "# Tests\n\ncommands_run:\n- python -m pytest tests\n\nexit_code: 0\n\nstdout_summary:\n- 1 passed\n\nstderr_summary:\n- none\n\nverdict: PASS\n",
            encoding="utf-8",
        )
    if screenshot:
        target = project / "screenshots" / "ui_screenshot.png"
        if solid_screenshot:
            bridge.write_rgb_png(target, 160, 100, lambda x, y: (240, 240, 240))
        else:
            bridge.write_rgb_png(target, 160, 100, lambda x, y: ((x * 3) % 255, (y * 5) % 255, ((x + y) * 2) % 255))
    return project


def package_project(project: pathlib.Path) -> dict:
    screenshot = next((project / "screenshots").glob("*.png"), None)
    return local_packager.package_project(project, startup_command="python main.py", screenshot_path=screenshot if screenshot else None)


def test_ambiguous_model_mode_message_does_not_restart_active_run(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        client = FakeTelegramClient()
        bridge.save_session(session_dir, make_session("chat-e2e"))
        starts: list[str] = []

        def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
            session = bridge.load_session(session_dir_arg, chat_id)
            starts.append(session["active_run"]["id"])
            session["generation"]["status"] = "running"
            bridge.save_session(session_dir_arg, session)

        monkeypatch.setattr(bridge, "provider_user_message", lambda **kwargs: "")
        monkeypatch.setattr(bridge, "start_agent_generation", fake_start)

        bridge.handle_text(client, "chat-e2e", "走本地模型 + 开始做吧", session_dir, log_dir, "gpt-test", 60)
        bridge.handle_text(client, "chat-e2e", "还在做吗", session_dir, log_dir, "gpt-test", 60)
        bridge.handle_text(client, "chat-e2e", "还在做吗", session_dir, log_dir, "gpt-test", 60)

        saved = bridge.load_session(session_dir, "chat-e2e")
        assert starts == []
        assert saved["active_run"]["id"] == "run-chat-e2e"


def test_final_gate_rejects_missing_final_bundle() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        project = make_project(root)
        session = make_session("missing-package")
        manifest = {"project_dir": str(project), "startup_command": "python main.py", "quality_evidence": local_packager.collect_quality_evidence(project)}

        gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        assert not gate["delivery_allowed"]
        assert "production_candidate_provenance" in gate[
            "canonical_evidence_gate"
        ]["failures"]


def test_final_gate_rejects_missing_screenshot() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        project = make_project(root, screenshot=False)
        session = make_session("missing-screenshot")
        manifest = package_project(project)

        gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        assert not gate["delivery_allowed"]
        assert "production_candidate_provenance" in gate[
            "canonical_evidence_gate"
        ]["failures"]


def test_final_gate_rejects_missing_test_report() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        project = make_project(root, test_report=False)
        session = make_session("missing-test-report")
        manifest = package_project(project)

        gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        assert not gate["delivery_allowed"]
        assert "production_candidate_provenance" in gate[
            "canonical_evidence_gate"
        ]["failures"]


def test_final_gate_rejects_blank_or_solid_screenshot() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        project = make_project(root, solid_screenshot=True)
        session = make_session("solid-screenshot")
        manifest = package_project(project)

        gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        assert not gate["delivery_allowed"]
        assert "production_candidate_provenance" in gate[
            "canonical_evidence_gate"
        ]["failures"]


def test_incomplete_manifest_sends_no_public_artifacts() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        session_dir = root / "sessions"
        project = make_project(root)
        manifest = package_project(project)
        session = make_session("delivery-success")
        bridge.save_session(session_dir, session)
        client = FakeTelegramClient()

        sent = bridge.send_delivery_from_manifest(client, "delivery-success", session_dir, session, manifest)
        saved = bridge.load_session(session_dir, "delivery-success")
        assert sent == []
        assert not client.documents
        assert not client.photos
        assert saved["generation"]["status"] == "rework_blocked"
        visible = "\n".join(text for _, text in client.messages)
        assert "继续修复" in visible


def test_delivery_is_not_complete_when_telegram_document_send_fails() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        session_dir = root / "sessions"
        project = make_project(root)
        manifest = package_project(project)
        session = make_session("delivery-send-failed")
        bridge.save_session(session_dir, session)
        client = FakeTelegramClient(fail_documents=True)

        sent = bridge.send_delivery_from_manifest(client, "delivery-send-failed", session_dir, session, manifest)
        saved = bridge.load_session(session_dir, "delivery-send-failed")
        visible = "\n".join(text for _, text in client.messages)

        assert not any(item["kind"] == "package" for item in sent)
        assert saved["generation"]["status"] == "rework_blocked"
        assert saved["active_run"]["status"] == "rework_blocked"
        assert "继续修复" in visible
        assert "403" not in visible
        assert "quota" not in visible.lower()
        assert "provider" not in visible.lower()
