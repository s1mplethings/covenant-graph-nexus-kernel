from __future__ import annotations

import json
from typing import Any, Mapping

from cgkn.providers import ProviderCompletion


CLI_CORE = '''from __future__ import annotations

import csv
from collections.abc import Iterable

def clean_csv(input_path, output_path, dedupe_column=None, fill=""):
    with open(input_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, strict=True)
        if not reader.fieldnames:
            raise ValueError("CSV header is required")
        fields = list(reader.fieldnames)
        if dedupe_column is not None and dedupe_column not in fields:
            raise ValueError(f"unknown dedupe column: {dedupe_column}")
        rows, seen = [], set()
        for raw in reader:
            row = {name: (fill if raw.get(name, "") == "" and fill else raw.get(name, "")) for name in fields}
            key = row[dedupe_column] if dedupe_column else tuple(row[name] for name in fields)
            if key not in seen:
                seen.add(key); rows.append(row)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    return fields, rows
'''

CLI_MAIN = '''from __future__ import annotations

import argparse
import csv
import io
import sys
from csv_cleaner.core import clean_csv

def main(argv=None):
    parser = argparse.ArgumentParser(description="Clean a CSV file")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--dedupe-column")
    parser.add_argument("--fill", default="")
    parser.add_argument("--preview", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        fields, rows = clean_csv(args.input, args.output, args.dedupe_column, args.fill)
        if args.preview:
            stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\\n"); writer.writerows(rows[:args.preview]); sys.stdout.write(stream.getvalue())
        return 0
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))

if __name__ == "__main__":
    raise SystemExit(main())
'''

CLI_TESTS = '''from __future__ import annotations
import csv
import subprocess
import sys

def write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle: csv.writer(handle).writerows(rows)

def read(path):
    with path.open(newline="", encoding="utf-8") as handle: return list(csv.reader(handle))

def test_whole_and_column_dedupe(tmp_path):
    source=tmp_path/"in.csv"; out=tmp_path/"out.csv"; write(source, [["id","name"],["1","Ada"],["1","Ada"],["1","Other"]])
    done=subprocess.run([sys.executable,"-m","csv_cleaner",str(source),str(out)],text=True,capture_output=True)
    assert done.returncode == 0 and read(out) == [["id","name"],["1","Ada"],["1","Other"]]
    done=subprocess.run([sys.executable,"-m","csv_cleaner",str(source),str(out),"--dedupe-column","id"],text=True,capture_output=True)
    assert done.returncode == 0 and read(out) == [["id","name"],["1","Ada"]]
'''


class ScriptedSemanticProvider:
    """Same deterministic Provider behavior for all three design adapters."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: Any) -> ProviderCompletion:
        payload = json.loads(user)
        self.calls.append({"schema_name": schema_name, "role": config.role, "model": config.model})
        if schema_name == "semantic_experiment_plan":
            value = {"decision_id": "fake-plan", "accepted": True, "unit_order": payload["allowed_unit_ids"], "rationale": "preserve declared cohesive units"}
        elif schema_name == "semantic_experiment_repair":
            value = {"decision_id": "fake-repair", "target_unit": payload["allowed_repair_units"][0], "reason": "repair deterministically attributed owner"}
        elif schema_name == "cgkn_semantic_worker":
            node = payload["node_id"]
            if node == "cli-core":
                actions = [{"action": "write_file", "path": "csv_cleaner/__init__.py", "content": "from csv_cleaner.core import clean_csv\n__all__ = ['clean_csv']\n"},
                           {"action": "write_file", "path": "csv_cleaner/__main__.py", "content": CLI_MAIN},
                           {"action": "write_file", "path": "csv_cleaner/core.py", "content": CLI_CORE}]
            elif node == "public-tests":
                actions = [{"action": "write_file", "path": "tests/test_csv_cleaner.py", "content": CLI_TESTS}]
            elif node == "documentation":
                actions = [{"action": "write_file", "path": "README.md", "content": "# CSV Cleaner\n\nRun `python -m csv_cleaner INPUT OUTPUT [--dedupe-column COLUMN] [--fill VALUE] [--preview N]`.\n"}]
            else:
                actions = [{"action": "patch_file", "path": "math_utils.py", "find": "return a - b", "replace": "return a + b"}]
            value = {"schema_version": "1.0", "node_id": node, "summary": "bounded semantic work unit", "actions": actions,
                     "expected_outputs": ["declared contract satisfied"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
        else:
            raise AssertionError(f"unexpected schema: {schema_name}")
        return ProviderCompletion(json.dumps(value), config.model, f"fake-{len(self.calls)}", {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20})
