from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.local_packager as local_packager
import scripts.browser_visual_evidence as browser_visual_evidence
import scripts.customer_runtime_runner as customer_runtime_runner
import scripts.real_test_execution as real_test_execution
import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self, *, document_success: bool = True, photo_success: bool = True, video_success: bool = True) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.videos: list[tuple[str, pathlib.Path, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.document_success = document_success
        self.photo_success = photo_success
        self.video_success = video_success

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))

    def send_photo(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.photos.append((str(chat_id), pathlib.Path(path), caption))
        return self.photo_success

    def send_video(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.videos.append((str(chat_id), pathlib.Path(path), caption))
        return self.video_success

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return self.document_success


def vn_session(chat_id: str) -> dict:
    session = bridge.default_session(chat_id)
    session["whiteboard"]["project_summary"] = "本地可运行的 VN 项目助手，桌面界面，文件导出，能直接生成背景和立绘图片"
    session["whiteboard"]["delivery_requirements"] = ["交付项目包、界面截图、生成背景、生成立绘"]
    session["whiteboard"]["acceptance_criteria"] = ["NO TEST EXECUTED 不能公开交付"]
    session["active_run"] = {"id": f"run-{chat_id}-1", "status": "running", "created_at": bridge.now()}
    session["generation"] = {"status": "running"}
    return session


def requirement_session(chat_id: str, text: str) -> dict:
    session = bridge.default_session(chat_id)
    session["messages"].append({"role": "user", "text": text, "created_at": bridge.now()})
    session["whiteboard"]["delivery_requirements"] = [text]
    return session


def make_deliverable_project(root: pathlib.Path) -> tuple[pathlib.Path, dict]:
    project = root / "project"
    (project / "screenshots").mkdir(parents=True)
    (project / "generated").mkdir(parents=True)
    (project / "README.md").write_text("# VN helper\n", encoding="utf-8")
    (project / "TEST_PLAN.md").write_text("# Test plan\n", encoding="utf-8")
    (project / "index.html").write_text("<main><h1>VN helper</h1><button>Export</button></main>\n", encoding="utf-8")
    (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: PASS\n", encoding="utf-8")
    run_id = "run-public-gate"
    candidate_hash = "sha256:public-gate-candidate"
    commit_sha = "commit-public-gate"
    real_test_execution.run_tests(project, run_id=run_id, candidate_hash=candidate_hash, commit_sha=commit_sha)
    runtime = customer_runtime_runner.run(project, run_id=run_id, candidate_hash=candidate_hash, commit_sha=commit_sha)
    visual = browser_visual_evidence.run(project, runtime_ref=runtime["result_file"])
    if visual["status"] != "PASS":
        raise AssertionError(visual)
    screenshot = pathlib.Path(visual["screenshot_path"])
    background = project / "generated" / "background_scene.png"
    sprite = project / "generated" / "character_sprite.png"
    background.write_bytes(b"png")
    sprite.write_bytes(b"png")
    manifest = local_packager.package_project(project, startup_command="python -m http.server 8000", screenshot_path=screenshot)
    return project, manifest


def make_media_project_without_browser_evidence(root: pathlib.Path, *, media: str = "background") -> tuple[pathlib.Path, dict]:
    project = root / "project"
    (project / "generated").mkdir(parents=True)
    (project / "artifacts").mkdir(parents=True)
    (project / "README.md").write_text("# Media helper\n", encoding="utf-8")
    (project / "TEST_PLAN.md").write_text("# Test plan\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: PASS\n", encoding="utf-8")
    (project / "index.html").write_text("<main><h1>Media helper</h1></main>\n", encoding="utf-8")
    (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    run_id = "run-media-gate"
    candidate_hash = "sha256:media-gate-candidate"
    commit_sha = "commit-media-gate"
    real_test_execution.run_tests(project, run_id=run_id, candidate_hash=candidate_hash, commit_sha=commit_sha)
    customer_runtime_runner.run(project, run_id=run_id, candidate_hash=candidate_hash, commit_sha=commit_sha)
    if media == "background":
        (project / "generated" / "background_scene.png").write_bytes(b"real-background")
    elif media == "sprite":
        (project / "generated" / "character_sprite.png").write_bytes(b"real-sprite")
    elif media == "video":
        (project / "artifacts" / "workflow_demo.mp4").write_bytes(b"real-video")
    manifest = local_packager.package_project(project, startup_command="python -m http.server 8000")
    return project, manifest


def write_json(path: pathlib.Path, update: dict) -> None:
    import json

    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(update)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


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
        self.assertIn("需要继续修复", joined_replies)
        self.assertIn("完成必要修复后再重新判断", joined_replies)
        self.assertNotIn("后台", joined_replies)
        self.assertNotIn("中间测试和预览证据已准备好", joined_replies)

    def test_runnable_visual_assets_and_zip_allow_public_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project, manifest = make_deliverable_project(root)
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

    def test_test_execution_fail_blocks_even_with_package_and_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "test_execution.json", {"status": "FAIL", "verdict": "FAIL"})
            session = vn_session("chat-test-fail")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertEqual("NEEDS_REWORK", gate["status"])
        self.assertIn("test_execution", gate["canonical_evidence_gate"]["failures"])

    def test_customer_runtime_fail_blocks_even_with_package_and_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "customer_runtime.json", {"status": "FAIL"})
            session = vn_session("chat-runtime-fail")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertEqual("NEEDS_REWORK", gate["status"])
        self.assertIn("customer_runtime", gate["canonical_evidence_gate"]["failures"])

    def test_required_visual_fail_blocks_even_with_plain_png(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            (project / "screenshots" / "plain_existing.png").write_bytes(b"plain png")
            write_json(project / "visual_evidence.json", {"status": "FAIL"})
            session = vn_session("chat-visual-fail")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertEqual("NEEDS_REWORK", gate["status"])
        self.assertIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])

    def test_identity_mismatch_blocks_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "customer_runtime.json", {"candidate_hash": "sha256:other-candidate"})
            session = vn_session("chat-identity-fail")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(gate["canonical_evidence_gate"]["identity_consistent"])
        self.assertIn("identity_mismatch:candidate_hash", gate["canonical_evidence_gate"]["failures"])

    def test_test_identity_missing_run_id_blocks_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "test_execution.json", {"run_id": ""})
            session = vn_session("chat-test-identity-missing")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(gate["canonical_evidence_gate"]["identity_consistent"])
        self.assertIn("identity_missing:test_execution:run_id", gate["canonical_evidence_gate"]["failures"])

    def test_runtime_identity_missing_candidate_hash_blocks_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "customer_runtime.json", {"candidate_hash": "none"})
            session = vn_session("chat-runtime-identity-missing")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("identity_missing:customer_runtime:candidate_hash", gate["canonical_evidence_gate"]["failures"])

    def test_required_visual_identity_missing_commit_sha_blocks_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "visual_evidence.json", {"commit_sha": "null"})
            session = vn_session("chat-visual-identity-missing")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("identity_missing:visual_evidence:commit_sha", gate["canonical_evidence_gate"]["failures"])

    def test_all_required_identity_fields_blank_are_not_consistent(self) -> None:
        blank = {"run_id": "", "candidate_id": "", "candidate_hash": "", "commit_sha": ""}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "test_execution.json", blank)
            write_json(project / "customer_runtime.json", blank)
            write_json(project / "visual_evidence.json", blank)
            session = vn_session("chat-identity-blank")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(gate["canonical_evidence_gate"]["identity_consistent"])
        self.assertIn("identity_missing:test_execution:run_id", gate["canonical_evidence_gate"]["failures"])
        self.assertIn("identity_missing:customer_runtime:candidate_hash", gate["canonical_evidence_gate"]["failures"])
        self.assertIn("identity_missing:visual_evidence:commit_sha", gate["canonical_evidence_gate"]["failures"])

    def test_visual_identity_mismatch_blocks_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "visual_evidence.json", {"run_id": "run-other-visual"})
            session = vn_session("chat-visual-identity-mismatch")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("identity_mismatch:run_id", gate["canonical_evidence_gate"]["failures"])

    def test_adaptive_pass_final_cannot_override_canonical_failure(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "test_execution.json", {"status": "FAIL", "verdict": "FAIL"})
            session = vn_session("chat-agent-pass-final")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(called["agent"])
        self.assertEqual("NEEDS_REWORK", gate["status"])

    def test_deliver_with_warnings_cannot_override_canonical_failure(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "DELIVER_WITH_WARNINGS", "delivery_allowed": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "customer_runtime.json", {"status": "FAIL"})
            session = vn_session("chat-agent-warning")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(called["agent"])
        self.assertEqual("NEEDS_REWORK", gate["status"])

    def test_adaptive_pass_final_cannot_override_missing_identity(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json(project / "test_execution.json", {"run_id": " "})
            session = vn_session("chat-agent-identity-missing")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(called["agent"])
        self.assertIn("identity_missing:test_execution:run_id", gate["canonical_evidence_gate"]["failures"])

    def test_canonical_pass_allows_adaptive_judgment_to_continue(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "ASK_USER_REVIEW", "delivery_allowed": True, "is_final": False}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            session = vn_session("chat-canonical-pass")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertTrue(gate["canonical_evidence_gate"]["identity_consistent"])
        self.assertEqual("PASS", gate["canonical_evidence_gate"]["status"])
        self.assertTrue(called["agent"])

    def test_placeholder_screenshot_does_not_satisfy_requested_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            for path in (project / "screenshots").glob("*"):
                path.unlink()
            placeholder = project / "screenshots" / "fallback_mock_screenshot.png"
            placeholder.write_bytes(b"placeholder")
            manifest["artifacts"]["preview_evidence"] = [str(placeholder)]
            session = vn_session("chat-placeholder-screen")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertIn("visual_evidence:screenshot_hash", gate["missing"])
        self.assertIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])

    def test_background_only_does_not_require_browser_visual_but_requires_background_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            session = requirement_session("chat-background-only", "只需要生成背景 background")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

            for path in (project / "generated").glob("*background*"):
                path.unlink()
            missing_manifest = local_packager.package_project(project, startup_command="python -m http.server 8000")
            missing_gate = bridge.evaluate_public_delivery_gate(project, missing_manifest, session, phase="final")

        self.assertFalse(gate["browser_visual_required"])
        self.assertEqual("PASS", gate["canonical_evidence_gate"]["status"])
        self.assertNotIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])
        self.assertFalse(missing_gate["delivery_allowed"])
        self.assertIn("generated_background", missing_gate["missing"])

    def test_sprite_only_does_not_require_browser_visual_but_requires_sprite_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="sprite")
            session = requirement_session("chat-sprite-only", "只需要角色立绘 sprite")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

            for path in (project / "generated").glob("*sprite*"):
                path.unlink()
            missing_manifest = local_packager.package_project(project, startup_command="python -m http.server 8000")
            missing_gate = bridge.evaluate_public_delivery_gate(project, missing_manifest, session, phase="final")

        self.assertFalse(gate["browser_visual_required"])
        self.assertEqual("PASS", gate["canonical_evidence_gate"]["status"])
        self.assertNotIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])
        self.assertFalse(missing_gate["delivery_allowed"])
        self.assertIn("generated_sprite", missing_gate["missing"])

    def test_video_only_does_not_require_browser_visual_but_requires_video_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="video")
            session = requirement_session("chat-video-only", "只需要演示视频 video")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

            for path in (project / "artifacts").glob("*.mp4"):
                path.unlink()
            missing_manifest = local_packager.package_project(project, startup_command="python -m http.server 8000")
            missing_gate = bridge.evaluate_public_delivery_gate(project, missing_manifest, session, phase="final")

        self.assertFalse(gate["browser_visual_required"])
        self.assertEqual("PASS", gate["canonical_evidence_gate"]["status"])
        self.assertNotIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])
        self.assertFalse(missing_gate["delivery_allowed"])
        self.assertIn("videos", missing_gate["missing"])

    def test_screenshot_request_requires_canonical_browser_visual_even_with_plain_png(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            (project / "screenshots").mkdir(exist_ok=True)
            (project / "screenshots" / "plain_existing.png").write_bytes(b"plain png")
            manifest = local_packager.package_project(project, startup_command="python -m http.server 8000")
            session = requirement_session("chat-screenshot-required", "需要界面截图 screenshot")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertTrue(gate["browser_visual_required"])
        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])

    def test_checkpoint_canonical_failure_short_circuits_adaptive_agent(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "ASK_USER_REVIEW", "delivery_allowed": True, "is_final": False}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            write_json(project / "test_execution.json", {"status": "FAIL", "verdict": "FAIL"})
            session = requirement_session("chat-checkpoint-fail", "只需要生成背景")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="checkpoint", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(called["agent"])
        self.assertEqual("NEEDS_REWORK", gate["status"])

    def test_checkpoint_canonical_pass_without_final_zip_can_ask_user_review(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {
                "verdict": "ASK_USER_REVIEW",
                "delivery_allowed": True,
                "is_final": False,
                "confidence": 0.8,
                "reasons": ["checkpoint review"],
                "user_visible_warnings": [],
                "required_repairs": [],
                "can_send_artifacts": [],
                "must_not_claim": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            package = pathlib.Path(str(manifest["package_path"]))
            package.unlink()
            manifest["package_path"] = ""
            manifest["artifacts"]["delivery_zip"] = ""
            session = requirement_session("chat-checkpoint-pass", "只需要生成背景")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="checkpoint", agent=agent)

        self.assertTrue(called["agent"])
        self.assertTrue(gate["delivery_allowed"])
        self.assertFalse(gate["is_final"])
        self.assertEqual("ASK_USER_REVIEW", gate["verdict"])

    def test_placeholder_background_does_not_satisfy_requested_background(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            for path in (project / "generated").glob("*"):
                path.unlink()
            placeholder = project / "generated" / "fallback_mock_background.png"
            placeholder.write_bytes(b"placeholder")
            manifest["artifacts"]["preview_evidence"] = [str(placeholder)]
            session = vn_session("chat-placeholder-bg")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertIn("generated_background", gate["missing"])
        self.assertIn("generated_images", gate["missing"])
        self.assertTrue(any("Requested real delivery evidence is missing" in item for item in gate["warnings"]))

    def test_delivery_allowed_but_no_artifact_sent_does_not_mark_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project, manifest = make_deliverable_project(root)
            session = vn_session("chat-empty-send")
            bridge.save_session(session_dir, session)
            original_gate = bridge.evaluate_public_delivery_gate
            bridge.evaluate_public_delivery_gate = lambda *args, **kwargs: {
                "verdict": "ASK_USER_REVIEW",
                "status": "ASK_USER_REVIEW",
                "delivery_allowed": True,
                "is_final": False,
                "can_send_artifacts": [],
                "missing": [],
                "warnings": [],
            }
            try:
                sent = bridge.send_delivery_from_manifest(FakeTelegramClient(), "chat-empty-send", session_dir, session, manifest)
            finally:
                bridge.evaluate_public_delivery_gate = original_gate
            saved = bridge.load_session(session_dir, "chat-empty-send")

        self.assertEqual([], sent)
        self.assertNotIn(saved["generation"]["status"], {"delivered", "delivered_with_warnings"})
        self.assertEqual("no_public_artifacts_sent", saved["generation"]["delivery_gate"]["delivery_send_diagnostic"]["reason"])

    def test_final_delivery_requires_package_send_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project, manifest = make_deliverable_project(root)
            session = vn_session("chat-package-fail")
            bridge.save_session(session_dir, session)
            client = FakeTelegramClient(document_success=False)

            sent = bridge.send_delivery_from_manifest(client, "chat-package-fail", session_dir, session, manifest)
            saved = bridge.load_session(session_dir, "chat-package-fail")

        self.assertFalse(any(item["kind"] == "package" for item in sent))
        self.assertNotIn(saved["generation"]["status"], {"delivered", "delivered_with_warnings"})
        self.assertEqual("final_package_send_failed", saved["generation"]["delivery_gate"]["delivery_send_diagnostic"]["reason"])


if __name__ == "__main__":
    unittest.main()
