from __future__ import annotations

import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import runnable_project_contract


def test_docs_only_zip_fails(tmp_path: pathlib.Path) -> None:
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("README.md", "# Demo\n")
        zf.writestr("report.json", "{}")
    result = runnable_project_contract.evaluate_project(bundle)
    assert result["verdict"] == "FAIL"
    assert "entrypoint" in result["missing"]


def test_runnable_python_project_passes(tmp_path: pathlib.Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n\nRun `python app.py`.\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    result = runnable_project_contract.evaluate_project(tmp_path)
    assert result["verdict"] == "PASS"


def test_readme_command_without_entrypoint_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n\nRun `python app.py`.\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    result = runnable_project_contract.evaluate_project(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "entrypoint" in result["missing"]
