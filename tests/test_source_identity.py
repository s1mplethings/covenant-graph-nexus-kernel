from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import source_identity


def test_identity_is_repeatable_when_repository_bytes_do_not_change() -> None:
    assert source_identity.capture(ROOT)["source_identity_hash"] == source_identity.capture(ROOT)["source_identity_hash"]


def test_required_git_failure_is_not_interpreted_as_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["git", *args], 128, "", "simulated failure")

    monkeypatch.setattr(source_identity, "_git", fail)
    with pytest.raises(RuntimeError, match="GIT_COMMAND_FAILED"):
        source_identity.capture(ROOT)


def test_publish_runtime_does_not_change_source_identity(tmp_path: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "test: baseline"], cwd=tmp_path, check=True, capture_output=True)
    before = source_identity.capture(tmp_path)["source_identity_hash"]
    runtime = tmp_path / ".cgkn" / "publish" / "test_receipt.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text('{"status":"PASS"}\n', encoding="utf-8")
    after = source_identity.capture(tmp_path)["source_identity_hash"]
    assert after == before
