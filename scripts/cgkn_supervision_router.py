#!/usr/bin/env python3
"""Deterministic routing for bounded false-pass audit results.

The router records what CGKN must do next.  It never asks a model to choose a
target and it owns no Provider, evidence, packaging, or delivery authority.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any


CANONICAL_ACTIONS = {
    "resume",
    "rework_project",
    "recheck_evidence",
    "repair_kernel",
    "user_decision",
    "halt",
}

ACTION_SCOPES = {
    "resume": {"none"},
    "rework_project": {"project", "integration", "requirements"},
    "recheck_evidence": {"evidence", "runtime", "visual", "identity"},
    "repair_kernel": {"kernel"},
    "user_decision": {"user"},
    "halt": {"safety"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_write(path: pathlib.Path, value: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def validate_route_input(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    action = str(result.get("action", ""))
    scope = str(result.get("scope", ""))
    if action not in CANONICAL_ACTIONS:
        errors.append("route.action")
    elif scope not in ACTION_SCOPES[action]:
        errors.append("route.scope")
    refs = result.get("evidence_refs", [])
    if not isinstance(refs, list):
        errors.append("route.evidence_refs")
    elif action != "resume" and action != "user_decision" and not refs:
        errors.append("route.evidence_refs_required")
    targets = result.get("repair_targets", [])
    if not isinstance(targets, list):
        errors.append("route.repair_targets")
    elif action in {"rework_project", "repair_kernel"} and not targets:
        errors.append("route.repair_targets_required")
    elif action not in {"rework_project", "repair_kernel"} and targets:
        errors.append("route.repair_targets_unexpected")
    return sorted(set(errors))


def dispatch(
    result: dict[str, Any],
    checkpoint: dict[str, Any],
    state_dir: str | pathlib.Path,
) -> dict[str, Any]:
    """Persist one deterministic next-action receipt for a CGKN worker."""
    errors = validate_route_input(result)
    if errors:
        raise ValueError("invalid supervision route: " + ",".join(errors))
    action = str(result["action"])
    route_type = {
        "resume": "continue_current_stage",
        "rework_project": "provider_repair_required",
        "recheck_evidence": "canonical_verification_rerun_required",
        "repair_kernel": "governed_kernel_repair_required",
        "user_decision": "wait_for_user",
        "halt": "stop_safely",
    }[action]
    receipt: dict[str, Any] = {
        "kind": "CGKNSupervisionRouteReceipt",
        "schema_version": "1.0",
        "created_at": _now(),
        "checkpoint_id": str(checkpoint.get("checkpoint_id", "")),
        "checkpoint_sha256": str(checkpoint.get("checkpoint_sha256", "")),
        "result_sha256": str(result.get("result_sha256", "")),
        "action": action,
        "scope": str(result["scope"]),
        "route_type": route_type,
        "evidence_refs": list(result.get("evidence_refs", [])),
        "repair_targets": list(result.get("repair_targets", [])),
        "acceptance_checks": list(result.get("acceptance_checks", [])),
        "provider_authoring_required": action == "rework_project",
        "provider_authoring_forbidden": action in {"resume", "recheck_evidence", "repair_kernel", "user_decision", "halt"},
        "codex_kernel_write_required": action == "repair_kernel",
        "formal_evidence_authorized": False,
        "package_authorized": False,
        "delivery_authorized": False,
    }
    receipt["route_sha256"] = _hash(receipt)
    root = pathlib.Path(state_dir).resolve() / "routes"
    _atomic_write(root / f"{receipt['checkpoint_id']}.json", receipt)
    if action == "rework_project":
        _atomic_write(root / "pending_provider_repair.json", receipt)
    elif action == "recheck_evidence":
        _atomic_write(root / "pending_evidence_recheck.json", receipt)
    elif action == "repair_kernel":
        _atomic_write(root / "pending_kernel_repair.json", receipt)
    return receipt
