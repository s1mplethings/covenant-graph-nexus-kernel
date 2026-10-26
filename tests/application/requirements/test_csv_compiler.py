from __future__ import annotations

import json

from cgkn.application.requirements import compile_csv_cleaner, write_obligation_preflight


EXPECTED = {
    "OBL-CSV-INPUT-OUTPUT", "OBL-CSV-HEADER-PRESERVATION", "OBL-CSV-DEDUP-WHOLE-ROW",
    "OBL-CSV-DEDUP-COLUMN", "OBL-CSV-STABLE-ORDER", "OBL-CSV-FILL-EMPTY", "OBL-CSV-PREVIEW",
    "OBL-CSV-PREVIEW-WRITES-OUTPUT", "OBL-CSV-CLI-HELP", "OBL-CSV-ERR-UNKNOWN-COLUMN",
    "OBL-CSV-ERR-NONZERO", "OBL-CSV-README", "OBL-CSV-PUBLIC-TESTS", "OBL-CSV-RUNTIME-STDLIB",
    "OBL-CSV-TEST-PYTEST", "OBL-CSV-NETWORK-OFFLINE",
}


def test_csv_goal_compiles_every_public_behavior_and_policy() -> None:
    result = compile_csv_cleaner()
    assert {item.obligation_id for item in result.obligations.obligations} == EXPECTED
    receipt = result.preflight.as_dict()
    assert receipt["status"] == "COMPLETE"
    assert receipt["unmapped_requirements"] == []
    assert receipt["unverifiable_obligations"] == []
    assert receipt["ambiguous_behaviors"] == ["malformed_csv=UNSPECIFIED"]
    assert receipt["dependency_policies"][0]["runtime"]["stdlib_only"] is True
    assert receipt["dependency_policies"][0]["test"]["allowed_packages"] == ["pytest"]
    assert receipt["dependency_policies"][0]["network"]["outbound"] == "FORBIDDEN"
    assert {item["obligation_id"] for item in receipt["error_semantics"]} == {"OBL-CSV-ERR-UNKNOWN-COLUMN", "OBL-CSV-ERR-NONZERO"}
    assert receipt["hidden_coverage"]["coverage"] == 1.0


def test_preflight_round_trip_file_has_all_generation_gate_fields(tmp_path) -> None:
    target = write_obligation_preflight(tmp_path / "obligation_preflight.json", compile_csv_cleaner().preflight)
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["status"] == "COMPLETE"
    for key in ("requirements_total", "obligations_total", "unmapped_requirements", "unverifiable_obligations", "ambiguous_behaviors", "dependency_policies", "error_semantics", "hidden_coverage"):
        assert key in document


def test_hidden_acceptance_manifest_is_fully_traceable() -> None:
    result = compile_csv_cleaner()
    assert result.preflight.traceability.status == "PASS"
    assert result.preflight.traceability.hidden_acceptance_coverage == 1.0
    assert not any("MALFORMED" in key for key in result.traceability.acceptance_to_obligation)


def test_hidden_assertion_for_nonexistent_requirement_is_harness_gap(tmp_path) -> None:
    manifest = tmp_path / "hidden.json"
    manifest.write_text(json.dumps({"tests": [{"test_id": "ACCEPT-UNDECLARED", "obligation_ids": ["OBL-CSV-NOT-DECLARED"]}]}), encoding="utf-8")
    result = compile_csv_cleaner(hidden_manifest=manifest)
    assert result.preflight.as_dict()["status"] == "HARNESS_CONTRACT_GAP"
    assert result.preflight.traceability.hidden_acceptance_coverage == 0.0


def test_malformed_csv_can_only_become_an_obligation_when_policy_explicitly_requires_it() -> None:
    default = compile_csv_cleaner()
    explicit = compile_csv_cleaner(require_malformed_rejection=True)
    assert "OBL-CSV-ERR-MALFORMED" not in {item.obligation_id for item in default.obligations.obligations}
    assert "OBL-CSV-ERR-MALFORMED" in {item.obligation_id for item in explicit.obligations.obligations}
    assert explicit.preflight.as_dict()["ambiguous_behaviors"] == []
