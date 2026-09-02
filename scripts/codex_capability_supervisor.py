#!/usr/bin/env python3
"""Bounded handoff contract between CGKN's librarian and a Codex supervisor.

This module creates and validates support artifacts only.  It does not call a
model, generate project files, authorize formal evidence, package, or deliver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Any, Iterable


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
for import_path in (ROOT, SCRIPTS_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))


REQUEST_KIND = "CGKNCodexCapabilityEscalation"
RESPONSE_KIND = "CGKNCodexCapabilitySupervisorResponse"
BRIEF_KIND = "CGKNCodexCapabilityBrief"
SCHEMA_VERSION = "1.0"

ALLOWED_CATEGORIES = {
    "planning_gap",
    "generation_failure",
    "integration_failure",
    "test_failure",
    "environment_blocker",
    "research_gap",
    "tool_gap",
}
ALLOWED_OUTPUTS = {
    "diagnosis",
    "provider_guidance",
    "repair_targets",
    "acceptance_checks",
    "context_requests",
    "tool_evidence_requests",
}
ALLOWED_WORKFLOW_STATES = {"ready", "needs_context", "declined"}
PROHIBITED_RESPONSE_KEYS = {
    "delivery_allowed",
    "evidence_status",
    "formal_status",
    "final_verdict",
    "package_path",
    "files",
    "source_code",
    "patch",
}
SENSITIVE_KEY_MARKERS = ("api_key", "apikey", "authorization", "password", "secret", "token")
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
)

DEFAULT_BUDGETS = {
    "max_context_items": 8,
    "max_evidence_items": 8,
    "max_request_chars": 12000,
    "max_guidance_chars": 4000,
    "max_response_items": 8,
}

REQUEST_FIELDS = {
    "kind", "schema_version", "request_id", "created_at", "goal_summary",
    "capability_gap", "librarian_context", "failure_evidence",
    "requested_outputs", "budgets", "authority", "request_sha256",
}
RESPONSE_FIELDS = {
    "kind", "schema_version", "request_id", "request_sha256", "created_at",
    "workflow_state", "summary", "diagnosis", "provider_guidance",
    "repair_targets", "acceptance_checks", "context_requests",
    "tool_evidence_requests", "known_limits", "authority", "response_sha256",
}
BRIEF_FIELDS = {
    "kind", "schema_version", "created_at", "request_id", "request_sha256",
    "response_sha256", "workflow_state", "summary", "provider_guidance",
    "repair_targets", "acceptance_checks", "context_requests",
    "tool_evidence_requests", "known_limits", "authority", "brief_sha256",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _without_hash(doc: dict[str, Any], field: str) -> dict[str, Any]:
    copy = dict(doc)
    copy.pop(field, None)
    return copy


def _redact_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[: max(0, limit)]


def _redact_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:32]:
            key = str(raw_key)[:100]
            lowered = key.lower()
            clean[key] = (
                "[REDACTED]"
                if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)
                else _redact_value(raw_value, depth=depth + 1)
            )
        return clean
    if isinstance(value, list):
        return [_redact_value(item, depth=depth + 1) for item in value[:32]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _redact_text(value, 1200)


def _string_list(value: Any, *, limit: int, item_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _redact_text(item, item_chars)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _bounded_budget(overrides: dict[str, Any] | None = None) -> dict[str, int]:
    raw = overrides if isinstance(overrides, dict) else {}
    limits = {
        "max_context_items": (1, 16),
        "max_evidence_items": (1, 16),
        "max_request_chars": (2000, 16000),
        "max_guidance_chars": (500, 6000),
        "max_response_items": (1, 12),
    }
    result: dict[str, int] = {}
    for key, (lower, upper) in limits.items():
        try:
            candidate = int(raw.get(key, DEFAULT_BUDGETS[key]))
        except (TypeError, ValueError):
            candidate = DEFAULT_BUDGETS[key]
        result[key] = max(lower, min(upper, candidate))
    return result


def _context_items(librarian_context: dict[str, Any], budget: int) -> list[dict[str, Any]]:
    raw_items = librarian_context.get("selected_items", [])
    if not isinstance(raw_items, list):
        return []
    selected: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items[:budget]):
        source = item if isinstance(item, dict) else {"summary": item}
        summary = (
            source.get("summary")
            or source.get("excerpt")
            or source.get("content")
            or source.get("evidence")
            or ""
        )
        selected.append(
            {
                "id": _redact_text(source.get("id") or f"context-{index + 1}", 120),
                "kind": _redact_text(source.get("kind") or "context", 80),
                "path": _redact_text(source.get("path"), 300),
                "summary": _redact_text(summary, 1200),
                "sha256": _redact_text(source.get("sha256"), 64),
            }
        )
    return selected


def _evidence_items(evidence: Iterable[Any], budget: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for index, item in enumerate(list(evidence)[:budget]):
        source = item if isinstance(item, dict) else {"summary": item}
        selected.append(
            {
                "id": _redact_text(source.get("id") or f"evidence-{index + 1}", 120),
                "kind": _redact_text(source.get("kind") or "evidence", 80),
                "path": _redact_text(source.get("path"), 300),
                "summary": _redact_text(source.get("summary") or source.get("error"), 1200),
                "sha256": _redact_text(source.get("sha256"), 64),
            }
        )
    return selected


def build_escalation_request(
    *,
    goal_summary: str,
    capability_gap: str,
    category: str,
    librarian_context: dict[str, Any] | None = None,
    failure_evidence: Iterable[Any] = (),
    prior_attempts: Iterable[Any] = (),
    requested_outputs: Iterable[str] = ALLOWED_OUTPUTS,
    budgets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one secret-redacted, bounded request for the Codex supervisor."""
    budget = _bounded_budget(budgets)
    context = librarian_context if isinstance(librarian_context, dict) else {}
    clean_category = str(category or "").strip().lower()
    if clean_category not in ALLOWED_CATEGORIES:
        raise ValueError(f"unsupported capability-gap category: {category}")
    outputs = [str(item).strip() for item in requested_outputs if str(item).strip() in ALLOWED_OUTPUTS]
    outputs = list(dict.fromkeys(outputs)) or sorted(ALLOWED_OUTPUTS)
    clean_context = _redact_value(context)
    core = {
        "goal_summary": _redact_text(goal_summary, 2000),
        "capability_gap": {
            "category": clean_category,
            "summary": _redact_text(capability_gap, 1600),
            "prior_attempts": _string_list(list(prior_attempts), limit=6, item_chars=600),
        },
        "librarian_context": {
            "source_kind": _redact_text(context.get("kind") or "CGKNLibrarianContextPack", 100),
            "source_sha256": _canonical_hash(clean_context),
            "selected_items": _context_items(context, budget["max_context_items"]),
            "excluded_count": max(0, int(context.get("excluded_count", 0) or 0)),
        },
        "failure_evidence": _evidence_items(failure_evidence, budget["max_evidence_items"]),
        "requested_outputs": outputs,
        "budgets": budget,
        "authority": {
            "advisory_only": True,
            "formal_evidence_authorized": False,
            "candidate_write_authorized": False,
            "package_authorized": False,
            "delivery_authorized": False,
        },
    }
    request_id = f"codex-escalation-{_canonical_hash(core)[:16]}"
    request = {
        "kind": REQUEST_KIND,
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "created_at": now(),
        **core,
    }
    request["request_sha256"] = _canonical_hash(request)
    errors = validate_escalation_request(request)
    if errors:
        raise ValueError("invalid Codex escalation request: " + "; ".join(errors))
    return request


def validate_escalation_request(request: Any) -> list[str]:
    if not isinstance(request, dict):
        return ["request must be an object"]
    errors: list[str] = []
    if request.get("kind") != REQUEST_KIND:
        errors.append("request kind mismatch")
    if request.get("schema_version") != SCHEMA_VERSION:
        errors.append("request schema_version mismatch")
    unexpected = sorted(set(request).difference(REQUEST_FIELDS))
    if unexpected:
        errors.append("request contains unsupported fields: " + ", ".join(unexpected))
    if request.get("request_sha256") != _canonical_hash(_without_hash(request, "request_sha256")):
        errors.append("request hash mismatch")
    gap = request.get("capability_gap", {})
    if not isinstance(gap, dict) or gap.get("category") not in ALLOWED_CATEGORIES:
        errors.append("request capability-gap category is invalid")
    if not _redact_text(request.get("goal_summary"), 2000):
        errors.append("request goal_summary is required")
    if not isinstance(gap, dict) or not _redact_text(gap.get("summary"), 1600):
        errors.append("request capability-gap summary is required")
    authority = request.get("authority", {})
    if not isinstance(authority, dict) or authority != {
        "advisory_only": True,
        "formal_evidence_authorized": False,
        "candidate_write_authorized": False,
        "package_authorized": False,
        "delivery_authorized": False,
    }:
        errors.append("request authority boundary is invalid")
    budget = request.get("budgets", {})
    if not isinstance(budget, dict) or budget != _bounded_budget(budget):
        errors.append("request budget is invalid")
    elif len(json.dumps(request, ensure_ascii=False)) > budget["max_request_chars"]:
        errors.append("request exceeds max_request_chars")
    return errors


def build_supervisor_response(
    request: dict[str, Any],
    *,
    workflow_state: str,
    summary: str,
    diagnosis: Iterable[Any] = (),
    provider_guidance: Iterable[Any] = (),
    repair_targets: Iterable[Any] = (),
    acceptance_checks: Iterable[Any] = (),
    context_requests: Iterable[Any] = (),
    tool_evidence_requests: Iterable[Any] = (),
    known_limits: Iterable[Any] = (),
) -> dict[str, Any]:
    """Build a response object; this helper does not make the response authoritative."""
    request_errors = validate_escalation_request(request)
    if request_errors:
        raise ValueError("invalid request: " + "; ".join(request_errors))
    state = str(workflow_state or "").strip().lower()
    if state not in ALLOWED_WORKFLOW_STATES:
        raise ValueError(f"unsupported supervisor workflow state: {workflow_state}")
    budget = request["budgets"]
    count = budget["max_response_items"]
    response = {
        "kind": RESPONSE_KIND,
        "schema_version": SCHEMA_VERSION,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "created_at": now(),
        "workflow_state": state,
        "summary": _redact_text(summary, 1200),
        "diagnosis": _string_list(list(diagnosis), limit=count, item_chars=700),
        "provider_guidance": _string_list(list(provider_guidance), limit=count, item_chars=700),
        "repair_targets": _string_list(list(repair_targets), limit=count, item_chars=300),
        "acceptance_checks": _string_list(list(acceptance_checks), limit=count, item_chars=700),
        "context_requests": _string_list(list(context_requests), limit=count, item_chars=500),
        "tool_evidence_requests": _string_list(list(tool_evidence_requests), limit=count, item_chars=500),
        "known_limits": _string_list(list(known_limits), limit=count, item_chars=500),
        "authority": {
            "advisory_only": True,
            "formal_evidence_status": "NOT_EVALUATED",
            "candidate_write_authorized": False,
            "package_authorized": False,
            "delivery_authorized": False,
        },
    }
    response["response_sha256"] = _canonical_hash(response)
    errors = validate_supervisor_response(request, response)
    if errors:
        raise ValueError("invalid Codex supervisor response: " + "; ".join(errors))
    return response


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _safe_relative_target(value: str) -> bool:
    text = str(value or "").replace("\\", "/").strip()
    path = pathlib.PurePosixPath(text)
    return bool(text) and not path.is_absolute() and ".." not in path.parts and ":" not in text


def validate_supervisor_response(request: Any, response: Any) -> list[str]:
    request_errors = validate_escalation_request(request)
    if request_errors:
        return [f"request: {item}" for item in request_errors]
    if not isinstance(response, dict):
        return ["response must be an object"]
    errors: list[str] = []
    if response.get("kind") != RESPONSE_KIND:
        errors.append("response kind mismatch")
    if response.get("schema_version") != SCHEMA_VERSION:
        errors.append("response schema_version mismatch")
    unexpected = sorted(set(response).difference(RESPONSE_FIELDS))
    if unexpected:
        errors.append("response contains unsupported fields: " + ", ".join(unexpected))
    if response.get("request_id") != request.get("request_id"):
        errors.append("response request_id mismatch")
    if response.get("request_sha256") != request.get("request_sha256"):
        errors.append("response request hash mismatch")
    if response.get("response_sha256") != _canonical_hash(_without_hash(response, "response_sha256")):
        errors.append("response hash mismatch")
    if response.get("workflow_state") not in ALLOWED_WORKFLOW_STATES:
        errors.append("response workflow_state is invalid")
    prohibited = sorted(PROHIBITED_RESPONSE_KEYS.intersection(set(_walk_keys(response))))
    if prohibited:
        errors.append("response contains prohibited authority or mutation keys: " + ", ".join(prohibited))
    authority = response.get("authority", {})
    if not isinstance(authority, dict) or authority != {
        "advisory_only": True,
        "formal_evidence_status": "NOT_EVALUATED",
        "candidate_write_authorized": False,
        "package_authorized": False,
        "delivery_authorized": False,
    }:
        errors.append("response authority boundary is invalid")
    max_items = request["budgets"]["max_response_items"]
    for key in (
        "diagnosis",
        "provider_guidance",
        "repair_targets",
        "acceptance_checks",
        "context_requests",
        "tool_evidence_requests",
        "known_limits",
    ):
        value = response.get(key, [])
        if not isinstance(value, list) or len(value) > max_items:
            errors.append(f"response {key} exceeds its item budget")
    if sum(len(str(item)) for item in response.get("provider_guidance", [])) > request["budgets"]["max_guidance_chars"]:
        errors.append("response provider guidance exceeds its character budget")
    for target in response.get("repair_targets", []):
        if not _safe_relative_target(str(target)):
            errors.append(f"unsafe advisory repair target: {target}")
    if response.get("workflow_state") == "ready" and not (
        response.get("provider_guidance") or response.get("acceptance_checks") or response.get("tool_evidence_requests")
    ):
        errors.append("ready response has no actionable guidance or checks")
    return errors


def build_capability_brief(request: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    errors = validate_supervisor_response(request, response)
    if errors:
        raise ValueError("invalid Codex supervisor response: " + "; ".join(errors))
    brief = {
        "kind": BRIEF_KIND,
        "schema_version": SCHEMA_VERSION,
        "created_at": now(),
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "response_sha256": response["response_sha256"],
        "workflow_state": response["workflow_state"],
        "summary": response["summary"],
        "provider_guidance": response["provider_guidance"],
        "repair_targets": response["repair_targets"],
        "acceptance_checks": response["acceptance_checks"],
        "context_requests": response["context_requests"],
        "tool_evidence_requests": response["tool_evidence_requests"],
        "known_limits": response["known_limits"],
        "authority": dict(response["authority"]),
    }
    brief["brief_sha256"] = _canonical_hash(brief)
    return brief


def validate_capability_brief(brief: dict[str, Any]) -> list[str]:
    """Validate a sealed advisory brief before another CGKN lane consumes it."""
    if not isinstance(brief, dict):
        return ["brief must be an object"]
    errors: list[str] = []
    extra = sorted(set(brief) - BRIEF_FIELDS)
    missing = sorted(BRIEF_FIELDS - set(brief))
    if extra:
        errors.append("brief contains unsupported fields: " + ", ".join(extra))
    if missing:
        errors.append("brief is missing required fields: " + ", ".join(missing))
    if brief.get("kind") != BRIEF_KIND or brief.get("schema_version") != SCHEMA_VERSION:
        errors.append("brief kind or schema version is invalid")
    if brief.get("brief_sha256") != _canonical_hash(_without_hash(brief, "brief_sha256")):
        errors.append("brief hash mismatch")
    if brief.get("workflow_state") not in ALLOWED_WORKFLOW_STATES:
        errors.append("brief workflow state is invalid")
    authority = brief.get("authority", {})
    if not isinstance(authority, dict) or authority != {
        "advisory_only": True,
        "formal_evidence_status": "NOT_EVALUATED",
        "candidate_write_authorized": False,
        "package_authorized": False,
        "delivery_authorized": False,
    }:
        errors.append("brief authority boundary is invalid")
    for field in ("request_sha256", "response_sha256", "brief_sha256"):
        value = str(brief.get(field, ""))
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            errors.append(f"brief {field} is invalid")
    for key in (
        "provider_guidance",
        "repair_targets",
        "acceptance_checks",
        "context_requests",
        "tool_evidence_requests",
        "known_limits",
    ):
        value = brief.get(key, [])
        if not isinstance(value, list) or len(value) > DEFAULT_BUDGETS["max_response_items"]:
            errors.append(f"brief {key} exceeds its item budget")
        elif any(not isinstance(item, str) or len(item) > 1600 for item in value):
            errors.append(f"brief {key} contains an invalid item")
    if sum(len(str(item)) for item in brief.get("provider_guidance", [])) > DEFAULT_BUDGETS["max_guidance_chars"]:
        errors.append("brief provider guidance exceeds its character budget")
    for target in brief.get("repair_targets", []):
        if not _safe_relative_target(str(target)):
            errors.append(f"unsafe advisory repair target: {target}")
    if brief.get("workflow_state") == "ready" and not (
        brief.get("provider_guidance")
        or brief.get("acceptance_checks")
        or brief.get("tool_evidence_requests")
    ):
        errors.append("ready brief has no actionable guidance or checks")
    return errors


def whiteboard_patch_from_brief(brief: dict[str, Any]) -> dict[str, Any]:
    errors = validate_capability_brief(brief)
    if errors:
        raise ValueError("invalid Codex capability brief: " + "; ".join(errors))
    return {
        "codex_capability_supervision": {
            "request_id": brief.get("request_id"),
            "request_sha256": brief.get("request_sha256"),
            "response_sha256": brief.get("response_sha256"),
            "brief_sha256": brief.get("brief_sha256"),
            "workflow_state": brief.get("workflow_state"),
            "summary": brief.get("summary"),
            "provider_guidance": list(brief.get("provider_guidance", [])),
            "repair_targets": list(brief.get("repair_targets", [])),
            "acceptance_checks": list(brief.get("acceptance_checks", [])),
            "known_limits": list(brief.get("known_limits", [])),
            "advisory_only": True,
        },
        "critical_questions": list(brief.get("context_requests", [])),
    }


def append_handoff_event(session_path: pathlib.Path, artifact: dict[str, Any]) -> None:
    """Append a compact request/response/brief reference to agent_session."""
    import agent_conversation_loop

    kind = str(artifact.get("kind", ""))
    event_kind = {
        REQUEST_KIND: "codex_capability_escalation_requested",
        RESPONSE_KIND: "codex_capability_supervisor_responded",
        BRIEF_KIND: "codex_capability_brief_validated",
    }.get(kind)
    if not event_kind:
        raise ValueError(f"unsupported handoff artifact kind: {kind}")
    agent_conversation_loop.append_event(
        pathlib.Path(session_path),
        {
            "kind": event_kind,
            "role": "codex_capability_supervisor" if kind != REQUEST_KIND else "context_librarian",
            "request_id": artifact.get("request_id"),
            "request_sha256": artifact.get("request_sha256"),
            "response_sha256": artifact.get("response_sha256"),
            "brief_sha256": artifact.get("brief_sha256"),
            "workflow_state": artifact.get("workflow_state"),
            "summary": _redact_text(artifact.get("summary"), 500),
            "advisory_only": True,
        },
    )


def _read_json(path: str) -> dict[str, Any]:
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"JSON object required: {path}")
    return doc


def _write_json(path: str, value: dict[str, Any]) -> pathlib.Path:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or validate bounded CGKN Codex supervisor handoffs.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--goal", required=True)
    prepare.add_argument("--gap", required=True)
    prepare.add_argument("--category", choices=sorted(ALLOWED_CATEGORIES), required=True)
    prepare.add_argument("--librarian-json")
    prepare.add_argument("--evidence-json")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--session")
    respond = sub.add_parser("respond")
    respond.add_argument("--request", required=True)
    respond.add_argument("--draft", required=True)
    respond.add_argument("--output", required=True)
    respond.add_argument("--session")
    validate = sub.add_parser("validate")
    validate.add_argument("--request", required=True)
    validate.add_argument("--response", required=True)
    validate.add_argument("--output", required=True)
    validate.add_argument("--whiteboard-patch")
    validate.add_argument("--session")
    project = sub.add_parser("project-whiteboard")
    project.add_argument("--brief", required=True)
    project.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.command == "prepare":
        librarian = _read_json(args.librarian_json) if args.librarian_json else {}
        evidence_doc = _read_json(args.evidence_json) if args.evidence_json else {}
        evidence = evidence_doc.get("evidence", []) if isinstance(evidence_doc.get("evidence", []), list) else [evidence_doc]
        artifact = build_escalation_request(
            goal_summary=args.goal,
            capability_gap=args.gap,
            category=args.category,
            librarian_context=librarian,
            failure_evidence=evidence,
        )
    elif args.command == "respond":
        request = _read_json(args.request)
        draft = _read_json(args.draft)
        artifact = build_supervisor_response(
            request,
            workflow_state=str(draft.get("workflow_state", "")),
            summary=str(draft.get("summary", "")),
            diagnosis=draft.get("diagnosis", []),
            provider_guidance=draft.get("provider_guidance", []),
            repair_targets=draft.get("repair_targets", []),
            acceptance_checks=draft.get("acceptance_checks", []),
            context_requests=draft.get("context_requests", []),
            tool_evidence_requests=draft.get("tool_evidence_requests", []),
            known_limits=draft.get("known_limits", []),
        )
    elif args.command == "validate":
        request = _read_json(args.request)
        response = _read_json(args.response)
        artifact = build_capability_brief(request, response)
    else:
        brief = _read_json(args.brief)
        output = _write_json(args.output, whiteboard_patch_from_brief(brief))
        print(json.dumps({"ok": True, "kind": "CGKNCodexCapabilityWhiteboardPatch", "output": str(output)}, ensure_ascii=False))
        return 0

    output = _write_json(args.output, artifact)
    if args.command == "validate" and args.whiteboard_patch:
        _write_json(args.whiteboard_patch, whiteboard_patch_from_brief(artifact))
    if args.session:
        append_handoff_event(pathlib.Path(args.session), artifact)
    print(json.dumps({"ok": True, "kind": artifact["kind"], "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
