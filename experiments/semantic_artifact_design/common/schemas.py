from __future__ import annotations

from typing import Any, Mapping

from jsonschema import Draft202012Validator


KINDS = (
    "project.contract@1", "project.structure@1", "work_unit.contract@1",
    "interface.manifest@1", "test.contract@1", "test.result@1",
    "failure.evidence@1", "repair.directive@1", "project.snapshot@1",
    "acceptance.receipt@1",
)


def _object(required: list[str], properties: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": required, "properties": dict(properties)}


STRINGS = {"type": "array", "items": {"type": "string"}}
SCHEMAS: dict[str, dict[str, Any]] = {
    "project.contract@1": _object(
        ["project_id", "public_goal", "constraints", "required_entrypoints", "public_acceptance", "runtime_requirements"],
        {"project_id": {"type": "string", "minLength": 1}, "public_goal": {"type": "string", "minLength": 1}, "constraints": STRINGS,
         "required_entrypoints": STRINGS, "public_acceptance": STRINGS, "runtime_requirements": STRINGS},
    ),
    "project.structure@1": _object(
        ["units"], {"units": {"type": "array", "minItems": 1, "items": _object(
            ["unit_id", "role", "paths"], {"unit_id": {"type": "string", "minLength": 1}, "role": {"type": "string", "minLength": 1}, "paths": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string", "minLength": 1}}})}},
    ),
    "work_unit.contract@1": _object(
        ["unit_id", "role", "paths", "responsibilities", "dependencies", "public_interfaces", "allowed_changes"],
        {"unit_id": {"type": "string", "minLength": 1}, "role": {"type": "string", "minLength": 1},
         "paths": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string", "minLength": 1}},
         "responsibilities": STRINGS, "dependencies": STRINGS, "public_interfaces": STRINGS, "allowed_changes": STRINGS},
    ),
    "interface.manifest@1": _object(
        ["modules", "manifest_hash"], {"modules": {"type": "array", "items": {"type": "object"}}, "manifest_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}},
    ),
    "test.contract@1": _object(
        ["test_paths", "requirements"], {"test_paths": STRINGS, "requirements": STRINGS},
    ),
    "test.result@1": _object(
        ["status", "returncode", "failed_tests", "stdout_tail", "stderr_tail"],
        {"status": {"enum": ["PASS", "FAIL", "BLOCKED_ENVIRONMENT"]}, "returncode": {"type": "integer"}, "failed_tests": STRINGS,
         "stdout_tail": {"type": "string"}, "stderr_tail": {"type": "string"}},
    ),
    "failure.evidence@1": _object(
        ["failure_class", "owner_file", "owner_module", "owner_interface", "first_project_frame", "failed_test", "expected", "observed", "allowed_repair_units"],
        {"failure_class": {"enum": ["SYNTAX_ERROR", "IMPORT_ERROR", "NAME_ERROR", "INTERFACE_MISMATCH", "TEST_DEFECT", "SOURCE_BEHAVIOR_DEFECT", "CLI_CONTRACT_DEFECT", "RUNTIME_DEFECT", "STATE_DEFECT", "UNKNOWN"]},
         "owner_file": {"type": "string"}, "owner_module": {"type": "string"}, "owner_interface": {"type": "string"},
         "first_project_frame": {"type": "string"}, "failed_test": {"type": "string"}, "expected": {"type": "string"},
         "observed": {"type": "string"}, "allowed_repair_units": STRINGS},
    ),
    "repair.directive@1": _object(
        ["target_unit", "reason", "allowed_paths"], {"target_unit": {"type": "string", "minLength": 1}, "reason": {"type": "string", "minLength": 1}, "allowed_paths": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string"}}},
    ),
    "project.snapshot@1": _object(
        ["snapshot_hash", "project_tree_hash", "files"], {"snapshot_hash": {"type": "string", "pattern": "^sha256:"}, "project_tree_hash": {"type": "string", "pattern": "^sha256:"}, "files": {"type": "array", "items": {"type": "object"}}},
    ),
    "acceptance.receipt@1": _object(
        ["status", "snapshot_hash", "failed_requirement_ids"], {"status": {"enum": ["PASS", "FAIL", "BLOCKED_ENVIRONMENT"]}, "snapshot_hash": {"type": "string"}, "failed_requirement_ids": STRINGS},
    ),
}


def validate_payload(kind: str, payload: Mapping[str, Any]) -> None:
    schema = SCHEMAS.get(kind)
    if schema is None:
        raise ValueError(f"unknown semantic artifact kind: {kind}")
    errors = sorted(Draft202012Validator(schema).iter_errors(dict(payload)), key=lambda item: list(item.path))
    if errors:
        raise ValueError("invalid semantic payload: " + "; ".join(error.message for error in errors[:3]))
