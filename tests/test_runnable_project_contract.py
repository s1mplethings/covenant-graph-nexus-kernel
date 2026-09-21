from __future__ import annotations

import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import customer_runtime_runner, runnable_project_contract


def test_docs_only_zip_fails(tmp_path: pathlib.Path) -> None:
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("README.md", "# Demo\n")
        zf.writestr("report.json", "{}")
    result = runnable_project_contract.evaluate_project(bundle)
    assert result["verdict"] == "FAIL"
    assert "entrypoint" in result["missing"]


def test_runnable_static_project_passes_with_runtime_evidence(tmp_path: pathlib.Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n\nRun `python -m http.server 8000`.\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("<h1>ok</h1>\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    result = runnable_project_contract.evaluate_project(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "customer_runtime_evidence" in result["missing"]
    customer_runtime_runner.run(tmp_path)
    result = runnable_project_contract.evaluate_project(tmp_path)
    assert result["verdict"] == "PASS"


def test_readme_command_without_entrypoint_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n\nRun `python app.py`.\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    result = runnable_project_contract.evaluate_project(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "entrypoint" in result["missing"]
