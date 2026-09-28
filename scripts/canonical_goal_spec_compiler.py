#!/usr/bin/env python3
"""Grounded open-domain GoalSpec compilation for the canonical requirement lane.

Provider planning output is proposal evidence only.  This module validates its
binding and grounding, preserves user/system constraints, and emits the sole
canonical requirement projection consumed by downstream planning.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


COMPILER_VERSION = "1.0"
GOAL_SPEC_SCHEMA_VERSION = "2.0"
PLANNING_PROPOSAL_SCHEMA_VERSION = "1.0"
CANONICAL_AUTHORITY = "canonical_requirement_authority"
PROPOSAL_AUTHORITY = "proposal"

PROPOSAL_LIST_FIELDS = (
    "intended_users",
    "desired_outcomes",
    "proposed_core_capabilities",
    "proposed_supporting_capabilities",
    "proposed_user_workflows",
    "explicit_constraints_found",
    "necessary_inferences",
    "assumptions",
    "open_questions",
    "proposed_acceptance_anchors",
    "proposed_forbidden_substitutions",
    "source_grounding",
)
GROUNDED_FIELDS = {
    "intended_users",
    "desired_outcomes",
    "proposed_core_capabilities",
    "proposed_supporting_capabilities",
    "proposed_user_workflows",
    "proposed_workstreams",
    "explicit_constraints_found",
    "proposed_acceptance_anchors",
    "proposed_forbidden_substitutions",
}
SOURCE_KIND_TO_PROVENANCE = {
    "RAW_GOAL": "USER_EXPLICIT",
    "CONVERSATION_CONTEXT": "USER_CONTEXT",
    "NECESSARY_INFERENCE": "NECESSARY_INFERENCE",
    "SYSTEM_POLICY": "SYSTEM_POLICY",
}
ALLOWED_PROVENANCE = {
    "USER_EXPLICIT",
    "USER_CONTEXT",
    "NECESSARY_INFERENCE",
    "PROVIDER_PROPOSAL",
    "SYSTEM_POLICY",
    "UNGROUNDED",
}


# ASCII-safe canonical marker definitions.  Unicode escapes keep Windows patch
# and checkout encoding from changing requirement semantics.
LOCAL_MARKERS = ("\u672c\u5730", "\u79bb\u7ebf", "offline", "local")
CLOUD_MARKERS = ("\u4e91\u7aef", "\u4e91\u670d\u52a1", "\u4e0a\u4f20", "cloud", "remote upload", "saas")
IDENTITY_MARKERS = ("\u540c\u4e00\u771f\u4eba", "\u771f\u4eba\u8eab\u4efd", "\u4eba\u7269\u8eab\u4efd", "\u6307\u5b9a\u89d2\u8272", "\u89d2\u8272\u8eab\u4efd", "same person", "person identity")
IDENTITY_CAPABILITY_MARKERS = IDENTITY_MARKERS + ("identity", "identify_person", "character_identity", "face_recognition")
PROXY_MARKERS = ("\u989c\u8272", "\u4e3b\u8272", "\u80cc\u666f", "\u56fa\u5b9a\u4f4d\u7f6e", "\u6587\u4ef6\u540d", "\u65f6\u95f4\u6233", "color", "background", "fixed position", "filename", "timestamp")
ALL_MARKERS = ("\u6240\u6709", "\u5168\u90e8", "every", "all ")
SAMPLE_MARKERS = ("\u968f\u673a", "\u62bd\u6837", "\u51e0\u4e2a", "random", "sample", "a few")
AUTOMATIC_MARKERS = ("\u81ea\u52a8", "automatically", "automatic")
MANUAL_MARKERS = ("\u4eba\u5de5", "\u624b\u52a8", "manual")
VIDEO_EXPORT_MARKERS = ("\u5bfc\u51fa\u7247\u6bb5", "\u89c6\u9891\u7247\u6bb5", "export clips", "export video")
TIMESTAMP_ONLY_MARKERS = ("\u4ec5\u65f6\u95f4\u6233", "\u53ea\u8f93\u51fa\u65f6\u95f4\u6233", "timestamps only", "json only")
HIGH_RISK_ADDITIONS = ("\u4e0a\u4f20\u4e91\u7aef", "\u4e91\u7aef\u4e0a\u4f20", "cloud upload", "remote biometric", "\u81ea\u52a8\u5220\u9664", "irreversible delete")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def raw_goal_hash(raw_goal: str) -> str:
    return "sha256:" + hashlib.sha256(str(raw_goal).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", _text(value).lower())


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", _text(value).lower()).strip("_")
    return text[:72] or "workstream"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(_text(item) for item in value if _text(item)))


def canonicalize_assumptions(*sources: Any) -> list[str]:
    """The sole canonical assembly point for GoalSpec assumptions."""
    return list(
        dict.fromkeys(
            item
            for source in sources
            for item in _string_list(source)
            if item
        )
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = _text(text).lower()
    return any(marker in lowered for marker in markers)


def validate_planning_proposal(proposal: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(proposal, dict):
        return ["planning_proposal_object_required"]
    if proposal.get("schema_version") != PLANNING_PROPOSAL_SCHEMA_VERSION:
        errors.append("planning_proposal_schema_version")
    allowed = {"schema_version", "interpreted_goal", "proposed_workstreams", *PROPOSAL_LIST_FIELDS}
    for field in sorted(set(proposal) - allowed):
        errors.append(f"unexpected_field:{field}")
    if not _text(proposal.get("interpreted_goal")):
        errors.append("interpreted_goal_required")
    for field in PROPOSAL_LIST_FIELDS:
        if not isinstance(proposal.get(field), list):
            errors.append(f"{field}_must_be_array")
        elif field == "source_grounding" and any(not isinstance(item, dict) for item in proposal[field]):
            errors.append(f"{field}_contains_invalid_item")
        elif field != "source_grounding" and any(not isinstance(item, str) or not _text(item) for item in proposal[field]):
            errors.append(f"{field}_contains_invalid_item")
    for field in ("intended_users", "desired_outcomes", "proposed_core_capabilities", "proposed_user_workflows", "proposed_acceptance_anchors", "source_grounding"):
        if isinstance(proposal.get(field), list) and not proposal[field]:
            errors.append(f"{field}_must_not_be_empty")
    if not isinstance(proposal.get("proposed_workstreams"), list):
        errors.append("proposed_workstreams_must_be_array")
    for index, row in enumerate(proposal.get("proposed_workstreams", [])):
        if not isinstance(row, dict):
            errors.append(f"proposed_workstreams[{index}]_object_required")
            continue
        if not _text(row.get("id")) or not _text(row.get("scope")):
            errors.append(f"proposed_workstreams[{index}]_id_scope_required")
        if set(row) - {"id", "scope", "covers_capabilities"}:
            errors.append(f"proposed_workstreams[{index}]_unexpected_field")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,71}", _text(row.get("id"))):
            errors.append(f"proposed_workstreams[{index}]_id_format")
        if not isinstance(row.get("covers_capabilities"), list):
            errors.append(f"proposed_workstreams[{index}]_covers_capabilities_array")
    for index, row in enumerate(proposal.get("source_grounding", [])):
        if not isinstance(row, dict):
            errors.append(f"source_grounding[{index}]_object_required")
            continue
        if _text(row.get("target")) not in GROUNDED_FIELDS:
            errors.append(f"source_grounding[{index}]_target")
        if not _text(row.get("value")):
            errors.append(f"source_grounding[{index}]_value")
        if _text(row.get("source_kind")) not in SOURCE_KIND_TO_PROVENANCE:
            errors.append(f"source_grounding[{index}]_source_kind")
        if not _text(row.get("source_excerpt")):
            errors.append(f"source_grounding[{index}]_source_excerpt")
        if not _text(row.get("rationale")):
            errors.append(f"source_grounding[{index}]_rationale")
        if set(row) - {"target", "value", "source_kind", "source_excerpt", "rationale"}:
            errors.append(f"source_grounding[{index}]_unexpected_field")
    return sorted(set(errors))


def planning_proposal_prompt_contract() -> dict[str, Any]:
    return {
        "schema_version": PLANNING_PROPOSAL_SCHEMA_VERSION,
        "interpreted_goal": "non-empty string",
        "intended_users": ["string"],
        "desired_outcomes": ["string"],
        "proposed_core_capabilities": ["snake_case capability id"],
        "proposed_supporting_capabilities": ["snake_case capability id"],
        "proposed_user_workflows": ["observable user workflow"],
        "proposed_workstreams": [
            {"id": "snake_case id", "scope": "bounded requirement scope", "covers_capabilities": ["capability id"]}
        ],
        "explicit_constraints_found": ["constraint"],
        "necessary_inferences": ["inference with rationale represented in source_grounding"],
        "assumptions": ["revisable assumption"],
        "open_questions": ["non-blocking question unless the raw goal is contradictory or irreversible"],
        "proposed_acceptance_anchors": ["observable user outcome"],
        "proposed_forbidden_substitutions": ["forbidden goal degradation"],
        "source_grounding": [
            {
                "target": "one proposal list field",
                "value": "exact item value, or workstream id",
                "source_kind": "RAW_GOAL | CONVERSATION_CONTEXT | NECESSARY_INFERENCE | SYSTEM_POLICY",
                "source_excerpt": "bounded supporting excerpt",
                "rationale": "how the source supports the item",
            }
        ],
    }


def build_planning_artifact(
    *,
    proposal: dict[str, Any],
    raw_goal: str,
    provider_mode: str,
    artifact_ref: str,
    transport_identity: dict[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    artifact = {
        "kind": "CGKNRequirementsPlanningProposalArtifact",
        "schema_version": "1.0",
        "stage": "requirements_planning",
        "authority": PROPOSAL_AUTHORITY,
        "governance_authority": False,
        "acceptance_authority": False,
        "release_authority": False,
        "provider_mode": _text(provider_mode),
        "raw_goal_hash": raw_goal_hash(raw_goal),
        "proposal": proposal,
        "proposal_hash": stable_hash(proposal),
        "artifact_ref": _text(artifact_ref),
        "transport_identity": dict(transport_identity),
        "created_at": created_at or now(),
    }
    artifact["artifact_hash"] = stable_hash(artifact)
    return artifact


def validate_planning_artifact(
    artifact: dict[str, Any] | None,
    raw_goal: str,
) -> list[str]:
    if not isinstance(artifact, dict) or not artifact:
        return ["planning_artifact_required"]
    errors: list[str] = []
    if artifact.get("kind") != "CGKNRequirementsPlanningProposalArtifact":
        errors.append("planning_artifact_kind")
    if artifact.get("stage") != "requirements_planning":
        errors.append("planning_artifact_stage")
    if artifact.get("authority") != PROPOSAL_AUTHORITY:
        errors.append("planning_artifact_authority")
    if any(bool(artifact.get(field)) for field in ("governance_authority", "acceptance_authority", "release_authority")):
        errors.append("planning_artifact_claims_canonical_authority")
    if artifact.get("raw_goal_hash") != raw_goal_hash(raw_goal):
        errors.append("planning_artifact_raw_goal_hash")
    proposal = artifact.get("proposal", {})
    errors.extend(validate_planning_proposal(proposal if isinstance(proposal, dict) else {}))
    if artifact.get("proposal_hash") != stable_hash(proposal):
        errors.append("planning_artifact_proposal_hash")
    expected_artifact_hash = stable_hash({key: value for key, value in artifact.items() if key != "artifact_hash"})
    if artifact.get("artifact_hash") != expected_artifact_hash:
        errors.append("planning_artifact_hash")
    identity = artifact.get("transport_identity", {})
    if not isinstance(identity, dict):
        errors.append("planning_transport_identity")
    else:
        for field in ("run_id", "project_id", "job_id", "attempt_id", "stage", "request_hash", "response_hash"):
            if not _text(identity.get(field)):
                errors.append(f"planning_transport_{field}")
        if identity.get("stage") != "requirements_planning":
            errors.append("planning_transport_stage_mismatch")
        if identity.get("validated") is not True:
            errors.append("planning_transport_not_validated")
        if _text(artifact.get("provider_mode")) in {"codex_surrogate", "deterministic_replay"}:
            if identity.get("accepted") is not True or identity.get("consumed") is not True:
                errors.append("planning_transport_not_accepted_consumed")
    return sorted(set(errors))


def _goal_segments(raw_goal: str) -> list[str]:
    segments = [
        _text(item)
        for item in re.split(r"[\n\u3002\uff01\uff1f!?\uff1b;\uff0c,]+|\bthen\b|\band then\b", str(raw_goal or ""), flags=re.I)
        if _text(item)
    ]
    return [re.sub(r"^(?:\u6211\u60f3\u8981|\u8bf7|\u5e2e\u6211|please)\s*", "", item, flags=re.I) for item in segments]


def extract_explicit_constraints(raw_goal: str, conversation_context: Any = None) -> list[str]:
    markers = (
        "\u5fc5\u987b", "\u4e0d\u5f97", "\u4e0d\u80fd", "\u4e0d\u5141\u8bb8", "\u5b8c\u5168\u672c\u5730", "\u672c\u5730\u8fd0\u884c", "\u79bb\u7ebf", "\u9690\u79c1", "\u4e0d\u4e0a\u4f20",
        "must", "must not", "cannot", "without cloud", "no cloud", "offline", "privacy", "local",
        "\u4e2d\u6587\u8def\u5f84", "\u4e2d\u6587\u754c\u9762", "\u4e2d\u6587\u540d\u79f0",
    )
    values = [segment for segment in _goal_segments(raw_goal) if _contains_any(segment, markers)]
    if isinstance(conversation_context, dict):
        for value in conversation_context.get("explicit_constraints", []):
            if _text(value):
                values.append(_text(value))
    return list(dict.fromkeys(values))


def _constraint_classes(value: str) -> set[str]:
    text = _text(value).lower()
    classes: set[str] = set()
    if _contains_any(text, LOCAL_MARKERS):
        classes.add("local")
    if _contains_any(text, CLOUD_MARKERS) and _contains_any(text, ("\u4e0d", "no", "not", "without", "\u4e0d\u5f97", "\u4e0d\u80fd")):
        classes.add("no_cloud")
    if _contains_any(text, ("\u9690\u79c1", "privacy")):
        classes.add("privacy")
    if _contains_any(text, ("\u4e2d\u6587", "chinese")):
        classes.add("chinese")
    return classes


def _grounding_index(
    proposal: dict[str, Any],
    raw_goal: str,
    conversation_context: Any,
    system_constraints: list[str],
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], list[str]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    invalid: list[str] = []
    context_text = canonical_json(conversation_context or {})
    policy_text = "\n".join(system_constraints)
    raw_norm = _norm(raw_goal)
    for row in proposal.get("source_grounding", []):
        if not isinstance(row, dict):
            continue
        target = _text(row.get("target"))
        value = _text(row.get("value"))
        source_kind = _text(row.get("source_kind"))
        excerpt = _text(row.get("source_excerpt"))
        valid = bool(target and value and source_kind in SOURCE_KIND_TO_PROVENANCE and excerpt and _text(row.get("rationale")))
        if valid and source_kind == "RAW_GOAL":
            valid = _norm(excerpt) in raw_norm
        elif valid and source_kind == "CONVERSATION_CONTEXT":
            valid = _norm(excerpt) in _norm(context_text)
        elif valid and source_kind == "SYSTEM_POLICY":
            valid = _norm(excerpt) in _norm(policy_text)
        elif valid and source_kind == "NECESSARY_INFERENCE":
            valid = len(_text(row.get("rationale"))) >= 8
        if not valid:
            invalid.append(f"ungrounded:{target}:{value}")
            continue
        normalized = dict(row)
        normalized["provenance"] = ["PROVIDER_PROPOSAL", SOURCE_KIND_TO_PROVENANCE[source_kind]]
        index.setdefault((target, value), []).append(normalized)
    return index, sorted(set(invalid))


def _workstreams(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in value if isinstance(value, list) else []:
        if not isinstance(row, dict):
            continue
        workstream_id = _slug(row.get("id"))
        if workstream_id in seen:
            continue
        seen.add(workstream_id)
        result.append(
            {
                "id": workstream_id,
                "scope": _text(row.get("scope")),
                "covers_capabilities": _string_list(row.get("covers_capabilities")),
            }
        )
    return result


def _covered_segments(raw_goal: str, grounding: dict[tuple[str, str], list[dict[str, Any]]]) -> list[str]:
    excerpts = [
        _norm(row.get("source_excerpt"))
        for rows in grounding.values()
        for row in rows
        if row.get("source_kind") == "RAW_GOAL"
    ]
    uncovered: list[str] = []
    for segment in _goal_segments(raw_goal):
        normalized = _norm(segment)
        if len(normalized) < 3:
            continue
        if not any(normalized in excerpt or excerpt in normalized for excerpt in excerpts if excerpt):
            uncovered.append(segment)
    return uncovered


def _anchor_covers_outcome(
    outcome: str,
    anchors: list[str],
    grounding: dict[tuple[str, str], list[dict[str, Any]]],
) -> bool:
    outcome_excerpts = {
        _norm(row.get("source_excerpt"))
        for row in grounding.get(("desired_outcomes", outcome), [])
    }
    for anchor in anchors:
        anchor_excerpts = {
            _norm(row.get("source_excerpt"))
            for row in grounding.get(("proposed_acceptance_anchors", anchor), [])
        }
        if outcome_excerpts.intersection(anchor_excerpts):
            return True
        if _norm(outcome) in _norm(anchor) or _norm(anchor) in _norm(outcome):
            return True
    return False


def _semantic_failures(
    raw_goal: str,
    core_capabilities: list[str],
    all_capabilities: list[str],
    desired_outcomes: list[str],
    acceptance_anchors: list[str],
    proposal_text: str,
    explicit_constraints: list[str],
) -> list[str]:
    failures: list[str] = []
    raw = _text(raw_goal).lower()
    core = " ".join(core_capabilities).lower()
    outcomes = " ".join([*desired_outcomes, *acceptance_anchors]).lower()
    if _contains_any(raw, IDENTITY_MARKERS) and _contains_any(core, PROXY_MARKERS) and not _contains_any(core, IDENTITY_CAPABILITY_MARKERS):
        failures.append("forbidden_proxy_substitution:semantic_identity_replaced")
    if _contains_any(raw, ALL_MARKERS) and _contains_any(outcomes, SAMPLE_MARKERS) and not _contains_any(outcomes, ALL_MARKERS):
        failures.append("silent_goal_reduction:all_replaced_by_sample")
    if _contains_any(raw, AUTOMATIC_MARKERS) and _contains_any(raw, MANUAL_MARKERS):
        automatic_actions = AUTOMATIC_MARKERS + ("\u8bc6\u522b", "\u5b9a\u4f4d", "\u5206\u6790", "detect", "identify", "locate", "analyze")
        if _contains_any(core, MANUAL_MARKERS) and not _contains_any(core, automatic_actions):
            failures.append("silent_goal_reduction:automatic_core_replaced_by_manual")
    if _contains_any(raw, VIDEO_EXPORT_MARKERS) and _contains_any(outcomes, TIMESTAMP_ONLY_MARKERS):
        failures.append("silent_goal_reduction:video_export_replaced_by_metadata")
    raw_classes = set().union(*(_constraint_classes(item) for item in extract_explicit_constraints(raw_goal)), set())
    compiled_classes = set().union(*(_constraint_classes(item) for item in explicit_constraints), set())
    if not raw_classes.issubset(compiled_classes):
        failures.append("dropped_explicit_constraint:" + ",".join(sorted(raw_classes - compiled_classes)))
    if "local" in raw_classes and _contains_any(" ".join(all_capabilities), HIGH_RISK_ADDITIONS + CLOUD_MARKERS):
        failures.append("unsupported_high_risk_addition:cloud_scope")
    return sorted(set(failures))


def compile_goal_spec(
    *,
    raw_goal: str,
    planning_artifact: dict[str, Any],
    fast_path_profile: dict[str, Any] | None = None,
    conversation_context: dict[str, Any] | None = None,
    system_constraints: list[str] | None = None,
) -> dict[str, Any]:
    raw_goal = _text(raw_goal)
    conversation_context = dict(conversation_context or {})
    system_constraints = _string_list(system_constraints or [
        "Preserve the original user goal and explicit constraints.",
        "Provider planning output has proposal authority only.",
        "Do not add unrequested cloud processing or replace semantic outcomes with easier proxies.",
    ])
    artifact_errors = validate_planning_artifact(planning_artifact, raw_goal)
    proposal = planning_artifact.get("proposal", {}) if isinstance(planning_artifact, dict) else {}
    proposal = proposal if isinstance(proposal, dict) else {}
    grounding, invalid_grounding = _grounding_index(proposal, raw_goal, conversation_context, system_constraints)

    raw_fields: dict[str, list[str]] = {
        field: _string_list(proposal.get(field))
        for field in (
            "intended_users", "desired_outcomes", "proposed_core_capabilities",
            "proposed_supporting_capabilities", "proposed_user_workflows",
            "explicit_constraints_found", "assumptions", "open_questions",
            "proposed_acceptance_anchors", "proposed_forbidden_substitutions",
        )
    }
    provenance_by_field: dict[str, list[dict[str, Any]]] = {}

    def grounded(field: str, values: list[str]) -> list[str]:
        accepted: list[str] = []
        rows: list[dict[str, Any]] = []
        for value in values:
            sources = grounding.get((field, value), [])
            provenance = list(dict.fromkeys(
                item for source in sources for item in source.get("provenance", []) if item in ALLOWED_PROVENANCE
            ))
            if not sources:
                rows.append({"value": value, "provenance": ["PROVIDER_PROPOSAL", "UNGROUNDED"], "accepted": False})
                continue
            rows.append({
                "value": value,
                "provenance": provenance,
                "accepted": True,
                "source_refs": [source.get("source_excerpt") for source in sources],
            })
            accepted.append(value)
        provenance_by_field[field] = rows
        return accepted

    intended_users = grounded("intended_users", raw_fields["intended_users"])
    desired_outcomes = grounded("desired_outcomes", raw_fields["desired_outcomes"])
    core_capabilities = grounded("proposed_core_capabilities", raw_fields["proposed_core_capabilities"])
    supporting_capabilities = grounded("proposed_supporting_capabilities", raw_fields["proposed_supporting_capabilities"])
    user_workflows = grounded("proposed_user_workflows", raw_fields["proposed_user_workflows"])
    proposed_constraints = grounded("explicit_constraints_found", raw_fields["explicit_constraints_found"])
    acceptance_anchors = grounded("proposed_acceptance_anchors", raw_fields["proposed_acceptance_anchors"])
    forbidden_substitutions = grounded("proposed_forbidden_substitutions", raw_fields["proposed_forbidden_substitutions"])
    canonical_workstreams: list[dict[str, Any]] = []
    workstream_provenance: list[dict[str, Any]] = []
    for row in _workstreams(proposal.get("proposed_workstreams")):
        sources = grounding.get(("proposed_workstreams", row["id"]), [])
        accepted = bool(sources)
        workstream_provenance.append({
            "value": row["id"],
            "provenance": list(dict.fromkeys(
                item for source in sources for item in source.get("provenance", [])
            )) if sources else ["PROVIDER_PROPOSAL", "UNGROUNDED"],
            "accepted": accepted,
            "source_refs": [source.get("source_excerpt") for source in sources],
        })
        if accepted:
            canonical_workstreams.append(row)
    provenance_by_field["proposed_workstreams"] = workstream_provenance

    independently_extracted_constraints = extract_explicit_constraints(raw_goal, conversation_context)
    explicit_constraints = list(dict.fromkeys([*independently_extracted_constraints, *proposed_constraints]))
    provenance_by_field["explicit_constraints"] = [
        {"value": value, "provenance": ["USER_EXPLICIT"], "accepted": True, "source_refs": [value]}
        for value in independently_extracted_constraints
    ] + provenance_by_field.get("explicit_constraints_found", [])
    inferred_constraints = list(dict.fromkeys(system_constraints))
    provenance_by_field["inferred_constraints"] = [
        {"value": value, "provenance": ["SYSTEM_POLICY"], "accepted": True, "source_refs": [value]}
        for value in inferred_constraints
    ]

    missing_capabilities = [] if core_capabilities else ["at least one grounded core capability"]
    missing_workstreams = [] if canonical_workstreams else ["at least one grounded workstream"]
    covered = {cap for row in canonical_workstreams for cap in row["covers_capabilities"]}
    uncovered_capabilities = [cap for cap in core_capabilities if cap not in covered]
    uncovered_outcomes = [
        outcome for outcome in desired_outcomes
        if not _anchor_covers_outcome(outcome, acceptance_anchors, grounding)
    ]
    uncovered_goal_segments = _covered_segments(raw_goal, grounding)
    ungrounded = [
        row["value"]
        for rows in provenance_by_field.values()
        for row in rows
        if "UNGROUNDED" in row.get("provenance", [])
    ]
    proposal_text = canonical_json(proposal)
    semantic_failures = _semantic_failures(
        raw_goal, core_capabilities, [*core_capabilities, *supporting_capabilities], desired_outcomes, acceptance_anchors,
        proposal_text, explicit_constraints,
    )
    failures = list(dict.fromkeys([
        *artifact_errors,
        *invalid_grounding,
        *(["missing_core_capabilities"] if missing_capabilities else []),
        *(["missing_workstreams"] if missing_workstreams else []),
        *(f"uncovered_core_capability:{item}" for item in uncovered_capabilities),
        *(f"uncovered_user_outcome:{item}" for item in uncovered_outcomes),
        *(f"uncovered_goal_segment:{item}" for item in uncovered_goal_segments),
        *semantic_failures,
    ]))
    fast_path_profile = dict(fast_path_profile or {})
    domain = _text(fast_path_profile.get("domain")) or "custom_local_application"
    capabilities = list(dict.fromkeys([*core_capabilities, *supporting_capabilities]))
    assumptions = canonicalize_assumptions(
        raw_fields["assumptions"],
        proposal.get("necessary_inferences"),
        fast_path_profile.get("assumptions"),
    )
    open_questions = raw_fields["open_questions"]
    provenance_by_field["normalized_goal"] = [
        {"value": raw_goal, "provenance": ["USER_EXPLICIT"], "accepted": True, "source_refs": [raw_goal]}
    ]
    provenance_by_field["assumptions"] = [
        {
            "value": value,
            "provenance": [
                "PROVIDER_PROPOSAL",
                "NECESSARY_INFERENCE" if value in _string_list(proposal.get("necessary_inferences")) else "UNGROUNDED",
            ],
            "accepted": True,
        }
        for value in assumptions
    ]
    provenance_by_field["open_questions"] = [
        {"value": value, "provenance": ["PROVIDER_PROPOSAL", "UNGROUNDED"], "accepted": True}
        for value in open_questions
    ]
    provenance_by_field["non_goals"] = [
        {"value": value, "provenance": ["SYSTEM_POLICY"], "accepted": True}
        for value in ("unrequested external services", "unrelated product scope")
    ]
    entities = _string_list(fast_path_profile.get("entities")) or ["ProjectState"]
    interfaces = _string_list(fast_path_profile.get("interfaces")) or ["primary_workspace", "result_review"]
    interaction_modes = _string_list(fast_path_profile.get("interaction_modes"))
    result: dict[str, Any] = {
        "kind": "GoalSpec",
        "schema_version": GOAL_SPEC_SCHEMA_VERSION,
        "goal_id": "goal-" + raw_goal_hash(raw_goal).split(":", 1)[1][:20],
        "raw_goal": raw_goal,
        "raw_goal_hash": raw_goal_hash(raw_goal),
        # A Provider interpretation remains proposal evidence.  The canonical
        # normalized goal is lossless with respect to the user-owned raw goal.
        "normalized_goal": raw_goal,
        "intended_users": intended_users,
        "desired_outcomes": desired_outcomes,
        "core_capabilities": core_capabilities,
        "supporting_capabilities": supporting_capabilities,
        "user_workflows": user_workflows,
        "workstreams": canonical_workstreams,
        "explicit_constraints": explicit_constraints,
        "inferred_constraints": inferred_constraints,
        "non_goals": list(dict.fromkeys(["unrequested external services", "unrelated product scope"])),
        "open_questions": open_questions,
        "assumptions": assumptions,
        "acceptance_anchors": acceptance_anchors,
        "forbidden_substitutions": forbidden_substitutions,
        "source_refs": [
            {"kind": "raw_goal", "hash": raw_goal_hash(raw_goal)},
            {"kind": "planning_artifact", "ref": planning_artifact.get("artifact_ref", ""), "hash": planning_artifact.get("artifact_hash", "")},
        ],
        "planning_artifact_ref": _text(planning_artifact.get("artifact_ref")),
        "planning_artifact_hash": _text(planning_artifact.get("artifact_hash")),
        "provenance_by_field": provenance_by_field,
        "compiler_version": COMPILER_VERSION,
        "compiled_at": now(),
        "authority": CANONICAL_AUTHORITY,
        "authority_decision": "PASS" if not failures else "NEEDS_REWORK",
        "grounding_validation": {
            "status": "PASS" if not failures else "NEEDS_REWORK",
            "failures": failures,
            "missing_capabilities": missing_capabilities,
            "missing_workstreams": missing_workstreams,
            "dropped_constraints": [item for item in failures if item.startswith("dropped_explicit_constraint")],
            "unsupported_additions": [*ungrounded, *[item for item in failures if item.startswith("unsupported_high_risk_addition")]],
            "uncovered_goal_segments": uncovered_goal_segments,
            "uncovered_core_capabilities": uncovered_capabilities,
            "uncovered_user_outcomes": uncovered_outcomes,
            "required_corrections": failures,
        },
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "reason": "" if not failures else "INSUFFICIENT_GROUNDED_GOAL_PLAN",
        "ready_to_generate": not failures,
        # Compatibility projection for existing downstream consumers.
        "goal": raw_goal,
        "domain": domain,
        "capabilities": capabilities,
        "user_flows": user_workflows,
        "entities": entities,
        "interfaces": interfaces,
        "interaction_modes": interaction_modes,
        "report_formats": _string_list(fast_path_profile.get("report_formats")),
        "runtime_dependencies": _string_list(fast_path_profile.get("runtime_dependencies")),
        "entrypoints": _string_list(fast_path_profile.get("entrypoints")),
        "package_name": _text(fast_path_profile.get("package_name")),
        "feature_contracts": list(fast_path_profile.get("feature_contracts", []))
        if isinstance(fast_path_profile.get("feature_contracts"), list) else [],
        "constraints": list(dict.fromkeys([*explicit_constraints, *inferred_constraints])),
        "acceptance_behaviors": acceptance_anchors,
    }
    result["goal_spec_hash"] = stable_hash(result)
    return result


def requirement_replan_feedback(goal_spec: dict[str, Any]) -> dict[str, Any]:
    validation = goal_spec.get("grounding_validation", {}) if isinstance(goal_spec.get("grounding_validation"), dict) else {}
    return {
        "kind": "CGKNRequirementReplanFeedback",
        "schema_version": "1.0",
        "status": "NEEDS_REWORK",
        "raw_goal_hash": goal_spec.get("raw_goal_hash", ""),
        "goal_spec_hash": goal_spec.get("goal_spec_hash", ""),
        "missing_capabilities": list(validation.get("missing_capabilities", [])),
        "missing_workstreams": list(validation.get("missing_workstreams", [])),
        "dropped_constraints": list(validation.get("dropped_constraints", [])),
        "unsupported_additions": list(validation.get("unsupported_additions", [])),
        "uncovered_goal_segments": list(validation.get("uncovered_goal_segments", [])),
        "required_corrections": list(validation.get("required_corrections", [])),
        "candidate_repair": False,
    }
