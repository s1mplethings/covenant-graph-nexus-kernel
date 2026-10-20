from __future__ import annotations

import csv

from _helpers import assert_project_hygiene, project_root, run


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerows(rows)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle: return list(csv.reader(handle))


def test_deduplication_contract(tmp_path):
    source = tmp_path / "in.csv"; whole = tmp_path / "whole.csv"; keyed = tmp_path / "key.csv"
    write_csv(source, [["id", "name", "city"], ["1", "Ada", ""], ["1", "Ada", ""], ["1", "Other", "X"], ["2", "", "Y"]])
    first = run("-m", "csv_cleaner", str(source), str(whole))
    assert first.returncode == 0, first.stderr
    assert read_csv(whole) == [["id", "name", "city"], ["1", "Ada", ""], ["1", "Other", "X"], ["2", "", "Y"]]
    second = run("-m", "csv_cleaner", str(source), str(keyed), "--dedupe-column", "id")
    assert second.returncode == 0, second.stderr
    assert read_csv(keyed) == [["id", "name", "city"], ["1", "Ada", ""], ["2", "", "Y"]]


def test_fill_and_preview_contract(tmp_path):
    source = tmp_path / "in.csv"; output = tmp_path / "out.csv"
    write_csv(source, [["id", "name", "city"], ["1", "Ada", ""], ["2", "", "Y"], ["3", "Lin", "Z"]])
    result = run("-m", "csv_cleaner", str(source), str(output), "--fill", "NA", "--preview", "2")
    assert result.returncode == 0, result.stderr
    assert read_csv(output) == [["id", "name", "city"], ["1", "Ada", "NA"], ["2", "NA", "Y"], ["3", "Lin", "Z"]]
    assert result.stdout.splitlines() == ["1,Ada,NA", "2,NA,Y"]


def test_output_and_invalid_input_contract(tmp_path):
    source = tmp_path / "in.csv"; output = tmp_path / "out.csv"
    write_csv(source, [["id", "name"], ["1", "Ada"]])
    valid = run("-m", "csv_cleaner", str(source), str(output))
    assert valid.returncode == 0 and read_csv(output) == [["id", "name"], ["1", "Ada"]]
    missing = run("-m", "csv_cleaner", str(tmp_path / "missing.csv"), str(output))
    assert missing.returncode != 0 and (missing.stderr or missing.stdout).strip()
    unknown = run("-m", "csv_cleaner", str(source), str(output), "--dedupe-column", "missing")
    assert unknown.returncode != 0 and (unknown.stderr or unknown.stdout).strip()
    help_result = run("-m", "csv_cleaner", "--help")
    assert help_result.returncode == 0


def test_readme_and_public_tests():
    root = project_root()
    assert (root / "README.md").is_file()
    assert any((root / "tests").glob("test_*.py"))
    internal = run("-m", "pytest", "-q")
    assert internal.returncode == 0, internal.stdout + internal.stderr


def test_stdlib_and_offline_contract():
    assert_project_hygiene()
