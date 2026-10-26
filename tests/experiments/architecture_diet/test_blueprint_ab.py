from __future__ import annotations

import json
import pathlib
from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator

from cgkn.application.software_project.catalog import get_case
from experiments.architecture_diet.blueprint_ab import (
    MinimalSemanticBlueprint,
    _design,
    decode_minimal_blueprint,
    encode_minimal_blueprint,
    minimal_blueprint_schema,
    representation_metrics,
    run_offline_blueprint_ab,
)


ROOT = pathlib.Path(__file__).resolve().parents[3]


def _contract(case_id: str) -> dict[str, object]:
    case = get_case(case_id)
    return {
        "case_id": case.case_id,
        "public_goal": case.public_goal,
        "public_acceptance": list(case.public_acceptance),
        "entrypoint": case.entrypoint,
        "runtime_command": list(case.runtime_command),
        "constraints": [
            "stdlib only", "offline", "no hidden acceptance access",
            "no placeholders", "worker writes exactly unit.owns",
        ],
    }


@pytest.mark.parametrize("case_id", ["cli_csv_cleaner", "seeded_repair"])
def test_minimal_blueprint_round_trip_is_exact_and_smaller(case_id: str) -> None:
    contract = _contract(case_id)
    authority = _design(case_id, contract)

    compact = encode_minimal_blueprint(authority, contract)
    decoded = decode_minimal_blueprint(
        MinimalSemanticBlueprint.from_dict(compact.as_dict()), contract,
    )
    metrics = representation_metrics(authority, compact)

    assert decoded.as_dict() == authority.as_dict()
    assert metrics["b1"]["bytes"] < metrics["b0"]["bytes"]
    assert metrics["byte_reduction_percent"] >= 50
    assert set(metrics["retained_semantics"]) == {
        "responsibility", "ownership", "read_scope", "public_requirement_ids",
        "required_interfaces", "dependencies", "project_goal", "project_constraints",
    }
    serialized = json.dumps(compact.as_dict(), sort_keys=True)
    assert "executor_ref" not in serialized
    assert "protected_paths" not in serialized
    assert "checks" not in serialized


def test_minimal_blueprint_schema_and_parser_are_strict() -> None:
    contract = _contract("cli_csv_cleaner")
    value = encode_minimal_blueprint(_design("cli_csv_cleaner", contract), contract).as_dict()
    schema = minimal_blueprint_schema()

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    value["surprise"] = True
    with pytest.raises(ValueError, match="unknown or missing fields"):
        MinimalSemanticBlueprint.from_dict(value)


def test_codec_rejects_unproven_execution_metadata_drift() -> None:
    contract = _contract("cli_csv_cleaner")
    authority = _design("cli_csv_cleaner", contract)
    changed = replace(
        authority,
        units=(replace(authority.units[0], timeout_seconds=121), *authority.units[1:]),
        blueprint_hash="",
    )

    with pytest.raises(ValueError, match="semantic mismatch: units"):
        encode_minimal_blueprint(changed, contract)


def test_offline_b0_b1_preserve_csv_and_seeded_repair_behavior(tmp_path: pathlib.Path) -> None:
    result = run_offline_blueprint_ab(ROOT, tmp_path / "evidence")

    assert result["status"] == "PASS"
    assert result["paid_provider_calls"] == 0
    assert result["production_authority_changed"] is False
    assert len(result["source_commit"]) == 40 and len(result["source_tree"]) == 40
    assert result["receipt_hash"].startswith("sha256:")
    assert result["representation_equivalence"] == "PROVEN_OFFLINE"
    assert result["representation_size_benefit"] == "PROVEN_OFFLINE"
    assert result["runtime_token_call_benefit"] == "NOT_PROVEN_PROMPT_CHARS_AND_CALLS_IDENTICAL"
    assert result["d3_adaptive_gate"] == "NOT_QUALIFIED"
    assert result["production_adoption"] == "NOT_ADOPTED"
    assert result["recommendation"] == "KEEP_CURRENT_PRODUCTION_BLUEPRINT"
    assert (tmp_path / "evidence" / "blueprint-ab.json").is_file()
    by_case = {item["case_id"]: item for item in result["cases"]}
    assert set(by_case) == {"cli_csv_cleaner", "seeded_repair"}
    for item in by_case.values():
        assert item["semantic_equivalence"]
        assert item["tree_equal"] and item["dag_equal"] and item["behavior_equal"]
        assert item["b0_behavior"]["status"] == "SUCCEEDED"
        assert item["b0_behavior"]["scope_preserved"]
        assert item["b0_behavior"]["hidden_source_exposed"] is False
    repair = by_case["seeded_repair"]["b0_behavior"]
    assert repair["repair_calls"] == 1 and repair["repair_rounds"] == 1

