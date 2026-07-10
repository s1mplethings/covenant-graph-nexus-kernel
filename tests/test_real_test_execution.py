from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import real_test_execution


def test_model_written_summary_without_execution_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "TEST_REPORT.md").write_text("# Test Report\n\nlooks good\n", encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"


def test_real_pytest_execution_passes(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def add(a,b): return a+b\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    result = real_test_execution.run_tests(tmp_path)
    assert result["verdict"] == "PASS"
    assert real_test_execution.inspect_test_report(tmp_path)["verdict"] == "PASS"


def test_no_real_execution_marker_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "TEST_REPORT.md").write_text("commands_run:\n- NO REAL TEST EXECUTION\nexit_code: none\nNO REAL TEST EXECUTION\n", encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
