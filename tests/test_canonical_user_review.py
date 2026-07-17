from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import canonical_delivery_manifest
from scripts import canonical_evidence_hash
from scripts import canonical_user_review
from scripts import customer_runtime_runner
from scripts import local_packager
from scripts import real_test_execution
from scripts import telegram_live_bridge as bridge


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
    assert real_test_execution.run_tests(project, **identity)["status"] == "PASS"
    assert customer_runtime_runner.run(project, **identity)["status"] == "PASS"
    return project


def request_for(project: pathlib.Path, chat_id: str = "group-1") -> dict:
    request = canonical_user_review.create_review_request_snapshot(
        project,
        chat_id=chat_id,
        expected_reviewer_user_id=303,
        requirement_snapshot=["review this build"],
    )
    assert request["status"] == "waiting_user_review"
    return canonical_user_review.mark_review_request_presented(
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


def context(**updates) -> dict:
    value = {
        "update_id": 101,
        "message_id": 202,
        "chat_id": "group-1",
        "from_user_id": 303,
        "from_username": "reviewer",
        "message_date": time.time(),
        "edited_message": False,
    }
    value.update(updates)
    return value


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
            assert review["status"] == "PASS", name
            mutate(review, request)
            review["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(review, ("artifact_hash",))
            (project / "user_review.json").write_text(
                json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            assert canonical_user_review.inspect_user_review_evidence(project)["status"] == "NEEDS_REWORK", name


def test_required_presentation_roles_are_backed_by_actual_sent_artifacts() -> None:
    for role in ("screenshot", "background", "sprite", "generated_image", "video"):
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
        for role in ("screenshot", "background", "sprite", "generated_image", "video"):
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
