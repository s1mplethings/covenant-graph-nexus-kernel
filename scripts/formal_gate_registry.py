from __future__ import annotations

import json
import pathlib
from typing import Any, Callable

from scripts import browser_visual_evidence
from scripts import canonical_delivery_manifest
from scripts import canonical_delivery_receipt
from scripts import canonical_evidence_hash
from scripts import canonical_user_review
from scripts import customer_runtime_runner
from scripts import real_test_execution
from scripts import production_candidate_provenance
from scripts import provider_causal_trace

FORMAL_GATE_STATUS_PRODUCER = "scripts/formal_mainline_acceptance.py"
FORMAL_GATE_STATUS_KIND = "CGKNFormalGateStatus"
TELEGRAM_BLOCKABLE_GATES = {
    "user_review",
    "delivery_manifest",
    "delivery_receipt",
}
PROVENANCE_BOUND_GATES = {
    "test_execution",
    "customer_runtime",
    "visual_evidence",
}
FORBIDDEN_PRODUCER_PREFIXES = (
    "tests",
    "test/",
    "tests/",
    "fixture",
    "example",
    "benchmark",
)
FORBIDDEN_PRODUCERS = {
    "scripts/final_internal_acceptance.py",
    "scripts/final_contract_unification_acceptance.py",
}

GATE_SPECS: dict[str, dict[str, Any]] = {
    "test_execution": {
        "scope": "candidate",
        "producer": "scripts/real_test_execution.py",
        "inspector": "scripts.real_test_execution.inspect_test_report",
        "artifact": "test_execution.json",
    },
    "customer_runtime": {
        "scope": "candidate",
        "producer": "scripts/customer_runtime_runner.py",
        "inspector": "scripts.customer_runtime_runner.inspect",
        "artifact": "customer_runtime.json",
    },
    "visual_evidence": {
        "scope": "candidate",
        "producer": "scripts/browser_visual_evidence.py",
        "inspector": "scripts.browser_visual_evidence.inspect",
        "artifact": "visual_evidence.json",
    },
    "media_evidence": {
        "scope": "candidate",
        "producer": "scripts/canonical_media_validation.py",
        "inspector": "scripts.canonical_media_validation.validate_media",
        "artifact": "",
    },
    "user_review": {
        "scope": "candidate",
        "producer": "scripts/canonical_user_review.py",
        "inspector": "scripts.canonical_user_review.inspect_user_review_evidence",
        "artifact": "user_review.json",
    },
    "delivery_manifest": {
        "scope": "candidate",
        "producer": "scripts/local_packager.py",
        "inspector": "scripts.canonical_delivery_manifest.inspect_canonical_delivery_manifest",
        "artifact": "delivery_manifest.json",
    },
    "delivery_receipt": {
        "scope": "candidate",
        "producer": "scripts/canonical_delivery_receipt.py",
        "inspector": "scripts.canonical_delivery_receipt.inspect_canonical_delivery_receipt",
        "artifact": "delivery_receipt.json",
    },
    "leaf_profile": {"scope": "candidate", "producer": "", "inspector": "", "artifact": ""},
    "workspace_truth": {"scope": "candidate", "producer": "", "inspector": "", "artifact": ""},
    "full_all": {
        "scope": "repository",
        "producer": "scripts/run_test_profile.py",
        "inspector": "scripts.formal_gate_registry.inspect_full_all",
        "artifact": "full_all_result.json",
    },
    "replan": {"scope": "candidate", "producer": "", "inspector": "", "artifact": ""},
    "recovery": {"scope": "candidate", "producer": "", "inspector": "", "artifact": ""},
    "provider_causal_trace": {
        "scope": "candidate",
        "producer": "scripts/telegram_live_bridge.py",
        "inspector": "scripts.provider_causal_trace.inspect",
        "artifact": "provider_causal_trace.json",
    },
    "collaboration_timing": {"scope": "candidate", "producer": "", "inspector": "", "artifact": ""},
    "startup_profile": {"scope": "candidate", "producer": "", "inspector": "", "artifact": ""},
    "deterministic_e2e": {"scope": "candidate", "producer": "", "inspector": "", "artifact": ""},
    "live_provider_e2e": {"scope": "candidate", "producer": "", "inspector": "", "artifact": ""},
}


def _read(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _producer_forbidden(producer: str) -> bool:
    normalized = producer.strip().replace("\\", "/").lower()
    return (
        normalized in {item.lower() for item in FORBIDDEN_PRODUCERS}
        or not normalized
        or any(normalized.startswith(prefix) for prefix in FORBIDDEN_PRODUCER_PREFIXES)
        or "/fixture" in normalized
        or "/example" in normalized
        or "/benchmark" in normalized
        or "/demo" in normalized
    )


def inspect_full_all(path: pathlib.Path, *, commit_sha: str) -> dict[str, Any]:
    doc = _read(path)
    failures: list[str] = []
    if doc.get("kind") != "CGKNTestProfileResult" or doc.get("profile") != "full_all":
        failures.append("full_all_contract")
    if doc.get("producer") != "scripts/run_test_profile.py":
        failures.append("producer_not_authorized")
    if doc.get("commit_sha") != commit_sha:
        failures.append("commit_mismatch")
    if doc.get("status") != "PASS" or doc.get("exit_code") != 0 or doc.get("pytest_run") is not True:
        failures.append("full_all_not_pass")
    if doc.get("collected") != doc.get("executed") or doc.get("executed") != doc.get("passed"):
        failures.append("full_all_incomplete")
    if not isinstance(doc.get("collected"), int) or int(doc.get("collected", 0)) <= 0:
        failures.append("full_all_empty")
    if any(doc.get(key) != 0 for key in ("failed", "skipped", "deselected")):
        failures.append("full_all_exclusions")
    if doc.get("timeout") is not False:
        failures.append("full_all_timeout")
    if doc.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(doc, ("artifact_hash",)):
        failures.append("artifact_hash_mismatch")
    return {"status": "PASS" if not failures else "NEEDS_REWORK", "failures": failures}


def _identity_failures(
    document: dict[str, Any], expected_identity: dict[str, str], *, scope: str
) -> list[str]:
    failures: list[str] = []
    fields = ("run_id", "candidate_id", "candidate_hash", "commit_sha")
    if scope == "repository":
        fields = ("commit_sha",)
    for field in fields:
        if str(document.get(field, "")) != str(expected_identity.get(field, "")):
            label = "candidate_identity_mismatch" if field in {"candidate_id", "candidate_hash"} else f"{field}_mismatch"
            failures.append(label)
    return failures


def inspect_source(
    gate: str,
    source_ref: str | pathlib.Path,
    *,
    expected_identity: dict[str, str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = GATE_SPECS.get(gate)
    if not spec:
        return {"status": "NOT_EVALUATED", "failures": ["gate_not_registered"]}
    path = pathlib.Path(source_ref).resolve()
    document = _read(path)
    failures: list[str] = []
    if not path.is_file() or path.is_symlink() or not document:
        return {"status": "NOT_EVALUATED", "failures": ["source_missing"], "source_ref": str(path)}
    artifact_name = str(spec.get("artifact", "")).strip()
    if artifact_name and path.name != artifact_name:
        failures.append("authoritative_artifact_path_mismatch")
    producer = str(document.get("producer", ""))
    if _producer_forbidden(producer) or producer != spec.get("producer"):
        failures.append("producer_not_authorized")
    failures.extend(_identity_failures(document, expected_identity, scope=str(spec["scope"])))
    provenance_inspection: dict[str, Any] = {
        "status": "NOT_EVALUATED",
        "failures": ["not_required_for_gate"],
    }
    provenance_ref_value = str(
        (context or {}).get("production_provenance_ref", "")
    ).strip()
    if gate in PROVENANCE_BOUND_GATES:
        if not provenance_ref_value:
            return {
                "status": "NEEDS_REWORK",
                "failures": sorted(set(failures + ["production_candidate_provenance_missing"])),
                "source_ref": str(path),
                "source_hash": canonical_evidence_hash.sha256_file(path),
                "source_producer": producer,
                "inspector": spec.get("inspector", ""),
                "provenance_inspection": {
                    "status": "NEEDS_REWORK",
                    "failures": ["production_provenance_missing"],
                },
                "scope": spec["scope"],
            }
        provenance_inspection = production_candidate_provenance.inspect(
            provenance_ref_value,
            expected_candidate_dir=path.parent,
            expected_run_id=expected_identity["run_id"],
            expected_candidate_id=expected_identity["candidate_id"],
            expected_candidate_hash=expected_identity["candidate_hash"],
            expected_commit_sha=expected_identity["commit_sha"],
        )
        if provenance_inspection.get("status") != "PASS":
            return {
                "status": "NEEDS_REWORK",
                "failures": sorted(
                    set(
                        failures
                        + ["production_candidate_provenance_not_verified"]
                        + list(provenance_inspection.get("failures", []))
                    )
                ),
                "source_ref": str(path),
                "source_hash": canonical_evidence_hash.sha256_file(path),
                "source_producer": producer,
                "inspector": spec.get("inspector", ""),
                "provenance_inspection": provenance_inspection,
                "scope": spec["scope"],
            }
        provenance_hash = str(provenance_inspection["provenance_hash"])
    else:
        provenance_hash = ""
    if not spec.get("inspector") or gate == "media_evidence":
        return {
            "status": "NOT_EVALUATED",
            "failures": sorted(
                set(
                    failures
                    + [
                        "production_media_evidence_contract_missing"
                        if gate == "media_evidence"
                        else "formal_inspector_unavailable"
                    ]
                )
            ),
            "source_ref": str(path),
        }
    inspection: dict[str, Any]
    if gate == "test_execution":
        inspection = real_test_execution.inspect_test_report(
            path.parent,
            run_id=expected_identity["run_id"],
            candidate_id=expected_identity["candidate_id"],
            candidate_hash=expected_identity["candidate_hash"],
            commit_sha=expected_identity["commit_sha"],
            production_provenance_ref=provenance_ref_value,
            production_provenance_hash=provenance_hash,
        )
    elif gate == "customer_runtime":
        inspection = customer_runtime_runner.inspect(
            path,
            run_id=expected_identity["run_id"],
            candidate_id=expected_identity["candidate_id"],
            candidate_hash=expected_identity["candidate_hash"],
            commit_sha=expected_identity["commit_sha"],
            production_provenance_ref=provenance_ref_value,
            production_provenance_hash=provenance_hash,
        )
    elif gate == "visual_evidence":
        inspection = browser_visual_evidence.inspect(
            path.parent,
            run_id=expected_identity["run_id"],
            candidate_id=expected_identity["candidate_id"],
            candidate_hash=expected_identity["candidate_hash"],
            commit_sha=expected_identity["commit_sha"],
            production_provenance_ref=provenance_ref_value,
            production_provenance_hash=provenance_hash,
        )
    elif gate == "user_review":
        inspection = canonical_user_review.inspect_user_review_evidence(path.parent)
    elif gate == "delivery_manifest":
        inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(path.parent, path)
    elif gate == "delivery_receipt":
        expectations = (context or {}).get("delivery_receipt_expectations")
        if not isinstance(expectations, dict):
            inspection = {"status": "NOT_EVALUATED", "failures": ["receipt_expectations_missing"]}
        else:
            inspection = canonical_delivery_receipt.inspect_canonical_delivery_receipt(
                path.parent,
                expected_chat_id=expectations.get("chat_id"),
                expected_requirements=expectations.get("requirements"),
                expected_attachment_refs=expectations.get("attachment_refs"),
            )
    elif gate == "full_all":
        inspection = inspect_full_all(path, commit_sha=expected_identity["commit_sha"])
    elif gate == "provider_causal_trace":
        inspection = provider_causal_trace.inspect(
            path,
            expected_production_run_dir=path.parent,
            expected_run_id=expected_identity["run_id"],
            expected_candidate_id=expected_identity["candidate_id"],
            expected_candidate_hash=expected_identity["candidate_hash"],
            expected_commit_sha=expected_identity["commit_sha"],
        )
    else:
        inspection = {"status": "NOT_EVALUATED", "failures": ["formal_inspector_unavailable"]}
    inspection_status = str(inspection.get("status") or inspection.get("verdict") or "NOT_EVALUATED")
    if inspection_status != "PASS":
        failures.extend(
            str(item)
            for item in (inspection.get("failures") or inspection.get("missing") or [f"inspector:{inspection_status}"])
        )
    status = "PASS" if not failures and inspection_status == "PASS" else (
        "NOT_EVALUATED" if inspection_status == "NOT_EVALUATED" and not [x for x in failures if x != "formal_inspector_unavailable"] else "NEEDS_REWORK"
    )
    return {
        "status": status,
        "failures": sorted(set(failures)),
        "source_ref": str(path),
        "source_hash": canonical_evidence_hash.sha256_file(path),
        "source_producer": producer,
        "inspector": spec.get("inspector", ""),
        "inspector_result": inspection,
        "provenance_inspection": provenance_inspection,
        "scope": spec["scope"],
    }


def inspect_gate_status(
    gate: str,
    gate_ref: str | pathlib.Path,
    *,
    expected_identity: dict[str, str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = pathlib.Path(gate_ref).resolve()
    document = _read(path)
    failures: list[str] = []
    if not path.is_file() or path.is_symlink() or not document:
        return {"status": "NOT_EVALUATED", "failures": ["gate_status_missing"]}
    if (
        document.get("kind") != FORMAL_GATE_STATUS_KIND
        or document.get("schema_version") != "1.0"
        or document.get("gate") != gate
    ):
        failures.append("gate_status_contract")
    if document.get("producer") != FORMAL_GATE_STATUS_PRODUCER:
        failures.append("producer_not_authorized")
    if document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",)):
        failures.append("artifact_hash_mismatch")
    if "source_inspection" in document:
        failures.append("deprecated_source_inspection")
    spec = GATE_SPECS.get(gate, {})
    failures.extend(_identity_failures(document, expected_identity, scope=str(spec.get("scope", "candidate"))))
    claimed = str(document.get("status", "NOT_EVALUATED"))
    source_ref = str(document.get("source_ref", "")).strip()
    if source_ref:
        source = pathlib.Path(source_ref).resolve()
        if document.get("source_hash") != (
            canonical_evidence_hash.sha256_file(source) if source.is_file() and not source.is_symlink() else ""
        ):
            failures.append("source_hash_mismatch")
        actual = inspect_source(gate, source, expected_identity=expected_identity, context=context)
        if actual["status"] != claimed:
            failures.append("inspector_status_mismatch")
            failures.extend(str(item) for item in actual.get("failures", []))
        if document.get("source_producer") != actual.get("source_producer"):
            failures.append("source_producer_mismatch")
        if document.get("inspector") != actual.get("inspector"):
            failures.append("inspector_mismatch")
        if gate in PROVENANCE_BOUND_GATES:
            expected_provenance_value = str(
                (context or {}).get("production_provenance_ref", "")
            ).strip()
            expected_provenance = (
                pathlib.Path(expected_provenance_value).resolve()
                if expected_provenance_value
                else pathlib.Path()
            )
            expected_provenance_hash = (
                canonical_evidence_hash.sha256_file(expected_provenance)
                if expected_provenance_value
                and expected_provenance.is_file()
                and not expected_provenance.is_symlink()
                else ""
            )
            if document.get("production_provenance_ref") != (
                str(expected_provenance) if expected_provenance_value else ""
            ):
                failures.append("production_provenance_ref_mismatch")
            if (
                not expected_provenance_hash
                or document.get("production_provenance_hash")
                != expected_provenance_hash
            ):
                failures.append("production_provenance_hash_mismatch")
    else:
        actual = {
            "status": claimed,
            "failures": [],
            "reason": str(document.get("reason", "")),
            "blocker_code": str(document.get("blocker_code", "")),
        }
        if claimed == "PASS":
            failures.append("source_missing")
        if claimed.startswith("BLOCKED") and (
            gate not in TELEGRAM_BLOCKABLE_GATES
            or document.get("blocker_code") != "BLOCKED_TELEGRAM_TEST_CHAT"
        ):
            failures.append("unsupported_source_free_blocker")
        if spec.get("inspector") and claimed not in {"BLOCKED", "NOT_EVALUATED", "NEEDS_REWORK"}:
            failures.append("inspector_not_executed")
    status = "NEEDS_REWORK" if failures else claimed
    return {
        "status": status,
        "failures": sorted(set(failures)),
        "claimed_status": claimed,
        "gate_ref": str(path),
        "source_inspection": actual,
    }
