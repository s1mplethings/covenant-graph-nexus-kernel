from __future__ import annotations

import json
import pathlib

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def validator_class():
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft202012Validator


@pytest.mark.parametrize(
    ("artifact_path", "schema_name"),
    [
        (
            "project_management/cgkn/project_management.json",
            "adaptive_project_management_pack.schema.json",
        ),
        (
            "project_management/cgkn/iterations/ITER-001.json",
            "adaptive_iteration.schema.json",
        ),
        (
            "project_management/enterprise_experience.json",
            "enterprise_experience_pack.schema.json",
        ),
    ],
)
def test_self_hosting_artifact_matches_registered_schema(
    validator_class,
    artifact_path: str,
    schema_name: str,
) -> None:
    artifact = json.loads((ROOT / artifact_path).read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    errors = sorted(validator_class(schema).iter_errors(artifact), key=lambda error: list(error.path))
    assert errors == []


def test_workflow_state_cannot_be_used_as_evidence_status(validator_class) -> None:
    artifact = json.loads(
        (ROOT / "project_management" / "cgkn" / "project_management.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "schemas" / "adaptive_project_management_pack.schema.json").read_text(encoding="utf-8")
    )
    artifact["evidence_status"] = "delivering"
    assert list(validator_class(schema).iter_errors(artifact))


def test_approved_experience_without_evidence_fails_semantic_validation() -> None:
    sys_path = str(ROOT / "src")
    import sys

    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from cgkn_project_management import validate_enterprise_experience_pack

    artifact = json.loads(
        (ROOT / "project_management" / "enterprise_experience.json").read_text(encoding="utf-8")
    )
    artifact["items"][0]["evidence_refs"] = []
    result = validate_enterprise_experience_pack(artifact)
    assert result["status"] == "FAIL"
    assert any(row["code"] == "EXPERIENCE_EVIDENCE_MISSING" for row in result["errors"])
