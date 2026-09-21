#!/usr/bin/env python3
"""Deterministic cross-validation receipts and bounded feedforward projections.

This module is deliberately a support boundary.  Its lower-case pass/fail
status can veto component publication, but it cannot assert a formal CGKN
evidence status, package a project, or authorize delivery.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


def _canonical_hash(document: dict[str, Any], hash_field: str) -> str:
    payload = dict(document)
    payload.pop(hash_field, None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_paths(values: Iterable[Any]) -> list[str]:
    return sorted(
        {
            str(value).replace("\\", "/").strip()
            for value in values
            if str(value).strip()
        }
    )


def _receipt_hash_valid(document: Any, hash_field: str) -> bool:
    return bool(
        isinstance(document, dict)
        and str(document.get(hash_field, ""))
        and str(document.get(hash_field, "")) == _canonical_hash(document, hash_field)
    )


def build_component_receipt(
    *,
    component_id: str,
    required_paths: Iterable[Any],
    actual_paths: Iterable[Any],
    component_quality_validation: dict[str, Any],
    interface_registry: dict[str, Any],
    integration_feedforward: dict[str, Any],
) -> dict[str, Any]:
    """Cross-bind independent planning, quality, interface, and upstream views."""
    component_id = str(component_id).strip()
    required = _normalized_paths(required_paths)
    actual = _normalized_paths(actual_paths)
    blockers: list[str] = []
    affected: set[str] = set()

    missing_required = sorted(set(required) - set(actual))
    if missing_required:
        affected.update(missing_required)
        blockers.append("planned required paths are absent: " + ", ".join(missing_required))

    quality_paths = _normalized_paths(component_quality_validation.get("validated_paths", []))
    if str(component_quality_validation.get("status", "")).lower() != "pass":
        blockers.append("component quality receipt is not pass")
    if not _receipt_hash_valid(component_quality_validation, "receipt_sha256"):
        blockers.append("component quality receipt hash is invalid")
    if quality_paths != actual:
        affected.update(set(quality_paths).symmetric_difference(actual))
        blockers.append("component quality receipt paths do not match current component files")

    if not _receipt_hash_valid(interface_registry, "registry_sha256"):
        blockers.append("project interface registry hash is invalid")
    provider_paths = _normalized_paths(
        item.get("path", "")
        for item in interface_registry.get("providers", [])
        if isinstance(item, dict)
    )
    missing_registry_paths = sorted(set(actual) - set(provider_paths))
    if missing_registry_paths:
        affected.update(missing_registry_paths)
        blockers.append(
            "current component files are absent from the interface registry: "
            + ", ".join(missing_registry_paths)
        )
    if int(interface_registry.get("provider_count", -1)) != len(provider_paths):
        blockers.append("project interface registry provider count does not match its catalog")

    if not _receipt_hash_valid(integration_feedforward, "snapshot_sha256"):
        blockers.append("integration feedforward snapshot hash is invalid")
    current_contract = integration_feedforward.get("current_contract", {})
    upstream_state = integration_feedforward.get("upstream_state", {})
    expected_upstream = _normalized_paths(current_contract.get("expected_upstream_components", []))
    completed_upstream = _normalized_paths(upstream_state.get("completed_components", []))
    missing_upstream = sorted(set(expected_upstream) - set(completed_upstream))
    if missing_upstream:
        blockers.append("expected upstream components have not completed: " + ", ".join(missing_upstream))

    prior_projections = [
        item
        for item in upstream_state.get("cross_validation_feedforward", [])
        if isinstance(item, dict)
    ]
    projected_upstream = {
        str(item.get("component_id", "")).strip()
        for item in prior_projections
        if str(item.get("receipt_sha256", "")).strip()
        and str(item.get("status", "")).lower() == "pass"
    }
    unvalidated_upstream = sorted(set(expected_upstream) - projected_upstream)
    if unvalidated_upstream:
        blockers.append(
            "expected upstream components lack passing cross-validation receipts: "
            + ", ".join(unvalidated_upstream)
        )

    downstream_ids = _normalized_paths(
        item.get("id", "")
        for item in integration_feedforward.get("downstream_consumers", [])
        if isinstance(item, dict)
    )
    receipt: dict[str, Any] = {
        "kind": "CGKNCrossValidationFeedforwardReceipt",
        "schema_version": 1,
        "scope": "component",
        "component_id": component_id,
        "status": "pass" if not blockers else "fail",
        "checks": [
            "plan_to_output_path_coverage",
            "component_quality_receipt_integrity",
            "quality_to_current_file_binding",
            "implemented_interface_registry_integrity",
            "upstream_completion_and_receipt_binding",
        ],
        "bindings": {
            "required_paths": required,
            "actual_paths": actual,
            "component_quality_receipt_sha256": str(
                component_quality_validation.get("receipt_sha256", "")
            ),
            "interface_registry_sha256": str(interface_registry.get("registry_sha256", "")),
            "integration_feedforward_snapshot_sha256": str(
                integration_feedforward.get("snapshot_sha256", "")
            ),
            "expected_upstream_components": expected_upstream,
            "upstream_receipt_sha256": sorted(
                str(item.get("receipt_sha256", ""))
                for item in prior_projections
                if str(item.get("receipt_sha256", ""))
            ),
            "downstream_component_ids": downstream_ids,
        },
        "blockers": list(dict.fromkeys(blockers)),
        "affected_files": sorted(affected),
        "authority": {
            "veto_only": True,
            "can_assert_formal_evidence": False,
            "can_package": False,
            "can_deliver": False,
        },
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt, "receipt_sha256")
    return receipt


def component_feedforward_projection(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded downstream projection for a verified passing receipt."""
    if (
        str(receipt.get("kind", "")) != "CGKNCrossValidationFeedforwardReceipt"
        or str(receipt.get("scope", "")) != "component"
        or str(receipt.get("status", "")).lower() != "pass"
        or not _receipt_hash_valid(receipt, "receipt_sha256")
    ):
        return {}
    bindings = receipt.get("bindings", {}) if isinstance(receipt.get("bindings"), dict) else {}
    return {
        "kind": "CGKNCrossValidationFeedforwardProjection",
        "schema_version": 1,
        "status": "pass",
        "component_id": str(receipt.get("component_id", "")),
        "receipt_sha256": str(receipt.get("receipt_sha256", "")),
        "validated_paths": _normalized_paths(bindings.get("actual_paths", [])),
        "component_quality_receipt_sha256": str(
            bindings.get("component_quality_receipt_sha256", "")
        ),
        "interface_registry_sha256": str(bindings.get("interface_registry_sha256", "")),
    }


def build_project_receipt(
    *,
    component_receipts: Iterable[dict[str, Any]],
    assembled_quality_validation: dict[str, Any],
    required_final_paths: Iterable[Any],
    actual_paths: Iterable[Any],
    interface_registry: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate component receipts before the existing post-build evidence stage."""
    receipts = [item for item in component_receipts if isinstance(item, dict)]
    required = _normalized_paths(required_final_paths)
    actual = _normalized_paths(actual_paths)
    blockers: list[str] = []
    missing = sorted(set(required) - set(actual))
    if missing:
        blockers.append("required final paths are absent: " + ", ".join(missing))
    invalid_components = [
        str(item.get("component_id", ""))
        for item in receipts
        if str(item.get("status", "")).lower() != "pass"
        or not _receipt_hash_valid(item, "receipt_sha256")
    ]
    if invalid_components:
        blockers.append(
            "component cross-validation receipts are not valid pass receipts: "
            + ", ".join(invalid_components)
        )
    if str(assembled_quality_validation.get("status", "")).lower() != "pass":
        blockers.append("assembled project quality receipt is not pass")
    if not _receipt_hash_valid(assembled_quality_validation, "receipt_sha256"):
        blockers.append("assembled project quality receipt hash is invalid")
    if not _receipt_hash_valid(interface_registry, "registry_sha256"):
        blockers.append("assembled project interface registry hash is invalid")

    receipt: dict[str, Any] = {
        "kind": "CGKNCrossValidationFeedforwardReceipt",
        "schema_version": 1,
        "scope": "assembled_project",
        "status": "pass" if not blockers else "fail",
        "checks": [
            "component_cross_validation_receipt_integrity",
            "assembled_quality_receipt_integrity",
            "required_final_path_coverage",
            "assembled_interface_registry_integrity",
        ],
        "bindings": {
            "component_receipt_sha256": [
                str(item.get("receipt_sha256", "")) for item in receipts
            ],
            "assembled_quality_receipt_sha256": str(
                assembled_quality_validation.get("receipt_sha256", "")
            ),
            "interface_registry_sha256": str(interface_registry.get("registry_sha256", "")),
            "required_final_paths": required,
            "actual_paths": actual,
        },
        "blockers": list(dict.fromkeys(blockers)),
        "authority": {
            "veto_only": True,
            "can_assert_formal_evidence": False,
            "can_package": False,
            "can_deliver": False,
        },
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt, "receipt_sha256")
    return receipt


def receipt_hash_valid(receipt: dict[str, Any]) -> bool:
    return _receipt_hash_valid(receipt, "receipt_sha256")
