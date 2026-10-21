from __future__ import annotations

import json
import pathlib

from cgkn.application.project_blueprint import BlueprintUnit, FailureAction, FailureReport, FailureStage
from cgkn.application.project_loop import BlueprintUnitExecutor
from cgkn.application.repair_convergence import (
    CanonicalRepairTargetValidator,
    RepairAttemptEvidence,
    RepairEvidencePacket,
    RepairFailureFingerprint,
    RepairProgress,
    RepairTargetSpec,
    classify_repair_progress,
    localize_repair_sources,
)
from cgkn.execution import BlockExecutionRequest, TaskContext
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.application.test_authority import PublicContractProjection
from cgkn.application.software_project.catalog import get_case


FIXTURE = pathlib.Path(__file__).parents[1] / "fixtures" / "repair_non_convergence.json"


class QueueClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def complete(self, *, system, user, schema_name, schema, config):
        self.calls.append({"system": system, "user": user, "schema": schema, "model": config.model})
        value = self.responses.pop(0)
        return ProviderCompletion(
            json.dumps(value), config.model, f"repair-{len(self.calls)}",
            {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        )


BROKEN_SOURCE = '''import csv
import pathlib
import sys

MARKER = 1

def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))

def _print_preview(rows, count):
    if count:
        sys.stdout.write(",".join(rows[0]) + "\\n\\n")

def main():
    input_path, output_path = sys.argv[1], sys.argv[2]
    rows = _read_csv(input_path)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    _print_preview(rows[1:], int(sys.argv[4]))

if __name__ == "__main__":
    main()
'''


def _patch(*edits: tuple[str, str]) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "kind": "patch_bundle",
        "unit_id": "implementation-1",
        "files": [{
            "path": "csv_cleaner/__main__.py",
            "edits": [{"find": find, "replace": replacement} for find, replacement in edits],
        }],
    }


def _workspace(root: pathlib.Path, *, with_regression: bool = False) -> None:
    package = root / "csv_cleaner"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(BROKEN_SOURCE, encoding="utf-8")
    if with_regression:
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_marker.py").write_text(
            "from csv_cleaner.__main__ import MARKER\ndef test_marker(): assert MARKER == 1\n",
            encoding="utf-8",
        )


def _fingerprint(baseline_hash: str, *, actual=None) -> RepairFailureFingerprint:
    return RepairFailureFingerprint(
        ("OBL-CSV-PREVIEW", "REQ-002"),
        "implementation-1",
        "test_preview_prints_rows_and_writes_output",
        "stdout.csv_rows",
        json.dumps({
            "input_path": "input.csv", "output_path": "output.csv",
            "delimiter": ",", "header": ["id", "name", "city"],
            "rows": [["1", "Ada", ""], ["2", "Lin", "Paris"]],
        }, sort_keys=True, separators=(",", ":")),
        json.dumps([["1", "Ada", ""]], separators=(",", ":")),
        json.dumps(actual if actual is not None else [["1", "Ada", ""], []], separators=(",", ":")),
        "EXTRA_EMPTY_ROW",
        "python -m csv_cleaner",
        "csv_cleaner/__main__.py:_print_preview",
        baseline_hash,
    )


def _target(baseline_hash: str) -> RepairTargetSpec:
    setup = {
        "input_path": "input.csv", "output_path": "output.csv", "delimiter": ",",
        "header": ["id", "name", "city"],
        "rows": [["1", "Ada", ""], ["2", "Lin", "Paris"]],
    }
    operation = {"commands": [{"argv": ["python", "-m", "csv_cleaner", "input.csv", "output.csv", "--preview", "1"]}]}
    expected = {"rows": [["1", "Ada", ""]], "output_created": True}
    return RepairTargetSpec(
        _fingerprint(baseline_hash),
        json.dumps(operation, sort_keys=True, separators=(",", ":")),
        json.dumps(setup, sort_keys=True, separators=(",", ":")),
        json.dumps(expected, sort_keys=True, separators=(",", ":")),
    )


def _executor(root: pathlib.Path, responses, *, with_regression: bool = False):
    _workspace(root, with_regression=with_regression)
    unit = BlueprintUnit(
        "implementation-1", "CSV CLI", "implementation", ("csv_cleaner/__main__.py",),
        executor_ref="llm.cheap@1", instruction="repair preview", acceptance=("exact preview rows",),
        allowed_effects=("filesystem.write",),
    )
    client = QueueClient(responses)
    executor = BlueprintUnitExecutor(root, client, ModelRoleConfig("worker", "qwen3.7-flash"))
    executor.register_materialized_baseline(unit)
    baseline_hash = executor.materialized_units[unit.unit_id][1]
    executor.repair_targets[unit.unit_id] = _target(baseline_hash)
    executor.failure_reports[unit.unit_id] = FailureReport(
        "tests-1", "PUBLIC_CONTRACT_FAILURE", failure_stage=FailureStage.TEST.value,
        owner_unit_id=unit.unit_id, recovery_action=FailureAction.REPAIR_EXISTING.value,
        materialized_baseline=True, failed_check="pytest", expected="one CSV preview row",
        observed="an additional empty CSV record",
    )
    request = BlockExecutionRequest(
        "project", "run", "attempt", unit.unit_id, "project.unit.implementation@1", "llm.cheap@1",
        TaskContext("repair preview", node_config={"unit": unit.as_dict(), "project_goal": "exact CSV preview"}),
        declared_effects=unit.allowed_effects,
    )
    return executor, client, request, baseline_hash


def test_historical_fixture_is_public_safe_and_records_two_wrong_locations() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["public_safe"] is True
    assert fixture["source_after_repair_2"].count("_print_preview") == 1
    assert "csv.writer(sys.stdout)" in fixture["source_after_repair_2"]
    assert "rows[1:] if row" in fixture["repair_1_patch"]["replace"]
    assert "any(cell" in fixture["repair_2_patch"]["replace"]
    assert "hidden" not in json.dumps(fixture).casefold()


def test_failure_fingerprint_is_stable_round_trippable_and_sensitive_to_actual() -> None:
    first = _fingerprint("sha256:baseline")
    second = RepairFailureFingerprint.from_dict(first.as_dict())
    changed = _fingerprint("sha256:baseline", actual=[["1", "Ada", ""]])
    assert first == second
    assert first.fingerprint_hash == second.fingerprint_hash
    assert changed.fingerprint_hash != first.fingerprint_hash


def test_progress_classification_covers_fixed_progress_no_progress_and_regression() -> None:
    before = _fingerprint("sha256:baseline", actual=[["1", "Ada", ""], [], []])
    assert classify_repair_progress(before, None) is RepairProgress.FIXED
    assert classify_repair_progress(before, before) is RepairProgress.NO_PROGRESS
    assert classify_repair_progress(before, _fingerprint("sha256:baseline", actual=[["1", "Ada", ""], []])) is RepairProgress.PROGRESSED
    assert classify_repair_progress(before, _fingerprint("sha256:baseline", actual=[["1", "Ada", ""], [], [], []])) is RepairProgress.REGRESSED


def test_source_localization_selects_preview_function_not_csv_reader() -> None:
    relevant, functions, locator = localize_repair_sources(
        {"csv_cleaner/__main__.py": BROKEN_SOURCE, "csv_cleaner/core.py": "def unrelated(): return 1\n"},
        _fingerprint("sha256:baseline"),
    )
    assert tuple(relevant) == ("csv_cleaner/__main__.py",)
    assert functions == ("_print_preview",)
    assert locator.endswith(":_print_preview")
    assert "def _print_preview" in relevant["csv_cleaner/__main__.py"]
    assert "def _read_csv" not in relevant["csv_cleaner/__main__.py"]


def test_canonical_validator_detects_extra_record_and_accepts_exact_fix(tmp_path: pathlib.Path) -> None:
    _workspace(tmp_path)
    target = _target("sha256:baseline")
    failed = CanonicalRepairTargetValidator().validate(target, tmp_path)
    assert failed.status == "FAIL"
    assert failed.fingerprint is not None
    assert failed.fingerprint.failure_kind == "EXTRA_EMPTY_ROW"
    source = (tmp_path / "csv_cleaner/__main__.py").read_text(encoding="utf-8")
    (tmp_path / "csv_cleaner/__main__.py").write_text(source.replace('+ "\\n\\n"', '+ "\\n"'), encoding="utf-8")
    passed = CanonicalRepairTargetValidator().validate(target, tmp_path)
    assert passed.status == "PASS"
    assert passed.fingerprint is None


def test_canonical_test_failure_creates_structured_repair_target_and_source_locator(tmp_path: pathlib.Path) -> None:
    _workspace(tmp_path)
    core = BlueprintUnit(
        "implementation-1", "CSV CLI", "implementation", ("csv_cleaner/__main__.py",),
        executor_ref="llm.cheap@1", instruction="implement CSV preview", acceptance=("preview",),
        allowed_effects=("filesystem.write",),
    )
    tests = BlueprintUnit(
        "tests-1", "public tests", "tests", ("tests/test_cli.py",), depends_on=(core.unit_id,),
        executor_ref="llm.cheap@1", instruction="validate preview", acceptance=("preview",),
        allowed_effects=("filesystem.write",),
    )
    source = '''import csv
import subprocess
import sys

def test_preview_prints_rows_and_writes_output():
    result = subprocess.run([sys.executable, '-m', 'csv_cleaner', 'input.csv', 'output.csv', '--preview', '1'], capture_output=True, text=True)
    assert result.returncode == 0
    preview_rows = list(csv.reader(result.stdout.splitlines()))
    assert preview_rows == [['1', 'Ada', '']]
'''
    executor = BlueprintUnitExecutor(
        tmp_path, QueueClient([{
            "schema_version": "1.0", "kind": "file_bundle", "unit_id": tests.unit_id,
            "files": [{"path": "tests/test_cli.py", "content": source}],
            "summary": "generated", "needs_escalation": False, "escalation_reason": "",
        }]), ModelRoleConfig("worker", "qwen3.7-flash"),
    )
    executor.register_materialized_baseline(core)
    request = BlockExecutionRequest(
        "project", "run", "attempt", tests.unit_id, "project.unit.tests@1", "llm.cheap@1",
        TaskContext(tests.instruction, node_config={
            "unit": tests.as_dict(), "project_goal": get_case("cli_csv_cleaner").public_goal,
            "public_contract_projection": PublicContractProjection.for_case("cli_csv_cleaner").as_dict(),
            "owned_public_requirement_ids": [f"REQ-{index:03d}" for index in range(1, 6)],
        }), declared_effects=tests.allowed_effects,
    )
    result = executor.execute(request)
    assert not result.succeeded
    assert result.error.details["failure_type"] == "PUBLIC_CONTRACT_FAILURE"
    target = executor.repair_targets[core.unit_id]
    assert target.fingerprint.observable == "stdout.csv_rows"
    assert json.loads(target.fingerprint.normalized_actual) == [["1", "Ada", ""], []]
    assert target.fingerprint.failure_kind == "EXTRA_EMPTY_ROW"
    assert target.fingerprint.relevant_source_locator.endswith(":_print_preview")
    assert target.fingerprint.requirement_ids
    assert target.fingerprint.baseline_hash == executor.materialized_units[core.unit_id][1]


def test_public_contract_repair_without_exact_target_fails_before_provider_call(tmp_path: pathlib.Path) -> None:
    executor, client, request, baseline_hash = _executor(
        tmp_path,
        [_patch(("MARKER = 1", "MARKER = 2"))],
    )
    executor.repair_targets.clear()
    before = (tmp_path / "csv_cleaner/__main__.py").read_text(encoding="utf-8")

    result = executor.execute(request)

    assert not result.succeeded
    assert result.error.details["failure_type"] == "REPAIR_TARGET_UNAVAILABLE"
    assert client.calls == []
    assert (tmp_path / "csv_cleaner/__main__.py").read_text(encoding="utf-8") == before
    assert executor.materialized_units["implementation-1"][1] == baseline_hash


def test_no_progress_patch_is_discarded_without_changing_workspace_or_baseline(tmp_path: pathlib.Path) -> None:
    wrong = _patch(("return list(csv.reader(handle))", "return [row for row in csv.reader(handle) if row]"))
    executor, client, request, baseline_hash = _executor(tmp_path, [wrong])
    before = (tmp_path / "csv_cleaner/__main__.py").read_text(encoding="utf-8")
    result = executor.execute(request)
    assert not result.succeeded
    assert result.error.details["failure_type"] == "REPAIR_NO_PROGRESS"
    assert (tmp_path / "csv_cleaner/__main__.py").read_text(encoding="utf-8") == before
    assert executor.materialized_units["implementation-1"][1] == baseline_hash
    assert executor.calls[0]["candidate_committed"] is False
    assert executor.calls[0]["repair_candidate_state"]["status"] == "DISCARDED"
    assert "csv_cleaner/core.py" not in client.calls[0]["user"]


def test_two_identical_failure_fingerprints_stop_as_repair_stalled(tmp_path: pathlib.Path) -> None:
    first = _patch(("MARKER = 1", "MARKER = 2"))
    second = _patch(("MARKER = 1", "MARKER = 3"))
    executor, _, request, baseline_hash = _executor(tmp_path, [first, second])
    one = executor.execute(request)
    two = executor.execute(request)
    assert one.error.details["failure_type"] == "REPAIR_NO_PROGRESS"
    assert two.error.details["failure_type"] == "REPAIR_STALLED"
    assert executor.materialized_units["implementation-1"][1] == baseline_hash
    assert "previous_failed_attempt" in json.loads(executor.generation.client.calls[1]["user"])["repair_evidence_packet"]


def test_fixed_candidate_passes_target_and_commits_new_baseline(tmp_path: pathlib.Path) -> None:
    correct = _patch(('+ "\\n\\n"', '+ "\\n"'))
    executor, _, request, baseline_hash = _executor(tmp_path, [correct])
    result = executor.execute(request)
    assert result.succeeded
    assert executor.calls[0]["repair_progress"] == "FIXED"
    assert executor.calls[0]["candidate_committed"] is True
    assert executor.materialized_units["implementation-1"][1] != baseline_hash
    assert '+ "\\n"' in (tmp_path / "csv_cleaner/__main__.py").read_text(encoding="utf-8")


def test_target_fix_with_regression_is_discarded_atomically(tmp_path: pathlib.Path) -> None:
    regressed = _patch(('+ "\\n\\n"', '+ "\\n"'), ("MARKER = 1", "MARKER = 2"))
    executor, _, request, baseline_hash = _executor(tmp_path, [regressed], with_regression=True)
    result = executor.execute(request)
    assert not result.succeeded
    assert result.error.details["failure_type"] == "REPAIR_REGRESSION"
    source = (tmp_path / "csv_cleaner/__main__.py").read_text(encoding="utf-8")
    assert '+ "\\n\\n"' in source and "MARKER = 1" in source
    assert executor.materialized_units["implementation-1"][1] == baseline_hash


def test_evidence_packet_is_minimal_public_safe_and_carries_previous_diff(tmp_path: pathlib.Path) -> None:
    wrong = _patch(("MARKER = 1", "MARKER = 2"))
    correct = _patch(('+ "\\n\\n"', '+ "\\n"'))
    executor, client, request, _ = _executor(tmp_path, [wrong, correct])
    executor.execute(request)
    executor.execute(request)
    first_prompt = json.loads(client.calls[0]["user"])
    second_prompt = json.loads(client.calls[1]["user"])
    packet = second_prompt["repair_evidence_packet"]
    assert packet["exact_observable"] == "stdout.csv_rows"
    assert packet["expected_public_result"] == [["1", "Ada", ""]]
    assert packet["actual_public_result"] == [["1", "Ada", ""], []]
    assert packet["previous_failed_attempt"]["progress"] == "NO_PROGRESS"
    assert "MARKER = 2" in packet["previous_failed_attempt"]["diff"]
    assert "hidden" not in json.dumps(packet).casefold()
    assert "normative_public_contract" not in second_prompt
    assert "failure_report" not in second_prompt
    assert "current_files" not in second_prompt
    assert "def _print_preview" in packet["relevant_implementation_files"]["csv_cleaner/__main__.py"]
    assert "def _read_csv" not in packet["relevant_implementation_files"]["csv_cleaner/__main__.py"]
    assert len(json.dumps(second_prompt)) < len(json.dumps(first_prompt)) + 6000


def test_original_baseline_is_used_for_second_repair_after_discard(tmp_path: pathlib.Path) -> None:
    wrong = _patch(("MARKER = 1", "MARKER = 2"))
    correct = _patch(('+ "\\n\\n"', '+ "\\n"'))
    executor, _, request, baseline_hash = _executor(tmp_path, [wrong, correct])
    executor.execute(request)
    assert executor.materialized_units["implementation-1"][1] == baseline_hash
    repaired = executor.execute(request)
    assert repaired.succeeded
    assert "MARKER = 1" in (tmp_path / "csv_cleaner/__main__.py").read_text(encoding="utf-8")

