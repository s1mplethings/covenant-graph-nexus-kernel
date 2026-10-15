from __future__ import annotations

import importlib.util
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "adaptive_autonomous_validation", ROOT / "scripts" / "adaptive_autonomous_validation.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def project(project_id: str):
    return next(item for item in module.PROJECTS if item.spec.project_id == project_id)


def test_operation_schema_rejects_unknown_and_invalid_without_mapping() -> None:
    orbit = project("orbit360")
    document = {
        "actions": [
            {"op": "plan", "args": {"units": "twelve", "width": 4}},
            {"op": "create_plan", "args": {"units": 12, "width": 4}},
            {"op": "plan", "args": {"units": 12, "width": 4}},
        ]
    }

    result = module.validate_model_document(orbit, document, 6)

    assert [item["op"] for item in result["actions"]] == ["plan"]
    assert [item["reason"] for item in result["unsupported_proposals"]] == ["schema_invalid", "unsupported_operation"]
    assert all(item["executed"] is False and item["auto_mapped"] is False for item in result["unsupported_proposals"])


def test_compression_retains_failure_and_independent_issue() -> None:
    row = {
        "observation_id": "obs-01",
        "op": "sample",
        "result": {"rows": list(range(1000))},
        "before": [],
        "after": [1],
        "returncode": 1,
        "stderr": "important failure",
        "independent_issues": [{"issue_type": "sample_failure", "summary": "failed", "details": {}}],
    }

    compressed = module.compress_observation(row, "raw.json")
    audit = module.compression_audit([row], [compressed])

    assert compressed["operation_id"] == "obs-01"
    assert compressed["execution_result"]["returncode"] == 1
    assert compressed["errors"] == ["important failure"]
    assert compressed["independent_issues"][0]["issue_type"] == "sample_failure"
    assert audit["status"] == "PASS"
    assert audit["important_failure_evidence_lost"] is False


def test_escalation_gate_stays_closed_for_sufficient_normal_evidence() -> None:
    gate = module.escalation_gate(
        [{"observation_id": "obs-01", "op": "list_tasks", "returncode": 0, "independent_issues": []}],
        {"actions": [{"op": "list_tasks"}], "unsupported_proposals": []},
    )

    assert gate["allowed"] is False
    assert gate["normal_evidence_sufficient"] is True


def test_token_preflight_is_conservative_and_includes_output_cap() -> None:
    assert module.conservative_call_token_ceiling("abcd") == 1802
    assert module.conservative_call_token_ceiling("知识") >= 1803


def test_task_ledger_oracle_accepts_valid_append_and_rejects_silent_invalid_mutation() -> None:
    valid = {
        "observation_id": "obs-01", "op": "add_task", "args": {"title": "review"},
        "before": [], "after": [{"title": "review"}], "result": None, "returncode": 0,
    }
    invalid = {
        "observation_id": "obs-02", "op": "add_task", "args": {"title": ""},
        "before": [], "after": [{"title": ""}], "result": None, "returncode": 0,
    }

    assert module.task_ledger_oracle(valid) == []
    assert module.task_ledger_oracle(invalid)[0]["issue_type"] == "invalid_task_mutated_ledger"


def test_report_schema_preserves_support_only_boundary() -> None:
    schema = json.loads((ROOT / "schemas" / "adaptive_autonomous_validation_report_v1.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["formal_evidence_status"]["const"] == "NOT_EVALUATED"
    assert schema["properties"]["release_authority"]["const"] is False
    assert schema["properties"]["conditional_escalation_default_enabled"]["type"] == "boolean"

