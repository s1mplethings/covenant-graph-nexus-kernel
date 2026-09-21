from __future__ import annotations

import copy
from typing import Any, Iterable


CANONICAL_EVIDENCE_STATUSES = {
    "PASS",
    "PASS_WITH_LIMITS",
    "NOT_EVALUATED",
    "BLOCKED",
    "BLOCKED_PROVIDER",
    "BLOCKED_LOCAL_MODEL",
    "BLOCKED_ENVIRONMENT",
    "NEEDS_REWORK",
    "FAIL",
}
DELIVERY_APPROACHES = {"predictive", "adaptive", "hybrid"}
ITERATION_WORKFLOW_STATES = {"planned", "active", "reviewing", "closed", "cancelled"}
EXPERIENCE_STATES = {"candidate", "validated", "approved", "retired"}
BACKLOG_STATES = {"idea", "ready", "active", "done", "deferred", "cancelled"}
LEVELS = {"low": 0, "medium": 1, "high": 2}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _unique_strings(values: Iterable[Any]) -> list[str]:
    return sorted({_text(value) for value in values if _text(value)})


def select_delivery_approach(
    *,
    requirements_uncertainty: str,
    technical_uncertainty: str,
    criticality: str,
) -> dict[str, str]:
    req = requirements_uncertainty if requirements_uncertainty in LEVELS else "medium"
    tech = technical_uncertainty if technical_uncertainty in LEVELS else "medium"
    crit = criticality if criticality in LEVELS else "medium"
    uncertainty = max(LEVELS[req], LEVELS[tech])
    if uncertainty == 0 and LEVELS[crit] <= 1:
        approach = "predictive"
        rationale = "Requirements and technology are stable enough for a plan-led delivery flow."
    elif uncertainty == 2 and LEVELS[crit] == 0:
        approach = "adaptive"
        rationale = "High uncertainty and low criticality favor short learning and value increments."
    else:
        approach = "hybrid"
        rationale = (
            "Stable governance boundaries are needed while requirements, technology, or criticality "
            "still require iterative learning."
        )
    return {
        "delivery_approach": approach,
        "requirements_uncertainty": req,
        "technical_uncertainty": tech,
        "criticality": crit,
        "rationale": rationale,
    }


def new_project_management_pack(
    *,
    project_id: str,
    project_name: str,
    goal: str,
    requirements_uncertainty: str = "medium",
    technical_uncertainty: str = "medium",
    criticality: str = "medium",
) -> dict[str, Any]:
    selection = select_delivery_approach(
        requirements_uncertainty=requirements_uncertainty,
        technical_uncertainty=technical_uncertainty,
        criticality=criticality,
    )
    return {
        "kind": "CGKNAdaptiveProjectManagementPack",
        "schema_version": "1.0",
        "project_id": _text(project_id),
        "project_name": _text(project_name),
        "goal": _text(goal),
        "delivery_approach": selection["delivery_approach"],
        "tailoring": {
            "requirements_uncertainty": selection["requirements_uncertainty"],
            "technical_uncertainty": selection["technical_uncertainty"],
            "criticality": selection["criticality"],
            "iteration_length_days": 7,
            "rationale": selection["rationale"],
        },
        "governance": {
            "success_metrics": ["Accepted value increments satisfy their measurable quality targets."],
            "fixed_constraints": [],
            "escalation_thresholds": ["Escalate when an iteration cannot meet a fixed constraint."],
        },
        "product_backlog": [],
        "quality_management": {
            "definition_of_done": [
                "Acceptance criteria are evaluated.",
                "Applicable automated tests pass.",
                "Known limits and evidence are recorded.",
            ],
            "metrics": [
                {
                    "id": "QM-ACCEPTANCE",
                    "measure": "accepted backlog outcomes",
                    "target": "all selected outcomes accepted or explicitly returned for rework",
                    "method": "iteration review",
                }
            ],
            "assurance_activities": ["Review contracts and quality plans before implementation."],
            "control_activities": ["Run proportionate automated and runtime checks."],
            "improvement_policy": "Use review and retrospective evidence to update the improvement backlog.",
        },
        "risks": [],
        "iteration_refs": [],
        "improvement_backlog": [],
        "workflow_state": "planning",
        "evidence_status": "NOT_EVALUATED",
        "experience_query": {"phase": "planning", "tags": [], "max_items": 8},
    }


def new_enterprise_experience_pack(organization: str = "CGKN") -> dict[str, Any]:
    return {
        "kind": "CGKNEnterpriseExperiencePack",
        "schema_version": "1.0",
        "organization": _text(organization),
        "items": [],
        "usage_receipts": [],
    }


def _error(code: str, message: str, path: str = "") -> dict[str, str]:
    return {"code": code, "message": message, "path": path}


def _base_validation(doc: dict[str, Any], *, expected_kind: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if doc.get("kind") != expected_kind:
        errors.append(_error("KIND_INVALID", f"expected {expected_kind}", "kind"))
    if doc.get("schema_version") != "1.0":
        errors.append(_error("SCHEMA_VERSION_INVALID", "schema_version must be 1.0", "schema_version"))
    return errors


def validate_project_management_pack(doc: dict[str, Any]) -> dict[str, Any]:
    errors = _base_validation(doc, expected_kind="CGKNAdaptiveProjectManagementPack")
    if doc.get("delivery_approach") not in DELIVERY_APPROACHES:
        errors.append(_error("DELIVERY_APPROACH_INVALID", "unknown delivery approach", "delivery_approach"))
    if doc.get("evidence_status") not in CANONICAL_EVIDENCE_STATUSES:
        errors.append(_error("EVIDENCE_STATUS_INVALID", "non-canonical evidence status", "evidence_status"))
    tailoring = doc.get("tailoring", {})
    if not isinstance(tailoring, dict) or any(tailoring.get(key) not in LEVELS for key in (
        "requirements_uncertainty",
        "technical_uncertainty",
        "criticality",
    )):
        errors.append(_error("TAILORING_INVALID", "tailoring levels must be low, medium, or high", "tailoring"))
    quality = doc.get("quality_management", {})
    if not isinstance(quality, dict) or not _list(quality.get("definition_of_done")):
        errors.append(_error("DEFINITION_OF_DONE_MISSING", "quality definition of done is required", "quality_management"))
    metrics = _list(quality.get("metrics")) if isinstance(quality, dict) else []
    metric_ids = {_text(row.get("id")) for row in metrics if isinstance(row, dict)}
    if not metric_ids:
        errors.append(_error("QUALITY_METRICS_MISSING", "at least one quality metric is required", "quality_management.metrics"))
    backlog = _list(doc.get("product_backlog"))
    backlog_ids = [_text(row.get("id")) for row in backlog if isinstance(row, dict)]
    if len(backlog_ids) != len(set(backlog_ids)):
        errors.append(_error("BACKLOG_ID_DUPLICATE", "backlog ids must be unique", "product_backlog"))
    for index, item in enumerate(backlog):
        if not isinstance(item, dict):
            errors.append(_error("BACKLOG_ITEM_INVALID", "backlog item must be an object", f"product_backlog.{index}"))
            continue
        if item.get("state") not in BACKLOG_STATES:
            errors.append(_error("BACKLOG_STATE_INVALID", "unknown backlog state", f"product_backlog.{index}.state"))
        if not _list(item.get("acceptance_criteria")):
            errors.append(_error("BACKLOG_ACCEPTANCE_MISSING", "acceptance criteria are required", f"product_backlog.{index}"))
        unknown_metrics = set(_unique_strings(_list(item.get("quality_metric_ids")))) - metric_ids
        if unknown_metrics:
            errors.append(
                _error(
                    "BACKLOG_QUALITY_METRIC_UNKNOWN",
                    f"unknown quality metrics: {sorted(unknown_metrics)}",
                    f"product_backlog.{index}.quality_metric_ids",
                )
            )
    return {
        "kind": "CGKNManagementValidationResult",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def validate_iteration(doc: dict[str, Any], project_pack: dict[str, Any] | None = None) -> dict[str, Any]:
    errors = _base_validation(doc, expected_kind="CGKNAdaptiveIteration")
    if doc.get("workflow_state") not in ITERATION_WORKFLOW_STATES:
        errors.append(_error("ITERATION_STATE_INVALID", "unknown iteration workflow state", "workflow_state"))
    if doc.get("evidence_status") not in CANONICAL_EVIDENCE_STATUSES:
        errors.append(_error("EVIDENCE_STATUS_INVALID", "non-canonical evidence status", "evidence_status"))
    if not _list(doc.get("backlog_item_ids")):
        errors.append(_error("ITERATION_BACKLOG_EMPTY", "iteration must select at least one backlog item", "backlog_item_ids"))
    if not _list(doc.get("acceptance_criteria")):
        errors.append(_error("ITERATION_ACCEPTANCE_MISSING", "iteration acceptance criteria are required", "acceptance_criteria"))
    if not _list(doc.get("quality_metrics")):
        errors.append(_error("ITERATION_QUALITY_MISSING", "iteration quality metrics are required", "quality_metrics"))
    if project_pack:
        known = {_text(row.get("id")) for row in _list(project_pack.get("product_backlog")) if isinstance(row, dict)}
        unknown = set(_unique_strings(_list(doc.get("backlog_item_ids")))) - known
        if unknown:
            errors.append(_error("ITERATION_BACKLOG_UNKNOWN", f"unknown backlog ids: {sorted(unknown)}", "backlog_item_ids"))
    if doc.get("workflow_state") == "closed" and doc.get("evidence_status") == "NOT_EVALUATED":
        errors.append(_error("CLOSED_WITHOUT_EVIDENCE", "closed iteration must be evaluated", "evidence_status"))
    return {
        "kind": "CGKNManagementValidationResult",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def validate_enterprise_experience_pack(doc: dict[str, Any]) -> dict[str, Any]:
    errors = _base_validation(doc, expected_kind="CGKNEnterpriseExperiencePack")
    item_ids: list[str] = []
    for index, item in enumerate(_list(doc.get("items"))):
        if not isinstance(item, dict):
            errors.append(_error("EXPERIENCE_ITEM_INVALID", "experience item must be an object", f"items.{index}"))
            continue
        item_ids.append(_text(item.get("id")))
        state = item.get("experience_state")
        if state not in EXPERIENCE_STATES:
            errors.append(_error("EXPERIENCE_STATE_INVALID", "unknown experience state", f"items.{index}.experience_state"))
        if state in {"validated", "approved"} and not _list(item.get("evidence_refs")):
            errors.append(
                _error(
                    "EXPERIENCE_EVIDENCE_MISSING",
                    "validated and approved experience requires evidence",
                    f"items.{index}.evidence_refs",
                )
            )
        usage = int(item.get("usage_count", 0) or 0)
        successful = int(item.get("successful_usage_count", 0) or 0)
        if successful > usage:
            errors.append(
                _error(
                    "EXPERIENCE_USAGE_INVALID",
                    "successful usage cannot exceed total usage",
                    f"items.{index}.successful_usage_count",
                )
            )
        if not _list(item.get("applicable_when")):
            errors.append(
                _error("EXPERIENCE_APPLICABILITY_MISSING", "applicability boundaries are required", f"items.{index}")
            )
    if len(item_ids) != len(set(item_ids)):
        errors.append(_error("EXPERIENCE_ID_DUPLICATE", "experience ids must be unique", "items"))
    return {
        "kind": "CGKNManagementValidationResult",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def new_iteration(
    project_pack: dict[str, Any],
    *,
    iteration_id: str,
    goal: str,
    backlog_item_ids: list[str],
) -> dict[str, Any]:
    selected_ids = _unique_strings(backlog_item_ids)
    selected = [
        row
        for row in _list(project_pack.get("product_backlog"))
        if isinstance(row, dict) and _text(row.get("id")) in selected_ids
    ]
    acceptance = _unique_strings(
        criterion
        for item in selected
        for criterion in _list(item.get("acceptance_criteria"))
    )
    metric_ids = {
        metric_id
        for item in selected
        for metric_id in _unique_strings(_list(item.get("quality_metric_ids")))
    }
    quality = project_pack.get("quality_management", {})
    metrics = [
        copy.deepcopy(row)
        for row in _list(quality.get("metrics")) if isinstance(quality, dict)
        if isinstance(row, dict) and _text(row.get("id")) in metric_ids
    ]
    return {
        "kind": "CGKNAdaptiveIteration",
        "schema_version": "1.0",
        "iteration_id": _text(iteration_id),
        "project_id": _text(project_pack.get("project_id")),
        "goal": _text(goal),
        "backlog_item_ids": selected_ids,
        "workflow_state": "planned",
        "evidence_status": "NOT_EVALUATED",
        "acceptance_criteria": acceptance,
        "quality_metrics": metrics,
        "quality_activities": {
            "prevention": ["Confirm acceptance, interfaces, and applicable kernel constraints before implementation."],
            "assurance": list(quality.get("assurance_activities", [])) if isinstance(quality, dict) else [],
            "control": list(quality.get("control_activities", [])) if isinstance(quality, dict) else [],
            "improvement": ["Record review findings and one bounded improvement experiment."],
        },
        "interface_expectations": [],
        "evidence_refs": [],
        "review": {"outcome": "pending", "feedback": [], "accepted_backlog_item_ids": []},
        "retrospective": {"worked": [], "did_not_work": [], "experiments": []},
    }


def close_iteration(
    iteration: dict[str, Any],
    *,
    evidence_status: str,
    review_outcome: str,
    evidence_refs: list[str],
    feedback: list[str] | None = None,
    worked: list[str] | None = None,
    did_not_work: list[str] | None = None,
    experiments: list[str] | None = None,
) -> dict[str, Any]:
    if evidence_status not in CANONICAL_EVIDENCE_STATUSES or evidence_status == "NOT_EVALUATED":
        raise ValueError("closing an iteration requires an evaluated canonical evidence status")
    if review_outcome not in {"accepted", "accepted_with_limits", "rejected"}:
        raise ValueError("review_outcome must be accepted, accepted_with_limits, or rejected")
    out = copy.deepcopy(iteration)
    out["workflow_state"] = "closed"
    out["evidence_status"] = evidence_status
    out["evidence_refs"] = _unique_strings(evidence_refs)
    accepted = out.get("backlog_item_ids", []) if review_outcome in {"accepted", "accepted_with_limits"} else []
    out["review"] = {
        "outcome": review_outcome,
        "feedback": _unique_strings(feedback or []),
        "accepted_backlog_item_ids": list(accepted),
    }
    out["retrospective"] = {
        "worked": _unique_strings(worked or []),
        "did_not_work": _unique_strings(did_not_work or []),
        "experiments": _unique_strings(experiments or []),
    }
    return out


def retrieve_experience(
    pack: dict[str, Any],
    *,
    tags: list[str],
    max_items: int = 8,
    include_validated: bool = True,
) -> dict[str, Any]:
    query_tags = {tag.lower() for tag in _unique_strings(tags)}
    allowed_states = {"approved", "validated"} if include_validated else {"approved"}
    candidates: list[tuple[int, int, str, dict[str, Any]]] = []
    excluded: list[dict[str, str]] = []
    for item in _list(pack.get("items")):
        if not isinstance(item, dict):
            continue
        state = _text(item.get("experience_state"))
        if state not in allowed_states:
            excluded.append({"experience_id": _text(item.get("id")), "reason": f"state:{state}"})
            continue
        item_tags = {tag.lower() for tag in _unique_strings(_list(item.get("tags")))}
        overlap = len(query_tags.intersection(item_tags))
        if query_tags and overlap == 0:
            excluded.append({"experience_id": _text(item.get("id")), "reason": "tag_mismatch"})
            continue
        usage = int(item.get("usage_count", 0) or 0)
        success = int(item.get("successful_usage_count", 0) or 0)
        confidence = int(1000 * success / usage) if usage else 0
        candidates.append((-overlap, -confidence, _text(item.get("id")), copy.deepcopy(item)))
    limit = max(1, min(16, int(max_items or 8)))
    ranked = sorted(candidates)
    selected = [row[3] for row in ranked[:limit]]
    excluded.extend(
        {"experience_id": _text(row[3].get("id")), "reason": "over_budget"}
        for row in ranked[limit:]
    )
    return {
        "kind": "CGKNEnterpriseExperienceRetrievalResult",
        "query": {"tags": sorted(query_tags), "max_items": limit},
        "selected_items": selected,
        "excluded_items": excluded,
    }


def record_experience_usage(
    pack: dict[str, Any],
    *,
    experience_id: str,
    project_id: str,
    iteration_id: str,
    applied: bool,
    outcome: str = "pending",
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    if outcome not in {"pending", "successful", "unsuccessful", "inconclusive"}:
        raise ValueError("invalid experience usage outcome")
    out = copy.deepcopy(pack)
    found = False
    for item in _list(out.get("items")):
        if isinstance(item, dict) and _text(item.get("id")) == _text(experience_id):
            found = True
            if applied:
                item["usage_count"] = int(item.get("usage_count", 0) or 0) + 1
                if outcome == "successful":
                    item["successful_usage_count"] = int(item.get("successful_usage_count", 0) or 0) + 1
    if not found:
        raise KeyError(f"unknown experience id: {experience_id}")
    out.setdefault("usage_receipts", []).append(
        {
            "experience_id": _text(experience_id),
            "project_id": _text(project_id),
            "iteration_id": _text(iteration_id),
            "applied": bool(applied),
            "outcome": outcome,
            "evidence_refs": _unique_strings(evidence_refs or []),
        }
    )
    return out


def render_project_management_markdown(pack: dict[str, Any]) -> str:
    lines = [
        f"# {_text(pack.get('project_name'))} Project Management",
        "",
        f"- Project ID: `{_text(pack.get('project_id'))}`",
        f"- Delivery approach: `{_text(pack.get('delivery_approach'))}`",
        f"- Workflow state: `{_text(pack.get('workflow_state'))}`",
        f"- Evidence status: `{_text(pack.get('evidence_status'))}`",
        "",
        "## Goal",
        "",
        _text(pack.get("goal")),
        "",
        "## Ordered backlog",
        "",
    ]
    backlog = sorted(
        [row for row in _list(pack.get("product_backlog")) if isinstance(row, dict)],
        key=lambda row: (int(row.get("priority", 9999) or 9999), _text(row.get("id"))),
    )
    lines.extend(
        f"- `{_text(item.get('id'))}` [{_text(item.get('state'))}] {_text(item.get('title'))}"
        for item in backlog
    )
    lines.extend(["", "## Definition of done", ""])
    quality = pack.get("quality_management", {})
    lines.extend(
        f"- {_text(item)}"
        for item in _list(quality.get("definition_of_done")) if isinstance(quality, dict)
    )
    lines.extend(["", "## Active risks", ""])
    risks = [
        row for row in _list(pack.get("risks"))
        if isinstance(row, dict) and row.get("state") != "closed"
    ]
    lines.extend(
        f"- `{_text(item.get('id'))}` {_text(item.get('description'))} — {_text(item.get('response'))}"
        for item in risks
    )
    return "\n".join(lines).rstrip() + "\n"


def render_enterprise_experience_markdown(pack: dict[str, Any]) -> str:
    lines = ["# Enterprise Experience", "", f"Organization: {_text(pack.get('organization'))}", ""]
    for item in sorted(
        [row for row in _list(pack.get("items")) if isinstance(row, dict)],
        key=lambda row: _text(row.get("id")),
    ):
        lines.extend(
            [
                f"## {_text(item.get('id'))}: {_text(item.get('title'))}",
                "",
                f"- State: `{_text(item.get('experience_state'))}`",
                f"- Situation: {_text(item.get('situation'))}",
                f"- Action: {_text(item.get('action'))}",
                f"- Outcome: {_text(item.get('outcome'))}",
                f"- Tags: {', '.join(_unique_strings(_list(item.get('tags'))))}",
                f"- Evidence: {', '.join(_unique_strings(_list(item.get('evidence_refs')))) or 'not yet validated'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
