from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import local_conversation_manager as conversations
from scripts import local_repo_manager as repos
from scripts import project_revision_lane as revisions
from scripts.main_agent_manager import MainAgentManager


def _prepared_revision(tmp_path, monkeypatch) -> tuple[dict, dict, pathlib.Path]:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))
    monkeypatch.setenv("CGNK_MANAGED_PROJECT_ROOT", str(tmp_path / "managed"))
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('v0')\n", encoding="utf-8")
    (source / "delete_me.txt").write_text("remove\n", encoding="utf-8")
    conversation = conversations.default_conversation("chat-exec", source="local_cli")
    conversations.update_whiteboard(conversation, {"project_summary": "demo app"}, "test")
    revisions.bind_initial_project_delivery(conversation, source, package_path="final_project_bundle.zip", delivery_manifest="delivery_manifest.json")
    prepared = MainAgentManager().start_project_revision(conversation, "把上次项目改成第二版")
    manifest = revisions._load_json_object(prepared["revision_manifest"])
    return conversation, manifest, repos.current_worktree(conversations.get_active_project(conversation)["project_id"])


def _provider_success(**kwargs):
    out_dir = pathlib.Path(kwargs["out_dir"])
    (out_dir / "app.py").write_text("print('v1')\n", encoding="utf-8")
    (out_dir / "new.py").write_text("print('new')\n", encoding="utf-8")
    delete_me = out_dir / "delete_me.txt"
    if delete_me.exists():
        delete_me.unlink()
    return {"ok": True, "generated_files": ["app.py", "new.py"]}


def _post_build_finalize(**kwargs):
    project_dir = pathlib.Path(kwargs["project_dir"])
    (project_dir / "TEST_REPORT.md").write_text("commands_run: pytest\nexit_code: 0\n", encoding="utf-8")
    return {"ok": True}


def _package_project(**kwargs):
    project_dir = pathlib.Path(kwargs["project_dir"])
    package_path = project_dir / "final_project_bundle.zip"
    manifest_path = project_dir / "delivery_manifest.json"
    package_path.write_bytes(b"zip")
    manifest_path.write_text('{"kind":"CGNKDeliveryManifest"}\n', encoding="utf-8")
    return {"package_path": str(package_path), "manifest_path": str(manifest_path), "status": "ready"}


def _gate_allowed(**kwargs):
    return {"delivery_allowed": True, "status": "PASS"}


def _gate_rejected(**kwargs):
    return {"delivery_allowed": False, "status": "REWORK", "missing": ["preview"]}


def test_revision_execution_success_promotes_current_and_updates_active_project(tmp_path, monkeypatch) -> None:
    conversation, manifest, current = _prepared_revision(tmp_path, monkeypatch)

    result = revisions.run_provider_revision_job(
        conversation=conversation,
        revision_manifest=manifest,
        provider_execute=_provider_success,
        post_build_finalize=_post_build_finalize,
        package_project=_package_project,
        evaluate_public_delivery_gate=_gate_allowed,
        model="gpt-test",
    )

    active = conversations.get_active_project(conversation)
    loaded_manifest = revisions._load_json_object(result["revision_manifest"])
    assert result["status"] == "ready"
    assert active["revision_index"] == 1
    assert active["status"] == "revision_ready"
    assert (current / "app.py").read_text(encoding="utf-8") == "print('v1')\n"
    assert loaded_manifest["package_path"].endswith("final_project_bundle.zip")
    assert loaded_manifest["delivery_manifest"].endswith("delivery_manifest.json")
    assert loaded_manifest["public_delivery_gate"]["delivery_allowed"] is True
    assert "modified:app.py" in loaded_manifest["changed_files"]
    assert "added:new.py" in loaded_manifest["changed_files"]
    assert "deleted:delete_me.txt" in loaded_manifest["changed_files"]
    assert loaded_manifest["provider_route"] == "api_provider_project_generation"
    assert "local_packager" in loaded_manifest["delivery_contract"]
    assert "public_delivery_gate" in loaded_manifest["delivery_contract"]


def test_main_agent_manager_executes_revision_with_adapters(tmp_path, monkeypatch) -> None:
    conversation, manifest, _current = _prepared_revision(tmp_path, monkeypatch)

    result = MainAgentManager().execute_project_revision(
        conversation,
        str(manifest["manifest_path"]),
        {
            "provider_execute": _provider_success,
            "post_build_finalize": _post_build_finalize,
            "package_project": _package_project,
            "evaluate_public_delivery_gate": _gate_allowed,
            "model": "gpt-test",
        },
    )

    assert result["status"] == "ready"
    assert conversation["generation"]["status"] == "revision_delivered"


def test_gate_rejection_does_not_promote_current(tmp_path, monkeypatch) -> None:
    conversation, manifest, current = _prepared_revision(tmp_path, monkeypatch)

    result = revisions.run_provider_revision_job(
        conversation=conversation,
        revision_manifest=manifest,
        provider_execute=_provider_success,
        post_build_finalize=_post_build_finalize,
        package_project=_package_project,
        evaluate_public_delivery_gate=_gate_rejected,
        model="gpt-test",
    )

    active = conversations.get_active_project(conversation)
    assert result["status"] == "rework_blocked"
    assert active["revision_index"] == 0
    assert (current / "app.py").read_text(encoding="utf-8") == "print('v0')\n"


def test_provider_exception_does_not_promote_current(tmp_path, monkeypatch) -> None:
    conversation, manifest, current = _prepared_revision(tmp_path, monkeypatch)

    def provider_fails(**kwargs):
        raise RuntimeError("provider failed")

    result = revisions.run_provider_revision_job(
        conversation=conversation,
        revision_manifest=manifest,
        provider_execute=provider_fails,
        post_build_finalize=_post_build_finalize,
        package_project=_package_project,
        evaluate_public_delivery_gate=_gate_allowed,
        model="gpt-test",
    )

    active = conversations.get_active_project(conversation)
    assert result["status"] == "rework_blocked"
    assert "provider failed" in result["error"]
    assert active["revision_index"] == 0
    assert (current / "app.py").read_text(encoding="utf-8") == "print('v0')\n"


def test_internal_package_suffix_blocks_public_delivery(tmp_path, monkeypatch) -> None:
    conversation, manifest, current = _prepared_revision(tmp_path, monkeypatch)

    def package_internal(**kwargs):
        project_dir = pathlib.Path(kwargs["project_dir"])
        package_path = project_dir / "leak.json"
        manifest_path = project_dir / "delivery_manifest.json"
        package_path.write_text("{}", encoding="utf-8")
        manifest_path.write_text("{}", encoding="utf-8")
        return {"package_path": str(package_path), "manifest_path": str(manifest_path)}

    result = revisions.run_provider_revision_job(
        conversation=conversation,
        revision_manifest=manifest,
        provider_execute=_provider_success,
        post_build_finalize=_post_build_finalize,
        package_project=package_internal,
        evaluate_public_delivery_gate=_gate_allowed,
        model="gpt-test",
    )

    active = conversations.get_active_project(conversation)
    assert result["status"] == "rework_blocked"
    assert active["revision_index"] == 0
    assert (current / "app.py").read_text(encoding="utf-8") == "print('v0')\n"
    assert not revisions.public_delivery_is_safe("leak.json")


def test_telegram_bridge_does_not_implement_revision_execution_details() -> None:
    bridge = (ROOT / "scripts" / "telegram_live_bridge.py").read_text(encoding="utf-8")
    branch = bridge[bridge.find('if intent == "project_revision_request":') : bridge.find('if intent == "new_project_request":')]
    assert "MainAgentManager().start_project_revision" in branch
    assert "run_provider_revision_job" not in branch
    assert "local_packager.package_project" not in branch
