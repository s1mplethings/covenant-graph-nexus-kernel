from __future__ import annotations

import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import local_repo_manager as repos
from scripts import local_studio_cli


def test_local_studio_does_not_add_second_generation_mainline() -> None:
    source = (ROOT / "scripts" / "local_studio_cli.py").read_text(encoding="utf-8")
    assert "run_local_pipeline" not in source
    assert "generate_project.py" not in source
    assert "simulator" not in source
    assert "MainAgentManager" in source


def test_local_studio_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/local_studio_cli.py", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "list-conversations" in result.stdout
    assert "execute-revision" in result.stdout


def test_local_studio_docs_preserve_delivery_contract() -> None:
    doc = (ROOT / "docs" / "10_local_studio.md").read_text(encoding="utf-8")
    assert "not introduce a new formal generation path" in doc
    assert "MainAgentManager" in doc
    assert "local_packager" in doc
    assert "public_delivery_gate" in doc
    assert "delivery_manifest" in doc


def test_project_level_rollback_reports_conversation_sync_not_applied(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_MANAGED_PROJECT_ROOT", str(tmp_path / "managed"))
    project_id = repos.project_id_for_conversation("chat-rollback")
    repos.ensure_project(project_id, "chat-rollback")
    current = repos.current_worktree(project_id)
    (current / "app.py").write_text("print('v0')\n", encoding="utf-8")
    repos.copy_current_to_revision_workspace(project_id, 0)

    payload = local_studio_cli.rollback_project_payload(project_id, 0)

    assert payload["status"] == "rolled_back"
    assert payload["project_id"] == project_id
    assert payload["revision_index"] == 0
    assert payload["conversation_sync"] == "not_applied"
    assert "Phase 2" in payload["note"]


def test_execute_revision_command_requires_host_adapters() -> None:
    payload = local_studio_cli.execute_revision_payload("chat", "revision.json")
    assert payload["status"] == "blocked"
    assert payload["reason"] == "execution_adapters_required"
