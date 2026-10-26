from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

from cgkn.application.project_blueprint import BlueprintCheck, BlueprintUnit, FailureAction, FailureReport, FailureStage, ProjectBlueprint
from cgkn.application.project_loop import AcceptanceAttributionDecision, BlueprintUnitExecutor, MinimalProjectLoop, _dependency_prompt_projection, compile_blueprint, coordinator_design_request
from cgkn.application.test_authority import PublicContractProjection
from cgkn.application.software_project.catalog import get_case
from cgkn.application.software_project.scope import CommitFailure
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode, TaskContext
from cgkn.orchestration import compile_tree
from cgkn.providers import GatewayCompletionError, ModelRoleConfig, ProviderCompletion
from cgkn.application.project_corpus import ProjectCorpus


class QueueClient:
    def __init__(self, responses): self.responses = list(responses); self.calls = []

    def complete(self, *, system, user, schema_name, schema, config):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name, "schema": schema, "role": config.role, "operation": config.operation, "thinking_mode": config.thinking_mode})
        if not self.responses: raise AssertionError("unexpected Provider call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return ProviderCompletion(json.dumps(response), config.model, f"req-{len(self.calls)}", {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})


class TruncatedClient:
    def complete(self, *, system, user, schema_name, schema, config):
        raise GatewayCompletionError("PROVIDER_OUTPUT_TRUNCATED", "bounded", evidence={
            "request_id": "failed-request-1", "model": "deepseek", "finish_reason": "length",
            "usage": {"prompt_tokens": 31, "completion_tokens": 6000, "total_tokens": 6031},
            "reasoning_tokens": None, "cached_tokens": 4, "transport_attempts": 1,
            "transport_attempts_detail": [{"attempt_id": "transport-1", "status": "COMPLETED"}],
            "thinking_mode_requested": "disabled", "thinking_mode_forwarded": "disabled",
            "schema_hash": "sha256:schema", "prompt_hash": "sha256:prompt",
            "final_status": "PROVIDER_OUTPUT_TRUNCATED",
        })


class FakeAttributor:
    def __init__(self, decisions=(), error=None):
        self.decisions = tuple(decisions); self.error = error; self.calls = []

    def attribute(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.decisions


def _bundle(unit_id, files):
    return {"schema_version": "1.0", "kind": "file_bundle", "unit_id": unit_id, "files": [{"path": path, "content": content} for path, content in files.items()], "summary": "generated", "needs_escalation": False, "escalation_reason": ""}


def _patch(unit_id, path, find, replace):
    return {"schema_version": "2.0", "kind": "patch_bundle", "unit_id": unit_id, "files": [{"path": path, "edits": [{"find": find, "replace": replace}]}]}


def _patch_files(unit_id, files):
    return {"schema_version": "2.0", "kind": "patch_bundle", "unit_id": unit_id, "files": [{"path": path, "edits": [{"find": find, "replace": replace} for find, replace in edits]} for path, edits in files.items()]}


def _configs():
    return ModelRoleConfig("agent", "qwen3.8-max"), ModelRoleConfig("worker", "qwen3.7-flash")


def test_dependency_prompt_projection_excludes_volatile_execution_metadata() -> None:
    stable = {
        "summary": "implemented add",
        "modified_files": ["math_utils.py"],
        "observed_interfaces": {"math_utils.py": {"functions": [{"name": "add"}]}},
        "test_authority_receipt": None,
        "unit_result": {
            "unit_id": "implementation-1",
            "status": "SUCCEEDED",
            "changed_files": ["math_utils.py"],
            "observed_interfaces": ["sha256:interface"],
            "produced_artifact_refs": [],
            "materialized_baseline": True,
            "error": "",
            "duration": 9,
            "result_hash": "sha256:first",
            "provider_usage": {"total_tokens": "30"},
        },
        "context_chars": 100,
        "action_results": [{"action": "write_file", "bytes": 32}],
    }
    later = json.loads(json.dumps(stable))
    later["unit_result"].update({
        "duration": 1042,
        "result_hash": "sha256:second",
        "provider_usage": {"total_tokens": "31"},
    })
    later["context_chars"] = 101

    first = _dependency_prompt_projection({"implementation-1": stable})
    second = _dependency_prompt_projection({"implementation-1": later})

    assert first == second
    rendered = json.dumps(first, sort_keys=True)
    for volatile in ("duration", "result_hash", "provider_usage", "context_chars", "action_results"):
        assert volatile not in rendered


def _csv_blueprint() -> ProjectBlueprint:
    units = (
        BlueprintUnit("core", "CSV package", "implementation", ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py"), executor_ref="llm.cheap@1", instruction="implement the complete CSV cleaner package", required_interfaces=("clean_rows",), acceptance=("stable dedupe", "fill", "preview"), allowed_effects=("filesystem.write",)),
        BlueprintUnit("tests", "public tests", "tests", ("tests/test_csv_cleaner.py",), reads=("csv_cleaner/core.py",), depends_on=("core",), executor_ref="llm.cheap@1", instruction="test public behavior", acceptance=("pytest passes",), allowed_effects=("filesystem.write",)),
        BlueprintUnit("docs", "README", "documentation", ("README.md",), depends_on=(), executor_ref="llm.cheap@1", instruction="document exact CLI", acceptance=("usage documented",), allowed_effects=("filesystem.write",)),
    )
    checks = (
        BlueprintCheck("compile", "verification", (sys.executable, "-m", "compileall", "-q", "."), ("core", "tests", "docs"), ("syntax",)),
        BlueprintCheck("pytest", "verification", (sys.executable, "-m", "pytest", "-q"), ("compile",), ("public tests",)),
        BlueprintCheck("accept", "acceptance", (), ("pytest",), get_case("cli_csv_cleaner").public_acceptance),
    )
    return ProjectBlueprint("1.0", "cli_csv_cleaner", 1, "Build a stdlib CSV cleaner", ("stdlib only", "offline"), units, checks).freeze()


def _materialized_executor(tmp_path: pathlib.Path, blueprint: ProjectBlueprint, *, skip=()) -> BlueprintUnitExecutor:
    executor = BlueprintUnitExecutor(tmp_path, QueueClient([]), _configs()[1])
    for unit in blueprint.units:
        if unit.unit_id in skip:
            continue
        for relative in unit.owns:
            target = tmp_path / relative; target.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith(".py"):
                content = "def clean_rows(*args):\n    return []\n" if relative.endswith("core.py") else "value = 1\n"
            else:
                content = "# README\n"
            target.write_text(content, encoding="utf-8")
        executor.register_materialized_baseline(unit)
    return executor


def _acceptance_failure(*, summary="public behavior", marker="") -> BlockExecutionResult:
    details = {
        "failure_class": "PROJECT_FAILURE",
        "failed_requirement_ids": ["public-requirement-1"],
        "public_requirement_summaries": {"public-requirement-1": summary},
        "requirement_manifest_hash": "sha256:manifest",
        "mapping_complete": True,
    }
    return BlockExecutionResult(
        "p", "r", "a", "external_acceptance", "project.acceptance@1", BlockStatus.FAILED,
        outputs=details | {"stdout": marker},
        error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, "one or more external requirements failed", details),
    )


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
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, lineterminator="\\n"); writer.writerows(rows[:args.preview])
    return 0

if __name__ == "__main__": raise SystemExit(main())
'''


def test_coordinator_request_is_minimal_public_only_and_has_stable_requirement_ids() -> None:
    case = get_case("cli_csv_cleaner")
    contract = {
        "public_goal": case.public_goal,
        "public_acceptance": list(case.public_acceptance),
        "constraints": ["stdlib only", "offline"],
        "entrypoint": case.entrypoint,
        "hidden_acceptance": "DO-NOT-EXPOSE",
        "traceback": "SECRET-TRACE",
    }
    request = coordinator_design_request(contract)
    serialized = json.dumps(request, sort_keys=True)
    assert "DO-NOT-EXPOSE" not in serialized and "SECRET-TRACE" not in serialized
    assert list(request["prompt"]["public_requirements"]) == [
        f"REQ-{index:03d}" for index in range(1, len(case.public_acceptance) + 1)
    ]
    unit_properties = request["schema"]["properties"]["units"]["items"]["properties"]
    assert set(unit_properties) == {"kind", "purpose", "owns", "requirement_ids"}
    assert request["schema"]["additionalProperties"] is False
    assert "do not split tests into separate files by requirement" in request["system"]


def _authority_node_config(unit: BlueprintUnit) -> dict[str, object]:
    return {
        "unit": unit.as_dict(),
        "project_goal": get_case("cli_csv_cleaner").public_goal,
        "public_contract_projection": PublicContractProjection.for_case("cli_csv_cleaner").as_dict(),
        "owned_public_requirement_ids": [f"REQ-{index:03d}" for index in range(1, 6)],
    }


def test_test_authority_conflict_retries_before_atomic_commit(tmp_path: pathlib.Path) -> None:
    unit = BlueprintUnit(
        "tests", "public tests", "tests", ("tests/test_cli.py",),
        executor_ref="llm.cheap@1", instruction="test preview", acceptance=("preview",),
        allowed_effects=("filesystem.write",),
    )
    conflicting = "from types import SimpleNamespace\ndef test_preview():\n result=SimpleNamespace(stdout='id,name,city\\n1,Ada,\\n')\n assert result.stdout == 'id,name,city\\n1,Ada,\\n'\n"
    canonical = "import csv, io\nfrom types import SimpleNamespace\ndef test_preview():\n result=SimpleNamespace(stdout='1,Ada,\\n')\n assert list(csv.reader(io.StringIO(result.stdout))) == [['1','Ada','']]\n"
    client = QueueClient([_bundle("tests", {"tests/test_cli.py": conflicting}), _bundle("tests", {"tests/test_cli.py": canonical})])
    executor = BlueprintUnitExecutor(tmp_path, client, ModelRoleConfig("worker", "deepseek"))
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.tests@1", "llm.cheap@1",
        TaskContext(unit.instruction, node_config=_authority_node_config(unit)),
        declared_effects=unit.allowed_effects,
    )

    result = executor.execute(request)

    assert result.succeeded and len(client.calls) == 2
    assert (tmp_path / "tests/test_cli.py").read_text(encoding="utf-8") == canonical
    assert executor.calls[0]["failure_type"] == "TEST_CONTRACT_CONFLICT"
    assert executor.calls[0]["test_authority_receipt"]["status"] == "FAIL"
    assert executor.calls[1]["test_authority_receipt"]["status"] == "PASS"
    assert "never filter, drop, strip, or normalize parsed rows" in client.calls[0]["system"]
    assert "TEST_CONTRACT_CONFLICT" in client.calls[1]["user"]


def test_implementation_repair_forces_tests_authority_revalidation_before_pytest(tmp_path: pathlib.Path) -> None:
    unit = BlueprintUnit(
        "tests", "public tests", "tests", ("tests/test_cli.py",),
        executor_ref="llm.cheap@1", instruction="test preview", acceptance=("preview",),
        allowed_effects=("filesystem.write",),
    )
    target = tmp_path / "tests/test_cli.py"; target.parent.mkdir(parents=True)
    target.write_text("def test_preview(result):\n assert result.stdout == 'id,name,city\\n1,Ada,\\n'\n", encoding="utf-8")
    executor = BlueprintUnitExecutor(tmp_path, QueueClient([]), ModelRoleConfig("worker", "deepseek"))
    executor.register_materialized_baseline(unit)
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.tests@1", "llm.cheap@1",
        TaskContext(unit.instruction, node_config=_authority_node_config(unit)),
        declared_effects=unit.allowed_effects,
    )

    result = executor.execute(request)

    assert not result.succeeded
    assert result.error.details["failure_type"] == "TEST_CONTRACT_CONFLICT"
    assert result.outputs["test_authority_receipt"]["status"] == "FAIL"
    assert executor.calls == []


def test_tests_staged_pytest_retries_before_atomic_commit(tmp_path: pathlib.Path) -> None:
    unit = BlueprintUnit(
        "tests", "public tests", "tests", ("tests/test_cli.py",),
        executor_ref="llm.cheap@1", instruction="validate public behavior", acceptance=("works",),
        allowed_effects=("filesystem.write",),
    )
    failing = "def test_generated():\n assert False\n"
    passing = "def test_generated():\n assert True\n"
    client = QueueClient([
        _bundle("tests", {"tests/test_cli.py": failing}),
        _bundle("tests", {"tests/test_cli.py": passing}),
    ])
    executor = BlueprintUnitExecutor(tmp_path, client, ModelRoleConfig("worker", "deepseek"))
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.tests@1", "llm.cheap@1",
        TaskContext(unit.instruction, node_config=_authority_node_config(unit)),
        declared_effects=unit.allowed_effects,
    )

    result = executor.execute(request)

    assert result.succeeded and len(client.calls) == 2
    assert executor.calls[0]["failure_type"] == "TEST_FAILURE"
    assert "never switch only to a temporary-data directory" in client.calls[0]["system"]
    assert "TEST_FAILURE" in client.calls[1]["user"]
    assert (tmp_path / "tests/test_cli.py").read_text(encoding="utf-8") == passing


def test_canonical_staged_assertion_failure_routes_to_implementation(tmp_path: pathlib.Path) -> None:
    package = tmp_path / "csv_cleaner"
    package.mkdir()
    (package / "__init__.py").write_text('\"\"\"CSV cleaner.\"\"\"\n', encoding="utf-8")
    (package / "__main__.py").write_text("print('wrong')\n", encoding="utf-8")
    unit = BlueprintUnit(
        "tests", "public tests", "tests", ("tests/test_cli.py",),
        depends_on=("core",), executor_ref="llm.cheap@1", instruction="validate preview",
        acceptance=("preview",), allowed_effects=("filesystem.write",),
    )
    canonical_but_failing = """import csv
import subprocess
import sys

def test_preview_prints_data_rows():
    result = subprocess.run([sys.executable, '-m', 'csv_cleaner', 'input.csv', 'output.csv', '--preview', '1'], capture_output=True, text=True)
    preview_rows = list(csv.reader(result.stdout.splitlines()))
    assert preview_rows == [['1', 'Ada', '']]
"""
    executor = BlueprintUnitExecutor(
        tmp_path,
        QueueClient([_bundle("tests", {"tests/test_cli.py": canonical_but_failing})]),
        ModelRoleConfig("worker", "deepseek"),
    )
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.tests@1", "llm.cheap@1",
        TaskContext(unit.instruction, node_config=_authority_node_config(unit)),
        declared_effects=unit.allowed_effects,
    )

    result = executor.execute(request)

    assert not result.succeeded
    assert result.error.details["failure_type"] == "PUBLIC_CONTRACT_FAILURE"
    assert result.error.details["failure_stage"] == FailureStage.TEST.value
    assert result.error.details["owner_unit_id"] == "core"
    assert not (tmp_path / "tests/test_cli.py").exists()


def test_tests_repair_receives_projection_and_can_replace_wrong_assertion(tmp_path: pathlib.Path) -> None:
    unit = BlueprintUnit(
        "tests", "public tests", "tests", ("tests/test_cli.py",),
        executor_ref="llm.cheap@1", instruction="test preview", acceptance=("preview",),
        allowed_effects=("filesystem.write",),
    )
    old = "from types import SimpleNamespace\ndef test_preview():\n result=SimpleNamespace(stdout='id,name,city\\n1,Ada,\\n')\n assert result.stdout == 'id,name,city\\n1,Ada,\\n'\n"
    new = "import csv, io\nfrom types import SimpleNamespace\ndef test_preview():\n result=SimpleNamespace(stdout='1,Ada,\\n')\n assert list(csv.reader(io.StringIO(result.stdout))) == [['1','Ada','']]\n"
    target = tmp_path / "tests/test_cli.py"; target.parent.mkdir(parents=True); target.write_text(old, encoding="utf-8")
    client = QueueClient([_patch("tests", "tests/test_cli.py", old, new)])
    executor = BlueprintUnitExecutor(tmp_path, client, ModelRoleConfig("worker", "deepseek"))
    executor.register_materialized_baseline(unit)
    executor.failure_reports[unit.unit_id] = FailureReport(
        "pytest", "TEST_CONTRACT_CONFLICT", failure_stage=FailureStage.TEST.value,
        owner_unit_id=unit.unit_id, recovery_action=FailureAction.REPAIR_EXISTING.value,
        materialized_baseline=True, failed_check="pytest", observed="generated assertion conflicts",
    )
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.tests@1", "llm.cheap@1",
        TaskContext(unit.instruction, node_config=_authority_node_config(unit)),
        declared_effects=unit.allowed_effects,
    )

    result = executor.execute(request)

    assert result.succeeded
    assert '"public_contract_projection"' in client.calls[0]["user"]
    assert "modify, weaken, replace, or remove conflicting assertions" in client.calls[0]["system"]
    assert result.outputs["test_authority_receipt"]["status"] == "PASS"
    assert target.read_text(encoding="utf-8") == new


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
    assert all(_csv_blueprint().goal in call["user"] for call in client.calls)


def test_fake_repair_preserves_blueprint_and_reruns_only_owner_and_checks(tmp_path: pathlib.Path) -> None:
    units = (BlueprintUnit("core", "math implementation", "implementation", ("math_utils.py",), executor_ref="llm.cheap@1", instruction="implement add", required_interfaces=("add",), acceptance=("addition",), allowed_effects=("filesystem.write",)),)
    checks = (BlueprintCheck("pytest", "verification", (sys.executable, "-m", "pytest", "-q"), ("core",), ("public tests",)), BlueprintCheck("accept", "acceptance", (), ("pytest",), get_case("seeded_repair").public_acceptance))
    blueprint = ProjectBlueprint("1.0", "seeded_repair", 1, "repair arithmetic", ("smallest change",), units, checks).freeze()
    client = QueueClient([_bundle("core", {"math_utils.py": "def add(a, b):\n    return a - b\n"}), _patch("core", "math_utils.py", "return a - b", "return a + b")])
    workspace = tmp_path / "workspace"; workspace.mkdir(); (workspace / "test_math_utils.py").write_text("from math_utils import add\ndef test_add(): assert add(2,3)==5\n", encoding="utf-8")
    agent, worker = _configs(); outcome = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", client, agent, worker).run(blueprint, workspace, case_id="seeded_repair")
    assert outcome.status == "SUCCEEDED" and outcome.repair_rounds == 1 and outcome.repair_calls == 1
    assert outcome.blueprint.project_id == blueprint.project_id and outcome.blueprint.revision == blueprint.revision
    assert outcome.failure_reports[0].unit_id == "core"
    assert outcome.summary.actual_executions == ("core", "pytest", "accept")
    assert "return a + b" in (workspace / "math_utils.py").read_text(encoding="utf-8")
    assert all(blueprint.goal in call["user"] for call in client.calls)
    assert '"normative_public_contract":"repair arithmetic"' in client.calls[1]["user"]
    assert '"repair_attempt_number":1' in client.calls[1]["user"]
    assert "generated tests as non-authoritative examples" in client.calls[1]["system"]


def test_generation_and_repair_thinking_policies_are_independent(tmp_path: pathlib.Path) -> None:
    units = (BlueprintUnit("core", "math", "implementation", ("math_utils.py",), executor_ref="llm.cheap@1", instruction="implement add", required_interfaces=("add",), acceptance=("addition",), allowed_effects=("filesystem.write",)),)
    checks = (
        BlueprintCheck("pytest", "verification", (sys.executable, "-m", "pytest", "-q"), ("core",), ("tests",)),
        BlueprintCheck("accept", "acceptance", (), ("pytest",), get_case("seeded_repair").public_acceptance),
    )
    blueprint = ProjectBlueprint("1.0", "seeded_repair", 1, "repair", ("smallest change",), units, checks).freeze()
    client = QueueClient([_bundle("core", {"math_utils.py": "def add(a, b):\n    return a - b\n"}), _patch("core", "math_utils.py", "return a - b", "return a + b")])
    workspace = tmp_path / "workspace"; workspace.mkdir()
    (workspace / "test_math_utils.py").write_text("from math_utils import add\ndef test_add(): assert add(2,3)==5\n", encoding="utf-8")
    agent = ModelRoleConfig("agent", "qwen")
    generation = ModelRoleConfig("worker", "deepseek", thinking_mode="disabled")
    repair = ModelRoleConfig("worker", "deepseek", thinking_mode="default")
    outcome = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", client, agent, generation, repair).run(blueprint, workspace, case_id="seeded_repair")
    assert outcome.status == "SUCCEEDED"
    assert [call["thinking_mode"] for call in client.calls] == ["disabled", "default"]


def test_generation_and_repair_use_single_bounded_prompt_projection(tmp_path: pathlib.Path) -> None:
    units = (BlueprintUnit("core", "math", "implementation", ("math_utils.py",), executor_ref="llm.cheap@1", instruction="implement add", required_interfaces=("add",), acceptance=("addition",), allowed_effects=("filesystem.write",)),)
    checks = (
        BlueprintCheck("pytest", "verification", (sys.executable, "-m", "pytest", "-q"), ("core",), ("tests",)),
        BlueprintCheck("accept", "acceptance", (), ("pytest",), get_case("seeded_repair").public_acceptance),
    )
    blueprint = ProjectBlueprint("1.0", "seeded_repair", 1, "repair", ("smallest change",), units, checks).freeze()
    client = QueueClient([_bundle("core", {"math_utils.py": "def add(a, b):\n    return a - b\n"}), _patch("core", "math_utils.py", "return a - b", "return a + b")])
    workspace = tmp_path / "workspace"; workspace.mkdir()
    (workspace / "test_math_utils.py").write_text("from math_utils import add\ndef test_add(): assert add(2,3)==5\n", encoding="utf-8")
    agent = ModelRoleConfig("agent", "qwen")
    worker = ModelRoleConfig("worker", "deepseek", thinking_mode="disabled")
    outcome = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", client, agent, worker, worker).run(blueprint, workspace, case_id="seeded_repair")
    assert outcome.status == "SUCCEEDED"
    generation_prompt, repair_prompt = (json.loads(call["user"]) for call in client.calls)
    assert "AUTHORITATIVE CONTRACT" not in generation_prompt
    assert "AUTHORITATIVE CONTRACT" not in repair_prompt
    assert generation_prompt["current_files"] == {}
    assert repair_prompt["current_files"] == {"math_utils.py": "def add(a, b):\n    return a - b\n"}
    assert repair_prompt["failure_report"]["failed_check"] == "pytest"
    assert repair_prompt["lessons"] == []


def test_unchanged_committed_downstream_unit_reuses_baseline_without_provider_call(tmp_path: pathlib.Path) -> None:
    unit = BlueprintUnit(
        "tests", "public tests", "tests", ("tests/test_public.py",),
        executor_ref="llm.cheap@1", instruction="test the public contract",
        acceptance=("public tests pass",), allowed_effects=("filesystem.write",),
    )
    target = tmp_path / "tests" / "test_public.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_public():\n    assert True\n", encoding="utf-8")
    client = QueueClient([])
    executor = BlueprintUnitExecutor(tmp_path, client, ModelRoleConfig("worker", "deepseek"))
    executor.register_materialized_baseline(unit)
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.tests@1", "llm.cheap@1",
        TaskContext(unit.instruction, node_config={"unit": unit.as_dict()}),
        declared_effects=unit.allowed_effects,
    )

    result = executor.execute(request)

    assert result.succeeded
    assert result.outputs["reused_materialized_baseline"] is True
    assert result.outputs["modified_files"] == ()
    assert client.calls == [] and executor.calls == []


def test_failed_worker_provider_call_is_recorded_with_reported_usage(tmp_path: pathlib.Path) -> None:
    unit = BlueprintUnit(
        "core", "CSV core", "implementation", ("core.py",), executor_ref="llm.cheap@1",
        instruction="implement core", acceptance=("syntax",), allowed_effects=("filesystem.write",),
    )
    executor = BlueprintUnitExecutor(
        tmp_path, TruncatedClient(),
        ModelRoleConfig("worker", "deepseek", timeout_seconds=150, max_output_tokens=6000, thinking_mode="disabled"),
    )
    request = BlockExecutionRequest(
        "project-1", "run-1", "attempt-1", "core", "project.unit.implementation@1", "llm.cheap@1",
        TaskContext("implement core", node_config={"unit": unit.as_dict()}),
        timeout_seconds=150, declared_effects=("filesystem.write",),
    )
    result = executor.execute(request)
    assert not result.succeeded
    assert len(executor.calls) == 3
    call = executor.calls[0]
    assert call["result"] == "FAILED"
    assert call["failure_type"] == "PROVIDER_OUTPUT_TRUNCATED"
    assert call["request_id"] == "failed-request-1"
    assert call["thinking_mode_requested"] == call["thinking_mode_forwarded"] == "disabled"
    assert call["prompt_tokens"] == 31 and call["completion_tokens"] == 6000
    assert call["reasoning_tokens"] is None and call["cached_tokens"] == 4
    assert call["usage_status"] == "REPORTED"
    assert call["transport_attempt_count"] == 1
    assert [item["call_class"] for item in executor.calls] == [
        "GENERATION", "GENERATION_RETRY", "GENERATION_RETRY",
    ]
    assert result.error.details["failure_type"] == "PROVIDER_FAILURE"


def test_failed_worker_provider_call_keeps_unknown_usage_null(tmp_path: pathlib.Path) -> None:
    class UnknownFailureClient:
        def complete(self, **_kwargs):
            raise GatewayCompletionError("outcome_unknown", "timeout", evidence={"request_id": "unknown-1"})

    unit = BlueprintUnit("core", "core", "implementation", ("core.py",), executor_ref="llm.cheap@1", instruction="core", acceptance=("syntax",), allowed_effects=("filesystem.write",))
    executor = BlueprintUnitExecutor(tmp_path, UnknownFailureClient(), ModelRoleConfig("worker", "deepseek"))
    request = BlockExecutionRequest("project-1", "run-1", "attempt-1", "core", "project.unit.implementation@1", "llm.cheap@1", TaskContext("core", node_config={"unit": unit.as_dict()}))
    executor.execute(request)
    call = executor.calls[0]
    assert call["usage_status"] == "UNKNOWN_AFTER_FAILURE"
    assert call["prompt_tokens"] is call["completion_tokens"] is call["total_tokens"] is None


def test_initial_generation_failure_retries_generation_before_any_repair(tmp_path: pathlib.Path) -> None:
    first_failure = GatewayCompletionError(
        "PROVIDER_OUTPUT_TRUNCATED", "first generation failed before materialization",
        evidence={"request_id": "failed-generation", "finish_reason": "length"},
    )
    client = QueueClient([
        first_failure,
        _bundle("core", {
            "csv_cleaner/__init__.py": "from .core import clean_file, clean_rows\n",
            "csv_cleaner/__main__.py": MAIN,
            "csv_cleaner/core.py": CORE,
        }),
        _bundle("docs", {"README.md": "# CSV Cleaner\n\nUsage documented.\n"}),
        _bundle("tests", {"tests/test_csv_cleaner.py": "def test_ok():\n    assert True\n"}),
    ])
    agent, worker = _configs()
    outcome = MinimalProjectLoop(
        pathlib.Path(__file__).parents[2], tmp_path / "runs", client, agent, worker,
    ).run(_csv_blueprint(), tmp_path / "workspace", case_id="cli_csv_cleaner")

    assert outcome.status == "SUCCEEDED"
    assert outcome.repair_rounds == 0 and outcome.generation_retries == 0
    assert outcome.generation_retry_calls == 1
    core_operations = [
        call["operation"] for call in client.calls
        if json.loads(call["user"]).get("unit", {}).get("unit_id") == "core"
    ]
    assert core_operations[:2] == ["EXECUTE", "EXECUTE"]


def test_partial_tests_generation_continues_only_missing_path_without_failure_report(tmp_path: pathlib.Path) -> None:
    client = QueueClient([
        _bundle("core", {"csv_cleaner/__init__.py": "from .core import clean_file, clean_rows\n", "csv_cleaner/__main__.py": MAIN, "csv_cleaner/core.py": CORE}),
        _bundle("docs", {"README.md": "# CSV Cleaner\n\nUsage documented.\n"}),
        _bundle("tests", {"tests/test_csv_cleaner.py": "def test_partial():\n    assert True\n"}),
        _bundle("tests", {"tests/test_cli.py": "def test_cli():\n    assert True\n"}),
    ])
    blueprint = _csv_blueprint()
    tests = blueprint.by_id["tests"]
    widened = BlueprintUnit.from_dict(tests.as_dict() | {"owns": ["tests/test_csv_cleaner.py", "tests/test_cli.py"], "max_files": 2})
    blueprint = ProjectBlueprint("1.0", blueprint.project_id, blueprint.revision, blueprint.goal, blueprint.constraints, tuple(widened if unit.unit_id == "tests" else unit for unit in blueprint.units), blueprint.checks).freeze()
    agent, worker = _configs()
    outcome = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", client, agent, worker).run(blueprint, tmp_path / "workspace", case_id="cli_csv_cleaner")

    assert outcome.status == "SUCCEEDED"
    assert outcome.generation_continuations == 1 and outcome.generation_retries == 0
    assert outcome.failure_reports == () and outcome.repair_rounds == outcome.repair_calls == 0
    tests_operations = [
        call["operation"] for call in client.calls
        if json.loads(call["user"]).get("unit", {}).get("unit_id") == "tests"
    ]
    assert tests_operations == ["EXECUTE", "EXECUTE"]
    tests_calls = [
        call for call in client.calls
        if json.loads(call["user"]).get("unit", {}).get("unit_id") == "tests"
    ]
    tests_prompts = [json.loads(call["user"]) for call in tests_calls]
    assert tests_prompts[0]["failure_report"] is None
    assert tests_prompts[1]["requested_paths"] == ["tests/test_cli.py"]
    file_item = tests_calls[1]["schema"]["oneOf"][0]["properties"]["files"]
    assert file_item["maxItems"] == 1
    assert file_item["items"]["properties"]["path"]["enum"] == ["tests/test_cli.py"]


def _run_unit_materialization(
    tmp_path: pathlib.Path, responses: list[object], *,
    owns: tuple[str, ...] = ("pkg/a.py", "pkg/b.py", "pkg/c.py"),
    max_output_bytes: int = 64_000,
    required_interfaces: tuple[str, ...] = (),
):
    unit = BlueprintUnit(
        "cohesive", "cohesive package", "implementation", owns,
        executor_ref="llm.cheap@1", instruction="materialize the cohesive package",
        acceptance=("all owned files exist",), allowed_effects=("filesystem.write",),
        required_interfaces=required_interfaces,
        max_actions=len(owns), max_files=len(owns), max_output_bytes=max_output_bytes,
    )
    client = QueueClient(responses)
    executor = BlueprintUnitExecutor(tmp_path, client, ModelRoleConfig("worker", "deepseek", thinking_mode="disabled"))
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.implementation@1", "llm.cheap@1",
        TaskContext("materialize", node_config={"unit": unit.as_dict()}),
    )
    return executor.execute(request), executor, client, unit


def test_incremental_materialization_two_slices_commits_atomically(tmp_path: pathlib.Path) -> None:
    result, executor, client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n"}),
        _bundle("cohesive", {"pkg/c.py": "C = 3\n"}),
    ])
    assert result.succeeded and executor.has_materialized_baseline(unit.unit_id)
    assert [call["call_class"] for call in executor.calls] == ["GENERATION", "GENERATION_CONTINUATION"]
    assert executor.calls[0]["unit_result"] == "PARTIAL_VALID_OUTPUT"
    assert executor.calls[1]["requested_paths"] == ["pkg/c.py"]
    assert result.outputs["unit_materialization"]["status"] == "COMMITTED"
    assert result.outputs["unit_materialization"]["materialization_calls"] == 2
    assert result.outputs["unit_materialization"]["generation_calls"] == 1
    assert result.outputs["unit_materialization"]["continuation_calls"] == 1
    assert result.outputs["unit_materialization"]["generation_retry_calls"] == 0
    assert [row["status"] for row in result.outputs["unit_materialization"]["transitions"]] == [
        "EMPTY", "PARTIAL", "COMPLETE", "VALIDATING", "VALIDATED", "COMMITTING", "COMMITTED",
    ]
    assert all((tmp_path / path).is_file() for path in unit.owns)
    assert len(client.calls) == 2


def test_incremental_materialization_three_single_file_slices_passes(tmp_path: pathlib.Path) -> None:
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n"}),
        _bundle("cohesive", {"pkg/b.py": "B = 2\n"}),
        _bundle("cohesive", {"pkg/c.py": "C = 3\n"}),
    ])
    assert result.succeeded and executor.has_materialized_baseline(unit.unit_id)
    assert [call["call_class"] for call in executor.calls] == ["GENERATION", "GENERATION_CONTINUATION", "GENERATION_CONTINUATION"]
    state = result.outputs["unit_materialization"]
    assert state["materialization_calls"] == 3 and state["generation_calls"] == 1
    assert state["continuation_calls"] == 2 and state["generation_retry_calls"] == 0


def test_continuation_repeating_staged_path_is_scope_violation_and_discards(tmp_path: pathlib.Path) -> None:
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n"}),
        _bundle("cohesive", {"pkg/a.py": "A = 9\n"}),
    ])
    assert not result.succeeded
    assert result.error.details["failure_type"] == "UNIT_OUTPUT_SCOPE_VIOLATION"
    assert result.outputs["unit_materialization"]["status"] == "DISCARDED"
    assert not executor.has_materialized_baseline(unit.unit_id)
    assert all(not (tmp_path / path).exists() for path in unit.owns)


def test_incremental_materialization_rejects_extra_path_without_workspace_effect(tmp_path: pathlib.Path) -> None:
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n", "outside.py": "D = 4\n"}),
    ])
    assert not result.succeeded
    assert result.error.details["failure_type"] == "UNIT_OUTPUT_SCOPE_VIOLATION"
    assert not executor.has_materialized_baseline(unit.unit_id)
    assert not (tmp_path / "outside.py").exists()


def test_invalid_continuation_syntax_preserves_staging_for_generation_retry(tmp_path: pathlib.Path) -> None:
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n"}),
        _bundle("cohesive", {"pkg/c.py": "def broken(:\n"}),
        _bundle("cohesive", {"pkg/c.py": "C = 3\n"}),
    ])
    assert result.succeeded and executor.has_materialized_baseline(unit.unit_id)
    assert [call["call_class"] for call in executor.calls] == ["GENERATION", "GENERATION_CONTINUATION", "GENERATION_RETRY"]
    assert executor.calls[1]["failure_type"] == "SYNTAX_ERROR"
    assert executor.calls[2]["staged_paths_before_call"] == ["pkg/a.py", "pkg/b.py"]
    assert all((tmp_path / path).is_file() for path in unit.owns)


def test_provider_failure_after_partial_preserves_staging_for_retry(tmp_path: pathlib.Path) -> None:
    failure = GatewayCompletionError("outcome_unknown", "timeout", evidence={"request_id": "continuation-timeout"})
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n"}),
        failure,
        _bundle("cohesive", {"pkg/c.py": "C = 3\n"}),
    ])
    assert result.succeeded and executor.has_materialized_baseline(unit.unit_id)
    assert executor.calls[1]["request_id"] == "continuation-timeout"
    assert [call["call_class"] for call in executor.calls] == ["GENERATION", "GENERATION_CONTINUATION", "GENERATION_RETRY"]
    assert executor.calls[2]["staged_paths_before_call"] == ["pkg/a.py", "pkg/b.py"]


def test_materialization_call_budget_exhaustion_discards_partial_state(tmp_path: pathlib.Path) -> None:
    owns = ("pkg/a.py", "pkg/b.py", "pkg/c.py", "pkg/d.py")
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n"}),
        _bundle("cohesive", {"pkg/b.py": "B = 2\n"}),
        _bundle("cohesive", {"pkg/c.py": "C = 3\n"}),
    ], owns=owns)
    assert not result.succeeded
    assert result.error.details["failure_type"] == "UNIT_MATERIALIZATION_INCOMPLETE"
    assert len(executor.calls) == 3 and not executor.has_materialized_baseline(unit.unit_id)
    assert all(not (tmp_path / path).exists() for path in owns)


def test_duplicate_file_in_slice_is_invalid_and_never_committed(tmp_path: pathlib.Path) -> None:
    duplicate = {
        "schema_version": "1.0", "kind": "file_bundle", "unit_id": "cohesive",
        "files": [{"path": "pkg/a.py", "content": "A = 1\n"}, {"path": "pkg/a.py", "content": "A = 2\n"}],
        "summary": "", "needs_escalation": False, "escalation_reason": "",
    }
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [duplicate])
    assert not result.succeeded and result.error.details["failure_type"] == "UNIT_OUTPUT_INVALID"
    assert all(not (tmp_path / path).exists() for path in unit.owns)
    assert not executor.has_materialized_baseline(unit.unit_id)


def test_empty_python_source_is_retried_before_atomic_commit(tmp_path: pathlib.Path) -> None:
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "", "pkg/c.py": "C = 3\n"}),
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": '\"\"\"Package marker.\"\"\"\n', "pkg/c.py": "C = 3\n"}),
    ])
    assert result.succeeded and executor.has_materialized_baseline(unit.unit_id)
    assert [call["call_class"] for call in executor.calls] == ["GENERATION", "GENERATION_RETRY"]
    assert executor.calls[0]["failure_type"] == "UNIT_OUTPUT_INVALID"
    assert (tmp_path / "pkg/b.py").read_text(encoding="utf-8").strip()


def test_complete_first_materialization_call_preserves_original_success_path(tmp_path: pathlib.Path) -> None:
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n", "pkg/c.py": "C = 3\n"}),
    ])
    assert result.succeeded and len(executor.calls) == 1
    assert executor.calls[0]["call_class"] == "GENERATION"
    assert executor.calls[0]["materialization_status"] == "COMMITTED"
    assert executor.has_materialized_baseline(unit.unit_id)


def test_continuation_ledger_records_bounded_context_and_slice_identity(tmp_path: pathlib.Path) -> None:
    result, executor, _client, _unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n"}),
        _bundle("cohesive", {"pkg/c.py": "C = 3\n"}),
    ])
    assert result.succeeded
    first, continuation = executor.calls
    assert first["requested_paths"] == ["pkg/a.py", "pkg/b.py", "pkg/c.py"]
    assert continuation["requested_paths"] == ["pkg/c.py"]
    assert continuation["staged_paths_before_call"] == ["pkg/a.py", "pkg/b.py"]
    assert continuation["context_chars"] > 0
    assert continuation["context_tokens"] == 10
    assert continuation["staged_sibling_chars"] == len("A = 1\n") + len("B = 2\n")
    assert continuation["included_dependencies"] == []


def test_two_no_progress_responses_for_same_missing_set_are_stalled(tmp_path: pathlib.Path) -> None:
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n"}),
        _bundle("cohesive", {"pkg/c.py": "def broken(:\n"}),
        _bundle("cohesive", {"pkg/c.py": "def still_broken(:\n"}),
    ])
    assert not result.succeeded
    assert result.error.details["failure_type"] == "UNIT_MATERIALIZATION_STALLED"
    assert [call["call_class"] for call in executor.calls] == ["GENERATION", "GENERATION_CONTINUATION", "GENERATION_RETRY"]
    assert all(not (tmp_path / path).exists() for path in unit.owns)


def test_whole_unit_required_interface_failure_keeps_workspace_unchanged(tmp_path: pathlib.Path) -> None:
    result, executor, _client, unit = _run_unit_materialization(
        tmp_path,
        [_bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n", "pkg/c.py": "C = 3\n"})],
        required_interfaces=("required_symbol",),
    )
    assert not result.succeeded
    assert result.error.details["failure_type"] == "INTERFACE_MISMATCH"
    assert all(not (tmp_path / path).exists() for path in unit.owns)
    assert not executor.has_materialized_baseline(unit.unit_id)


def test_test_unit_validates_required_interfaces_from_bounded_read_dependencies(tmp_path: pathlib.Path) -> None:
    (tmp_path / "csv_cleaner").mkdir()
    (tmp_path / "csv_cleaner" / "cleaner.py").write_text(
        "def dedupe_rows(rows):\n    return rows\n\ndef fill_empty(rows, value):\n    return rows\n",
        encoding="utf-8",
    )
    (tmp_path / "csv_cleaner" / "cli.py").write_text(
        "def main(argv=None):\n    return 0\n",
        encoding="utf-8",
    )
    unit = BlueprintUnit(
        "tests", "CSV tests", "tests", ("tests/test_cleaner.py", "tests/test_cli.py"),
        reads=("csv_cleaner/cleaner.py", "csv_cleaner/cli.py"),
        executor_ref="llm.cheap@1", instruction="test public interfaces",
        required_interfaces=(
            "csv_cleaner.cleaner.dedupe_rows",
            "csv_cleaner.cleaner.fill_empty",
            "csv_cleaner.cli.main",
        ),
        acceptance=("tests exist",), allowed_effects=("filesystem.read", "filesystem.write"),
        max_actions=2, max_files=2,
    )
    client = QueueClient([_bundle("tests", {
        "tests/test_cleaner.py": "from csv_cleaner.cleaner import dedupe_rows, fill_empty\n\ndef test_cleaner():\n    assert dedupe_rows([]) == []\n    assert fill_empty([], 'x') == []\n",
        "tests/test_cli.py": "from csv_cleaner.cli import main\n\ndef test_cli():\n    assert main([]) == 0\n",
    })])
    executor = BlueprintUnitExecutor(tmp_path, client, ModelRoleConfig("worker", "deepseek", thinking_mode="disabled"))
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.tests@1", "llm.cheap@1",
        TaskContext("materialize tests", node_config={"unit": unit.as_dict()}),
    )

    result = executor.execute(request)

    assert result.succeeded
    assert executor.has_materialized_baseline(unit.unit_id)
    assert all((tmp_path / path).is_file() for path in unit.owns)


def test_whole_unit_cross_file_import_failure_keeps_workspace_unchanged(tmp_path: pathlib.Path) -> None:
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {
            "pkg/a.py": "from .missing import VALUE\n",
            "pkg/b.py": "B = 2\n",
            "pkg/c.py": "C = 3\n",
        }),
    ])
    assert not result.succeeded
    assert result.error.details["failure_type"] == "INTERFACE_MISMATCH"
    assert all(not (tmp_path / path).exists() for path in unit.owns)
    assert not executor.has_materialized_baseline(unit.unit_id)


def test_controlled_commit_failure_rolls_back_and_is_classified(tmp_path: pathlib.Path, monkeypatch) -> None:
    import cgkn.application.software_project.scope as scope_module

    real_replace = scope_module.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected commit failure")
        return real_replace(source, target)

    monkeypatch.setattr(scope_module.os, "replace", fail_second)
    result, executor, _client, unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n", "pkg/c.py": "C = 3\n"}),
    ])
    assert not result.succeeded
    assert result.error.details["failure_type"] == "COMMIT_FAILURE"
    assert all(not (tmp_path / path).exists() for path in unit.owns)
    assert not (tmp_path / "pkg").exists()
    assert not executor.has_materialized_baseline(unit.unit_id)


def test_continuation_request_contains_no_hidden_acceptance_payload(tmp_path: pathlib.Path) -> None:
    result, _executor, client, _unit = _run_unit_materialization(tmp_path, [
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n"}),
        _bundle("cohesive", {"pkg/c.py": "C = 3\n"}),
    ])
    assert result.succeeded
    continuation = client.calls[1]
    assert "SECRET_HIDDEN_ASSERTION" not in continuation["user"]
    assert continuation["schema"]["oneOf"][0]["properties"]["files"]["items"]["properties"]["path"]["enum"] == ["pkg/c.py"]


def test_full_retry_benchmark_policy_discards_partial_and_requests_whole_unit_again(tmp_path: pathlib.Path) -> None:
    owns = ("pkg/a.py", "pkg/b.py", "pkg/c.py")
    unit = BlueprintUnit(
        "cohesive", "cohesive package", "implementation", owns,
        executor_ref="llm.cheap@1", instruction="materialize package",
        acceptance=("complete",), allowed_effects=("filesystem.write",),
        max_actions=3, max_files=3,
    )
    client = QueueClient([
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n"}),
        _bundle("cohesive", {"pkg/a.py": "A = 1\n", "pkg/b.py": "B = 2\n", "pkg/c.py": "C = 3\n"}),
    ])
    executor = BlueprintUnitExecutor(
        tmp_path, client, ModelRoleConfig("worker", "deepseek"),
        materialization_policy="FULL_RETRY",
    )
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.implementation@1", "llm.cheap@1",
        TaskContext("materialize", node_config={"unit": unit.as_dict()}),
    )
    first = executor.execute(request)
    assert not first.succeeded and first.error.details["failure_type"] == "UNIT_OUTPUT_INCOMPLETE"
    assert all(not (tmp_path / path).exists() for path in owns)
    second = executor.execute(request)
    assert second.succeeded and all((tmp_path / path).is_file() for path in owns)
    assert [call["call_class"] for call in executor.calls] == ["GENERATION", "GENERATION_RETRY"]
    assert executor.calls[1]["requested_paths"] == list(owns)


def test_initial_repair_without_materialized_baseline_is_forbidden(tmp_path: pathlib.Path) -> None:
    unit = BlueprintUnit("core", "core", "implementation", ("core.py",), executor_ref="llm.cheap@1", instruction="core", acceptance=("works",), allowed_effects=("filesystem.write",))
    blueprint = ProjectBlueprint("1.0", "no-baseline", 1, "repair", (), (unit,), (BlueprintCheck("accept", "acceptance", depends_on=("core",), acceptance=("hidden",)),)).freeze()
    failure = FailureReport("pytest", "TEST_FAILURE", failure_stage=FailureStage.TEST.value, owner_unit_id="core", recovery_action=FailureAction.REPAIR_EXISTING.value, materialized_baseline=True)
    agent, worker = _configs()
    with pytest.raises(ValueError, match="REPAIR_WITHOUT_BASELINE"):
        MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", QueueClient([]), agent, worker).run(blueprint, tmp_path / "workspace", case_id="seeded_repair", initial_failure=failure)


def test_materialized_baseline_requires_current_workspace_identity(tmp_path: pathlib.Path) -> None:
    unit = BlueprintUnit("core", "core", "implementation", ("core.py",), executor_ref="llm.cheap@1", instruction="core", acceptance=("works",), allowed_effects=("filesystem.write",))
    (tmp_path / "core.py").write_text("value = 1\n", encoding="utf-8")
    executor = BlueprintUnitExecutor(tmp_path, QueueClient([]), ModelRoleConfig("worker", "deepseek"))
    executor.register_materialized_baseline(unit)
    assert executor.has_materialized_baseline("core")
    (tmp_path / "core.py").write_text("value = 2\n", encoding="utf-8")
    assert not executor.has_materialized_baseline("core")


def _execute_repair(tmp_path: pathlib.Path, payload: dict, *, repeated_source: bool = False):
    owns = ("pkg/a.py", "pkg/b.py", "pkg/c.py", "pkg/d.py")
    for index, relative in enumerate(owns):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        body = "value = 1\nlabel = 'old'\n" if index == 0 else f"value = {index + 1}\n"
        if repeated_source and index == 0:
            body = "value = 1\nvalue = 1\n"
        target.write_text(body, encoding="utf-8")
    unit = BlueprintUnit("core", "cohesive core", "implementation", owns, executor_ref="llm.cheap@1", instruction="repair", acceptance=("works",), allowed_effects=("filesystem.read", "filesystem.write"), max_files=4)
    executor = BlueprintUnitExecutor(tmp_path, QueueClient([payload]), ModelRoleConfig("worker", "deepseek"))
    executor.register_materialized_baseline(unit)
    executor.failure_reports[unit.unit_id] = FailureReport("pytest", "TEST_FAILURE", failure_stage=FailureStage.TEST.value, owner_unit_id="core", recovery_action=FailureAction.REPAIR_EXISTING.value, materialized_baseline=True)
    request = BlockExecutionRequest("project", "run", "attempt", unit.unit_id, "project.unit.implementation@1", "llm.cheap@1", TaskContext("repair", node_config={"unit": unit.as_dict()}))
    before = {path: (tmp_path / path).read_text(encoding="utf-8") for path in owns}
    return executor.execute(request), before, {path: (tmp_path / path).read_text(encoding="utf-8") for path in owns}


def test_repair_accepts_one_of_four_files_with_two_ordered_hunks(tmp_path: pathlib.Path) -> None:
    payload = _patch_files("core", {"pkg/a.py": [("value = 1", "value = 10"), ("label = 'old'", "label = 'new'")]})
    result, before, after = _execute_repair(tmp_path, payload)
    assert result.succeeded
    assert result.outputs["modified_files"] == ("pkg/a.py",)
    assert "value = 10" in after["pkg/a.py"] and "label = 'new'" in after["pkg/a.py"]
    assert all(after[path] == before[path] for path in ("pkg/b.py", "pkg/c.py", "pkg/d.py"))


def test_repair_accepts_two_of_four_owned_files(tmp_path: pathlib.Path) -> None:
    payload = _patch_files("core", {"pkg/a.py": [("value = 1", "value = 10")], "pkg/c.py": [("value = 3", "value = 30")]})
    result, before, after = _execute_repair(tmp_path, payload)
    assert result.succeeded and set(result.outputs["modified_files"]) == {"pkg/a.py", "pkg/c.py"}
    assert after["pkg/b.py"] == before["pkg/b.py"] and after["pkg/d.py"] == before["pkg/d.py"]


@pytest.mark.parametrize("payload", [
    _patch_files("core", {"outside.py": [("x", "y")]}),
    {"schema_version": "2.0", "kind": "patch_bundle", "unit_id": "core", "files": [
        {"path": "pkg/a.py", "edits": [{"find": "value = 1", "replace": "value = 2"}]},
        {"path": "pkg/a.py", "edits": [{"find": "label = 'old'", "replace": "label = 'new'"}]},
    ]},
])
def test_repair_rejects_undeclared_or_duplicate_file_objects_atomically(tmp_path: pathlib.Path, payload: dict) -> None:
    result, before, after = _execute_repair(tmp_path, payload)
    assert not result.succeeded and after == before


@pytest.mark.parametrize(("edits", "repeated"), [
    ([("value = 1", "value = 10"), ("missing", "replacement")], False),
    ([("value = 1", "value = 2")], True),
])
def test_failed_patch_hunk_leaves_whole_transaction_unchanged(tmp_path: pathlib.Path, edits, repeated: bool) -> None:
    payload = _patch_files("core", {"pkg/a.py": edits, "pkg/b.py": [("value = 2", "value = 20")]})
    result, before, after = _execute_repair(tmp_path, payload, repeated_source=repeated)
    assert not result.succeeded and after == before


def test_cross_unit_attribution_uses_evidence_and_never_implementation_fallback(tmp_path: pathlib.Path) -> None:
    blueprint = _csv_blueprint()
    agent, worker_config = _configs()
    executor = BlueprintUnitExecutor(tmp_path, QueueClient([]), worker_config)
    for unit_id in ("core", "tests"):
        unit = blueprint.by_id[unit_id]
        for relative in unit.owns:
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# materialized\n", encoding="utf-8")
        executor.register_materialized_baseline(unit)
    dag = compile_tree(compile_blueprint(blueprint, case_id="cli_csv_cleaner"))

    source_result = BlockExecutionResult("p", "r", "a", "pytest", "local.python-test@1", BlockStatus.FAILED, outputs={"stderr": "csv_cleaner/core.py:12: ValueError"}, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "csv_cleaner/core.py:12: ValueError"))
    source_report = MinimalProjectLoop._failure_report(blueprint, "pytest", source_result, dag, executor)
    assert source_report.owner_unit_id == "core" and source_report.recovery_action == FailureAction.REPAIR_EXISTING.value

    test_result = BlockExecutionResult("p", "r", "b", "pytest", "local.python-test@1", BlockStatus.FAILED, outputs={"stderr": "tests/test_csv_cleaner.py:9: assert False"}, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "tests/test_csv_cleaner.py:9: assert False"))
    test_report = MinimalProjectLoop._failure_report(blueprint, "pytest", test_result, dag, executor)
    assert test_report.owner_unit_id == "tests"

    nested_result = BlockExecutionResult(
        "p", "r", "nested", "pytest", "local.python-test@1", BlockStatus.FAILED,
        outputs={"stdout": (
            "tests/test_csv_cleaner.py:21: in test_missing_input\n"
            "    read_csv(missing)\n"
            "csv_cleaner/core.py:14: in read_csv\n"
            "    raise FileNotFoundError(path)\n"
            "E   FileNotFoundError: missing.csv\n"
        )},
        error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "command exited 1"),
    )
    nested_report = MinimalProjectLoop._failure_report(blueprint, "pytest", nested_result, dag, executor)
    assert nested_report.owner_unit_id == "core"
    assert nested_report.owner_file == "csv_cleaner/core.py"
    assert nested_report.first_project_frame == "csv_cleaner/core.py:14"
    assert nested_report.observed == "Public check failure summary:\nFileNotFoundError: missing.csv"
    assert "raise FileNotFoundError" not in nested_report.observed

    summarized_result = BlockExecutionResult(
        "p", "r", "summary", "pytest", "local.python-test@1", BlockStatus.FAILED,
        outputs={"stdout": (
            "tests/test_csv_cleaner.py:10: in test_public\n"
            "    hidden_like_source_line()\n"
            "E   TypeError: CsvCleaner.__init__() got an unexpected keyword argument 'fill'\n"
            "FAILED tests/test_csv_cleaner.py::test_public - TypeError: bad call\n"
        )},
        error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "command exited 1"),
    )
    summarized_report = MinimalProjectLoop._failure_report(blueprint, "pytest", summarized_result, dag, executor)
    assert "TypeError: CsvCleaner.__init__()" in summarized_report.observed
    assert "FAILED tests/test_csv_cleaner.py::test_public" in summarized_report.observed
    assert "hidden_like_source_line" not in summarized_report.observed
    assert "command exited 1" not in summarized_report.observed

    mixed_result = BlockExecutionResult(
        "p", "r", "mixed", "pytest", "local.python-test@1", BlockStatus.FAILED,
        outputs={"stdout": (
            "tests/test_csv_cleaner.py:20: in test_cli\n"
            "csv_cleaner/core.py:12: in clean_rows\n"
            "E   ValueError: public operation failed\n"
            "tests/test_csv_cleaner.py:40: in test_later_assertion\n"
            "E   AssertionError: later generated test also failed\n"
            "FAILED tests/test_csv_cleaner.py::test_cli - ValueError\n"
            "FAILED tests/test_csv_cleaner.py::test_later_assertion - AssertionError\n"
        )},
        error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "command exited 1"),
    )
    mixed_report = MinimalProjectLoop._failure_report(blueprint, "pytest", mixed_result, dag, executor)
    assert mixed_report.owner_unit_id == "core"
    assert mixed_report.owner_file == "csv_cleaner/core.py"

    unknown_result = BlockExecutionResult("p", "r", "c", "pytest", "local.python-test@1", BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "assertion failed without a project path"))
    unknown_report = MinimalProjectLoop._failure_report(blueprint, "pytest", unknown_result, dag, executor)
    assert unknown_report.owner_unit_id == "" and unknown_report.failure_type == "ATTRIBUTION_UNRESOLVED"
    assert unknown_report.recovery_action == FailureAction.STOP.value


def test_acceptance_unique_exact_interface_owner_is_deterministic(tmp_path: pathlib.Path) -> None:
    blueprint = _csv_blueprint(); executor = _materialized_executor(tmp_path, blueprint)
    fake = FakeAttributor(error=AssertionError("Coordinator attribution must not be called"))
    loop = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", QueueClient([]), *_configs(), acceptance_attributor=fake)
    dag = compile_tree(compile_blueprint(blueprint, case_id="cli_csv_cleaner"))
    report = loop._acceptance_failure_report(
        blueprint, _acceptance_failure(summary="clean_rows must satisfy the public contract"), dag, executor, "run",
    )
    assert report.owner_unit_id == "core"
    assert report.recovery_action == FailureAction.REPAIR_EXISTING.value
    assert report.attribution_source == "DETERMINISTIC" and report.attribution_status == "RESOLVED"
    assert fake.calls == []


def test_acceptance_ambiguous_candidates_call_coordinator_once(tmp_path: pathlib.Path) -> None:
    blueprint = _csv_blueprint(); executor = _materialized_executor(tmp_path, blueprint)
    fake = FakeAttributor((AcceptanceAttributionDecision("public-requirement-1", "core", FailureAction.REPAIR_EXISTING.value),))
    loop = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", QueueClient([]), *_configs(), acceptance_attributor=fake)
    dag = compile_tree(compile_blueprint(blueprint, case_id="cli_csv_cleaner"))
    report = loop._acceptance_failure_report(
        blueprint, _acceptance_failure(summary="clean_rows behavior and README.md documentation"), dag, executor, "run",
    )
    assert report.owner_unit_id == "core" and report.attribution_source == "COORDINATOR"
    assert set(report.candidate_owner_unit_ids) == {"core", "docs"}
    assert len(fake.calls) == 1


@pytest.mark.parametrize("decisions,skip", [
    ((AcceptanceAttributionDecision("public-requirement-1", "invented", FailureAction.REPAIR_EXISTING.value),), ()),
    ((AcceptanceAttributionDecision("public-requirement-1", "core", FailureAction.REPAIR_EXISTING.value),), ("core",)),
    ((AcceptanceAttributionDecision("public-requirement-1", "", FailureAction.STOP.value),), ()),
])
def test_acceptance_invalid_unmaterialized_or_stop_decisions_fail_closed(tmp_path: pathlib.Path, decisions, skip) -> None:
    blueprint = _csv_blueprint(); executor = _materialized_executor(tmp_path, blueprint, skip=skip)
    fake = FakeAttributor(decisions)
    loop = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", QueueClient([]), *_configs(), acceptance_attributor=fake)
    dag = compile_tree(compile_blueprint(blueprint, case_id="cli_csv_cleaner"))
    report = loop._acceptance_failure_report(blueprint, _acceptance_failure(), dag, executor, "run")
    assert report.owner_unit_id == "" and report.recovery_action == FailureAction.STOP.value
    assert report.attribution_status == "UNRESOLVED"


@pytest.mark.parametrize("error", [
    ValueError("invalid attribution schema"),
    GatewayCompletionError("transport_failure", "bounded"),
])
def test_acceptance_attribution_failure_never_guesses_owner(tmp_path: pathlib.Path, error: Exception) -> None:
    blueprint = _csv_blueprint(); executor = _materialized_executor(tmp_path, blueprint)
    loop = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", QueueClient([]), *_configs(), acceptance_attributor=FakeAttributor(error=error))
    dag = compile_tree(compile_blueprint(blueprint, case_id="cli_csv_cleaner"))
    report = loop._acceptance_failure_report(blueprint, _acceptance_failure(), dag, executor, "run")
    assert report.owner_unit_id == "" and report.failure_type == "ACCEPTANCE_FAILURE"
    assert report.recovery_action == FailureAction.STOP.value


def test_coordinator_attribution_prompt_and_failure_report_never_include_hidden_markers(tmp_path: pathlib.Path) -> None:
    marker_name = "SUPER_SECRET_HIDDEN_TEST_NAME"; marker_value = "SUPER_SECRET_EXPECTED_VALUE"
    blueprint = _csv_blueprint(); executor = _materialized_executor(tmp_path, blueprint)
    client = QueueClient([{
        "schema_version": "1.0",
        "decisions": [{"requirement_id": "public-requirement-1", "owner_unit_id": "core", "action": "REPAIR_EXISTING"}],
    }])
    loop = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", client, *_configs())
    dag = compile_tree(compile_blueprint(blueprint, case_id="cli_csv_cleaner"))
    report = loop._acceptance_failure_report(
        blueprint, _acceptance_failure(marker=marker_name + marker_value), dag, executor, "run",
    )
    rendered = json.dumps(report.as_dict(), ensure_ascii=False) + json.dumps(client.calls, ensure_ascii=False)
    assert marker_name not in rendered and marker_value not in rendered
    assert report.owner_unit_id == "core" and report.attribution_status == "RESOLVED"
    assert client.calls[0]["operation"] == "ACCEPTANCE_ATTRIBUTION"
    assert client.calls[0]["thinking_mode"] == "disabled"


def test_harness_mapping_unavailable_stops_without_attribution_call(tmp_path: pathlib.Path) -> None:
    blueprint = _csv_blueprint(); executor = _materialized_executor(tmp_path, blueprint)
    fake = FakeAttributor(error=AssertionError("must not call attributor"))
    loop = MinimalProjectLoop(pathlib.Path(__file__).parents[2], tmp_path / "runs", QueueClient([]), *_configs(), acceptance_attributor=fake)
    dag = compile_tree(compile_blueprint(blueprint, case_id="cli_csv_cleaner"))
    details = {"failure_class": "HARNESS_ATTRIBUTION_UNAVAILABLE", "failed_requirement_ids": [], "public_requirement_summaries": {}, "mapping_complete": False}
    result = BlockExecutionResult("p", "r", "a", "external_acceptance", "project.acceptance@1", BlockStatus.FAILED, outputs=details, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, "mapping unavailable", details))
    report = loop._acceptance_failure_report(blueprint, result, dag, executor, "run")
    assert report.failure_type == "HARNESS_ATTRIBUTION_UNAVAILABLE"
    assert report.attribution_status == "UNAVAILABLE" and report.recovery_action == FailureAction.STOP.value
    assert fake.calls == []


def test_project_loop_automatically_captures_failure_repair_pass_chain(
    tmp_path: pathlib.Path, monkeypatch,
) -> None:
    corpus_root = tmp_path / "corpus"
    monkeypatch.setenv("CGNK_PROJECT_CORPUS_ROOT", str(corpus_root))
    monkeypatch.setenv("CGNK_SOURCE_VERSION", "source-closure-test")
    units = (
        BlueprintUnit(
            "core", "math implementation", "implementation", ("math_utils.py",),
            executor_ref="llm.cheap@1", instruction="implement add", required_interfaces=("add",),
            acceptance=("addition",), allowed_effects=("filesystem.write",),
        ),
    )
    checks = (
        BlueprintCheck("pytest", "verification", (sys.executable, "-m", "pytest", "-q"), ("core",), ("public tests",)),
        BlueprintCheck("accept", "acceptance", (), ("pytest",), get_case("seeded_repair").public_acceptance),
    )
    blueprint = ProjectBlueprint("1.0", "seeded_repair", 1, "repair arithmetic", ("smallest change",), units, checks).freeze()
    client = QueueClient([
        _bundle("core", {"math_utils.py": "def add(a, b):\n    return a - b\n"}),
        _patch("core", "math_utils.py", "return a - b", "return a + b"),
    ])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "test_math_utils.py").write_text(
        "from math_utils import add\ndef test_add(): assert add(2,3)==5\n", encoding="utf-8",
    )

    outcome = MinimalProjectLoop(
        pathlib.Path(__file__).parents[2], tmp_path / "runs", client, *_configs(),
    ).run(blueprint, workspace, case_id="seeded_repair")

    assert outcome.status == "SUCCEEDED"
    corpus = ProjectCorpus(corpus_root)
    rows = corpus.list_attempts()
    assert len(rows) == 1 and rows[0]["status"] == "PASS"
    manifest = corpus.show(rows[0]["entry_id"])
    stages = [item["stage"] for item in manifest["snapshot_refs"]]
    assert stages == ["INPUT", "POST_MATERIALIZATION", "FAILED_TEST", "PRE_REPAIR", "POST_REPAIR", "FINAL"]
    assert manifest["failures"][0]["failure_type"] == "TEST_FAILURE"
    assert manifest["repairs"][0]["status"] == "FIXED"
    assert corpus.verify()["status"] == "PASS"


def test_corpus_capture_failure_cannot_fail_project_run(tmp_path: pathlib.Path, monkeypatch) -> None:
    impossible_root = tmp_path / "not-a-directory"
    impossible_root.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("CGNK_PROJECT_CORPUS_ROOT", str(impossible_root))
    client = QueueClient([
        _bundle("core", {"csv_cleaner/__init__.py": "from .core import clean_file, clean_rows\n__all__=['clean_file','clean_rows']\n", "csv_cleaner/__main__.py": MAIN, "csv_cleaner/core.py": CORE}),
        _bundle("docs", {"README.md": "# CSV Cleaner\n\nUsage documented.\n"}),
        _bundle("tests", {"tests/test_csv_cleaner.py": "def test_ok():\n    assert True\n"}),
    ])
    outcome = MinimalProjectLoop(
        pathlib.Path(__file__).parents[2], tmp_path / "runs", client, *_configs(),
    ).run(_csv_blueprint(), tmp_path / "workspace", case_id="cli_csv_cleaner")
    receipt = json.loads((outcome.run_root / "corpus_capture.json").read_text(encoding="utf-8"))
    assert outcome.status == "SUCCEEDED"
    assert receipt["status"] == "CAPTURE_FAILED"
