from __future__ import annotations

import json

import pytest

from cgkn.application.verification import (
    OracleEvidence,
    OracleKind,
    OraclePlan,
    OracleRegistry,
    OracleSpec,
    OracleStatus,
)


def spec(identifier: str = "ORACLE-CSV-001", **updates) -> OracleSpec:
    values = {
        "oracle_id": identifier,
        "obligation_ids": ("OBL-CSV-INPUT-OUTPUT",),
        "oracle_kind": OracleKind.CSV,
        "subject_ref": "csv_cleaner",
        "setup": {"fixture": {"header": ["id", "name"], "rows": [["1", "A"]]}},
        "operation": {"argv": ["python", "-m", "csv_cleaner"]},
        "expected": {"exit_code": 0, "output_created": True},
        "forbidden": {"shell": True},
        "side_effect_assertions": {"only": ["output.csv"]},
        "dependency_policy_refs": ("POLICY-CSV-DEPS",),
        "timeout_seconds": 10,
        "scope": ("project", "csv"),
        "provenance": {"compiler": "deterministic"},
    }
    values.update(updates)
    return OracleSpec(**values)


def plan(*specs: OracleSpec, source_ids: tuple[str, ...] = ("OBL-CSV-INPUT-OUTPUT",)) -> OraclePlan:
    return OraclePlan("PLAN-CSV-001", source_ids, "sha256:obligations", tuple(specs or (spec(),)))


def evidence(**updates) -> OracleEvidence:
    values = {
        "evidence_id": "EVIDENCE-ORACLE-001",
        "oracle_id": "ORACLE-CSV-001",
        "obligation_ids": ("OBL-CSV-INPUT-OUTPUT",),
        "status": OracleStatus.PASS,
        "expected": {"exit_code": 0},
        "observed": {"exit_code": 0},
        "return_code": 0,
        "artifacts": ({"path": "output.csv", "sha256": "abc"},),
        "duration_ms": 3,
    }
    values.update(updates)
    return OracleEvidence(**values)


def test_spec_round_trip_deep_immutability_and_stable_hash() -> None:
    first = spec()
    second = OracleSpec.from_dict(json.loads(json.dumps(first.as_dict())))
    assert second == first
    assert second.oracle_hash == first.oracle_hash
    assert hash(second) == hash(first)
    assert first.setup["fixture"]["header"] == ("id", "name")
    with pytest.raises(TypeError):
        first.expected["exit_code"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        first.setup["fixture"]["header"][0] = "other"  # type: ignore[index]


def test_plan_and_evidence_round_trip_are_deterministic() -> None:
    first = plan(spec("ORACLE-CSV-002"), spec())
    second = OraclePlan.from_dict(json.loads(json.dumps(first.as_dict())))
    assert second == first
    assert second.plan_hash == first.plan_hash
    assert [item.oracle_id for item in first.specs] == ["ORACLE-CSV-001", "ORACLE-CSV-002"]
    observed = evidence()
    assert OracleEvidence.from_dict(json.loads(json.dumps(observed.as_dict()))) == observed
    assert OracleEvidence.from_dict(observed.as_dict()).evidence_hash == observed.evidence_hash


def test_duplicate_oracle_and_unknown_obligation_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate oracle_id"):
        plan(spec(), spec())
    with pytest.raises(ValueError, match="unknown obligation"):
        plan(spec(obligation_ids=("OBL-CSV-UNKNOWN",)))


def test_unknown_kind_invalid_expected_and_invalid_timeout_are_rejected() -> None:
    document = spec().as_dict()
    document["oracle_kind"] = "UNIVERSAL_DSL"
    with pytest.raises(ValueError):
        OracleSpec.from_dict(document)
    with pytest.raises(ValueError, match="expected"):
        spec(expected={})
    with pytest.raises(ValueError, match="timeout"):
        spec(timeout_seconds=0)
    with pytest.raises(ValueError, match="timeout"):
        spec(timeout_seconds=301)


def test_dangling_required_oracle_and_evidence_refs_are_rejected() -> None:
    with pytest.raises(ValueError, match="dangling"):
        OraclePlan(
            "PLAN-CSV-001", ("OBL-CSV-INPUT-OUTPUT",), "sha256:obligations", (spec(),),
            required_oracle_ids=("ORACLE-CSV-404",),
        )
    registry = OracleRegistry(plan(spec()))
    with pytest.raises(KeyError):
        registry.get("ORACLE-CSV-404")
    with pytest.raises(ValueError, match="do not match"):
        registry.validate_evidence(evidence(obligation_ids=("OBL-CSV-HEADER-PRESERVATION",)))


def test_hash_tampering_and_invalid_evidence_state_are_rejected() -> None:
    document = spec().as_dict()
    document["oracle_hash"] = "sha256:bad"
    with pytest.raises(ValueError, match="hash mismatch"):
        OracleSpec.from_dict(document)
    with pytest.raises(ValueError, match="PASS evidence"):
        evidence(failure_class="SOURCE_DEFECT")


def test_registry_orders_and_resolves_specs_by_obligation() -> None:
    registry = OracleRegistry(plan(spec("ORACLE-CSV-002"), spec()))
    assert tuple(item.oracle_id for item in registry.for_obligation("OBL-CSV-INPUT-OUTPUT")) == (
        "ORACLE-CSV-001", "ORACLE-CSV-002"
    )
    registry.validate_evidence(evidence())
    with pytest.raises(KeyError):
        registry.for_obligation("OBL-CSV-UNKNOWN")
