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
