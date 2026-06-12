from __future__ import annotations

import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


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


def test_local_studio_docs_preserve_delivery_contract() -> None:
    doc = (ROOT / "docs" / "10_local_studio.md").read_text(encoding="utf-8")
    assert "not introduce a new formal generation path" in doc
    assert "MainAgentManager" in doc
    assert "local_packager" in doc
    assert "public_delivery_gate" in doc
    assert "delivery_manifest" in doc
