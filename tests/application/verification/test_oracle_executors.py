from __future__ import annotations

from pathlib import Path
import sys

import pytest

from cgkn.application.requirements import CSV_DEPENDENCY_POLICY, compile_csv_cleaner
from cgkn.application.verification import OracleExecutor, OracleKind, OraclePlanCompiler, OracleSpec, OracleStatus


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def project(root: Path) -> Path:
    write(root / "csv_cleaner/__init__.py", "from .core import clean\n")
    write(root / "csv_cleaner/core.py", '''import csv

def clean(input_path, output_path, column=None, fill=None):
    with open(input_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    header, data = rows[0], rows[1:]
    if column is not None and column not in header:
        raise ValueError("unknown column: " + column)
    index = header.index(column) if column else None
    seen = set()
    cleaned = []
    for row in data:
        key = row[index] if index is not None else tuple(row)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append([fill if fill is not None and value == "" else value for value in row])
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([header, *cleaned])
    return header, cleaned
''')
    write(root / "csv_cleaner/__main__.py", '''import argparse
import csv
import sys
from .core import clean

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--dedupe-column")
    parser.add_argument("--fill")
    parser.add_argument("--preview", type=int)
    args = parser.parse_args()
    try:
        header, rows = clean(args.input, args.output, args.dedupe_column, args.fill)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.preview is not None:
        csv.writer(sys.stdout, lineterminator="\\n").writerows([header, *rows[:args.preview]])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
''')
    write(root / "tests/test_csv_cleaner.py", '''import csv
from csv_cleaner import clean

def test_clean(tmp_path):
    source = tmp_path / "in.csv"
    target = tmp_path / "out.csv"
    source.write_text("id,name\\n1,A\\n1,A\\n", encoding="utf-8")
    clean(source, target)
    assert list(csv.reader(target.open())) == [["id", "name"], ["1", "A"]]
''')
    write(root / "README.md", "Run `python -m csv_cleaner input.csv output.csv` with `--dedupe-column`, `--fill`, and `--preview`.\n")
    return root


def oracle(kind: OracleKind, **updates) -> OracleSpec:
    values = {
        "oracle_id": f"ORACLE-{kind.value.replace('_', '-')}-TEST",
        "obligation_ids": ("OBL-TEST-001",),
        "oracle_kind": kind,
        "subject_ref": "fixture",
        "operation": {},
        "expected": {"ok": True},
    }
    values.update(updates)
    return OracleSpec(**values)


def test_complete_csv_plan_passes_all_seven_bounded_executor_kinds(tmp_path: Path) -> None:
    workspace = project(tmp_path / "project")
    compiled = compile_csv_cleaner()
    plan = OraclePlanCompiler().compile_csv(compiled.obligations, CSV_DEPENDENCY_POLICY)
    evidence = OracleExecutor((CSV_DEPENDENCY_POLICY,)).execute_plan(plan, workspace)
    assert {item.status for item in evidence} == {OracleStatus.PASS}, "\n".join(
        f"{item.oracle_id}: {item.status.value}: {dict(item.observed)}" for item in evidence
    )
    assert len(evidence) == len(plan.specs)


def test_command_supports_exact_stdout_stdin_and_env_allowlist(tmp_path: Path) -> None:
    spec = oracle(
        OracleKind.COMMAND,
        operation={"argv": [sys.executable, "-c", "import os,sys; print(os.environ['ORACLE_FLAG'] + sys.stdin.read())"], "stdin": "-ok", "env": {"ORACLE_FLAG": "yes"}, "env_allowlist": ["ORACLE_FLAG"]},
        expected={"exit_code": 0, "stdout_exact": "yes-ok"},
    )
    assert OracleExecutor().execute(spec, tmp_path).status is OracleStatus.PASS
    denied = oracle(OracleKind.COMMAND, operation={"argv": [sys.executable, "-c", "print('x')"], "env": {"SECRET": "x"}}, expected={"exit_code": 0})
    assert OracleExecutor().execute(denied, tmp_path).status is OracleStatus.HARNESS_FAILURE
    shell = oracle(OracleKind.COMMAND, operation={"argv": [sys.executable, "-c", "print('x')"], "shell": True}, expected={"exit_code": 0})
    assert OracleExecutor().execute(shell, tmp_path).status is OracleStatus.HARNESS_FAILURE


def test_command_rejects_unexpected_stdout(tmp_path: Path) -> None:
    spec = oracle(OracleKind.COMMAND, operation={"argv": [sys.executable, "-c", "print('unexpected')"]}, expected={"exit_code": 0, "stdout_exact": "expected"})
    result = OracleExecutor().execute(spec, tmp_path)
    assert result.status is OracleStatus.FAIL
    assert "stdout exact mismatch" in result.observed["assertion_errors"]


def test_command_timeout_and_missing_binary_are_not_pass(tmp_path: Path) -> None:
    timeout = oracle(OracleKind.COMMAND, operation={"argv": [sys.executable, "-c", "import time; time.sleep(2)"]}, expected={"exit_code": 0}, timeout_seconds=0.05)
    timed = OracleExecutor().execute(timeout, tmp_path)
    assert timed.status is OracleStatus.FAIL and timed.failure_class == "TIMEOUT"
    missing = oracle(OracleKind.COMMAND, operation={"argv": ["definitely-not-a-command-12345"]}, expected={"exit_code": 0})
    assert OracleExecutor().execute(missing, tmp_path).status is OracleStatus.BLOCKED_ENVIRONMENT


def test_file_oracle_detects_missing_empty_content_and_path_escape(tmp_path: Path) -> None:
    missing = oracle(OracleKind.FILE, operation={"path": "README.md"}, expected={"exists": True})
    assert OracleExecutor().execute(missing, tmp_path).status is OracleStatus.FAIL
    write(tmp_path / "README.md", "")
    empty = oracle(OracleKind.FILE, operation={"path": "README.md"}, expected={"exists": True, "nonempty": True})
    assert OracleExecutor().execute(empty, tmp_path).status is OracleStatus.FAIL
    escape = oracle(OracleKind.FILE, operation={"path": "../outside.txt"}, expected={"exists": True})
    assert OracleExecutor().execute(escape, tmp_path).status is OracleStatus.HARNESS_FAILURE


def test_csv_oracle_rejects_wrong_rows_and_wrong_order(tmp_path: Path) -> None:
    workspace = project(tmp_path)
    spec = oracle(
        OracleKind.CSV,
        setup={"input_path": "input.csv", "output_path": "output.csv", "header": ["id"], "rows": [["2"], ["1"]]},
        operation={"argv": ["python", "-m", "csv_cleaner", "input.csv", "output.csv"]},
        expected={"exit_code": 0, "header": ["id"], "rows": [["1"], ["2"]]},
    )
    result = OracleExecutor().execute(spec, workspace)
    assert result.status is OracleStatus.FAIL
    assert "CSV rows or order mismatch" in result.observed["assertion_errors"]


def test_cli_rejects_invalid_column_returning_zero_and_missing_stderr(tmp_path: Path) -> None:
    write(tmp_path / "bad.py", "from pathlib import Path\nPath('output.csv').write_text('id\\n1\\n')\n")
    spec = oracle(
        OracleKind.CLI,
        setup={"input_path": "input.csv", "output_path": "output.csv", "header": ["id"], "rows": [["1"]]},
        operation={"commands": [{"argv": [sys.executable, "bad.py"]}]},
        expected={"exit_code": "nonzero", "stderr": "nonempty"},
        forbidden={"successful_output_commit": True},
        side_effect_assertions={"output_created": False},
    )
    result = OracleExecutor().execute(spec, tmp_path)
    assert result.status is OracleStatus.FAIL
    assert result.return_code == 0
    assert "stderr is empty" in result.observed["assertion_errors"]
    assert "forbidden output side effect observed" in result.observed["assertion_errors"]


@pytest.mark.parametrize(
    ("path", "content", "domain", "expected"),
    [
        ("csv_cleaner/core.py", "import pytest\n", "runtime", OracleStatus.FAIL),
        ("tests/test_ok.py", "import pytest\n", "test", OracleStatus.PASS),
        ("csv_cleaner/core.py", "import requests\n", "runtime", OracleStatus.FAIL),
        ("tests/test_bad.py", "import requests\n", "test", OracleStatus.FAIL),
    ],
)
def test_dependency_oracle_is_domain_aware(tmp_path: Path, path: str, content: str, domain: str, expected: OracleStatus) -> None:
    write(tmp_path / path, content)
    spec = oracle(
        OracleKind.DEPENDENCY,
        operation={"domain": domain, "paths": [path]},
        expected={"policy": "enforced"},
        dependency_policy_refs=(CSV_DEPENDENCY_POLICY.policy_id,),
    )
    assert OracleExecutor((CSV_DEPENDENCY_POLICY,)).execute(spec, tmp_path).status is expected


def test_static_python_detects_syntax_placeholder_todo_absolute_and_missing_entrypoint(tmp_path: Path) -> None:
    write(tmp_path / "pkg/core.py", "# TODO C:/secret/file\nraise NotImplementedError\n")
    spec = oracle(
        OracleKind.STATIC_PYTHON,
        operation={"paths": ["pkg/**/*.py"], "placeholder_scan": True, "todo_scan": True, "absolute_path_scan": True, "entrypoint": "pkg/__main__.py"},
        expected={"compile": True},
    )
    result = OracleExecutor().execute(spec, tmp_path)
    assert result.status is OracleStatus.FAIL
    errors = tuple(result.observed["assertion_errors"])
    assert any(item.startswith("placeholder:") for item in errors)
    assert any(item.startswith("todo:") for item in errors)
    assert any(item.startswith("absolute_path:") for item in errors)
    assert "entrypoint missing" in errors


def test_documentation_oracle_is_objective_and_blocks_hidden_paths(tmp_path: Path) -> None:
    missing = oracle(OracleKind.DOCUMENTATION, operation={"path": "README.md"}, expected={"exists": True, "contains": ["python -m app"]})
    assert OracleExecutor().execute(missing, tmp_path).status is OracleStatus.FAIL
    write(tmp_path / "README.md", "python -m app\nhidden acceptance\n")
    exposed = oracle(OracleKind.DOCUMENTATION, operation={"path": "README.md"}, expected={"exists": True, "contains": ["python -m app"]}, forbidden={"contains": ["hidden acceptance"]})
    assert OracleExecutor().execute(exposed, tmp_path).status is OracleStatus.FAIL
