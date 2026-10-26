from __future__ import annotations

from .contracts import (
    DecisionContext,
    DecisionLevel,
    DecisionRisk,
    DecisionRiskClass,
    DecisionRoute,
    ValidationOutcome,
    ValidationStatus,
    stable_hash,
)


DECISION_POLICY_VERSION = "decision-hierarchy-v1"
ESCALATION_POLICY_VERSION = "validator-escalation-v1"

_CRITICAL_BOUNDARIES = {
    "KERNEL_AUTHORITY_CHANGE",
    "PRODUCT_DIRECTION_CHANGE",
    "ACCEPTANCE_LOWERING",
    "SECURITY_BOUNDARY_LOWERING",
    "IRREVERSIBLE_MIGRATION",
    "PROVIDER_BUDGET_INCREASE",
    "HIGH_IMPACT_EXTERNAL_ACTION",
}

_DETERMINISTIC_OPERATIONS = {
    "EXACT_DUPLICATE",
    "KNOWN_REQUIREMENT_OWNER",
    "EXACT_CAPABILITY_IDENTITY",
    "SCHEMA_VALIDATION",
    "HASH_COMPARISON",
    "SINGLE_ELIGIBLE_ROUTE",
    "DETERMINISTIC_FAILURE_OWNER",
    "KNOWN_SUPERSESSION_METADATA",
}


def policy_hashes() -> dict[str, str]:
    return {
        "decision_policy_hash": stable_hash(
            {"version": DECISION_POLICY_VERSION, "deterministic_operations": sorted(_DETERMINISTIC_OPERATIONS), "critical_boundaries": sorted(_CRITICAL_BOUNDARIES)}
        ),
        "escalation_policy_hash": stable_hash(
            {"version": ESCALATION_POLICY_VERSION, "statuses": [item.value for item in ValidationStatus], "same_failure_no_progress_threshold": 2}
        ),
    }


def assess_risk(context: DecisionContext) -> DecisionRisk:
    reasons: set[str] = set()
    critical = set(context.critical_boundaries) & _CRITICAL_BOUNDARIES
    if critical:
        return DecisionRisk(DecisionRiskClass.CRITICAL, tuple(sorted(critical)))
    if not context.reversible:
        reasons.add("IRREVERSIBLE_CHANGE")
    if context.crosses_authority_boundary:
        reasons.add("CROSS_AUTHORITY_BOUNDARY")
    if context.authority_scope.upper() not in {"LOCAL", "BOUNDED"}:
        reasons.add("HIGH_AUTHORITY_IMPACT")
    if context.candidate_count > 1:
        reasons.add("MULTIPLE_CAPABILITY_CANDIDATES")
    if context.candidate_count == 0:
        reasons.add("NO_ELIGIBLE_CAPABILITY")
    if not context.evidence_sufficient:
        reasons.add("INSUFFICIENT_EVIDENCE")
    if not context.capability_qualified:
        reasons.add("UNQUALIFIED_CAPABILITY")
    if not context.validator_available:
        reasons.add("NO_DETERMINISTIC_VALIDATOR")
    if context.uncertainty >= 0.65:
        reasons.add("HIGH_UNCERTAINTY")
    elif context.uncertainty >= 0.25:
        reasons.add("MEDIUM_UNCERTAINTY")

    if context.impact is DecisionRiskClass.CRITICAL:
        reasons.add("CRITICAL_IMPACT")
        risk = DecisionRiskClass.CRITICAL
    elif context.impact is DecisionRiskClass.HIGH or not context.reversible or context.crosses_authority_boundary or context.uncertainty >= 0.65:
        risk = DecisionRiskClass.HIGH
    elif reasons or context.impact is DecisionRiskClass.MEDIUM:
        risk = DecisionRiskClass.MEDIUM
    else:
        reasons.add("REVERSIBLE_LOCAL_CHANGE")
        risk = DecisionRiskClass.LOW
    return DecisionRisk(risk, tuple(sorted(reasons)))


class DecisionRouter:
    """Deterministic routing policy; it does not execute work or own project intent."""

    def route(self, context: DecisionContext) -> DecisionRoute:
        unknown_boundaries = set(context.critical_boundaries) - _CRITICAL_BOUNDARIES
        if unknown_boundaries:
            raise ValueError("unknown critical decision boundary: " + ", ".join(sorted(unknown_boundaries)))
        risk = assess_risk(context)
        if risk.risk_class is DecisionRiskClass.CRITICAL or context.critical_boundaries:
            return DecisionRoute(DecisionLevel.HUMAN_STOP, "STOP_FOR_HUMAN", risk, risk.reason_codes)

        deterministic = (
            context.operation in _DETERMINISTIC_OPERATIONS
            and context.deterministic_rule_available
            and context.deterministic_evidence_valid
        )
        if deterministic:
            return DecisionRoute(
                DecisionLevel.DETERMINISTIC,
                "APPLY_DETERMINISTIC_RULE",
                risk,
                ("UNAMBIGUOUS_CONTRACT", context.operation),
            )

        if not context.evidence_sufficient:
            return DecisionRoute(
                DecisionLevel.DETERMINISTIC,
                "RETRIEVE_EVIDENCE",
                risk,
                ("INSUFFICIENT_EVIDENCE",),
            )

        strong_reasons = set(risk.reason_codes) & {
            "CROSS_AUTHORITY_BOUNDARY",
            "HIGH_AUTHORITY_IMPACT",
            "HIGH_UNCERTAINTY",
            "MULTIPLE_CAPABILITY_CANDIDATES",
            "NO_DETERMINISTIC_VALIDATOR",
            "UNQUALIFIED_CAPABILITY",
            "NO_ELIGIBLE_CAPABILITY",
        }
        if strong_reasons or risk.risk_class is DecisionRiskClass.HIGH or not context.cheap_route_qualified:
            reasons = set(strong_reasons)
            if not context.cheap_route_qualified:
                reasons.add("CHEAP_ROUTE_NOT_QUALIFIED")
            return DecisionRoute(DecisionLevel.STRONG_MODEL, "STRONG_DECISION", risk, tuple(sorted(reasons)))

        if context.reversible and context.validator_available and context.cheap_route_qualified:
            return DecisionRoute(
                DecisionLevel.CHEAP_MODEL,
                "CHEAP_WITH_VALIDATOR",
                risk,
                ("BOUNDED_REVERSIBLE", "VALIDATOR_AVAILABLE", "CHEAP_ROUTE_QUALIFIED"),
            )
        return DecisionRoute(DecisionLevel.STRONG_MODEL, "STRONG_DECISION", risk, ("CHEAP_PRECONDITIONS_UNMET",))

    def route_after_validation(self, previous: DecisionRoute, outcome: ValidationOutcome) -> DecisionRoute:
        if outcome.status is ValidationStatus.PASS:
            return DecisionRoute(DecisionLevel.DETERMINISTIC, "ACCEPT_VALIDATED_RESULT", previous.risk, ("VALIDATOR_PASS",), previous.level)
        if outcome.status is ValidationStatus.EVIDENCE_MISSING:
            return DecisionRoute(DecisionLevel.DETERMINISTIC, "RETRIEVE_EVIDENCE", previous.risk, ("EVIDENCE_MISSING",), previous.level)
        if outcome.status is ValidationStatus.SCOPE_TOO_WIDE:
            return DecisionRoute(DecisionLevel.DETERMINISTIC, "CONSTRAIN_SCOPE", previous.risk, ("SCOPE_TOO_WIDE",), previous.level)
        if outcome.status is ValidationStatus.AMBIGUOUS:
            return DecisionRoute(DecisionLevel.STRONG_MODEL, "STRONG_DECISION", previous.risk, ("VALIDATOR_AMBIGUOUS",), previous.level)
        if outcome.status is ValidationStatus.NO_PROGRESS:
            if outcome.repeat_count >= 2:
                return DecisionRoute(DecisionLevel.STRONG_MODEL, "STRONG_DECISION", previous.risk, ("REPEATED_NO_PROGRESS", outcome.failure_fingerprint), previous.level)
            return DecisionRoute(DecisionLevel.CHEAP_MODEL, "CHEAP_BOUNDED_RETRY", previous.risk, ("FIRST_NO_PROGRESS", outcome.failure_fingerprint), previous.level)
        if outcome.status is ValidationStatus.INVALID:
            if previous.level is DecisionLevel.CHEAP_MODEL:
                return DecisionRoute(DecisionLevel.STRONG_MODEL, "STRONG_DECISION", previous.risk, ("CHEAP_RESULT_INVALID",), previous.level)
            return DecisionRoute(DecisionLevel.HUMAN_STOP, "STOP_INVALID_STRONG_RESULT", previous.risk, ("STRONG_RESULT_INVALID",), previous.level)
        raise ValueError(f"unsupported validation status: {outcome.status}")

