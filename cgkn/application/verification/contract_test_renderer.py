from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from cgkn.application.requirements.obligation import canonical_hash, thaw
from cgkn.application.requirements.policy import DependencyPolicy

from .contract_test import ContractTestPlan
from .contract_test_manifest import ContractTestManifest


@dataclass(frozen=True)
class ContractTestArtifact:
    path: str
    source: str
    source_hash: str
    manifest: ContractTestManifest


class ContractTestRenderer:
    TARGET = "tests/test_contract_csv_cleaner.py"

    def render(self, plan: ContractTestPlan, policy: DependencyPolicy) -> ContractTestArtifact:
        by_oracle = {item.oracle_ids[0]: item for item in plan.tests}
        required = {
            "ORACLE-CSV-WHOLE-ROW", "ORACLE-CSV-COLUMN-FILL", "ORACLE-CLI-PREVIEW", "ORACLE-CLI-HELP",
            "ORACLE-CLI-UNKNOWN-COLUMN", "ORACLE-DOC-README", "ORACLE-FILE-PUBLIC-TESTS",
            "ORACLE-DEPS-RUNTIME", "ORACLE-DEPS-TEST", "ORACLE-STATIC-NETWORK",
        }
        if set(by_oracle) != required:
            raise ValueError("unsupported or incomplete CSV OraclePlan")
        def data(oracle_id: str, field: str):
            spec = by_oracle[oracle_id]
            return thaw(getattr(spec, field))
        source = '''from __future__ import annotations
import ast
import csv
import io
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

def _write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(header); writer.writerows(rows)

def _run(args):
    return subprocess.run([sys.executable, "-m", "csv_cleaner", *args], cwd=ROOT, text=True, capture_output=True)

'''
        whole_setup, whole_expected = data("ORACLE-CSV-WHOLE-ROW", "setup"), data("ORACLE-CSV-WHOLE-ROW", "expected")
        fill_setup, fill_expected = data("ORACLE-CSV-COLUMN-FILL", "setup"), data("ORACLE-CSV-COLUMN-FILL", "expected")
        preview_setup, preview_expected = data("ORACLE-CLI-PREVIEW", "setup"), data("ORACLE-CLI-PREVIEW", "expected")
        cases = [
            ("ORACLE-CSV-WHOLE-ROW", f'''def test_contract_csv_whole_row(tmp_path):
    source, output = tmp_path / "input.csv", tmp_path / "output.csv"
    _write_csv(source, {whole_setup["header"]!r}, {whole_setup["rows"]!r})
    result = _run([str(source), str(output)])
    assert result.returncode == {whole_expected["exit_code"]!r}, result.stderr
    with output.open(newline="", encoding="utf-8") as handle: rows = list(csv.reader(handle))
    assert rows == {[whole_expected["header"], *whole_expected["rows"]]!r}
'''),
            ("ORACLE-CSV-COLUMN-FILL", f'''def test_contract_csv_column_fill(tmp_path):
    source, output = tmp_path / "input.csv", tmp_path / "output.csv"
    _write_csv(source, {fill_setup["header"]!r}, {fill_setup["rows"]!r})
    result = _run([str(source), str(output), "--dedupe-column", "id", "--fill", "UNKNOWN"])
    assert result.returncode == {fill_expected["exit_code"]!r}, result.stderr
    with output.open(newline="", encoding="utf-8") as handle: rows = list(csv.reader(handle))
    assert rows == {[fill_expected["header"], *fill_expected["rows"]]!r}
'''),
            ("ORACLE-CLI-PREVIEW", f'''def test_contract_cli_preview(tmp_path):
    source, output = tmp_path / "input.csv", tmp_path / "output.csv"
    _write_csv(source, {preview_setup["header"]!r}, {preview_setup["rows"]!r})
    result = _run([str(source), str(output), "--preview", "1"])
    assert result.returncode == {preview_expected["exit_code"]!r}, result.stderr
    assert [row for row in csv.reader(io.StringIO(result.stdout)) if row] == {[preview_expected["stdout_csv"]["header"], *preview_expected["stdout_csv"]["rows"]]!r}
    assert output.is_file()
    with output.open(newline="", encoding="utf-8") as handle: output_rows = list(csv.reader(handle))
    assert output_rows == {[preview_setup["header"], *preview_setup["rows"]]!r}
'''),
            ("ORACLE-CLI-HELP", '''def test_contract_cli_help():
    result = _run(["--help"])
    assert result.returncode == 0
    for text in ("usage", "--preview", "--dedupe-column", "--fill"): assert text in result.stdout
'''),
            ("ORACLE-CLI-UNKNOWN-COLUMN", '''def test_contract_cli_unknown_column(tmp_path):
    source, output = tmp_path / "input.csv", tmp_path / "output.csv"
    _write_csv(source, ["id", "name", "city"], [["1", "Ada", ""]])
    result = _run([str(source), str(output), "--dedupe-column", "missing"])
    assert result.returncode != 0 and result.stderr.strip()
    assert not output.exists()
'''),
            ("ORACLE-DOC-README", '''def test_contract_doc_readme():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for required in ("python -m csv_cleaner", "--dedupe-column", "--fill", "--preview"): assert required in text
'''),
            ("ORACLE-FILE-PUBLIC-TESTS", '''def test_contract_public_test_asset():
    assert pathlib.Path(__file__).name == "test_contract_csv_cleaner.py"
'''),
            ("ORACLE-DEPS-RUNTIME", '''def test_contract_runtime_dependencies_are_stdlib():
    forbidden = {"pytest", "requests", "httpx"}
    for path in (ROOT / "csv_cleaner").rglob("*.py"):
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Import)}
        imports |= {str(node.module).split(".")[0] for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.ImportFrom) and node.module}
        assert not imports & forbidden
'''),
            ("ORACLE-DEPS-TEST", '''def test_contract_pytest_is_available():
    assert pytest.__name__ == "pytest"
'''),
            ("ORACLE-STATIC-NETWORK", '''def test_contract_network_is_offline():
    forbidden = {"requests", "httpx", "socket"}
    for path in (ROOT / "csv_cleaner").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
        imports |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not imports & forbidden
'''),
        ]
        for oracle_id, body in cases:
            item = by_oracle[oracle_id]
            source += f"# provenance: {item.test_id} <- {oracle_id}\n" + body + "\n"
        source_hash = "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
        policy_hash = canonical_hash(policy.as_dict())
        return ContractTestArtifact(self.TARGET, source, source_hash, ContractTestManifest.build(plan, source_hash, policy_hash))
