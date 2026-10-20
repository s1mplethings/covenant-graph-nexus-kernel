from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

import pytest

from cgkn.application.requirements import (
    CSV_DEPENDENCY_POLICY,
    ObligationDAGService,
    TestPlanCompiler,
    compile_csv_cleaner,
    compile_csv_work_units,
    validate_dependency_actions,
)
from cgkn.application.software_project.scope import ScopeViolation
from cgkn.providers import ModelRoleConfig, ProviderCompletion


CORE = '''from __future__ import annotations
import csv

def clean_csv(input_path, output_path, dedupe_column=None, fill=""):
    with open(input_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if dedupe_column is not None and dedupe_column not in fields:
            raise ValueError(f"unknown dedupe column: {dedupe_column}")
        rows, seen = [], set()
        for raw in reader:
            row = {name: fill if raw.get(name, "") == "" and fill else raw.get(name, "") for name in fields}
            key = row[dedupe_column] if dedupe_column else tuple(row[name] for name in fields)
            if key not in seen:
                seen.add(key); rows.append(row)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    return fields, rows
'''

MAIN = '''from __future__ import annotations
import argparse, csv, io, sys
from csv_cleaner.core import clean_csv

def main(argv=None):
    parser = argparse.ArgumentParser(description="Clean a CSV file")
    parser.add_argument("input"); parser.add_argument("output")
    parser.add_argument("--dedupe-column"); parser.add_argument("--fill", default="")
    parser.add_argument("--preview", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        fields, rows = clean_csv(args.input, args.output, args.dedupe_column, args.fill)
        if args.preview:
            stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\\n")
            writer.writerows(rows[:args.preview]); sys.stdout.write(stream.getvalue())
        return 0
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
if __name__ == "__main__": raise SystemExit(main())
'''

TESTS = '''import csv
import pytest
from csv_cleaner.core import clean_csv

def test_clean_csv(tmp_path):
    source=tmp_path/"in.csv"; output=tmp_path/"out.csv"
    with source.open("w", newline="", encoding="utf-8") as handle: csv.writer(handle).writerows([["id","name"],["1",""]])
    fields, rows = clean_csv(source, output, fill="NA")
    assert fields == ["id", "name"] and rows == [{"id":"1", "name":"NA"}]

def test_unknown_column(tmp_path):
    source=tmp_path/"in.csv"; output=tmp_path/"out.csv"
    source.write_text("id,name\\n1,Ada\\n", encoding="utf-8")
    with pytest.raises(ValueError): clean_csv(source, output, dedupe_column="missing")
'''


class FakeObligationProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: Any) -> ProviderCompletion:
        payload = json.loads(user); node = payload["node_id"]
        self.calls.append(payload)
        if node == "WU-CORE":
            actions = [
                {"action": "write_file", "path": "csv_cleaner/__init__.py", "content": "from .core import clean_csv\n__all__ = ['clean_csv']\n"},
                {"action": "write_file", "path": "csv_cleaner/__main__.py", "content": MAIN},
                {"action": "write_file", "path": "csv_cleaner/core.py", "content": CORE},
            ]
        else:
            actions = [{"action": "write_file", "path": "README.md", "content": "# CSV Cleaner\n\nUse `python -m csv_cleaner INPUT OUTPUT [--dedupe-column COLUMN] [--fill VALUE] [--preview N]`.\n"}]
        value = {"schema_version": "1.0", "node_id": node, "summary": "implemented declared obligations", "actions": actions, "expected_outputs": ["contract satisfied"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
        return ProviderCompletion(json.dumps(value), config.model, f"fake-{len(self.calls)}", {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20})


def test_work_units_and_test_plan_are_complete_and_bounded() -> None:
    compilation = compile_csv_cleaner()
    units = compile_csv_work_units(compilation)
    assert [item.work_unit_id for item in units] == ["WU-CORE", "WU-TESTS", "WU-DOCS"]
    assert units[0].target_paths == ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py")
    assert units[0].interface_contract_refs == (
        "INTERFACE-CSV-MODULE-001", "INTERFACE-CSV-CLEAN-FUNCTION-001", "INTERFACE-CSV-CLI-001"
    )
    assert units[2].depends_on == ()
    assert units[2].allowed_read_paths == ()
    assert units[2].interface_contract_refs == ("INTERFACE-CSV-CLI-001",)
    assert set().union(*(set(item.obligation_ids) for item in units)) == {item.obligation_id for item in compilation.obligations.obligations}
    plan = TestPlanCompiler().compile(compilation.obligations)
    assert len(plan.cases) == len(compilation.obligations.obligations)
    assert all(item.obligation_ids for item in plan.cases)


def test_fake_provider_dag_passes_compile_public_runtime_and_hidden(tmp_path) -> None:
    provider = FakeObligationProvider()
    result = ObligationDAGService(pathlib.Path.cwd(), provider, ModelRoleConfig("worker", "fake-worker")).run_csv(tmp_path / "workspace", tmp_path / "runs")
    assert result.status == "PASS"
    assert result.provider_calls == 2
    assert (tmp_path / "runs" / "obligation_preflight.json").is_file()
    assert all(call["obligations"] and call["work_unit_contract"] for call in provider.calls)
    assert "import pytest" in (tmp_path / "workspace" / "tests/test_contract_csv_cleaner.py").read_text(encoding="utf-8")
    assert (tmp_path / "workspace" / "tests" / "contract_test_manifest.json").is_file()
    assert {call["node_id"] for call in provider.calls} == {"WU-CORE", "WU-DOCS"}
    core_prompt = next(call for call in provider.calls if call["node_id"] == "WU-CORE")
    assert {item["contract_id"] for item in core_prompt["executable_interface_contracts"]} == {
        "INTERFACE-CSV-MODULE-001", "INTERFACE-CSV-CLEAN-FUNCTION-001", "INTERFACE-CSV-CLI-001"
    }


class CorrectingInterfaceProvider(FakeObligationProvider):
    def __init__(self, workspace: pathlib.Path) -> None:
        super().__init__()
        self.workspace = workspace
        self.core_attempts = 0

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: Any) -> ProviderCompletion:
        payload = json.loads(user)
        if payload["node_id"] != "WU-CORE":
            return super().complete(system=system, user=user, schema_name=schema_name, schema=schema, config=config)
        self.calls.append(payload)
        self.core_attempts += 1
        if self.core_attempts == 2:
            assert not (self.workspace / "csv_cleaner/__main__.py").exists(), "rejected proposal polluted workspace"
            evidence = payload["interface_contract_evidence"]
            assert any(item["failure_class"] == "POSITIONAL_TO_OPTIONAL" for item in evidence)
        main = MAIN if self.core_attempts == 2 else MAIN.replace('parser.add_argument("input"); parser.add_argument("output")', 'parser.add_argument("input"); parser.add_argument("-o", "--output")')
        actions = [
            {"action": "write_file", "path": "csv_cleaner/__init__.py", "content": "from .core import clean_csv\n__all__ = ['clean_csv']\n"},
            {"action": "write_file", "path": "csv_cleaner/__main__.py", "content": main},
            {"action": "write_file", "path": "csv_cleaner/core.py", "content": CORE},
        ]
        value = {"schema_version": "1.0", "node_id": "WU-CORE", "summary": "corrected interface", "actions": actions, "expected_outputs": ["contract satisfied"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
        return ProviderCompletion(json.dumps(value), config.model, f"fake-{len(self.calls)}", {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20})


def test_local_interface_correction_is_staged_and_bounded(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    provider = CorrectingInterfaceProvider(workspace)
    result = ObligationDAGService(pathlib.Path.cwd(), provider, ModelRoleConfig("worker", "fake-worker")).run_csv(workspace, tmp_path / "runs")
    assert result.status == "PASS"
    assert provider.core_attempts == 2
    assert result.provider_calls == 3
    assert 'parser.add_argument("output")' in (workspace / "csv_cleaner/__main__.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("-o", "--output")' not in (workspace / "csv_cleaner/__main__.py").read_text(encoding="utf-8")


def test_dependency_policy_allows_pytest_for_tests_but_rejects_runtime(tmp_path) -> None:
    validate_dependency_actions(tmp_path, [{"action": "write_file", "path": "tests/test_x.py", "content": "import pytest\n"}], CSV_DEPENDENCY_POLICY)
    with pytest.raises(ScopeViolation, match="pytest in runtime"):
        validate_dependency_actions(tmp_path, [{"action": "write_file", "path": "csv_cleaner/core.py", "content": "import pytest\n"}], CSV_DEPENDENCY_POLICY)
