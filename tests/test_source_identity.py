from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import source_identity


def git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def init_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "CGKN Test")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("fixture\n", encoding="utf-8")
    git(tmp_path, "add", "--", "scripts/example.py", "VERSION", "AGENTS.md")
    git(tmp_path, "commit", "-m", "test: baseline")
    return tmp_path


def test_identity_is_repeatable_and_timing_is_not_hashed(tmp_path: pathlib.Path) -> None:
    root = init_repo(tmp_path)
    first = source_identity.capture(root)
    time.sleep(0.01)
    second = source_identity.capture(root)
    assert first["source_identity_hash"] == second["source_identity_hash"]
    assert first["captured_at"] != second["captured_at"]
    assert first["timing"]["total_seconds"] >= 0


def test_git_timeout_is_structured_and_fail_closed(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = init_repo(tmp_path)
    original = source_identity.subprocess.run

    def timeout_status(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if len(command) > 1 and command[1] == "status":
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 15), output="x" * 9000, stderr="slow")
        return original(command, **kwargs)

    monkeypatch.setattr(source_identity.subprocess, "run", timeout_status)
    with pytest.raises(RuntimeError) as caught:
        source_identity.capture(root)
    payload = json.loads(str(caught.value))
    assert payload["classification"] == "GIT_COMMAND_TIMEOUT"
    assert payload["operation"] == "status"
    assert payload["returncode"] is None
    assert payload["timeout_seconds"] <= 15
    assert len(payload["stdout"]) <= source_identity.MAX_GIT_DIAGNOSTIC_CHARS


def test_required_git_failure_is_not_interpreted_as_clean(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = init_repo(tmp_path)

    def fail(_root: pathlib.Path, *args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["git", *args], 128, "", "simulated failure")

    monkeypatch.setattr(source_identity, "_git", fail)
    with pytest.raises(RuntimeError, match="GIT_COMMAND_FAILED"):
        source_identity.capture(root)


def test_git_operations_are_bounded_and_pathspec_scoped(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = init_repo(tmp_path)
    calls: list[tuple[tuple[str, ...], int | None]] = []
    original = source_identity._git

    def record(repo: pathlib.Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs.get("timeout") if isinstance(kwargs.get("timeout"), int) else None))
        return original(repo, *args, **kwargs)

    monkeypatch.setattr(source_identity, "_git", record)
    source_identity.capture(root)
    argv = [args for args, _timeout in calls]
    assert all("--untracked-files=all" not in args for args in argv)
    status = next(args for args in argv if args and args[0] == "status")
    untracked = next(args for args in argv if args and args[0] == "ls-files")
    diff = next(args for args in argv if args and args[0] == "diff")
    assert "--untracked-files=no" in status
    assert untracked[:3] == ("ls-files", "--others", "--exclude-standard")
    for args in (status, untracked, diff):
        assert "--" in args
        assert "scripts" in args
        assert "governance" in args
        assert "VERSION" in args
        assert ":(exclude)**/generated/**" in args
    assert all(timeout is not None and timeout <= 20 for _args, timeout in calls)
    assert next(timeout for args, timeout in calls if args[:2] == ("rev-parse", "HEAD")) == 15


def test_git_environment_is_noninteractive_and_ignores_inherited_repository_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", "wrong-repository")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "wrong-config")
    environment = source_identity._git_environment()
    assert "GIT_DIR" not in environment
    assert "GIT_CONFIG_GLOBAL" not in environment
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GCM_INTERACTIVE"] == "Never"
    assert environment["GIT_OPTIONAL_LOCKS"] == "0"


def test_relevant_tracked_change_changes_identity_and_clean_state(tmp_path: pathlib.Path) -> None:
    root = init_repo(tmp_path)
    before = source_identity.capture(root)
    (root / "scripts" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    after = source_identity.capture(root)
    assert before["working_tree_clean"] is True
    assert after["working_tree_clean"] is False
    assert after["source_identity_hash"] != before["source_identity_hash"]


def test_relevant_untracked_source_changes_identity(tmp_path: pathlib.Path) -> None:
    root = init_repo(tmp_path)
    before = source_identity.capture(root)
    new_file = root / "scripts" / "new_module.py"
    new_file.write_text("VALUE = 3\n", encoding="utf-8")
    after = source_identity.capture(root)
    assert after["working_tree_clean"] is False
    assert after["source_identity_hash"] != before["source_identity_hash"]
    assert [item["path"] for item in after["relevant_untracked_manifest"]] == ["scripts/new_module.py"]


def test_root_version_change_changes_identity(tmp_path: pathlib.Path) -> None:
    root = init_repo(tmp_path)
    before = source_identity.capture(root)
    (root / "VERSION").write_text("1.0.1\n", encoding="utf-8")
    after = source_identity.capture(root)
    assert after["working_tree_clean"] is False
    assert after["source_identity_hash"] != before["source_identity_hash"]


def test_irrelevant_runtime_files_do_not_change_identity(tmp_path: pathlib.Path) -> None:
    root = init_repo(tmp_path)
    before = source_identity.capture(root)
    for relative in ("artifacts/huge.tmp", "generated/foo.json", "workspaces/bar.py", ".cgkn/cache/x.json"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("runtime\n", encoding="utf-8")
    after = source_identity.capture(root)
    assert after["working_tree_clean"] is True
    assert after["source_identity_hash"] == before["source_identity_hash"]


def test_large_excluded_tree_is_pruned_from_package_hash(tmp_path: pathlib.Path) -> None:
    root = init_repo(tmp_path)
    package = root / "tools" / "cgkn-agent-kit"
    package.mkdir(parents=True)
    (package / "kit.py").write_text("VALUE = 1\n", encoding="utf-8")
    before = source_identity.capture(root)
    excluded = package / "generated"
    excluded.mkdir()
    for index in range(2000):
        (excluded / f"file_{index}.py").write_text("ignored\n", encoding="utf-8")
    started = time.perf_counter()
    after = source_identity.capture(root)
    assert time.perf_counter() - started < 10
    assert after["agent_kit_file_count"] == before["agent_kit_file_count"] == 1
    assert after["source_identity_hash"] == before["source_identity_hash"]


def test_publish_runtime_does_not_change_source_identity(tmp_path: pathlib.Path) -> None:
    root = init_repo(tmp_path)
    before = source_identity.capture(root)["source_identity_hash"]
    runtime = root / ".cgkn" / "publish" / "test_receipt.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text('{"status":"PASS"}\n', encoding="utf-8")
    after = source_identity.capture(root)["source_identity_hash"]
    assert after == before
