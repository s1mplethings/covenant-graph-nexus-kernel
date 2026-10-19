from __future__ import annotations

import json
import pathlib
import shutil
import sys

from cgkn.application.project_blueprint import BlueprintCheck, BlueprintUnit, ProjectBlueprint
from cgkn.application.project_loop import MinimalProjectLoop
from cgkn.providers import ModelRoleConfig, ProviderCompletion


class QueueClient:
    def __init__(self, responses): self.responses = list(responses); self.calls = []

    def complete(self, *, system, user, schema_name, schema, config):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name, "role": config.role, "operation": config.operation})
        if not self.responses: raise AssertionError("unexpected Provider call")
        return ProviderCompletion(json.dumps(self.responses.pop(0)), config.model, f"req-{len(self.calls)}", {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})


def _bundle(unit_id, files):
    return {"schema_version": "1.0", "kind": "file_bundle", "unit_id": unit_id, "files": [{"path": path, "content": content} for path, content in files.items()], "summary": "generated", "needs_escalation": False, "escalation_reason": ""}


def _patch(unit_id, path, find, replace):
    return {"schema_version": "1.0", "kind": "patch_bundle", "unit_id": unit_id, "patches": [{"path": path, "find": find, "replace": replace}], "summary": "repaired", "needs_escalation": False, "escalation_reason": ""}


def _configs():
    return ModelRoleConfig("agent", "qwen3.8-max"), ModelRoleConfig("worker", "qwen3.7-flash")


def _csv_blueprint() -> ProjectBlueprint:
    units = (
        BlueprintUnit("core", "CSV package", "implementation", ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py"), executor_ref="llm.cheap@1", instruction="implement the complete CSV cleaner package", required_interfaces=("clean_rows",), acceptance=("stable dedupe", "fill", "preview"), allowed_effects=("filesystem.write",)),
        BlueprintUnit("tests", "public tests", "tests", ("tests/test_csv_cleaner.py",), reads=("csv_cleaner/core.py",), depends_on=("core",), executor_ref="llm.cheap@1", instruction="test public behavior", acceptance=("pytest passes",), allowed_effects=("filesystem.write",)),
        BlueprintUnit("docs", "README", "documentation", ("README.md",), depends_on=(), executor_ref="llm.cheap@1", instruction="document exact CLI", acceptance=("usage documented",), allowed_effects=("filesystem.write",)),
    )
    checks = (
        BlueprintCheck("compile", "verification", (sys.executable, "-m", "compileall", "-q", "."), ("core", "tests", "docs"), ("syntax",)),
        BlueprintCheck("pytest", "verification", (sys.executable, "-m", "pytest", "-q"), ("compile",), ("public tests",)),
        BlueprintCheck("accept", "acceptance", (), ("pytest",), ("hidden acceptance",)),
    )
    return ProjectBlueprint("1.0", "cli_csv_cleaner", 1, "Build a stdlib CSV cleaner", ("stdlib only", "offline"), units, checks).freeze()


CORE = '''from __future__ import annotations
import csv

def clean_rows(fieldnames, rows, dedupe_column=None, fill=None):
    if dedupe_column and dedupe_column not in fieldnames:
        raise ValueError(f"unknown column: {dedupe_column}")
    seen = set(); result = []
    for row in rows:
        current = {name: ((row.get(name) or fill) if fill is not None else (row.get(name) or "")) for name in fieldnames}
        key = current[dedupe_column] if dedupe_column else tuple(current[name] for name in fieldnames)
        if key not in seen:
            seen.add(key); result.append(current)
    return result

def clean_file(source, target, dedupe_column=None, fill=None):
    with open(source, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle); fieldnames = list(reader.fieldnames or []); rows = clean_rows(fieldnames, list(reader), dedupe_column, fill)
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames); writer.writeheader(); writer.writerows(rows)
    return fieldnames, rows
'''

MAIN = '''import argparse, csv, sys
from .core import clean_file

def main(argv=None):
    parser = argparse.ArgumentParser(description="Clean CSV files")
    parser.add_argument("input"); parser.add_argument("output")
    parser.add_argument("--dedupe-column"); parser.add_argument("--fill"); parser.add_argument("--preview", type=int, default=0)
    args = parser.parse_args(argv)
    try: fieldnames, rows = clean_file(args.input, args.output, args.dedupe_column, args.fill)
    except (OSError, ValueError) as exc: parser.error(str(exc))
    if args.preview:
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, lineterminator="\\n"); writer.writeheader(); writer.writerows(rows[:args.preview])
    return 0

if __name__ == "__main__": raise SystemExit(main())
'''


def test_fake_greenfield_runs_real_filesystem_pytest_and_hidden_acceptance(tmp_path: pathlib.Path) -> None:
    client = QueueClient([
        _bundle("core", {"csv_cleaner/__init__.py": "from .core import clean_file, clean_rows\n__all__=['clean_file','clean_rows']\n", "csv_cleaner/__main__.py": MAIN, "csv_cleaner/core.py": CORE}),
        _bundle("docs", {"README.md": "# CSV Cleaner\n\n`python -m csv_cleaner INPUT OUTPUT [--dedupe-column COLUMN] [--fill VALUE] [--preview N]`\n"}),
        _bundle("tests", {"tests/test_csv_cleaner.py": "from csv_cleaner.core import clean_rows\ndef test_dedupe():\n assert clean_rows(['id'],[{'id':'1'},{'id':'1'}]) == [{'id':'1'}]\n"}),
    ])
    agent, worker = _configs(); workspace = tmp_path / "workspace"
    outcome = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", client, agent, worker).run(_csv_blueprint(), workspace, case_id="cli_csv_cleaner")
    assert outcome.status == "SUCCEEDED"
    assert outcome.provider_calls == 3 and outcome.repair_rounds == 0
    assert (workspace / "csv_cleaner/core.py").is_file()


def test_fake_repair_preserves_blueprint_and_reruns_only_owner_and_checks(tmp_path: pathlib.Path) -> None:
    units = (BlueprintUnit("core", "math implementation", "implementation", ("math_utils.py",), executor_ref="llm.cheap@1", instruction="implement add", required_interfaces=("add",), acceptance=("addition",), allowed_effects=("filesystem.write",)),)
    checks = (BlueprintCheck("pytest", "verification", (sys.executable, "-m", "pytest", "-q"), ("core",), ("public tests",)), BlueprintCheck("accept", "acceptance", (), ("pytest",), ("hidden",)))
    blueprint = ProjectBlueprint("1.0", "seeded_repair", 1, "repair arithmetic", ("smallest change",), units, checks).freeze()
    client = QueueClient([_bundle("core", {"math_utils.py": "def add(a, b):\n    return a - b\n"}), _patch("core", "math_utils.py", "return a - b", "return a + b")])
    workspace = tmp_path / "workspace"; workspace.mkdir(); (workspace / "test_math_utils.py").write_text("from math_utils import add\ndef test_add(): assert add(2,3)==5\n", encoding="utf-8")
    agent, worker = _configs(); outcome = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", client, agent, worker).run(blueprint, workspace, case_id="seeded_repair")
    assert outcome.status == "SUCCEEDED" and outcome.repair_rounds == 1
    assert outcome.blueprint.project_id == blueprint.project_id and outcome.blueprint.revision == blueprint.revision
    assert outcome.failure_reports[0].unit_id == "core"
    assert outcome.summary.actual_executions == ("core", "pytest", "accept")
    assert "return a + b" in (workspace / "math_utils.py").read_text(encoding="utf-8")
