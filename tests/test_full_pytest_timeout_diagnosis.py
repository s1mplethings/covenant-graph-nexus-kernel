from __future__ import annotations

import pathlib
import sys

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.benchmark]

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.full_pytest_timeout_diagnosis import diagnose_full_pytest_timeout


def test_full_pytest_timeout_diagnosis_records_file_timings(tmp_path: pathlib.Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fast.py").write_text("def test_fast():\n    assert True\n", encoding="utf-8")

    summary = diagnose_full_pytest_timeout(out_dir=tmp_path / "diag", per_file_timeout=20, max_total_seconds=60, tests_dir=tests_dir)

    assert summary["collected_test_files"] == 1
    assert summary["completed_files"] == 1
    assert (tmp_path / "diag" / "full_pytest_file_timings.json").exists()
    assert (tmp_path / "diag" / "recommendations.md").exists()
