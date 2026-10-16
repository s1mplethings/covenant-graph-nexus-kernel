from __future__ import annotations

import csv

from _helpers import assert_project_hygiene, project_root, run


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerows(rows)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle: return list(csv.reader(handle))


def test_cli_contract(tmp_path):
    root = project_root(); assert_project_hygiene()
    assert run("-m", "csv_cleaner", "--help").returncode == 0
    source = tmp_path / "in.csv"; whole = tmp_path / "whole.csv"; keyed = tmp_path / "key.csv"
    write_csv(source, [["id", "name", "city"], ["1", "Ada", ""], ["1", "Ada", ""], ["1", "Other", "X"], ["2", "", "Y"]])
    first = run("-m", "csv_cleaner", str(source), str(whole), "--fill", "NA", "--preview", "2")
    assert first.returncode == 0, first.stderr
    assert read_csv(whole) == [["id", "name", "city"], ["1", "Ada", "NA"], ["1", "Other", "X"], ["2", "NA", "Y"]]
    assert "Ada" in first.stdout and "NA" in first.stdout
    second = run("-m", "csv_cleaner", str(source), str(keyed), "--dedupe-column", "id")
    assert second.returncode == 0, second.stderr
    assert read_csv(keyed) == [["id", "name", "city"], ["1", "Ada", ""], ["2", "", "Y"]]
    invalid = run("-m", "csv_cleaner", str(source), str(tmp_path / "bad.csv"), "--dedupe-column", "missing")
    assert invalid.returncode != 0 and (invalid.stderr or invalid.stdout).strip()


def test_malformed_csv_and_public_tests(tmp_path):
    malformed = tmp_path / "bad.csv"; malformed.write_text('a,b\n"unterminated,b\n', encoding="utf-8")
    result = run("-m", "csv_cleaner", str(malformed), str(tmp_path / "out.csv"))
    assert result.returncode != 0
    internal = run("-m", "pytest", "-q")
    assert internal.returncode == 0, internal.stdout + internal.stderr
