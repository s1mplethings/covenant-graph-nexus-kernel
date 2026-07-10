from __future__ import annotations

import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_gitignore_covers_runtime_outputs() -> None:
    lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required = {
        "generated/",
        "artifacts/",
        ".pytest_cache/",
        "__pycache__/",
        ".service_worktree/",
        ".vs/",
        "examples/runtime_runs/",
    }
    assert required <= lines
