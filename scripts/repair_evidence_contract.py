#!/usr/bin/env python3
"""Single schema and construction authority for production project repair evidence."""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "observed_project_failure_evidence_v1.schema.json"
KIND = "CGKNObservedProjectFailureEvidence"
SCHEMA_VERSION = "1.0"
FORBIDDEN_KEYS = frozenset(
    {"hidden_acceptance", "hidden_expected_implementation", "expected_implementation", "benchmark_answer", "evaluator_source"}
)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        if FORBIDDEN_KEYS.intersection(str(key).strip().lower() for key in value):
            return True
        return any(_contains_forbidden_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def validate(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["repair evidence must be an object"]
    if value.get("kind") != KIND:
        errors.append("kind must be CGKNObservedProjectFailureEvidence")
    if str(value.get("schema_version", "")) != SCHEMA_VERSION:
        errors.append("schema_version must be 1.0")
    required = (
        "evidence_id", "run_id", "project_id", "original_requirement_identity",
        "failure_category", "failed_acceptance_ids", "observable_failure",
        "candidate_identity", "repair_round", "repair_eligible", "failures", "constraints",
    )
    errors.extend(f"missing {key}" for key in required if key not in value)
    if _contains_forbidden_key(value):
        errors.append("repair evidence contains forbidden hidden evaluator material")
    identity = value.get("candidate_identity", {})
    if not isinstance(identity, dict):
        errors.append("candidate_identity must be an object")
        identity = {}
    for key in ("evaluated_candidate_dir", "candidate_sha256"):
        if not str(identity.get(key, "")).strip():
            errors.append(f"candidate_identity.{key} is required")
    if str(value.get("evaluated_candidate_dir", "")) != str(identity.get("evaluated_candidate_dir", "")):
        errors.append("evaluated_candidate_dir projection mismatch")
    if str(value.get("candidate_sha256", "")) != str(identity.get("candidate_sha256", "")):
        errors.append("candidate_sha256 projection mismatch")
    try:
        repair_round = int(value.get("repair_round", 0) or 0)
    except (TypeError, ValueError):
        repair_round = 0
    if repair_round not in {1, 2}:
        errors.append("repair_round must be 1 or 2")
    if not isinstance(value.get("failures"), list) or not value.get("failures"):
        errors.append("failures must be a non-empty array")
    if not isinstance(value.get("failed_acceptance_ids"), list):
        errors.append("failed_acceptance_ids must be an array")
    if not isinstance(value.get("observable_failure"), list) or not value.get("observable_failure"):
        errors.append("observable_failure must be a non-empty array")
    requirement_identity = str(value.get("original_requirement_identity", ""))
    if len(requirement_identity) != 64 or any(ch not in "0123456789abcdef" for ch in requirement_identity.lower()):
        errors.append("original_requirement_identity must be sha256 hex")
    return sorted(set(errors))


def load(path: pathlib.Path | str) -> dict[str, Any]:
    evidence_path = pathlib.Path(path).expanduser().resolve()
    if not evidence_path.is_file() or evidence_path.is_symlink():
        raise ValueError("repair_evidence must be an existing regular file")
    value = json.loads(evidence_path.read_text(encoding="utf-8"))
    errors = validate(value)
    if errors:
        raise ValueError("repair_evidence invalid: " + "; ".join(errors))
    return value


def build(
    *,
    run_id: str,
    project_id: str,
    user_goal: str,
    candidate_dir: pathlib.Path,
    candidate_sha256: str,
    repair_round: int,
    failure_category: str,
    failures: list[dict[str, Any]],
    repair_eligible: bool,
    blocking_reason: str,
    constraints: dict[str, Any],
) -> dict[str, Any]:
    failed_acceptance_ids = [
        str(item.get("criterion_id", "")).strip()
        for item in failures
        if str(item.get("criterion_id", "")).strip()
    ]
    observable_failure = [
        str(item.get("observed_behavior", item.get("details", ""))).strip()[:4000]
        for item in failures
        if str(item.get("observed_behavior", item.get("details", ""))).strip()
    ]
    candidate_identity = {
        "evaluated_candidate_dir": str(candidate_dir.resolve()),
        "candidate_sha256": str(candidate_sha256),
    }
    value = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "evidence_id": f"{run_id}:{project_id}:repair:{repair_round}",
        "run_id": str(run_id),
        "project_id": str(project_id),
        "case_id": str(project_id),
        "original_requirement_identity": hashlib.sha256(str(user_goal).encode("utf-8")).hexdigest(),
        "failure_category": str(failure_category).upper(),
        "failed_acceptance_ids": failed_acceptance_ids,
        "observable_failure": observable_failure or [f"Independent evaluator reported {failure_category}."],
        "runtime_error": "\n".join(str(item.get("runtime_error", "")) for item in failures if item.get("runtime_error"))[:8000],
        "dependency_error": "\n".join(str(item.get("dependency_error", "")) for item in failures if item.get("dependency_error"))[:8000],
        "stack_trace": "\n".join(str(item.get("failure_stack", "")) for item in failures if item.get("failure_stack"))[:12000],
        "affected_interfaces": sorted({str(name) for item in failures for name in item.get("affected_interfaces", []) if str(name).strip()}),
        "affected_files": sorted({str(name).replace("\\", "/") for item in failures for name in item.get("affected_files", []) if str(name).strip()}),
        "affected_work_nodes": sorted({str(name) for item in failures for name in item.get("affected_work_nodes", []) if str(name).strip()}),
        "candidate_identity": candidate_identity,
        "evaluated_candidate_dir": candidate_identity["evaluated_candidate_dir"],
        "candidate_sha256": candidate_identity["candidate_sha256"],
        "repair_round": int(repair_round),
        "repair_eligible": bool(repair_eligible),
        "blocking_reason": str(blocking_reason),
        "summary": f"Independent evaluator rejected {project_id} as {str(failure_category).upper()}.",
        "failures": failures,
        "constraints": constraints,
    }
    errors = validate(value)
    if errors:
        raise ValueError("repair_evidence invalid: " + "; ".join(errors))
    return value
