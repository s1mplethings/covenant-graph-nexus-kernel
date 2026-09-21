from __future__ import annotations

import json
import os
import pathlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

try:
    from . import browser_visual_evidence, canonical_evidence_hash, canonical_media_validation, customer_runtime_runner, real_test_execution
except ImportError:
    import browser_visual_evidence
    import canonical_evidence_hash
    import canonical_media_validation
    import customer_runtime_runner
    import real_test_execution


REVIEW_FILE = "user_review.json"
REQUEST_FILE = "user_review_request.json"
REPLAY_LEDGER_FILE = "user_review_replay_ledger.json"
SCHEMA_VERSION = "1.0"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
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


def _write_json_atomic(path: pathlib.Path, document: Any) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _read_object(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


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
        if inspection.get("status") != "PASS" or not path.is_file() or path.is_symlink():
            failures.append(f"{kind}_not_pass")
            continue
        details = inspection.get("details", {}) if isinstance(inspection.get("details"), dict) else {}
        identities.append({key: str(details.get(key, "")) for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha")})
        records.append({"kind": kind, "ref": str(path.resolve()), "hash": canonical_evidence_hash.sha256_file(path)})
    identity: dict[str, str] = {}
    for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
        values = {item.get(key, "") for item in identities} - {""}
        if len(values) != 1:
            failures.append(f"identity_mismatch:{key}")
        else:
            identity[key] = next(iter(values))
    if identity.get("candidate_hash") != canonical_evidence_hash.candidate_source_hash(project):
        failures.append("candidate_hash_current")
    return records, identity, failures


def create_review_request_snapshot(
    project_dir: str | pathlib.Path,
    *,
    conversation_id: int | str,
    expected_reviewer_id: int | str,
    requirement_snapshot: Any,
    visual_required: bool = False,
    required_presentation_roles: list[str] | None = None,
    replay_ledger_path: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    records, identity, failures = _evidence(project, visual_required)
    if str(conversation_id).strip() == "":
        failures.append("conversation_id_missing")
    if str(expected_reviewer_id).strip() == "":
        failures.append("expected_reviewer_missing")
    if failures:
        return {"status": "NEEDS_REWORK", "failures": sorted(set(failures))}
    requested = now()
    roles = list(dict.fromkeys(required_presentation_roles or (["screenshot"] if visual_required else ["nonvisual_summary"])))
    if visual_required and "screenshot" not in roles:
        return {"status": "NEEDS_REWORK", "failures": ["visual_screenshot_role_missing"]}
    if not visual_required and "screenshot" in roles:
        return {"status": "NEEDS_REWORK", "failures": ["unexpected_visual_binding"]}
    document: dict[str, Any] = {
        "kind": "CGKNUserReviewRequest", "schema_version": SCHEMA_VERSION, **identity,
        "producer": "scripts/canonical_user_review.py", "created_at": requested, "status": "waiting_user_review",
        "artifact_hash": "", "review_request_id": f"review-{uuid.uuid4().hex}", "project_dir": str(project),
        "conversation_id": str(conversation_id), "expected_reviewer_id": str(expected_reviewer_id),
        "replay_ledger_ref": str(pathlib.Path(replay_ledger_path).resolve()) if replay_ledger_path else str((project / REPLAY_LEDGER_FILE).resolve()),
        "reviewed_evidence": records, "reviewed_evidence_hashes": [item["hash"] for item in records],
        "visual_required": bool(visual_required),
        "required_presentation_roles": roles, "presented_artifacts": [],
        "requirement_snapshot": requirement_snapshot, "requested_at": requested, "presented_at": "",
        "presentation_succeeded": False,
    }
    document["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",))
    _write_json_atomic(project / REQUEST_FILE, document)
    return document


def mark_review_request_presented(
    project_dir: str | pathlib.Path,
    request: dict[str, Any],
    *,
    presented_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    disk = _read_object(project / REQUEST_FILE)
    if not disk or any(request.get(key) != value for key, value in disk.items()) or disk.get("status") != "waiting_user_review":
        return {"status": "NEEDS_REWORK", "failures": ["request_argument_mismatch"]}
    normalized: list[dict[str, Any]] = []
    for item in presented_artifacts:
        if not isinstance(item, dict) or item.get("sent") is not True:
            continue
        kind, ref, digest = str(item.get("kind", "")), str(item.get("ref") or item.get("path") or ""), str(item.get("sha256", ""))
        if not kind or not ref or not HASH_RE.fullmatch(digest):
            continue
        if kind != "nonvisual_summary":
            path = pathlib.Path(ref)
            if not path.is_file() or path.is_symlink() or canonical_evidence_hash.sha256_file(path) != digest:
                continue
            if kind == "screenshot":
                visual = _read_object(project / "visual_evidence.json")
                try:
                    screenshot_matches = path.resolve() == pathlib.Path(str(visual.get("screenshot_path", ""))).resolve()
                except OSError:
                    screenshot_matches = False
                if (
                    not disk.get("visual_required")
                    or not screenshot_matches
                    or visual.get("screenshot_hash") != digest
                    or canonical_media_validation.validate_image(path, project, requested_role="screenshot").get("status") != "PASS"
                ):
                    continue
            elif kind in {"background", "sprite", "generated_image", "video"}:
                if canonical_media_validation.validate_media(path, project, requested_role=kind).get("status") != "PASS":
                    continue
        normalized_item = {
            "kind": kind, "ref": ref, "sha256": digest, "sent": True,
            "presented_at": str(item.get("presented_at") or now()),
        }
        for key in ("turn_id", "conversation_id"):
            if item.get(key) not in (None, ""):
                normalized_item[key] = str(item[key])
        normalized.append(normalized_item)
    roles = set(str(x) for x in disk.get("required_presentation_roles", []))
    presented_roles = {str(x.get("kind")) for x in normalized}
    succeeded = bool(roles and roles <= presented_roles)
    disk["presented_artifacts"] = normalized
    disk["presented_at"] = now()
    disk["presentation_succeeded"] = succeeded
    disk["status"] = "presented" if succeeded else "presentation_failed"
    disk["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(disk, ("artifact_hash",))
    _write_json_atomic(project / REQUEST_FILE, disk)
    return dict(request) | disk


def invalidate_review_request(project_dir: str | pathlib.Path, *, status: str = "changes_requested") -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    request = _read_object(project / REQUEST_FILE)
    if request:
        request["status"] = status
        request["invalidated_at"] = now()
        request["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(request, ("artifact_hash",))
        _write_json_atomic(project / REQUEST_FILE, request)
        history = project / ".cgkn_review_history"
        history.mkdir(exist_ok=True)
        _write_json_atomic(history / f"{request.get('review_request_id', 'unknown')}.json", request)
    (project / REVIEW_FILE).unlink(missing_ok=True)
    return request


def inspect_user_review_request(project_dir: str | pathlib.Path, *, require_presented: bool = True) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    path = project / REQUEST_FILE
    document = _read_object(path)
    failures: list[str] = []
    if not document:
        return {"status": "NEEDS_REWORK", "failures": ["user_review_request_missing"], "details": {}}
    if document.get("kind") != "CGKNUserReviewRequest" or document.get("schema_version") != SCHEMA_VERSION:
        failures.append("request_contract")
    if not isinstance(document.get("visual_required"), bool):
        failures.append("visual_required_invalid")
    if document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",)):
        failures.append("request_artifact_hash")
    for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha", "review_request_id", "conversation_id", "expected_reviewer_id", "replay_ledger_ref"):
        if not str(document.get(key, "")).strip():
            failures.append(f"request_missing:{key}")
    requested, presented = _parse_time(document.get("requested_at")), _parse_time(document.get("presented_at"))
    if requested is None:
        failures.append("requested_at_invalid")
    if require_presented:
        if document.get("status") != "presented" or document.get("presentation_succeeded") is not True:
            failures.append("request_not_presented")
        if presented is None or (requested and requested > presented):
            failures.append("presented_at_invalid")
    visual_required = document.get("visual_required") is True
    records, identity, evidence_failures = _evidence(project, visual_required)
    failures.extend(evidence_failures)
    if records != document.get("reviewed_evidence") or [x["hash"] for x in records] != document.get("reviewed_evidence_hashes"):
        failures.append("request_evidence_changed")
    for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
        if document.get(key) != identity.get(key):
            failures.append(f"request_identity:{key}")
    roles = set(document.get("required_presentation_roles", []))
    if visual_required and "screenshot" not in roles:
        failures.append("visual_screenshot_role_missing")
    if not visual_required and (
        "screenshot" in roles
        or any(item.get("kind") == "visual_evidence" for item in document.get("reviewed_evidence", []) if isinstance(item, dict))
    ):
        failures.append("unexpected_visual_binding")
    artifacts = document.get("presented_artifacts", [])
    if not isinstance(artifacts, list):
        failures.append("presented_artifacts_invalid")
        artifacts = []
    present = set()
    for item in artifacts:
        if not isinstance(item, dict) or item.get("sent") is not True or not HASH_RE.fullmatch(str(item.get("sha256", ""))):
            failures.append("presented_artifact_invalid")
            continue
        kind, ref = str(item.get("kind", "")), str(item.get("ref", ""))
        present.add(kind)
        if kind != "nonvisual_summary":
            artifact = pathlib.Path(ref)
            if not artifact.is_file() or artifact.is_symlink() or canonical_evidence_hash.sha256_file(artifact) != item.get("sha256"):
                failures.append(f"presented_artifact_changed:{kind}")
            elif kind == "screenshot":
                visual = _read_object(project / "visual_evidence.json")
                try:
                    screenshot_matches = artifact.resolve() == pathlib.Path(str(visual.get("screenshot_path", ""))).resolve()
                except OSError:
                    screenshot_matches = False
                if not screenshot_matches or visual.get("screenshot_hash") != item.get("sha256"):
                    failures.append("presented_artifact_not_canonical:screenshot")
                if canonical_media_validation.validate_image(artifact, project, requested_role="screenshot").get("status") != "PASS":
                    failures.append("presented_artifact_not_decodable:screenshot")
            elif kind in {"background", "sprite", "generated_image", "video"}:
                if canonical_media_validation.validate_media(artifact, project, requested_role=kind).get("status") != "PASS":
                    failures.append(f"presented_artifact_not_canonical:{kind}")
    if require_presented and not roles <= present:
        failures.append("required_presentation_missing")
    return {"status": "PASS" if not failures else "NEEDS_REWORK", "failures": sorted(set(failures)), "details": document}


def _ledger(project: pathlib.Path, request: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ref = str((request or {}).get("replay_ledger_ref", "")).strip()
    ledger_path = pathlib.Path(ref) if ref else project / REPLAY_LEDGER_FILE
    value = _read_object(ledger_path)
    events = value.get("consumed", [])
    return events if isinstance(events, list) else []


def _is_replayed(events: list[dict[str, Any]], context: dict[str, Any]) -> bool:
    return any(
        str(event.get("event_id")) == str(context.get("event_id"))
        or (str(event.get("conversation_id")) == str(context.get("conversation_id")) and str(event.get("turn_id")) == str(context.get("turn_id")))
        for event in events
    )


def record_user_review_approval(
    project_dir: str | pathlib.Path,
    request: dict[str, Any],
    approval_text: str,
    turn_context: dict[str, Any] | None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    context = turn_context if isinstance(turn_context, dict) else {}
    inspection = inspect_user_review_request(project)
    disk = inspection.get("details", {})
    failures = list(inspection.get("failures", []))
    if any(request.get(key) != value for key, value in disk.items()):
        failures.append("request_argument_mismatch")
    if classify_review_text(approval_text) != "APPROVED":
        failures.append("approval_not_explicit")
    for key in ("event_id", "turn_id", "reviewer_id", "conversation_id", "turn_date"):
        if context.get(key) in (None, ""):
            failures.append(f"missing_turn_identity:{key}")
    if context.get("edited_turn"):
        failures.append("edited_turn_not_allowed")
    if str(context.get("conversation_id", "")) != str(disk.get("conversation_id", "")):
        failures.append("conversation_id_mismatch")
    if str(context.get("reviewer_id", "")) != str(disk.get("expected_reviewer_id", "")):
        failures.append("reviewer_mismatch")
    message_time = None
    try:
        message_time = datetime.fromtimestamp(float(context.get("turn_date")), timezone.utc)
    except (TypeError, ValueError, OSError):
        failures.append("turn_date_invalid")
    requested, presented = _parse_time(disk.get("requested_at")), _parse_time(disk.get("presented_at"))
    if requested is None or presented is None or message_time is None or not requested <= presented < message_time:
        failures.append("review_time_order")
    events = _ledger(project, disk)
    if _is_replayed(events, context):
        failures.append("conversation_turn_replayed")
    if failures:
        return {"status": "NEEDS_REWORK", "failures": sorted(set(failures))}
    reviewed_at = now()
    reviewed_time = _parse_time(reviewed_at)
    if message_time is None or reviewed_time is None or message_time > reviewed_time:
        return {"status": "NEEDS_REWORK", "failures": ["review_time_order"]}
    review: dict[str, Any] = {
        "kind": "CGKNUserReviewEvidence", "schema_version": SCHEMA_VERSION,
        **{key: disk[key] for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha")},
        "producer": "scripts/canonical_user_review.py", "created_at": reviewed_at, "status": "PASS", "artifact_hash": "",
        "review_required": True, "review_request_id": disk["review_request_id"],
        "visual_required": disk["visual_required"],
        "review_request_ref": str((project / REQUEST_FILE).resolve()),
        "review_request_hash": canonical_evidence_hash.sha256_file(project / REQUEST_FILE),
        "review_event_id": f"codex:{context['conversation_id']}:{context['turn_id']}",
        "reviewer": str(context["reviewer_id"]), "channel": "codex", "conversation_id": str(context["conversation_id"]),
        "event_id": str(context["event_id"]), "turn_id": str(context["turn_id"]),
        "turn_date": message_time.isoformat(), "reviewed_candidate_hash": disk["candidate_hash"],
        "reviewed_evidence": disk["reviewed_evidence"], "reviewed_evidence_hashes": disk["reviewed_evidence_hashes"],
        "review_request_created_at": disk["requested_at"], "review_request_presented_at": disk["presented_at"],
        "reviewed_at": reviewed_at, "approval_text_hash": canonical_evidence_hash.sha256_bytes(approval_text.encode("utf-8")),
        "decision": "APPROVED",
    }
    review["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(review, ("artifact_hash",))
    _write_json_atomic(project / REVIEW_FILE, review)
    event = {
        "conversation_id": str(context["conversation_id"]), "event_id": str(context["event_id"]), "turn_id": str(context["turn_id"]),
        "reviewer_id": str(context["reviewer_id"]), "review_request_id": disk["review_request_id"],
        "candidate_hash": disk["candidate_hash"], "consumed_at": reviewed_at,
    }
    ledger_path = pathlib.Path(str(disk.get("replay_ledger_ref") or project / REPLAY_LEDGER_FILE))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(ledger_path, {"consumed": events + [event]})
    final = inspect_user_review_evidence(project)
    if final["status"] != "PASS":
        (project / REVIEW_FILE).unlink(missing_ok=True)
        return {"status": "NEEDS_REWORK", "failures": final["failures"]}
    return review


def inspect_user_review_evidence(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    path = project / REVIEW_FILE
    document = _read_object(path)
    failures: list[str] = []
    if not document:
        return {"status": "NEEDS_REWORK", "failures": ["user_review_missing"], "details": {}}
    if document.get("kind") != "CGKNUserReviewEvidence" or document.get("schema_version") != SCHEMA_VERSION or document.get("status") != "PASS":
        failures.append("review_contract")
    if document.get("review_required") is not True or document.get("decision") != "APPROVED" or document.get("channel") != "codex":
        failures.append("review_decision")
    if not isinstance(document.get("visual_required"), bool):
        failures.append("review_visual_required_invalid")
    if document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",)):
        failures.append("artifact_hash_mismatch")
    request_inspection = inspect_user_review_request(project)
    request = request_inspection.get("details", {})
    failures.extend(request_inspection.get("failures", []))
    request_path = project / REQUEST_FILE
    if document.get("review_request_ref") != str(request_path.resolve()) or not request_path.is_file():
        failures.append("review_request_ref")
    elif document.get("review_request_hash") != canonical_evidence_hash.sha256_file(request_path):
        failures.append("review_request_hash")
    for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha", "review_request_id"):
        if not str(document.get(key, "")).strip() or document.get(key) != request.get(key):
            failures.append(f"review_identity:{key}")
    if not str(document.get("reviewer", "")).strip() or document.get("reviewer") != request.get("expected_reviewer_id"):
        failures.append("reviewer_mismatch")
    if document.get("conversation_id") != request.get("conversation_id"):
        failures.append("conversation_id_mismatch")
    if document.get("visual_required") != request.get("visual_required"):
        failures.append("review_visual_requirement_mismatch")
    for key in ("event_id", "turn_id"):
        if not str(document.get(key, "")).strip():
            failures.append(f"missing:{key}")
    expected_event = f"codex:{document.get('conversation_id', '')}:{document.get('turn_id', '')}"
    if document.get("review_event_id") != expected_event:
        failures.append("review_event_id")
    if not HASH_RE.fullmatch(str(document.get("approval_text_hash", ""))):
        failures.append("approval_text_hash")
    requested = _parse_time(document.get("review_request_created_at"))
    presented = _parse_time(document.get("review_request_presented_at"))
    message = _parse_time(document.get("turn_date"))
    reviewed = _parse_time(document.get("reviewed_at"))
    if None in (requested, presented, message, reviewed) or not requested <= presented < message <= reviewed:
        failures.append("review_time_order")
    records = document.get("reviewed_evidence")
    if not isinstance(records, list) or not records:
        failures.append("reviewed_evidence_empty")
        records = []
    kinds = [item.get("kind") for item in records if isinstance(item, dict)]
    if len(kinds) != len(set(kinds)):
        failures.append("reviewed_evidence_duplicate")
    expected_kinds = {"test_execution", "customer_runtime"} | ({"visual_evidence"} if request.get("visual_required") is True else set())
    if set(kinds) != expected_kinds:
        failures.append("required_reviewed_evidence")
    expected_records, identity, evidence_failures = _evidence(project, request.get("visual_required") is True)
    failures.extend(evidence_failures)
    if records != expected_records or document.get("reviewed_evidence_hashes") != [x["hash"] for x in expected_records]:
        failures.append("reviewed_evidence_changed")
    if document.get("reviewed_candidate_hash") != canonical_evidence_hash.candidate_source_hash(project):
        failures.append("reviewed_candidate_hash")
    for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
        if document.get(key) != identity.get(key):
            failures.append(f"identity:{key}")
    matching = [
        event for event in _ledger(project, request)
        if str(event.get("event_id")) == str(document.get("event_id"))
        and str(event.get("conversation_id")) == str(document.get("conversation_id"))
        and str(event.get("turn_id")) == str(document.get("turn_id"))
        and str(event.get("reviewer_id")) == str(document.get("reviewer"))
        and event.get("review_request_id") == document.get("review_request_id")
        and event.get("candidate_hash") == document.get("candidate_hash")
    ]
    if len(matching) != 1:
        failures.append("replay_ledger_binding")
    return {"status": "PASS" if not failures else "NEEDS_REWORK", "failures": sorted(set(failures)), "details": document}
