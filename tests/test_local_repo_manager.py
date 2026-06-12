from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import local_repo_manager as repos


def test_project_lifecycle_copy_promote_snapshot_and_rollback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_MANAGED_PROJECT_ROOT", str(tmp_path / "managed"))
    project_id = repos.project_id_for_conversation("chat-a")

    metadata = repos.ensure_project(project_id, "chat-a")
    assert pathlib.Path(metadata["current_worktree"]).exists()

    current = repos.current_worktree(project_id)
    (current / "app.py").write_text("print('v0')\n", encoding="utf-8")
    rev0 = repos.copy_current_to_revision_workspace(project_id, 0)
    assert (rev0 / "app.py").read_text(encoding="utf-8") == "print('v0')\n"

    rev1 = repos.copy_current_to_revision_workspace(project_id, 1)
    (rev1 / "app.py").write_text("print('v1')\n", encoding="utf-8")
    (rev1 / "new.txt").write_text("new\n", encoding="utf-8")
    changed = repos.compute_changed_files(current, rev1)
    assert "modified:app.py" in changed
    assert "added:new.txt" in changed
    assert (current / "app.py").read_text(encoding="utf-8") == "print('v0')\n"

    promoted = repos.promote_revision_to_current(project_id, 1)
    assert promoted["current_revision"] == 1
    assert (current / "app.py").read_text(encoding="utf-8") == "print('v1')\n"

    snapshot = repos.create_snapshot(project_id, 1)
    assert snapshot.exists()

    rolled_back = repos.rollback_to_revision(project_id, 0)
    assert rolled_back["status"] == "rolled_back"
    assert (current / "app.py").read_text(encoding="utf-8") == "print('v0')\n"


def test_failed_revision_workspace_does_not_affect_current(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_MANAGED_PROJECT_ROOT", str(tmp_path / "managed"))
    project_id = repos.project_id_for_conversation("chat-b")
    repos.ensure_project(project_id, "chat-b")
    current = repos.current_worktree(project_id)
    (current / "main.py").write_text("old\n", encoding="utf-8")
    failed = repos.copy_current_to_revision_workspace(project_id, 2)
    (failed / "main.py").write_text("failed\n", encoding="utf-8")

    assert (current / "main.py").read_text(encoding="utf-8") == "old\n"
