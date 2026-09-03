from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import browser_visual_evidence
import canonical_delivery_manifest
import canonical_evidence_hash
import canonical_media_validation


RECEIPT_NAME = "delivery_receipt.json"
SCHEMA_VERSION = "1.0"
ATTACHMENT_KINDS = ("package", "screenshot", "background", "sprite", "generated_image", "video")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: pathlib.Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def required_attachment_kinds(requirements: dict[str, Any]) -> list[str]:
    required = ["package"]
    for requirement, kind in (
        ("screenshot", "screenshot"),
        ("background", "background"),
        ("sprite", "sprite"),
        ("generated_image", "generated_image"),
    ):
        if requirements.get(requirement):
            required.append(kind)
    if requirements.get("video") or requirements.get("demo_video"):
        required.append("video")
    return required


def produce_canonical_delivery_receipt(
    project_dir: str | pathlib.Path,
    *,
    conversation_id: int | str,
    manifest_inspection: dict[str, Any],
    requirement_snapshot: dict[str, Any],
    attempted_items: list[tuple[pathlib.Path, str]],
    sent_items: list[dict[str, Any]],
    started_at: str,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    manifest_path = project / canonical_delivery_manifest.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = required_attachment_kinds(requirement_snapshot)
    finished_at = _now()
    conversation_receipts: list[dict[str, Any]] = []
    valid_sent: list[str] = []
    for item in sent_items:
        kind = str(item.get("kind", ""))
        local = pathlib.Path(str(item.get("path", "")))
        valid_identity = all(
            str(item.get(field, "")).strip()
            for field in ("turn_id", "conversation_id", "artifact_id")
        ) and str(item.get("conversation_id")) == str(conversation_id)
        if valid_identity and kind in ATTACHMENT_KINDS:
            valid_sent.append(kind)
        conversation_receipts.append(
            {
                "kind": kind,
                "local_ref": str(local.resolve()) if local.exists() else str(local),
                "local_sha256": canonical_evidence_hash.sha256_file(local) if local.is_file() else "",
                "conversation_id": str(item.get("conversation_id", "")),
                "turn_id": str(item.get("turn_id", "")),
                "artifact_id": str(item.get("artifact_id", "")),
                "artifact_unique_id": str(item.get("artifact_unique_id", "")),
                "sent_at": str(item.get("sent_at", finished_at)),
                "send_status": "PASS" if valid_identity else "FAIL",
            }
        )
    failed = sorted(set(required) - set(valid_sent))
    receipt: dict[str, Any] = {
        "kind": "CGKNDeliveryReceipt",
        "schema_version": SCHEMA_VERSION,
        "run_id": manifest.get("run_id", ""),
        "candidate_id": manifest.get("candidate_id", ""),
        "candidate_hash": manifest.get("candidate_hash", ""),
        "commit_sha": manifest.get("commit_sha", ""),
        "producer": "scripts/canonical_delivery_receipt.py",
        "created_at": finished_at,
        "status": "PASS" if not failed and len(valid_sent) == len(set(valid_sent)) else "NEEDS_REWORK",
        "artifact_hash": "",
        "project_dir": str(project),
        "conversation_id": str(conversation_id),
        "delivery_attempt_id": f"{manifest.get('run_id', '')}:{started_at}",
        "delivery_manifest_ref": str(manifest_path.resolve()),
        "delivery_manifest_file_hash": canonical_evidence_hash.sha256_file(manifest_path),
        "delivery_manifest_artifact_hash": manifest.get("artifact_hash", ""),
        "package_ref": str(manifest_inspection.get("package_path", "")),
        "package_sha256": str(manifest_inspection.get("package_sha256", "")),
        "package_entries_hash": str(manifest_inspection.get("package_entries_hash", "")),
        "requirement_snapshot": requirement_snapshot,
        "requirement_snapshot_hash": canonical_evidence_hash.canonical_json_hash(requirement_snapshot, ()),
        "required_attachment_kinds": required,
        "attempted_attachment_kinds": [kind for _, kind in attempted_items],
        "sent_attachment_kinds": valid_sent,
        "conversation_receipts": conversation_receipts,
        "failed_attachment_kinds": failed,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    receipt["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(receipt, ("artifact_hash",))
    _write_json(project / RECEIPT_NAME, receipt)
    return receipt


def inspect_canonical_delivery_receipt(
    project_dir: str | pathlib.Path,
    *,
    expected_conversation_id: int | str | None = None,
    expected_requirements: dict[str, Any] | None = None,
    expected_attachment_refs: dict[str, str | pathlib.Path] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    receipt_path = project / RECEIPT_NAME
    failures: list[str] = []
    try:
        if not receipt_path.is_file() or receipt_path.is_symlink():
            raise ValueError("receipt_path_invalid")
        document = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("receipt_not_object")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "NEEDS_REWORK", "failures": [str(exc) or "receipt_unreadable"], "receipt_path": str(receipt_path)}
    if document.get("kind") != "CGKNDeliveryReceipt" or document.get("schema_version") != SCHEMA_VERSION:
        failures.append("receipt_contract")
    if document.get("producer") != "scripts/canonical_delivery_receipt.py":
        failures.append("producer_mismatch")
    if document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",)):
        failures.append("artifact_hash_mismatch")
    if expected_conversation_id is None:
        failures.append("expected_conversation_id_required")
    if expected_requirements is None:
        failures.append("expected_requirements_required")
    if expected_attachment_refs is None:
        failures.append("expected_attachment_refs_required")
    requirements = expected_requirements if expected_requirements is not None else {}
    if document.get("requirement_snapshot") != requirements:
        failures.append("requirement_snapshot_mismatch")
    if document.get("requirement_snapshot_hash") != canonical_evidence_hash.canonical_json_hash(requirements, ()):
        failures.append("requirement_snapshot_hash_mismatch")
    required = required_attachment_kinds(requirements)
    if document.get("required_attachment_kinds") != required:
        failures.append("required_attachment_kinds_mismatch")
    for field in ("required_attachment_kinds", "attempted_attachment_kinds", "sent_attachment_kinds", "failed_attachment_kinds"):
        values = document.get(field, [])
        if not isinstance(values, list) or len(values) != len(set(values)) or any(value not in ATTACHMENT_KINDS for value in values):
            failures.append(f"{field}_invalid")
    attempted = document.get("attempted_attachment_kinds", [])
    if isinstance(attempted, list) and (any(kind not in required for kind in attempted) or not set(required).issubset(set(attempted))):
        failures.append("attempted_attachment_kinds_not_exact")
    approved_refs: dict[str, pathlib.Path] = {}
    for kind, value in (expected_attachment_refs or {}).items():
        if kind in ATTACHMENT_KINDS:
            try:
                approved_refs[kind] = pathlib.Path(value).resolve(strict=True)
            except (OSError, ValueError):
                failures.append(f"expected_attachment_ref_invalid:{kind}")
    if set(approved_refs) != set(required):
        failures.append("expected_attachment_refs_not_exact")
    if expected_conversation_id is not None and str(document.get("conversation_id")) != str(expected_conversation_id):
        failures.append("conversation_id_mismatch")
    if document.get("project_dir") != str(project) or not str(document.get("delivery_attempt_id", "")).strip():
        failures.append("delivery_binding_missing")
    if document.get("delivery_attempt_id") != f"{document.get('run_id', '')}:{document.get('started_at', '')}":
        failures.append("delivery_attempt_id_mismatch")
    if any(not str(document.get(field, "")).strip() for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha", "conversation_id")):
        failures.append("canonical_identity_missing")
    manifest_path = project / canonical_delivery_manifest.MANIFEST_NAME
    if document.get("delivery_manifest_ref") != str(manifest_path.resolve()):
        failures.append("delivery_manifest_ref_mismatch")
    manifest_inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(
        project, visual_required=bool(requirements.get("screenshot"))
    )
    if manifest_inspection.get("status") != "PASS":
        failures.append("delivery_manifest_inspection_failed")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if document.get("delivery_manifest_file_hash") != canonical_evidence_hash.sha256_file(manifest_path):
            failures.append("delivery_manifest_file_hash_mismatch")
        if document.get("delivery_manifest_artifact_hash") != manifest.get("artifact_hash"):
            failures.append("delivery_manifest_artifact_hash_mismatch")
        for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
            if document.get(field) != manifest.get(field):
                failures.append(f"{field}_mismatch")
        for field in ("package_sha256", "package_entries_hash"):
            if document.get(field) != manifest_inspection.get(field):
                failures.append(f"{field}_mismatch")
        if document.get("package_ref") != manifest_inspection.get("package_path"):
            failures.append("package_ref_mismatch")
    except (OSError, ValueError, json.JSONDecodeError):
        failures.append("delivery_manifest_unreadable")
    receipts = document.get("conversation_receipts", [])
    if not isinstance(receipts, list):
        receipts = []
        failures.append("conversation_receipts_invalid")
    turn_ids: set[str] = set()
    sent: list[str] = []
    try:
        started = datetime.fromisoformat(str(document.get("started_at")))
        finished = datetime.fromisoformat(str(document.get("finished_at")))
    except ValueError:
        started = finished = datetime.min.replace(tzinfo=timezone.utc)
        failures.append("delivery_time_invalid")
    for entry in receipts:
        if not isinstance(entry, dict):
            failures.append("codex_receipt_invalid")
            continue
        kind = str(entry.get("kind", ""))
        local = pathlib.Path(str(entry.get("local_ref", "")))
        if kind not in ATTACHMENT_KINDS or entry.get("send_status") != "PASS":
            failures.append(f"codex_receipt_failed:{kind}")
            continue
        if not all(str(entry.get(key, "")).strip() for key in ("turn_id", "conversation_id", "artifact_id")):
            failures.append(f"codex_identity_missing:{kind}")
        if str(entry.get("conversation_id")) != str(document.get("conversation_id")):
            failures.append(f"codex_chat_mismatch:{kind}")
        turn_id = str(entry.get("turn_id", ""))
        if turn_id in turn_ids:
            failures.append("duplicate_turn_id")
        turn_ids.add(turn_id)
        try:
            sent_at = datetime.fromisoformat(str(entry.get("sent_at")))
            if not started <= sent_at <= finished:
                failures.append(f"sent_time_out_of_range:{kind}")
        except ValueError:
            failures.append(f"sent_time_invalid:{kind}")
        try:
            resolved = local.resolve(strict=True)
            resolved.relative_to(project)
            if approved_refs.get(kind) != resolved:
                failures.append(f"local_ref_not_approved:{kind}")
            if local.is_symlink() or entry.get("local_sha256") != canonical_evidence_hash.sha256_file(resolved):
                failures.append(f"local_artifact_hash_mismatch:{kind}")
            if kind == "package" and resolved != pathlib.Path(str(document.get("package_ref", ""))).resolve(strict=True):
                failures.append("package_local_ref_mismatch")
            elif kind == "screenshot":
                visual = browser_visual_evidence.inspect(project)
                visual_details = visual.get("details", {}) if isinstance(visual.get("details"), dict) else {}
                if visual.get("status") != "PASS" or resolved != pathlib.Path(str(visual_details.get("screenshot_path", ""))).resolve(strict=True):
                    failures.append("screenshot_not_canonical")
            elif kind not in {"package", "screenshot"}:
                media = canonical_media_validation.validate_media(resolved, project, requested_role=kind)
                if media.get("status") != "PASS":
                    failures.append(f"media_not_canonical:{kind}")
        except (OSError, ValueError):
            failures.append(f"local_artifact_invalid:{kind}")
        sent.append(kind)
    if len(sent) != len(set(sent)):
        failures.append("duplicate_attachment_kind")
    if document.get("sent_attachment_kinds") != sent:
        failures.append("sent_attachment_kinds_mismatch")
    if set(sent) != set(required) or any(kind not in required for kind in sent):
        failures.append("required_attachments_not_exact")
    if document.get("failed_attachment_kinds"):
        failures.append("failed_attachment_kinds_nonempty")
    if document.get("status") != "PASS":
        failures.append("receipt_status_not_pass")
    if started > finished:
        failures.append("delivery_time_order_invalid")
    return {
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "failures": sorted(set(failures)),
        "receipt_path": str(receipt_path),
        "receipt": document,
    }


inspect = inspect_canonical_delivery_receipt
produce = produce_canonical_delivery_receipt
