from __future__ import annotations

import json
import base64
import pathlib
import sys
import tempfile
import time
from datetime import datetime
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import canonical_delivery_manifest
from scripts import canonical_evidence_hash
from scripts import canonical_user_review
from scripts import browser_visual_evidence
from scripts import customer_runtime_runner
from scripts import local_packager
from scripts import real_test_execution
from scripts import telegram_live_bridge as bridge
from scripts import production_candidate_provenance
from tests.test_telegram_public_delivery_gate import (
    bind_test_production_provenance,
)


@pytest.fixture(autouse=True)
def _allow_review_test_production_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
):
    temporary_root = pathlib.Path(tempfile.gettempdir()).resolve()
    monkeypatch.setattr(
        production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        temporary_root,
    )
    monkeypatch.setattr(
        bridge.production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        temporary_root,
    )
    monkeypatch.setattr(bridge, "DEFAULT_MEMORY_DIR", tmp_path / "project_memory")
    monkeypatch.setenv(
        "CGNK_LOCAL_STUDIO_CONVERSATION_ROOT",
        str(tmp_path / "conversations"),
    )


TEST_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGP4z8DAwMDAxMDAwMAAAAwAAf4B"
    "9pYAAAAASUVORK5CYII="
)


class FakeClient:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, _chat_id, text):
        self.messages.append(text)
        return True

    def send_chat_action(self, _chat_id, _action):
        return None


def make_project(root: pathlib.Path) -> pathlib.Path:
    project = root / "project"
    project.mkdir()
    (project / "index.html").write_text("<main><h1>Review target</h1></main>\n", encoding="utf-8")
    (project / "README.md").write_text("# Review target\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("# Delivery\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_app.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    identity = {
        "run_id": "run-review",
        "candidate_id": "candidate-review",
        "candidate_hash": candidate_hash,
        "commit_sha": "commit-review",
    }
    provenance = bind_test_production_provenance(
        root,
        project,
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
    )
    provenance_args = {
        "production_provenance_ref": provenance["provenance_ref"],
        "production_provenance_hash": provenance["provenance_hash"],
    }
    assert (
        real_test_execution.run_tests(
            project, **identity, **provenance_args
        )["status"]
        == "PASS"
    )
    assert (
        customer_runtime_runner.run(
            project, **identity, **provenance_args
        )["status"]
        == "PASS"
    )
    return project


def request_for(project: pathlib.Path, chat_id: str = "group-1") -> dict:
    request = canonical_user_review.create_review_request_snapshot(
        project,
        chat_id=chat_id,
        expected_reviewer_user_id=303,
        requirement_snapshot=["review this build"],
    )
    assert request["status"] == "waiting_user_review"
    presented = canonical_user_review.mark_review_request_presented(
        project,
        request,
        presented_artifacts=[{
            "kind": "nonvisual_summary",
            "ref": "telegram:summary",
            "sha256": canonical_evidence_hash.sha256_bytes(b"summary"),
            "sent": True,
            "presented_at": canonical_user_review.now(),
        }],
    )
    presented_epoch = datetime.fromisoformat(
        str(presented["presented_at"]).replace("Z", "+00:00")
    ).timestamp()
    deadline = time.monotonic() + 1.0
    while time.time() <= presented_epoch + 0.02 and time.monotonic() < deadline:
        time.sleep(0.001)
    assert time.time() > presented_epoch + 0.02
    return presented


def context(**updates) -> dict:
    value = {
        "update_id": 101,
        "message_id": 202,
        "chat_id": "group-1",
        "from_user_id": 303,
        "from_username": "reviewer",
        "message_date": time.time() - 0.005,
        "edited_message": False,
    }
    value.update(updates)
    return value


def make_visual_project(root: pathlib.Path) -> tuple[pathlib.Path, dict, dict]:
    project = root / "visual-project"
    project.mkdir()
    (project / "index.html").write_text("<main><h1>Visual checkpoint</h1></main>\n", encoding="utf-8")
    (project / "README.md").write_text("# Visual checkpoint\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("# Delivery\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_app.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (project / "screenshots").mkdir()
    (project / "screenshots" / "old.png").write_bytes(TEST_PNG)
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    identity = {
        "run_id": "run-visual-checkpoint",
        "candidate_id": "candidate-visual-checkpoint",
        "candidate_hash": candidate_hash,
        "commit_sha": "commit-visual-checkpoint",
    }
    provenance = bind_test_production_provenance(
        root,
        project,
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
    )
    provenance_args = {
        "production_provenance_ref": provenance["provenance_ref"],
        "production_provenance_hash": provenance["provenance_hash"],
    }
    assert (
        real_test_execution.run_tests(
            project, **identity, **provenance_args
        )["status"]
        == "PASS"
    )
    runtime = customer_runtime_runner.run(
        project,
        **identity,
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
    assert runtime["status"] == "PASS"
    assert visual["status"] == "PASS"
    assert browser_visual_evidence.inspect(project)["status"] == "PASS"
    return project, runtime, visual


class InvalidPhotoResultClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.photos: list[tuple[str, pathlib.Path, str]] = []

    def send_photo(self, chat_id, path, caption):
        self.photos.append((str(chat_id), pathlib.Path(path).resolve(), str(caption)))
        return {"ok": False}

    def send_document(self, _chat_id, _path, _caption):
        return False

    def send_video(self, _chat_id, _path, _caption):
        return False


class StructuredPhotoResultClient(InvalidPhotoResultClient):
    def __init__(self, *, raises: bool = False) -> None:
        super().__init__()
        self.raises = raises

    def send_photo(self, chat_id, path, caption):
        self.photos.append((str(chat_id), pathlib.Path(path).resolve(), str(caption)))
        if self.raises:
            raise RuntimeError("telegram photo send failed")
        return {
            "ok": True,
            "result": {
                "message_id": 7001,
                "chat": {"id": chat_id},
                "photo": [{"file_id": "fake-canonical-screenshot"}],
            },
        }


def test_explicit_approval_creates_candidate_bound_review_and_package() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = make_project(pathlib.Path(temp))
        request = request_for(project)
        review = canonical_user_review.record_user_review_approval(
            project,
            request,
            "我确认这个版本，可以最终打包",
            context(),
        )
        assert review["status"] == "PASS"
        assert review["reviewer"] == "303"
        assert review["chat_id"] == "group-1"
        assert review["telegram_message_id"] == "202"
        assert review["reviewed_candidate_hash"] == canonical_evidence_hash.candidate_source_hash(project)
        assert review["artifact_hash"] == canonical_evidence_hash.canonical_json_hash(review, ("artifact_hash",))
        assert canonical_user_review.inspect_user_review_evidence(project)["status"] == "PASS"
        manifest = local_packager.package_project(project, user_review_required=True)
        assert manifest["user_review_required"] is True
        assert manifest["user_review_hash"] == canonical_evidence_hash.sha256_file(project / "user_review.json")
        assert canonical_delivery_manifest.inspect_canonical_delivery_manifest(
            project,
            manifest,
            user_review_required=True,
        )["status"] == "PASS"
        session = bridge.default_session("group-1")
        session["pending_evidence_checkpoint"] = request | {"status": "approved"}
        called: list[bool] = []
        gate = bridge.evaluate_public_delivery_gate(
            project,
            manifest,
            session,
            phase="final",
            agent=lambda _messages: called.append(True) or {
                "verdict": "ASK_USER_REVIEW",
                "delivery_allowed": True,
                "is_final": False,
            },
        )
        assert gate["canonical_package_inspection"]["status"] == "PASS"
        assert called == [True]


def test_chinese_and_english_negative_or_ambiguous_text_never_approves() -> None:
    rejected = [
        "不可以",
        "不要打包",
        "这个版本没通过",
        "继续修改",
        "有问题，先别继续",
        "我还没确认",
        "继续",
        "可以再改一下",
        "not approved",
        "do not package",
        "continue editing",
        "not yet",
        "needs changes",
    ]
    for text in rejected:
        assert canonical_user_review.classify_review_text(text) != "APPROVED", text
    assert canonical_user_review.classify_review_text("I approve this version for final packaging.") == "APPROVED"


def test_missing_identity_edited_message_and_wrong_chat_are_rejected() -> None:
    for field in ("update_id", "message_id", "from_user_id"):
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(pathlib.Path(temp))
            result = canonical_user_review.record_user_review_approval(
                project,
                request_for(project),
                "这个版本通过，可以继续最终交付",
                context(**{field: None}),
            )
            assert result["status"] == "NEEDS_REWORK"
            assert any(field in item for item in result["failures"])
            assert not (project / "user_review.json").exists()
    for updates, expected in (({"edited_message": True}, "edited_message_not_allowed"), ({"chat_id": "other"}, "chat_id_mismatch")):
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(pathlib.Path(temp))
            result = canonical_user_review.record_user_review_approval(
                project,
                request_for(project),
                "我确认这个版本，可以最终打包",
                context(**updates),
            )
            assert expected in result["failures"]


def test_stale_candidate_and_evidence_are_rejected() -> None:
    for target in ("source", "test", "runtime"):
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(pathlib.Path(temp))
            request = request_for(project)
            if target == "source":
                (project / "index.html").write_text("<main>changed</main>\n", encoding="utf-8")
            elif target == "test":
                (project / "test_execution.json").write_bytes((project / "test_execution.json").read_bytes() + b" ")
            else:
                (project / "customer_runtime.json").write_bytes((project / "customer_runtime.json").read_bytes() + b" ")
            result = canonical_user_review.record_user_review_approval(
                project,
                request,
                "我确认这个版本，可以最终打包",
                context(),
            )
            assert result["status"] == "NEEDS_REWORK"
            assert not (project / "user_review.json").exists()


def test_presentation_failure_and_handwritten_review_do_not_pass() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = make_project(pathlib.Path(temp))
        request = canonical_user_review.create_review_request_snapshot(
            project, chat_id="group-1", expected_reviewer_user_id=303, requirement_snapshot=[]
        )
        request = canonical_user_review.mark_review_request_presented(project, request, presented_artifacts=[])
        result = canonical_user_review.record_user_review_approval(
            project,
            request,
            "我确认这个版本，可以最终打包",
            context(),
        )
        assert result["status"] == "NEEDS_REWORK"
        (project / "user_review.json").write_text('{"status":"PASS"}', encoding="utf-8")
        assert canonical_user_review.inspect_user_review_evidence(project)["status"] == "NEEDS_REWORK"
        manifest = local_packager.package_project(project, user_review_required=True, user_review_completed=True)
        assert manifest["status"] == "NEEDS_REWORK"


def test_root_review_is_excluded_but_nested_product_fixture_is_hashed() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = pathlib.Path(temp)
        (project / "product.txt").write_text("product\n", encoding="utf-8")
        (project / "fixtures").mkdir()
        root_review = project / "user_review.json"
        nested = project / "fixtures" / "user_review.json"
        root_review.write_text('{"a":1}', encoding="utf-8")
        nested.write_text('{"a":1}', encoding="utf-8")
        before = canonical_evidence_hash.candidate_source_hash(project)
        root_review.write_text('{"a":2}', encoding="utf-8")
        assert canonical_evidence_hash.candidate_source_hash(project) == before
        nested.write_text('{"a":2}', encoding="utf-8")
        assert canonical_evidence_hash.candidate_source_hash(project) != before
        root_request = project / "user_review_request.json"
        nested_request = project / "fixtures" / "user_review_request.json"
        root_request.write_text('{"a":1}', encoding="utf-8")
        nested_request.write_text('{"a":1}', encoding="utf-8")
        before_request = canonical_evidence_hash.candidate_source_hash(project)
        root_request.write_text('{"a":2}', encoding="utf-8")
        assert canonical_evidence_hash.candidate_source_hash(project) == before_request
        nested_request.write_text('{"a":2}', encoding="utf-8")
        assert canonical_evidence_hash.candidate_source_hash(project) != before_request


def test_telegram_message_cannot_be_replayed() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = make_project(pathlib.Path(temp))
        first = canonical_user_review.record_user_review_approval(
            project,
            request_for(project),
            "我确认这个版本，可以最终打包",
            context(),
        )
        assert first["status"] == "PASS"
        second_request = request_for(project)
        second = canonical_user_review.record_user_review_approval(
            project,
            second_request,
            "我确认这个版本，可以最终打包",
            context(),
        )
        assert second["status"] == "NEEDS_REWORK"
        assert "telegram_message_replayed" in second["failures"]


def test_handle_text_requires_message_context_and_feedback_invalidates_review() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        project = make_project(root)
        request = request_for(project)
        session_dir = root / "sessions"
        log_dir = root / "logs"
        session = bridge.default_session("group-1")
        session["generation"] = {"status": "waiting_user_review", "project_dir": str(project)}
        session["pending_evidence_checkpoint"] = request
        bridge.save_session(session_dir, session)
        resumed: list[bool] = []
        original_resume = bridge.resume_after_evidence_review
        original_start = bridge.start_agent_generation
        bridge.resume_after_evidence_review = lambda *args, **kwargs: resumed.append(True)
        bridge.start_agent_generation = lambda *args, **kwargs: None
        try:
            bridge.handle_text(
                FakeClient(),
                "group-1",
                "我确认这个版本，可以最终打包",
                session_dir,
                log_dir,
                "model",
                10,
                message_context=context(),
            )
            assert resumed == [True]
            assert canonical_user_review.inspect_user_review_evidence(project)["status"] == "PASS"

            session = bridge.load_session(session_dir, "group-1")
            session["generation"]["status"] = "waiting_user_review"
            session["pending_evidence_checkpoint"]["status"] = "presented"
            bridge.save_session(session_dir, session)
            bridge.handle_text(
                FakeClient(),
                "group-1",
                "有问题，需要修改",
                session_dir,
                log_dir,
                "model",
                10,
                message_context=context(update_id=102, message_id=203),
            )
        finally:
            bridge.resume_after_evidence_review = original_resume
            bridge.start_agent_generation = original_start
        saved = bridge.load_session(session_dir, "group-1")
        assert not (project / "user_review.json").exists()
        assert saved["pending_evidence_checkpoint"]["status"] == "feedback_received"
        assert "有问题，需要修改" in saved["whiteboard"]["change_requests"]


def test_required_review_missing_blocks_public_gate_before_adaptive() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = make_project(pathlib.Path(temp))
        manifest = local_packager.package_project(project)
        session = bridge.default_session("group-1")
        session["pending_evidence_checkpoint"] = {"status": "presented", "project_dir": str(project)}
        called: list[bool] = []
        gate = bridge.evaluate_public_delivery_gate(
            project,
            manifest,
            session,
            phase="final",
            agent=lambda _messages: called.append(True) or {
                "verdict": "PASS_FINAL",
                "delivery_allowed": True,
                "is_final": True,
            },
        )
        assert gate["status"] == "NEEDS_REWORK"
        assert gate["delivery_allowed"] is False
        assert called == []
        assert "user_review_requirement_mismatch" in gate["canonical_package_inspection"]["failures"]


def test_trust_boundary_regressions_require_disk_request_owner_date_and_durable_replay() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        project = make_project(root)
        request = request_for(project)
        assert (project / "user_review_request.json").is_file()
        missing_date = canonical_user_review.record_user_review_approval(
            project, request, "我确认这个版本，可以最终打包", context(message_date=None)
        )
        assert missing_date["status"] == "NEEDS_REWORK"
        wrong_user = canonical_user_review.record_user_review_approval(
            project, request, "我确认这个版本，可以最终打包", context(from_user_id=999)
        )
        assert wrong_user["status"] == "NEEDS_REWORK"
        tampered = dict(request)
        tampered["expected_reviewer_user_id"] = "999"
        assert canonical_user_review.record_user_review_approval(
            project, tampered, "我确认这个版本，可以最终打包", context(from_user_id=999)
        )["status"] == "NEEDS_REWORK"
        waiting = canonical_user_review.create_review_request_snapshot(
            project, chat_id="group-1", expected_reviewer_user_id=303, requirement_snapshot=[]
        )
        forged_presentation = dict(waiting)
        forged_presentation.update(
            status="presented", presentation_succeeded=True,
            presented_at=canonical_user_review.now(),
        )
        assert canonical_user_review.record_user_review_approval(
            project, forged_presentation, "我确认这个版本，可以最终打包", context()
        )["status"] == "NEEDS_REWORK"
        assert canonical_user_review.create_review_request_snapshot(
            project, chat_id="group-1", expected_reviewer_user_id="",
            requirement_snapshot=[],
        )["status"] == "NEEDS_REWORK"


def test_stale_review_does_not_infer_workflow_requirement() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = make_project(pathlib.Path(temp))
        (project / "user_review.json").write_text('{"status":"PASS"}\n', encoding="utf-8")
        manifest = local_packager.package_project(project, user_review_required=False)
        assert manifest["user_review_required"] is False
        assert manifest["user_review_ref"] == ""
        assert manifest["user_review_hash"] == ""
    with tempfile.TemporaryDirectory() as temp:
        project = make_project(pathlib.Path(temp))
        request = request_for(project)
        assert canonical_user_review.record_user_review_approval(
            project, request, "我确认这个版本，可以最终打包", context()
        )["status"] == "PASS"
        manifest = local_packager.package_project(project, user_review_required=False)
        assert manifest["status"] == "PASS"
        assert manifest["user_review_required"] is False
        assert manifest["user_review_request_ref"] == ""
        assert manifest["user_review_ref"] == ""
        import zipfile
        with zipfile.ZipFile(manifest["package_path"]) as archive:
            assert "user_review.json" not in archive.namelist()
            assert "user_review_request.json" not in archive.namelist()


def test_forged_but_self_hashed_reviews_are_independently_rejected() -> None:
    mutations = {
        "empty_reviewer": lambda review, request: review.update(reviewer=""),
        "empty_message": lambda review, request: review.update(telegram_message_id=""),
        "wrong_event": lambda review, request: review.update(review_event_id="telegram:forged"),
        "review_not_required": lambda review, request: review.update(review_required=False),
        "wrong_channel": lambda review, request: review.update(channel="manual"),
        "bad_time": lambda review, request: review.update(reviewed_at=request["requested_at"]),
        "request_hash": lambda review, request: review.update(review_request_hash="sha256:" + "0" * 64),
        "duplicate_evidence": lambda review, request: review["reviewed_evidence"].append(dict(review["reviewed_evidence"][0])),
        "missing_test": lambda review, request: review.update(
            reviewed_evidence=[item for item in review["reviewed_evidence"] if item["kind"] != "test_execution"]
        ),
        "handwritten_ids": lambda review, request: review.update(telegram_update_id="999", telegram_message_id="999"),
        "bad_approval_hash": lambda review, request: review.update(approval_text_hash="not-a-hash"),
    }
    for name, mutate in mutations.items():
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(pathlib.Path(temp))
            request = request_for(project)
            review = canonical_user_review.record_user_review_approval(
                project, request, "我确认这个版本，可以最终打包", context()
            )
            assert review["status"] == "PASS", (name, review)
            mutate(review, request)
            review["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(review, ("artifact_hash",))
            (project / "user_review.json").write_text(
                json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            assert canonical_user_review.inspect_user_review_evidence(project)["status"] == "NEEDS_REWORK", name


def test_required_presentation_roles_are_backed_by_actual_sent_artifacts() -> None:
    for role in ("background", "sprite", "generated_image", "video"):
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(pathlib.Path(temp))
            request = canonical_user_review.create_review_request_snapshot(
                project,
                chat_id="group-1",
                expected_reviewer_user_id=303,
                requirement_snapshot=[role],
                required_presentation_roles=["nonvisual_summary", role],
            )
            request = canonical_user_review.mark_review_request_presented(
                project,
                request,
                presented_artifacts=[{
                    "kind": "nonvisual_summary", "ref": "telegram:summary",
                    "sha256": canonical_evidence_hash.sha256_bytes(b"summary"), "sent": True,
                    "presented_at": canonical_user_review.now(),
                }],
            )
            assert request["status"] == "presentation_failed", role
            result = canonical_user_review.record_user_review_approval(
                project, request, "我确认这个版本，可以最终打包", context()
            )
            assert result["status"] == "NEEDS_REWORK", role


def test_feedback_keeps_replay_history_across_new_request_and_candidate() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = make_project(pathlib.Path(temp))
        request = request_for(project)
        assert canonical_user_review.record_user_review_approval(
            project, request, "我确认这个版本，可以最终打包", context()
        )["status"] == "PASS"
        canonical_user_review.invalidate_review_request(project)
        new_request = request_for(project)
        replay = canonical_user_review.record_user_review_approval(
            project, new_request, "我确认这个版本，可以最终打包", context()
        )
        assert replay["status"] == "NEEDS_REWORK"
        assert "telegram_message_replayed" in replay["failures"]
        assert "telegram_message_replayed" in canonical_user_review.record_user_review_approval(
            project, new_request, "我确认这个版本，可以最终打包",
            context(update_id=999, message_id=202),
        )["failures"]
        assert "telegram_message_replayed" in canonical_user_review.record_user_review_approval(
            project, new_request, "我确认这个版本，可以最终打包",
            context(update_id=101, message_id=999),
        )["failures"]


def test_checkpoint_sender_uses_actual_attachment_results_for_required_roles() -> None:
    originals = (
        bridge.evaluate_public_delivery_gate,
        bridge.send_customer_reply,
        bridge.collect_public_delivery_assets,
        bridge.filter_delivery_items_by_judgment,
        bridge.emit_public_delivery,
    )
    bridge.evaluate_public_delivery_gate = lambda *args, **kwargs: {"delivery_allowed": True}
    bridge.send_customer_reply = lambda *args, **kwargs: True
    bridge.collect_public_delivery_assets = lambda *args, **kwargs: {
        "packages": [], "screenshots": [], "generated_backgrounds": [], "generated_sprites": [],
        "generated_images": [], "videos": [],
    }
    bridge.filter_delivery_items_by_judgment = lambda items, _gate: items
    bridge.emit_public_delivery = lambda *args, **kwargs: []
    try:
        for role in ("background", "sprite", "generated_image", "video"):
            with tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                project = make_project(root)
                request = canonical_user_review.create_review_request_snapshot(
                    project, chat_id="group-1", expected_reviewer_user_id=303,
                    requirement_snapshot=[role], required_presentation_roles=["nonvisual_summary", role],
                )
                session_dir = root / "sessions"
                session = bridge.default_session("group-1")
                session["pending_evidence_checkpoint"] = request
                bridge.save_session(session_dir, session)
                bridge.send_evidence_checkpoint(FakeClient(), "group-1", session_dir, session, project, {})
                saved = bridge.load_session(session_dir, "group-1")["pending_evidence_checkpoint"]
                assert saved["status"] == "presentation_failed", role

        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            project = make_project(root)
            request = canonical_user_review.create_review_request_snapshot(
                project, chat_id="group-1", expected_reviewer_user_id=303,
                requirement_snapshot=[], required_presentation_roles=["nonvisual_summary"],
            )
            session_dir = root / "sessions"
            session = bridge.default_session("group-1")
            session["pending_evidence_checkpoint"] = request
            bridge.save_session(session_dir, session)
            bridge.send_evidence_checkpoint(FakeClient(), "group-1", session_dir, session, project, {})
            saved = bridge.load_session(session_dir, "group-1")["pending_evidence_checkpoint"]
            assert saved["status"] == "presented"
    finally:
        (
            bridge.evaluate_public_delivery_gate,
            bridge.send_customer_reply,
            bridge.collect_public_delivery_assets,
            bridge.filter_delivery_items_by_judgment,
            bridge.emit_public_delivery,
        ) = originals


def test_visual_request_inspector_uses_bound_visual_requirement() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = pathlib.Path(temp) / "visual-project"
        project.mkdir()
        (project / "index.html").write_text("<main><h1>Visual review</h1></main>\n", encoding="utf-8")
        (project / "README.md").write_text("# Visual review\n", encoding="utf-8")
        (project / "DELIVERY_NOTES.md").write_text("# Delivery\n", encoding="utf-8")
        (project / "tests").mkdir()
        (project / "tests" / "test_app.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
        candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
        identity = {
            "run_id": "run-visual-review",
            "candidate_id": "candidate-visual-review",
            "candidate_hash": candidate_hash,
            "commit_sha": "commit-visual-review",
        }
        provenance = bind_test_production_provenance(
            pathlib.Path(temp),
            project,
            run_id=identity["run_id"],
            candidate_id=identity["candidate_id"],
            commit_sha=identity["commit_sha"],
        )
        provenance_args = {
            "production_provenance_ref": provenance["provenance_ref"],
            "production_provenance_hash": provenance["provenance_hash"],
        }
        assert (
            real_test_execution.run_tests(
                project, **identity, **provenance_args
            )["status"]
            == "PASS"
        )
        runtime = customer_runtime_runner.run(
            project,
            **identity,
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
        assert visual["status"] == "PASS"
        missing_role_request = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-visual",
            expected_reviewer_user_id=303,
            requirement_snapshot=["screenshot required"],
            visual_required=True,
            required_presentation_roles=["nonvisual_summary"],
        )
        assert missing_role_request["status"] == "NEEDS_REWORK"
        assert "visual_screenshot_role_missing" in missing_role_request["failures"]
        failed_request = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-visual",
            expected_reviewer_user_id=303,
            requirement_snapshot=["screenshot required"],
            visual_required=True,
            required_presentation_roles=["screenshot"],
        )
        failed_request = canonical_user_review.mark_review_request_presented(
            project, failed_request, presented_artifacts=[]
        )
        assert failed_request["status"] == "presentation_failed"
        request = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-visual",
            expected_reviewer_user_id=303,
            requirement_snapshot=["screenshot required"],
            visual_required=True,
            required_presentation_roles=["screenshot"],
        )
        assert {item["kind"] for item in request["reviewed_evidence"]} == {
            "test_execution", "customer_runtime", "visual_evidence",
        }
        screenshot = pathlib.Path(visual["screenshot_path"])
        request = canonical_user_review.mark_review_request_presented(
            project,
            request,
            presented_artifacts=[{
                "kind": "screenshot",
                "ref": str(screenshot),
                "sha256": canonical_evidence_hash.sha256_file(screenshot),
                "sent": True,
                "presented_at": canonical_user_review.now(),
            }],
        )
        assert request["status"] == "presented"
        inspection = canonical_user_review.inspect_user_review_request(project)
        assert inspection["status"] == "PASS", inspection
        review = canonical_user_review.record_user_review_approval(
            project,
            request,
            "我确认这个版本，可以最终打包",
            context(chat_id="group-visual"),
        )
        assert review["status"] == "PASS", review
        assert review["visual_required"] is True
        assert canonical_user_review.inspect_user_review_evidence(project)["status"] == "PASS"
        manifest = local_packager.package_project(
            project,
            visual_required=True,
            user_review_required=True,
        )
        assert manifest["status"] == "PASS", manifest
        assert canonical_delivery_manifest.inspect_canonical_delivery_manifest(
            project,
            manifest,
            visual_required=True,
            user_review_required=True,
        )["status"] == "PASS"
        session = bridge.default_session("group-visual")
        session["whiteboard"]["project_summary"] = "需要真实界面截图"
        session["pending_evidence_checkpoint"] = request | {"status": "approved"}
        adaptive_called: list[bool] = []
        gate = bridge.evaluate_public_delivery_gate(
            project,
            manifest,
            session,
            phase="final",
            agent=lambda _messages: adaptive_called.append(True) or {
                "verdict": "PASS_FINAL",
                "delivery_allowed": True,
                "is_final": True,
                "confidence": 1.0,
                "reasons": ["canonical visual review passed"],
                "user_visible_warnings": [],
                "required_repairs": [],
                "can_send_artifacts": [manifest["package_path"], visual["screenshot_path"]],
                "must_not_claim": [],
            },
        )
        assert gate["delivery_allowed"] is True, gate
        assert gate["canonical_package_inspection"]["status"] == "PASS"
        assert adaptive_called == [True]
        screenshot_bytes = screenshot.read_bytes()
        screenshot.write_bytes(screenshot_bytes + b"changed")
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "NEEDS_REWORK"
        assert canonical_user_review.inspect_user_review_evidence(project)["status"] == "NEEDS_REWORK"
        blocked_agent: list[bool] = []
        blocked_gate = bridge.evaluate_public_delivery_gate(
            project,
            manifest,
            session,
            phase="final",
            agent=lambda _messages: blocked_agent.append(True) or {
                "verdict": "PASS_FINAL", "delivery_allowed": True, "is_final": True,
                "confidence": 1.0, "reasons": [], "user_visible_warnings": [],
                "required_repairs": [], "can_send_artifacts": [], "must_not_claim": [],
            },
        )
        assert blocked_gate["status"] == "NEEDS_REWORK"
        assert blocked_agent == []
        screenshot.write_bytes(screenshot_bytes)
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "PASS"
        visual_path = project / "visual_evidence.json"
        visual_bytes = visual_path.read_bytes()
        visual_path.write_bytes(visual_bytes + b" ")
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "NEEDS_REWORK"
        visual_path.write_bytes(visual_bytes)
        mismatched_visual = json.loads(visual_bytes.decode("utf-8"))
        mismatched_visual["screenshot_hash"] = "sha256:" + "0" * 64
        mismatched_visual["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(
            mismatched_visual, ("artifact_hash",)
        )
        visual_path.write_text(
            json.dumps(mismatched_visual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "NEEDS_REWORK"
        visual_path.write_bytes(visual_bytes)
        request_doc = json.loads((project / "user_review_request.json").read_text(encoding="utf-8"))
        request_doc["visual_required"] = False
        request_doc["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(request_doc, ("artifact_hash",))
        (project / "user_review_request.json").write_text(
            json.dumps(request_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "NEEDS_REWORK"
        assert canonical_user_review.inspect_user_review_evidence(project)["status"] == "NEEDS_REWORK"
        execution_root = pathlib.Path(runtime["execution_root"])
        assert runtime["shutdown_result"]["stopped"] is True
        assert runtime["cleanup_result"]["removed"] is True
        assert not execution_root.exists()


def test_formal_checkpoint_sender_rejects_invalid_telegram_photo_result() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        project, runtime, visual = make_visual_project(root)
        request = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-visual-sender",
            expected_reviewer_user_id=303,
            requirement_snapshot=["需要真实界面截图"],
            visual_required=True,
            required_presentation_roles=["nonvisual_summary", "screenshot"],
        )
        session_dir = root / "sessions"
        session = bridge.default_session("group-visual-sender")
        session["whiteboard"]["project_summary"] = "需要真实界面截图"
        session["pending_evidence_checkpoint"] = request
        bridge.save_session(session_dir, session)
        client = InvalidPhotoResultClient()
        bridge.send_evidence_checkpoint(
            client,
            "group-visual-sender",
            session_dir,
            session,
            project,
            {"screenshots": [str(pathlib.Path(visual["screenshot_path"]).relative_to(project))]},
        )
        saved = bridge.load_session(session_dir, "group-visual-sender")["pending_evidence_checkpoint"]
        assert len(client.photos) == 1
        assert saved["status"] == "presentation_failed", saved
        assert saved["presentation_succeeded"] is False
        assert {item["kind"] for item in saved["presented_artifacts"]} == {"nonvisual_summary"}
        assert not any(item.get("kind") == "screenshot" for item in saved["presented_artifacts"])
        assert "telegram_screenshot_send_failed_or_invalid" in saved["sender_diagnostic"]["failures"]
        assert runtime["shutdown_result"]["stopped"] is True
        assert runtime["cleanup_result"]["removed"] is True


def test_formal_checkpoint_sender_closes_visual_review_package_and_gate() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        project, runtime, visual = make_visual_project(root)
        canonical_screenshot = pathlib.Path(visual["screenshot_path"]).resolve()
        request = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-visual-success",
            expected_reviewer_user_id=303,
            requirement_snapshot=["需要真实界面截图"],
            visual_required=True,
            required_presentation_roles=["nonvisual_summary", "screenshot"],
        )
        session_dir = root / "sessions"
        session = bridge.default_session("group-visual-success")
        session["whiteboard"]["project_summary"] = "需要真实界面截图"
        session["pending_evidence_checkpoint"] = request
        bridge.save_session(session_dir, session)
        client = StructuredPhotoResultClient()
        sent = bridge.send_evidence_checkpoint(
            client,
            "group-visual-success",
            session_dir,
            session,
            project,
            {"screenshots": ["screenshots/old.png", str(canonical_screenshot.relative_to(project))]},
        )
        assert len(client.photos) == 1
        sent_chat, sent_path, sent_caption = client.photos[0]
        assert sent_chat == "group-visual-success"
        assert sent_path == canonical_screenshot
        assert sent_caption == "界面截图"
        assert canonical_evidence_hash.sha256_file(sent_path) == visual["screenshot_hash"]
        assert [item["kind"] for item in sent] == ["screenshot"]
        disk_request = json.loads((project / "user_review_request.json").read_text(encoding="utf-8"))
        assert disk_request["status"] == "presented"
        assert disk_request["presentation_succeeded"] is True
        assert {item["kind"] for item in disk_request["presented_artifacts"]} == {
            "nonvisual_summary", "screenshot",
        }
        screenshot_artifact = next(
            item for item in disk_request["presented_artifacts"] if item["kind"] == "screenshot"
        )
        assert pathlib.Path(screenshot_artifact["ref"]).resolve() == canonical_screenshot
        assert screenshot_artifact["sha256"] == visual["screenshot_hash"]
        assert screenshot_artifact["sent"] is True
        assert screenshot_artifact["telegram_message_id"] == "7001"
        assert screenshot_artifact["telegram_chat_id"] == "group-visual-success"
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "PASS"
        review = canonical_user_review.record_user_review_approval(
            project,
            bridge.load_session(session_dir, "group-visual-success")["pending_evidence_checkpoint"],
            "我确认这个版本，可以最终打包",
            context(chat_id="group-visual-success", update_id=7100, message_id=7101),
        )
        assert review["status"] == "PASS", review
        assert canonical_user_review.inspect_user_review_evidence(project)["status"] == "PASS"
        manifest = local_packager.package_project(
            project, visual_required=True, user_review_required=True
        )
        assert manifest["status"] == "PASS", manifest
        assert canonical_delivery_manifest.inspect_canonical_delivery_manifest(
            project, manifest, visual_required=True, user_review_required=True
        )["status"] == "PASS"
        approved_session = bridge.load_session(session_dir, "group-visual-success")
        approved_session["pending_evidence_checkpoint"]["status"] = "approved"
        adaptive_called: list[bool] = []
        gate = bridge.evaluate_public_delivery_gate(
            project,
            manifest,
            approved_session,
            phase="final",
            agent=lambda _messages: adaptive_called.append(True) or {
                "verdict": "PASS_FINAL", "delivery_allowed": True, "is_final": True,
                "confidence": 1.0, "reasons": ["canonical checkpoint passed"],
                "user_visible_warnings": [], "required_repairs": [],
                "can_send_artifacts": [manifest["package_path"], str(canonical_screenshot)],
                "must_not_claim": [],
            },
        )
        assert gate["delivery_allowed"] is True, gate
        assert gate["canonical_package_inspection"]["status"] == "PASS"
        assert adaptive_called == [True]
        assert runtime["shutdown_result"]["stopped"] is True
        assert runtime["cleanup_result"]["removed"] is True
        assert not pathlib.Path(runtime["execution_root"]).exists()


def test_formal_checkpoint_sender_exception_blocks_approval_package_and_adaptive_gate() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        project, _runtime, visual = make_visual_project(root)
        request = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-visual-exception",
            expected_reviewer_user_id=303,
            requirement_snapshot=["需要真实界面截图"],
            visual_required=True,
            required_presentation_roles=["nonvisual_summary", "screenshot"],
        )
        session_dir = root / "sessions"
        session = bridge.default_session("group-visual-exception")
        session["whiteboard"]["project_summary"] = "需要真实界面截图"
        session["pending_evidence_checkpoint"] = request
        bridge.save_session(session_dir, session)
        client = StructuredPhotoResultClient(raises=True)
        bridge.send_evidence_checkpoint(
            client,
            "group-visual-exception",
            session_dir,
            session,
            project,
            {"screenshots": [str(pathlib.Path(visual["screenshot_path"]).relative_to(project))]},
        )
        saved_session = bridge.load_session(session_dir, "group-visual-exception")
        saved_request = saved_session["pending_evidence_checkpoint"]
        assert len(client.photos) == 1
        assert saved_request["status"] == "presentation_failed"
        assert saved_request["presentation_succeeded"] is False
        assert "telegram_screenshot_send_failed_or_invalid" in saved_request["sender_diagnostic"]["failures"]
        assert canonical_user_review.record_user_review_approval(
            project,
            saved_request,
            "我确认这个版本，可以最终打包",
            context(chat_id="group-visual-exception", update_id=7200, message_id=7201),
        )["status"] == "NEEDS_REWORK"
        manifest = local_packager.package_project(
            project, visual_required=True, user_review_required=True
        )
        assert manifest["status"] == "NEEDS_REWORK"
        adaptive_called: list[bool] = []
        gate = bridge.evaluate_public_delivery_gate(
            project,
            manifest,
            saved_session,
            phase="final",
            agent=lambda _messages: adaptive_called.append(True) or {
                "verdict": "PASS_FINAL", "delivery_allowed": True, "is_final": True,
            },
        )
        assert gate["delivery_allowed"] is False
        assert adaptive_called == []


def test_formal_checkpoint_sender_detects_pre_send_and_post_send_tampering() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        project, _runtime, visual = make_visual_project(root)
        screenshot = pathlib.Path(visual["screenshot_path"])
        original_screenshot = screenshot.read_bytes()
        request = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-visual-tamper",
            expected_reviewer_user_id=303,
            requirement_snapshot=["需要真实界面截图"],
            visual_required=True,
            required_presentation_roles=["nonvisual_summary", "screenshot"],
        )
        session_dir = root / "sessions"
        session = bridge.default_session("group-visual-tamper")
        session["whiteboard"]["project_summary"] = "需要真实界面截图"
        session["pending_evidence_checkpoint"] = request
        bridge.save_session(session_dir, session)
        screenshot.write_bytes(original_screenshot + b"changed-before-send")
        pre_client = StructuredPhotoResultClient()
        bridge.send_evidence_checkpoint(
            pre_client,
            "group-visual-tamper",
            session_dir,
            session,
            project,
            {"screenshots": [str(screenshot.relative_to(project))]},
        )
        pre_saved = bridge.load_session(session_dir, "group-visual-tamper")["pending_evidence_checkpoint"]
        assert pre_client.photos == []
        assert pre_saved["status"] == "presentation_failed"
        assert "checkpoint_gate_failed" in pre_saved["sender_diagnostic"]["failures"]
        screenshot.write_bytes(original_screenshot)

        request = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-visual-tamper",
            expected_reviewer_user_id=303,
            requirement_snapshot=["需要真实界面截图"],
            visual_required=True,
            required_presentation_roles=["nonvisual_summary", "screenshot"],
        )
        session = bridge.default_session("group-visual-tamper")
        session["whiteboard"]["project_summary"] = "需要真实界面截图"
        session["pending_evidence_checkpoint"] = request
        bridge.save_session(session_dir, session)
        success_client = StructuredPhotoResultClient()
        bridge.send_evidence_checkpoint(
            success_client,
            "group-visual-tamper",
            session_dir,
            session,
            project,
            {"screenshots": [str(screenshot.relative_to(project))]},
        )
        sent_request = bridge.load_session(session_dir, "group-visual-tamper")["pending_evidence_checkpoint"]
        assert sent_request["status"] == "presented"
        screenshot.write_bytes(original_screenshot + b"changed-after-send")
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "NEEDS_REWORK"
        assert canonical_user_review.record_user_review_approval(
            project,
            sent_request,
            "我确认这个版本，可以最终打包",
            context(chat_id="group-visual-tamper", update_id=7300, message_id=7301),
        )["status"] == "NEEDS_REWORK"
        screenshot.write_bytes(original_screenshot)
        visual_path = project / "visual_evidence.json"
        original_visual = visual_path.read_bytes()
        visual_path.write_bytes(original_visual + b" ")
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "NEEDS_REWORK"
        assert canonical_user_review.record_user_review_approval(
            project,
            sent_request,
            "我确认这个版本，可以最终打包",
            context(chat_id="group-visual-tamper", update_id=7302, message_id=7303),
        )["status"] == "NEEDS_REWORK"


def test_formal_checkpoint_sender_nonvisual_summary_does_not_send_old_png() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        project = make_project(root)
        (project / "screenshots").mkdir()
        (project / "screenshots" / "old.png").write_bytes(TEST_PNG)
        candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
        identity = {
            "run_id": "run-review", "candidate_id": "candidate-review",
            "candidate_hash": candidate_hash, "commit_sha": "commit-review",
        }
        provenance = bind_test_production_provenance(
            root,
            project,
            run_id=identity["run_id"],
            candidate_id=identity["candidate_id"],
            commit_sha=identity["commit_sha"],
        )
        provenance_args = {
            "production_provenance_ref": provenance["provenance_ref"],
            "production_provenance_hash": provenance["provenance_hash"],
        }
        assert real_test_execution.run_tests(
            project, **identity, **provenance_args
        )["status"] == "PASS"
        assert customer_runtime_runner.run(
            project, **identity, **provenance_args
        )["status"] == "PASS"
        request = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-nonvisual-sender",
            expected_reviewer_user_id=303,
            requirement_snapshot=["plain cli"],
            visual_required=False,
            required_presentation_roles=["nonvisual_summary"],
        )
        session_dir = root / "sessions"
        session = bridge.default_session("group-nonvisual-sender")
        session["whiteboard"]["project_summary"] = "plain cli"
        session["pending_evidence_checkpoint"] = request
        bridge.save_session(session_dir, session)
        client = StructuredPhotoResultClient()
        sent = bridge.send_evidence_checkpoint(
            client,
            "group-nonvisual-sender",
            session_dir,
            session,
            project,
            {"screenshots": ["screenshots/old.png"]},
        )
        saved = bridge.load_session(session_dir, "group-nonvisual-sender")["pending_evidence_checkpoint"]
        assert client.photos == []
        assert sent == []
        assert saved["visual_required"] is False
        assert saved["status"] == "presented"
        assert {item["kind"] for item in saved["presented_artifacts"]} == {"nonvisual_summary"}
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "PASS"


def test_nonvisual_request_rejects_visual_scope_injection_and_old_screenshot_does_not_promote() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = make_project(pathlib.Path(temp))
        screenshots = project / "screenshots"
        screenshots.mkdir()
        (screenshots / "old.png").write_bytes(b"not canonical visual evidence")
        candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
        identity = {
            "run_id": "run-review", "candidate_id": "candidate-review",
            "candidate_hash": candidate_hash, "commit_sha": "commit-review",
        }
        provenance = bind_test_production_provenance(
            pathlib.Path(temp),
            project,
            run_id=identity["run_id"],
            candidate_id=identity["candidate_id"],
            commit_sha=identity["commit_sha"],
        )
        provenance_args = {
            "production_provenance_ref": provenance["provenance_ref"],
            "production_provenance_hash": provenance["provenance_hash"],
        }
        assert real_test_execution.run_tests(
            project, **identity, **provenance_args
        )["status"] == "PASS"
        assert customer_runtime_runner.run(
            project, **identity, **provenance_args
        )["status"] == "PASS"
        request = request_for(project)
        assert request["visual_required"] is False
        assert {item["kind"] for item in request["reviewed_evidence"]} == {
            "test_execution", "customer_runtime",
        }
        assert canonical_user_review.inspect_user_review_request(project)["status"] == "PASS"
        forged = json.loads((project / "user_review_request.json").read_text(encoding="utf-8"))
        forged["required_presentation_roles"].append("screenshot")
        forged["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(forged, ("artifact_hash",))
        (project / "user_review_request.json").write_text(
            json.dumps(forged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        inspection = canonical_user_review.inspect_user_review_request(project)
        assert inspection["status"] == "NEEDS_REWORK"
        assert "unexpected_visual_binding" in inspection["failures"]
        forged["required_presentation_roles"] = ["nonvisual_summary"]
        forged["reviewed_evidence"].append({
            "kind": "visual_evidence",
            "ref": str((project / "visual_evidence.json").resolve()),
            "hash": "sha256:" + "0" * 64,
        })
        forged["reviewed_evidence_hashes"].append("sha256:" + "0" * 64)
        forged["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(forged, ("artifact_hash",))
        (project / "user_review_request.json").write_text(
            json.dumps(forged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        inspection = canonical_user_review.inspect_user_review_request(project)
        assert inspection["status"] == "NEEDS_REWORK"
        assert "unexpected_visual_binding" in inspection["failures"]


def test_visual_request_requires_visual_evidence_and_screenshot_role() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = make_project(pathlib.Path(temp))
        missing_visual = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-1",
            expected_reviewer_user_id=303,
            requirement_snapshot=["visual"],
            visual_required=True,
        )
        assert missing_visual["status"] == "NEEDS_REWORK"
        missing_role = canonical_user_review.create_review_request_snapshot(
            project,
            chat_id="group-1",
            expected_reviewer_user_id=303,
            requirement_snapshot=["visual"],
            visual_required=True,
            required_presentation_roles=["nonvisual_summary"],
        )
        assert missing_role["status"] == "NEEDS_REWORK"
