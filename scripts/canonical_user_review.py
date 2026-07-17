from __future__ import annotations

import json
import pathlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

try:
    from . import browser_visual_evidence, canonical_evidence_hash, customer_runtime_runner, real_test_execution
except ImportError:
    import browser_visual_evidence
    import canonical_evidence_hash
    import customer_runtime_runner
    import real_test_execution


REVIEW_FILE = "user_review.json"
NEGATIVE_PATTERNS = (
    r"不可以", r"不要.*打包", r"没通过", r"继续修改", r"有问题", r"需要修改", r"先别继续",
    r"还没确认", r"可以再改", r"\bnot approved\b", r"\bdo not package\b",
    r"\bcontinue editing\b", r"\bnot yet\b", r"\bneeds changes\b",
)
APPROVAL_PATTERNS = (
    r"我确认.*这个版本.*可以.*最终打包",
    r"这个版本通过.*可以继续.*最终交付",
    r"\bi approve this version for final packaging\b",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_review_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not normalized:
        return "AMBIGUOUS"
    if any(re.search(pattern, normalized) for pattern in NEGATIVE_PATTERNS):
        return "CHANGES_REQUESTED"
    if any(re.search(pattern, normalized) for pattern in APPROVAL_PATTERNS):
        return "APPROVED"
    return "AMBIGUOUS"


def _evidence(project: pathlib.Path, visual_required: bool) -> tuple[list[dict[str, str]], dict[str, str], list[str]]:
    inspections = [
        ("test_execution", project / "test_execution.json", real_test_execution.inspect_test_report(project)),
        ("customer_runtime", project / "customer_runtime.json", customer_runtime_runner.inspect(project)),
    ]
    if visual_required:
        inspections.append(("visual_evidence", project / "visual_evidence.json", browser_visual_evidence.inspect(project)))
    records: list[dict[str, str]] = []
    identities: list[dict[str, str]] = []
    failures: list[str] = []
    for kind, path, inspection in inspections:
        if inspection.get("status") != "PASS" or not path.is_file():
            failures.append(f"{kind}_not_pass")
            continue
        details = inspection.get("details", {}) if isinstance(inspection.get("details"), dict) else {}
        identities.append({key: str(details.get(key, "")) for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha")})
        records.append({"kind": kind, "ref": str(path.resolve()), "hash": canonical_evidence_hash.sha256_file(path)})
    identity: dict[str, str] = {}
    for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
        values = {item.get(key, "") for item in identities}
        values.discard("")
        if len(values) != 1:
            failures.append(f"identity_mismatch:{key}")
        else:
            identity[key] = next(iter(values))
    current = canonical_evidence_hash.candidate_source_hash(project)
    if identity.get("candidate_hash") != current:
        failures.append("candidate_hash_current")
    return records, identity, failures


def create_review_request_snapshot(
    project_dir: str | pathlib.Path,
    *,
    chat_id: int | str,
    requirement_snapshot: Any,
    visual_required: bool = False,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    records, identity, failures = _evidence(project, visual_required)
    if failures:
        return {"status": "NEEDS_REWORK", "failures": failures}
    created = now()
    return {
        "review_request_id": f"review-{uuid.uuid4().hex}",
        "project_dir": str(project),
        "chat_id": str(chat_id),
        **identity,
        "reviewed_evidence": records,
        "reviewed_evidence_hashes": [item["hash"] for item in records],
        "requirement_snapshot": requirement_snapshot,
        "visual_required": bool(visual_required),
        "created_at": created,
        "presented_at": "",
        "presentation_succeeded": False,
        "status": "waiting_user_review",
        "consumed_message_id": "",
    }


def mark_review_request_presented(snapshot: dict[str, Any], *, presented: bool, evidence_kinds: list[str]) -> dict[str, Any]:
    result = dict(snapshot)
    result["presentation_succeeded"] = bool(presented)
    result["presented_at"] = now() if presented else ""
    result["presented_evidence_kinds"] = list(evidence_kinds)
    result["status"] = "presented" if presented else "presentation_failed"
    return result


def record_user_review_approval(
    project_dir: str | pathlib.Path,
    request: dict[str, Any],
    approval_text: str,
    message_context: dict[str, Any] | None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    context = message_context if isinstance(message_context, dict) else {}
    failures: list[str] = []
    if classify_review_text(approval_text) != "APPROVED":
        failures.append("approval_not_explicit")
    if request.get("status") != "presented" or not request.get("presentation_succeeded"):
        failures.append("review_not_presented")
    for key in ("update_id", "message_id", "from_user_id"):
        if context.get(key) in (None, ""):
            failures.append(f"missing_message_identity:{key}")
    if context.get("edited_message"):
        failures.append("edited_message_not_allowed")
    if context.get("message_date") not in (None, ""):
        try:
            message_time = datetime.fromtimestamp(float(context["message_date"]), timezone.utc)
            presented_time = datetime.fromisoformat(str(request.get("presented_at", "")))
            if message_time <= presented_time:
                failures.append("approval_before_presentation")
        except (TypeError, ValueError, OSError):
            failures.append("message_date_invalid")
    if str(context.get("chat_id", "")) != str(request.get("chat_id", "")):
        failures.append("chat_id_mismatch")
    if request.get("consumed_message_id"):
        failures.append("review_request_already_consumed")
    existing_path = project / REVIEW_FILE
    if existing_path.is_file():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            existing = {}
        if str(existing.get("telegram_message_id", "")) == str(context.get("message_id", "")):
            failures.append("telegram_message_replayed")
    records, identity, evidence_failures = _evidence(project, bool(request.get("visual_required")))
    failures.extend(evidence_failures)
    if identity.get("candidate_hash") != request.get("candidate_hash"):
        failures.append("candidate_changed")
    if records != request.get("reviewed_evidence"):
        failures.append("evidence_changed")
    if failures:
        return {"status": "NEEDS_REWORK", "failures": sorted(set(failures))}
    reviewed_at = now()
    document: dict[str, Any] = {
        "kind": "CGKNUserReviewEvidence",
        "schema_version": "1.0",
        **identity,
        "producer": "scripts/canonical_user_review.py",
        "created_at": reviewed_at,
        "status": "PASS",
        "artifact_hash": "",
        "review_required": True,
        "review_request_id": request["review_request_id"],
        "review_event_id": f"telegram:{context['chat_id']}:{context['message_id']}",
        "reviewer": str(context["from_user_id"]),
        "channel": "telegram",
        "chat_id": str(context["chat_id"]),
        "telegram_update_id": str(context["update_id"]),
        "telegram_message_id": str(context["message_id"]),
        "reviewed_candidate_hash": identity["candidate_hash"],
        "reviewed_evidence": records,
        "reviewed_evidence_hashes": [item["hash"] for item in records],
        "review_request_created_at": request["created_at"],
        "review_request_presented_at": request["presented_at"],
        "reviewed_at": reviewed_at,
        "approval_text_hash": canonical_evidence_hash.sha256_bytes(approval_text.encode("utf-8")),
        "decision": "APPROVED",
    }
    document["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",))
    path = project / REVIEW_FILE
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inspection = inspect_user_review_evidence(project)
    if inspection["status"] != "PASS":
        path.unlink(missing_ok=True)
        return {"status": "NEEDS_REWORK", "failures": inspection["failures"]}
    return document


def inspect_user_review_evidence(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    path = project / REVIEW_FILE
    failures: list[str] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"status": "NEEDS_REWORK", "failures": ["user_review_missing"], "details": {}}
    if document.get("kind") != "CGKNUserReviewEvidence" or document.get("status") != "PASS":
        failures.append("review_contract")
    if document.get("decision") != "APPROVED" or document.get("channel") != "telegram":
        failures.append("review_decision")
    if document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",)):
        failures.append("artifact_hash_mismatch")
    records, identity, evidence_failures = _evidence(project, any(item.get("kind") == "visual_evidence" for item in document.get("reviewed_evidence", [])))
    failures.extend(evidence_failures)
    if records != document.get("reviewed_evidence"):
        failures.append("reviewed_evidence_changed")
    if [item["hash"] for item in records] != document.get("reviewed_evidence_hashes"):
        failures.append("reviewed_evidence_hashes")
    if document.get("reviewed_candidate_hash") != canonical_evidence_hash.candidate_source_hash(project):
        failures.append("reviewed_candidate_hash")
    for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
        if document.get(key) != identity.get(key):
            failures.append(f"identity:{key}")
    return {"status": "PASS" if not failures else "NEEDS_REWORK", "failures": sorted(set(failures)), "details": document}
