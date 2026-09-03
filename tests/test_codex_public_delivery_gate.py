from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import pytest

pytestmark = pytest.mark.codex

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.local_packager as local_packager
import scripts.browser_visual_evidence as browser_visual_evidence
import scripts.canonical_delivery_manifest as canonical_delivery_manifest
import scripts.canonical_evidence_hash as canonical_evidence_hash
import scripts.customer_runtime_runner as customer_runtime_runner
import scripts.real_test_execution as real_test_execution
import scripts.production_candidate_provenance as production_candidate_provenance
import scripts.provider_causal_trace as provider_causal_trace
import scripts.codex_conversation as bridge


@pytest.fixture(autouse=True)
def _allow_test_production_candidate_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
):
    temporary_root = pathlib.Path(tempfile.gettempdir()).resolve()
    monkeypatch.setattr(
        production_candidate_provenance, "PRODUCTION_CANDIDATE_ROOT", temporary_root
    )
    monkeypatch.setattr(
        bridge.production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        temporary_root,
    )
    monkeypatch.setattr(
        bridge.provider_causal_trace.production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        temporary_root,
    )
    monkeypatch.setattr(bridge, "DEFAULT_MEMORY_DIR", tmp_path / "project_memory")
    monkeypatch.setenv(
        "CGNK_LOCAL_STUDIO_CONVERSATION_ROOT",
        str(tmp_path / "conversations"),
    )


def bind_test_production_provenance(
    root: pathlib.Path,
    project: pathlib.Path,
    *,
    run_id: str,
    candidate_id: str,
    commit_sha: str,
) -> dict:
    run_root = root / "production_run"
    run_root.mkdir(parents=True, exist_ok=True)
    provider_staging = root / "provider_staging"
    provider_staging.mkdir(parents=True, exist_ok=True)
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
    provider_result = run_root / "provider_generation_result.json"
    provider_result.write_text(
        (
            '{"status":"PASS","provider_semantic_review":{"status":"pass"},'
            f'"generated_files":{json.dumps(sorted(generated_files))}'
            "}"
        ),
        encoding="utf-8",
    )
    identity = {
        "run_id": run_id,
        "candidate_id": candidate_id,
        "commit_sha": commit_sha,
    }
    receipts = {}
    entry_started = provider_causal_trace.now()
    receipts["production_entry"] = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="production_entry",
        run_id=run_id,
        candidate_id=candidate_id,
        commit_sha=commit_sha,
        candidate_root=project,
        started_at=entry_started,
        finished_at=provider_causal_trace.now(),
    )
    generation_started = provider_causal_trace.now()
    request_capture = provider_causal_trace.begin_provider_request(
        candidate_dir=project,
        production_run_dir=run_root,
        identity=identity,
        goal="public delivery gate canonical provider fixture",
        model="reproducible-provider",
        request_started_at=generation_started,
    )
    capture = provider_causal_trace.consume_provider_response(
        candidate_dir=project,
        provider_staging_dir=provider_staging,
        production_run_dir=run_root,
        provider_result_path=provider_result,
        identity=identity,
        provider_request_capture=request_capture,
        response_received_at=provider_causal_trace.now(),
    )
    provider_document = json.loads(
        provider_result.read_text(encoding="utf-8")
    )
    provider_document.update(
        {
            "project_dir": str(project.resolve()),
            "provider_staging_dir": str(provider_staging.resolve()),
            "provider_causal_artifacts": {
                key: str(value) if isinstance(value, pathlib.Path) else value
                for key, value in capture.items()
            },
        }
    )
    provider_result.write_text(
        json.dumps(provider_document, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    manifest_hash = canonical_evidence_hash.canonical_json_hash(
        {
            "candidate_source_manifest": canonical_evidence_hash.candidate_source_manifest(
                project
            )
        },
        (),
    )
    provider_ref = {
        "role": "provider_generation_result",
        "ref": str(provider_result.resolve()),
        "hash": canonical_evidence_hash.sha256_file(provider_result),
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
    receipts["provider_generation"] = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="provider_generation",
        run_id=run_id,
        candidate_id=candidate_id,
        commit_sha=commit_sha,
        candidate_root=project,
        started_at=generation_started,
        finished_at=provider_causal_trace.now(),
        artifact_refs=[provider_ref, *causal_refs],
    )
    validation_started = provider_causal_trace.now()
    receipts["provider_validation"] = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="provider_validation",
        run_id=run_id,
        candidate_id=candidate_id,
        commit_sha=commit_sha,
        candidate_root=project,
        started_at=validation_started,
        finished_at=provider_causal_trace.now(),
        artifact_refs=[provider_ref, *causal_refs],
    )
    post_build_started = provider_causal_trace.now()
    receipts["post_build"] = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="post_build",
        run_id=run_id,
        candidate_id=candidate_id,
        commit_sha=commit_sha,
        candidate_root=project,
        started_at=post_build_started,
        finished_at=provider_causal_trace.now(),
        candidate_hash=candidate_hash,
        candidate_source_manifest_hash=manifest_hash,
    )
    provenance = production_candidate_provenance.produce(
        project,
        run_root,
        run_id=run_id,
        candidate_id=candidate_id,
        commit_sha=commit_sha,
        stage_receipts=receipts,
        provider_result_ref=provider_result,
    )
    provider_causal_trace.finalize(
        candidate_dir=project,
        production_run_dir=run_root,
        identity=identity,
        causal_capture=capture,
        production_provenance_ref=provenance["provenance_ref"],
    )
    return provenance


def write_real_png(path: pathlib.Path, width: int = 160, height: int = 120) -> None:
    bridge.write_rgb_png(path, width, height, lambda x, y: ((x * 3 + y) % 255, (x + y * 5) % 255, (x * 7 + y * 2) % 255))


def write_real_mp4(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x64:rate=10:duration=0.6",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


class FakeCodexConversation:
    def __init__(self, *, document_success: bool = True, photo_success: bool = True, video_success: bool = True) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.videos: list[tuple[str, pathlib.Path, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.document_success = document_success
        self.photo_success = photo_success
        self.video_success = video_success
        self._turn_id = 100

    def _result(self, conversation_id: int | str, field: str) -> dict:
        self._turn_id += 1
        return {
            "ok": True,
            "result": {
                "turn_id": self._turn_id,
                "conversation_id": conversation_id,
                "artifact_id": f"{field}-{self._turn_id}",
                "artifact_unique_id": f"unique-{field}-{self._turn_id}",
            },
        }

    def send_message(self, conversation_id: int | str, text: str) -> bool:
        self.messages.append((str(conversation_id), text))
        return True

    def send_chat_action(self, conversation_id: int | str, action: str) -> None:
        self.actions.append((str(conversation_id), action))

    def send_photo(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> dict | bool:
        self.photos.append((str(conversation_id), pathlib.Path(path), caption))
        return self._result(conversation_id, "photo") if self.photo_success else False

    def send_video(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> dict | bool:
        self.videos.append((str(conversation_id), pathlib.Path(path), caption))
        return self._result(conversation_id, "video") if self.video_success else False

    def send_document(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> dict | bool:
        self.documents.append((str(conversation_id), pathlib.Path(path), caption))
        return self._result(conversation_id, "document") if self.document_success else False


def vn_session(conversation_id: str) -> dict:
    session = bridge.default_session(conversation_id)
    session["whiteboard"]["project_summary"] = "本地可运行的 VN 项目助手，桌面界面，文件导出，能直接生成背景和立绘图片"
    session["whiteboard"]["delivery_requirements"] = ["交付项目包、界面截图、生成背景、生成立绘"]
    session["whiteboard"]["acceptance_criteria"] = ["NO TEST EXECUTED 不能公开交付"]
    session["active_run"] = {"id": f"run-{conversation_id}-1", "status": "running", "created_at": bridge.now()}
    session["generation"] = {"status": "running"}
    return session


def requirement_session(conversation_id: str, text: str) -> dict:
    session = bridge.default_session(conversation_id)
    session["messages"].append({"role": "user", "text": text, "created_at": bridge.now()})
    session["whiteboard"]["delivery_requirements"] = [text]
    return session


def make_deliverable_project(root: pathlib.Path, extra_product_files: dict[str, bytes | str] | None = None) -> tuple[pathlib.Path, dict]:
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
    background = project / "generated" / "background_scene.png"
    sprite = project / "generated" / "character_sprite.png"
    write_real_png(background, 160, 120)
    write_real_png(sprite, 128, 160)
    for relative, content in (extra_product_files or {}).items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    run_id = "run-public-gate"
    candidate_id = "project"
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    commit_sha = "commit-public-gate"
    provenance = bind_test_production_provenance(
        root,
        project,
        run_id=run_id,
        candidate_id=candidate_id,
        commit_sha=commit_sha,
    )
    provenance_args = {
        "production_provenance_ref": provenance["provenance_ref"],
        "production_provenance_hash": provenance["provenance_hash"],
    }
    real_test_execution.run_tests(
        project,
        run_id=run_id,
        candidate_id=candidate_id,
        candidate_hash=candidate_hash,
        commit_sha=commit_sha,
        **provenance_args,
    )
    runtime = {}
    visual = {}
    for _attempt in range(3):
        runtime = customer_runtime_runner.run(
            project,
            run_id=run_id,
            candidate_id=candidate_id,
            candidate_hash=candidate_hash,
            commit_sha=commit_sha,
            **provenance_args,
            live_consumer=browser_visual_evidence.capture_live_runtime,
            browser_capture_required=True,
        )
        visual = browser_visual_evidence.finalize_evidence(
            project,
            runtime_result=runtime,
            capture_receipt=runtime["browser_capture_receipt"],
            required=True,
        )
        if visual["status"] == "PASS" or "ERR_UNSAFE_PORT" not in str(visual.get("capture_error", "")):
            break
    if visual["status"] != "PASS":
        raise AssertionError(visual)
    screenshot = pathlib.Path(visual["screenshot_path"])
    manifest = local_packager.package_project(
        project,
        startup_command="python -m http.server 8000",
        screenshot_path=screenshot,
        visual_required=True,
        media_required=True,
    )
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
    if media == "background":
        write_real_png(project / "generated" / "background_scene.png", 160, 120)
    elif media == "sprite":
        write_real_png(project / "generated" / "character_sprite.png", 128, 160)
    elif media == "video":
        write_real_mp4(project / "artifacts" / "workflow_demo.mp4")
    elif media == "fake_background":
        (project / "generated" / "background_scene.png").write_bytes(b"real-background")
    elif media == "fake_sprite":
        (project / "generated" / "character_sprite.png").write_bytes(b"real-sprite")
    elif media == "fake_video":
        (project / "artifacts" / "workflow_demo.mp4").write_bytes(b"real-video")
    elif media == "placeholder_background":
        write_real_png(project / "generated" / "fallback_mock_background.png", 160, 120)
    run_id = "run-media-gate"
    candidate_id = "project"
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    commit_sha = "commit-media-gate"
    provenance = bind_test_production_provenance(
        root,
        project,
        run_id=run_id,
        candidate_id=candidate_id,
        commit_sha=commit_sha,
    )
    provenance_args = {
        "production_provenance_ref": provenance["provenance_ref"],
        "production_provenance_hash": provenance["provenance_hash"],
    }
    real_test_execution.run_tests(
        project,
        run_id=run_id,
        candidate_id=candidate_id,
        candidate_hash=candidate_hash,
        commit_sha=commit_sha,
        **provenance_args,
    )
    customer_runtime_runner.run(
        project,
        run_id=run_id,
        candidate_id=candidate_id,
        candidate_hash=candidate_hash,
        commit_sha=commit_sha,
        **provenance_args,
    )
    manifest = local_packager.package_project(
        project,
        startup_command="python -m http.server 8000",
        media_required=media in {"background", "sprite", "video", "fake_background", "fake_sprite", "fake_video", "placeholder_background"},
    )
    return project, manifest


def write_json(path: pathlib.Path, update: dict) -> None:
    import json

    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(update)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def write_json_with_artifact_hash(path: pathlib.Path, update: dict) -> None:
    import json

    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(update)
    doc["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(doc, ("artifact_hash",))
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


class CodexConversationPublicDeliveryGateTests(unittest.TestCase):
    def test_final_delivery_requires_canonical_receipt_not_bare_true(self) -> None:
        class BareTrueCodexConversation(FakeCodexConversation):
            def _result(self, conversation_id: int | str, field: str) -> bool:
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project, manifest = make_deliverable_project(root)
            session = vn_session("chat-receipt-missing")
            bridge.save_session(session_dir, session)
            sent = bridge.send_delivery_from_manifest(
                BareTrueCodexConversation(),
                "chat-receipt-missing",
                session_dir,
                session,
                manifest,
            )
            saved = bridge.load_session(session_dir, "chat-receipt-missing")
            receipt = project / "delivery_receipt.json"
            receipt_exists = receipt.is_file()

        self.assertFalse(any(item.get("kind") == "package" for item in sent))
        self.assertTrue(receipt_exists)
        self.assertNotEqual("delivered", saved["generation"]["status"])

    def test_readme_only_no_test_executed_blocks_public_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("# VN helper\n", encoding="utf-8")
            session = vn_session("chat-block")
            bridge.save_session(session_dir, session)
            client = FakeCodexConversation()
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
            client = FakeCodexConversation()

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
        self.assertIn(
            "production_candidate_provenance",
            gate["canonical_evidence_gate"]["failures"],
        )

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

    def test_unclean_customer_runtime_evidence_short_circuits_adaptive_agent(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json_with_artifact_hash(project / "customer_runtime.json", {"cwd": str(project.resolve())})
            session = vn_session("chat-runtime-clean-fail")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(called["agent"])
        self.assertEqual("NEEDS_REWORK", gate["status"])
        self.assertIn("customer_runtime", gate["canonical_evidence_gate"]["failures"])
        self.assertIn("customer_runtime:cwd", gate["canonical_evidence_gate"]["missing"])

    def test_visual_runtime_binding_mismatch_short_circuits_adaptive_agent(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            write_json_with_artifact_hash(project / "visual_evidence.json", {"runtime_url": "http://127.0.0.1:1/"})
            session = vn_session("chat-visual-binding-fail")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(called["agent"])
        self.assertEqual("NEEDS_REWORK", gate["status"])
        self.assertIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])
        self.assertIn("visual_evidence:runtime_url", gate["canonical_evidence_gate"]["missing"])

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

        self.assertIn(
            "production_candidate_provenance",
            gate["canonical_evidence_gate"]["failures"],
        )
        self.assertIn(
            "candidate_source_manifest_mismatch",
            gate["canonical_evidence_gate"]["failures"],
        )

    def test_background_only_does_not_require_browser_visual_but_requires_background_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            session = requirement_session("chat-background-only", "只需要生成背景 background")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

            missing_project, missing_manifest = make_media_project_without_browser_evidence(root / "missing-bg", media="none")
            missing_gate = bridge.evaluate_public_delivery_gate(missing_project, missing_manifest, session, phase="final")

        self.assertFalse(gate["browser_visual_required"])
        self.assertEqual("PASS", gate["canonical_evidence_gate"]["status"])
        self.assertNotIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])
        self.assertFalse(missing_gate["delivery_allowed"])
        self.assertIn("generated_background", missing_gate["missing"])
        self.assertEqual("PASS", gate["media_validation"]["overall_status"])

    def test_sprite_only_does_not_require_browser_visual_but_requires_sprite_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="sprite")
            session = requirement_session("chat-sprite-only", "只需要角色立绘 sprite")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

            missing_project, missing_manifest = make_media_project_without_browser_evidence(root / "missing-sprite", media="none")
            missing_gate = bridge.evaluate_public_delivery_gate(missing_project, missing_manifest, session, phase="final")

        self.assertFalse(gate["browser_visual_required"])
        self.assertEqual("PASS", gate["canonical_evidence_gate"]["status"])
        self.assertNotIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])
        self.assertFalse(missing_gate["delivery_allowed"])
        self.assertIn("generated_sprite", missing_gate["missing"])
        self.assertEqual("PASS", gate["media_validation"]["overall_status"])

    def test_video_only_does_not_require_browser_visual_but_requires_video_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="video")
            session = requirement_session("chat-video-only", "只需要演示视频 video")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

            missing_project, missing_manifest = make_media_project_without_browser_evidence(root / "missing-video", media="none")
            missing_gate = bridge.evaluate_public_delivery_gate(missing_project, missing_manifest, session, phase="final")

        self.assertFalse(gate["browser_visual_required"])
        self.assertEqual("PASS", gate["canonical_evidence_gate"]["status"])
        self.assertNotIn("visual_evidence", gate["canonical_evidence_gate"]["failures"])
        self.assertFalse(missing_gate["delivery_allowed"])
        self.assertIn("videos", missing_gate["missing"])
        self.assertEqual("PASS", gate["media_validation"]["overall_status"])

    def test_fake_background_media_blocks_before_adaptive_agent(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="fake_background")
            session = requirement_session("chat-fake-bg", "只需要生成背景 background")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertFalse(called["agent"])
        self.assertIn("generated_background", gate["missing"])
        self.assertTrue(gate["media_validation"]["rejected_assets"])

    def test_fake_sprite_media_blocks_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="fake_sprite")
            session = requirement_session("chat-fake-sprite", "只需要角色立绘 sprite")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("generated_sprite", gate["missing"])
        self.assertTrue(gate["media_validation"]["rejected_assets"])

    def test_fake_video_media_blocks_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="fake_video")
            session = requirement_session("chat-fake-video", "只需要演示视频 video")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("videos", gate["missing"])
        self.assertTrue(gate["media_validation"]["rejected_assets"])

    def test_media_tamper_after_manifest_blocks_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            (project / "generated" / "background_scene.png").write_bytes(b"tampered")
            session = requirement_session("chat-media-tamper", "只需要生成背景 background")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

        self.assertFalse(gate["delivery_allowed"])
        self.assertIn(
            "production_candidate_provenance",
            gate["canonical_evidence_gate"]["failures"],
        )
        self.assertIn(
            "candidate_source_manifest_mismatch",
            gate["canonical_evidence_gate"]["failures"],
        )

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
        self.assertIn(
            "production_candidate_provenance",
            gate["canonical_evidence_gate"]["failures"],
        )

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

    def test_source_tamper_after_canonical_evidence_short_circuits_adaptive_agent(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True, "is_final": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            (project / "index.html").write_text("<main><h1>Tampered after evidence</h1></main>\n", encoding="utf-8")
            session = vn_session("chat-source-tamper")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertEqual("NEEDS_REWORK", gate["status"])
        self.assertFalse(called["agent"])
        failures = gate["canonical_evidence_gate"]["failures"]
        self.assertIn("production_candidate_provenance", failures)
        self.assertIn("candidate_source_manifest_mismatch", failures)

    def test_export_product_tamper_after_canonical_evidence_short_circuits_adaptive_agent(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True, "is_final": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root, {"export/project.json": '{"version": 1}\n'})
            (project / "export" / "project.json").write_text('{"version": 2}\n', encoding="utf-8")
            session = vn_session("chat-export-tamper")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertEqual("NEEDS_REWORK", gate["status"])
        self.assertFalse(gate["is_final"])
        self.assertFalse(called["agent"])
        self.assertIn(
            "production_candidate_provenance",
            gate["canonical_evidence_gate"]["failures"],
        )
        self.assertIn(
            "candidate_source_manifest_mismatch",
            gate["canonical_evidence_gate"]["failures"],
        )

    def test_generated_image_product_tamper_after_canonical_evidence_short_circuits_adaptive_agent(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True, "is_final": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root, {"media/generated_images/final_background.png": b"image-v1"})
            (project / "media" / "generated_images" / "final_background.png").write_bytes(b"image-v2")
            session = vn_session("chat-generated-image-tamper")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(gate["delivery_allowed"])
        self.assertEqual("NEEDS_REWORK", gate["status"])
        self.assertFalse(gate["is_final"])
        self.assertFalse(called["agent"])
        self.assertIn(
            "production_candidate_provenance",
            gate["canonical_evidence_gate"]["failures"],
        )
        self.assertIn(
            "candidate_source_manifest_mismatch",
            gate["canonical_evidence_gate"]["failures"],
        )

    def test_placeholder_background_does_not_satisfy_requested_background(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="placeholder_background")
            session = requirement_session("chat-placeholder-bg", "只需要生成背景图片 background image")

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
                "browser_visual_required": True,
            }
            try:
                sent = bridge.send_delivery_from_manifest(FakeCodexConversation(), "chat-empty-send", session_dir, session, manifest)
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
            client = FakeCodexConversation(document_success=False)

            sent = bridge.send_delivery_from_manifest(client, "chat-package-fail", session_dir, session, manifest)
            saved = bridge.load_session(session_dir, "chat-package-fail")

        self.assertFalse(any(item["kind"] == "package" for item in sent))
        self.assertNotIn(saved["generation"]["status"], {"delivered", "delivered_with_warnings"})
        self.assertEqual("final_package_send_failed", saved["generation"]["delivery_gate"]["delivery_send_diagnostic"]["reason"])

    def test_package_tamper_short_circuits_adaptive_agent(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True, "is_final": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            package = pathlib.Path(manifest["package_path"])
            package.write_bytes(package.read_bytes() + b"tampered")
            session = requirement_session("chat-package-tamper", "只需要生成背景 background")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertFalse(called["agent"])
        self.assertFalse(gate["delivery_allowed"])
        self.assertEqual("canonical_delivery_manifest", gate["judgment_source"])
        self.assertIn("package_sha256_mismatch", gate["canonical_package_inspection"]["failures"])

    def test_gate_and_sender_do_not_modify_frozen_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            manifest_path = pathlib.Path(manifest["manifest_path"])
            frozen = manifest_path.read_bytes()
            session = requirement_session("chat-frozen-manifest", "只需要生成背景 background")
            bridge.save_session(session_dir, session)

            gate = bridge.evaluate_public_delivery_gate(
                project,
                manifest,
                session,
                phase="final",
                agent=lambda _messages: {
                    "verdict": "ASK_USER_REVIEW",
                    "delivery_allowed": True,
                    "is_final": False,
                    "confidence": 0.9,
                    "reasons": [],
                    "user_visible_warnings": [],
                    "required_repairs": [],
                    "can_send_artifacts": ["package", "background"],
                    "must_not_claim": [],
                },
            )
            self.assertEqual(frozen, manifest_path.read_bytes())
            original_gate = bridge.evaluate_public_delivery_gate
            bridge.evaluate_public_delivery_gate = lambda *args, **kwargs: gate
            try:
                bridge.send_delivery_from_manifest(
                    FakeCodexConversation(),
                    "chat-frozen-manifest",
                    session_dir,
                    session,
                    manifest,
                )
            finally:
                bridge.evaluate_public_delivery_gate = original_gate

            self.assertEqual(frozen, manifest_path.read_bytes())
            self.assertEqual(
                "PASS",
                canonical_delivery_manifest.inspect_canonical_delivery_manifest(project, manifest)["status"],
            )

    def test_package_replaced_after_inspector_is_not_sent(self) -> None:
        class ReplacingClient(FakeCodexConversation):
            def __init__(self, package: pathlib.Path) -> None:
                super().__init__()
                self.package = package

            def send_chat_action(self, conversation_id: int | str, action: str) -> None:
                super().send_chat_action(conversation_id, action)
                if action == "upload_document":
                    self.package.write_bytes(self.package.read_bytes() + b"replaced-before-send")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            session = requirement_session("chat-send-race", "只需要生成背景 background")
            bridge.save_session(session_dir, session)
            package = pathlib.Path(manifest["package_path"])
            client = ReplacingClient(package)

            sent = bridge.send_delivery_from_manifest(client, "chat-send-race", session_dir, session, manifest)
            saved = bridge.load_session(session_dir, "chat-send-race")

        self.assertFalse(client.documents)
        self.assertFalse(any(item["kind"] == "package" for item in sent))
        self.assertNotIn(saved["generation"]["status"], {"delivered", "delivered_with_warnings"})
        self.assertEqual(
            "package_changed_before_send",
            saved["generation"]["delivery_gate"]["delivery_send_diagnostic"]["reason"],
        )

    def test_unchanged_approved_package_is_sent_once_with_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project, manifest = make_media_project_without_browser_evidence(root, media="background")
            session = requirement_session("chat-send-bound", "只需要生成背景 background")
            bridge.save_session(session_dir, session)
            client = FakeCodexConversation()

            sent = bridge.send_delivery_from_manifest(client, "chat-send-bound", session_dir, session, manifest)
            package_documents = [item for item in client.documents if item[1].name == "final_project_bundle.zip"]
            sent_package_hash = canonical_evidence_hash.sha256_file(package_documents[0][1]) if package_documents else ""

        self.assertEqual(1, len(package_documents))
        self.assertEqual(pathlib.Path(manifest["package_path"]).resolve(), package_documents[0][1].resolve())
        self.assertTrue(any(item["kind"] == "package" for item in sent))
        self.assertEqual(manifest["package_sha256"], sent_package_hash)

    def test_visual_evidence_hash_tamper_blocks_before_adaptive_agent(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {"verdict": "PASS_FINAL", "delivery_allowed": True, "is_final": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_deliverable_project(root)
            changed = dict(manifest)
            changed["visual_evidence_hash"] = "sha256:" + "0" * 64
            changed["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(changed, ("artifact_hash",))
            pathlib.Path(manifest["manifest_path"]).write_text(
                __import__("json").dumps(changed, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            session = vn_session("chat-visual-manifest-hash")

            gate = bridge.evaluate_public_delivery_gate(project, changed, session, phase="final", agent=agent)

        self.assertFalse(called["agent"])
        self.assertFalse(gate["delivery_allowed"])
        self.assertIn("visual_evidence_hash", gate["canonical_package_inspection"]["failures"])

    def test_nonvisual_project_without_preview_reaches_adaptive_gate(self) -> None:
        called = {"agent": False}

        def agent(_messages):
            called["agent"] = True
            return {
                "verdict": "ASK_USER_REVIEW",
                "delivery_allowed": True,
                "is_final": False,
                "confidence": 0.9,
                "reasons": [],
                "user_visible_warnings": [],
                "required_repairs": [],
                "can_send_artifacts": ["package"],
                "must_not_claim": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project, manifest = make_media_project_without_browser_evidence(root, media="none")
            session = requirement_session("chat-nonvisual-package", "JSON API 后台服务，返回结构化数据")

            gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final", agent=agent)

        self.assertEqual("PASS", manifest["status"], manifest)
        self.assertFalse(manifest["quality_evidence"]["preview_evidence_found"])
        self.assertTrue(called["agent"])
        self.assertEqual("PASS", gate["canonical_package_inspection"]["status"])


if __name__ == "__main__":
    unittest.main()
