from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import local_conversation_manager as conversations
from scripts import local_repo_manager as repos
from scripts import project_revision_lane as revisions


def _conversation_with_project(tmp_path, monkeypatch) -> dict:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))
    monkeypatch.setenv("CGNK_MANAGED_PROJECT_ROOT", str(tmp_path / "managed"))
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('v0')\n", encoding="utf-8")
    conversation = conversations.default_conversation("chat-rev", source="local_cli")
    conversations.update_whiteboard(conversation, {"project_summary": "demo app"}, "test")
    revisions.bind_initial_project_delivery(conversation, source, package_path="final_project_bundle.zip", delivery_manifest="delivery_manifest.json")
    return conversation


def test_no_active_project_does_not_allow_revision(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))
    conversation = conversations.default_conversation("empty")
    assert not revisions.has_active_project(conversation)
    assert not revisions.is_revision_request("把上次那个项目加按钮", conversation)


def test_revision_request_plan_manifest_and_goal(tmp_path, monkeypatch) -> None:
    conversation = _conversation_with_project(tmp_path, monkeypatch)
    assert revisions.is_revision_request("把上次那个项目加一个导出按钮", conversation)

    request = revisions.create_revision_request(conversation, "把上次那个项目加一个导出按钮")
    assert request["revision_index"] == 1
    assert request["previous_manifest_ref"] == "delivery_manifest.json"

    plan = revisions.create_revision_plan(conversation, request)
    assert plan["revision_mode"] == "controlled_regenerate"
    assert plan["full_regenerate_reason"]
    assert "local_packager" in plan["delivery_contract"]
    assert "public_delivery_gate" in plan["delivery_contract"]

    workspace = revisions.prepare_revision_workspace(conversation, request)
    assert pathlib.Path(workspace["revision_workspace"]).exists()
    goal = revisions.build_revision_goal(conversation, request, plan)
    assert "Previous delivery manifest" in goal
    assert "local_packager" in goal

    manifest = revisions.create_revision_manifest(conversation, request, plan, workspace)
    path = revisions.write_revision_manifest(manifest)
    assert path.exists()
    assert manifest["previous_manifest_ref"] == "delivery_manifest.json"


def test_revision_failed_does_not_promote_current(tmp_path, monkeypatch) -> None:
    conversation = _conversation_with_project(tmp_path, monkeypatch)
    active = conversations.get_active_project(conversation)
    current = repos.current_worktree(active["project_id"])
    request = revisions.create_revision_request(conversation, "继续改，改成新版")
    plan = revisions.create_revision_plan(conversation, request)
    workspace = revisions.prepare_revision_workspace(conversation, request)
    (pathlib.Path(workspace["revision_workspace"]) / "app.py").write_text("broken\n", encoding="utf-8")
    manifest = revisions.create_revision_manifest(conversation, request, plan, workspace)

    revisions.mark_revision_failed(conversation, manifest, "tests_failed")
    assert (current / "app.py").read_text(encoding="utf-8") == "print('v0')\n"
    assert conversations.get_active_project(conversation)["revision_index"] == 0


def test_revision_success_promotes_current_and_records_history(tmp_path, monkeypatch) -> None:
    conversation = _conversation_with_project(tmp_path, monkeypatch)
    request = revisions.create_revision_request(conversation, "继续改，改成新版")
    plan = revisions.create_revision_plan(conversation, request)
    workspace = revisions.prepare_revision_workspace(conversation, request)
    (pathlib.Path(workspace["revision_workspace"]) / "app.py").write_text("print('v1')\n", encoding="utf-8")
    manifest = revisions.create_revision_manifest(conversation, request, plan, workspace)
    manifest["package_path"] = "final_project_bundle_rev001.zip"
    manifest["delivery_manifest"] = "delivery_001.json"
    manifest["public_delivery_gate"] = {"delivery_allowed": True}

    revisions.mark_revision_success(conversation, manifest)
    active = conversations.get_active_project(conversation)
    assert active["revision_index"] == 1
    assert active["status"] == "revision_ready"
    assert pathlib.Path(active["current_worktree"], "app.py").read_text(encoding="utf-8") == "print('v1')\n"
    assert conversation["revision_history"][-1]["status"] == "ready"


def test_public_delivery_rejects_internal_suffixes() -> None:
    assert revisions.public_delivery_is_safe("final_project_bundle.zip")
    assert not revisions.public_delivery_is_safe("delivery_manifest.json")
    assert not revisions.public_delivery_is_safe("README.md")
