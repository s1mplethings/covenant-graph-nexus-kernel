from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import shared_gui_cli_core_checker


def test_shared_gui_cli_core_checker_passes_when_both_entries_use_core(tmp_path: pathlib.Path) -> None:
    (tmp_path / "orchestrator.py").write_text("import stages\n\ndef run():\n    return stages.ingest()\n", encoding="utf-8")
    (tmp_path / "stages.py").write_text("def ingest():\n    return 'ok'\n", encoding="utf-8")
    (tmp_path / "cli.py").write_text("import argparse\nimport orchestrator\n\nif __name__ == '__main__': orchestrator.run()\n", encoding="utf-8")
    (tmp_path / "gui_app.py").write_text("import tkinter\nimport orchestrator\norchestrator.run()\n", encoding="utf-8")
    result = shared_gui_cli_core_checker.check(tmp_path)
    assert result["status"] == "PASS"


def test_shared_gui_cli_core_checker_fails_without_shared_core(tmp_path: pathlib.Path) -> None:
    (tmp_path / "cli.py").write_text("import argparse\n", encoding="utf-8")
    (tmp_path / "gui_app.py").write_text("import tkinter\n", encoding="utf-8")
    result = shared_gui_cli_core_checker.check(tmp_path)
    assert result["status"] == "FAIL"
    assert "orchestrator.py_missing" in result["blockers"]
    assert "stages.py_missing" in result["blockers"]
