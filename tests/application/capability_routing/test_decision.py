from __future__ import annotations

import pytest

from cgkn.application.capability_routing import (
    DecisionContext,
    DecisionLevel,
    DecisionRiskClass,
    DecisionRouter,
    ValidationOutcome,
    ValidationStatus,
    assess_risk,
    policy_hashes,
)


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def test_deterministic_known_fact_never_calls_a_model() -> None:
    route = DecisionRouter().route(DecisionContext(
        "EXACT_CAPABILITY_IDENTITY", deterministic_rule_available=True, deterministic_evidence_valid=True
    ))
    assert route.level is DecisionLevel.DETERMINISTIC
    assert route.action == "APPLY_DETERMINISTIC_RULE"


def test_low_risk_reversible_validated_work_uses_qualified_cheap_route() -> None:
    route = DecisionRouter().route(DecisionContext(
        "FORMAT_PUBLIC_RESPONSE", uncertainty=0.2, reversible=True, validator_available=True, cheap_route_qualified=True
    ))
    assert route.level is DecisionLevel.CHEAP_MODEL
    assert "VALIDATOR_AVAILABLE" in route.reason_codes


@pytest.mark.parametrize(
    "context,reason",
    [
        (DecisionContext("semantic", candidate_count=3), "MULTIPLE_CAPABILITY_CANDIDATES"),
        (DecisionContext("semantic", uncertainty=0.9), "HIGH_UNCERTAINTY"),
        (DecisionContext("semantic", crosses_authority_boundary=True), "CROSS_AUTHORITY_BOUNDARY"),
        (DecisionContext("semantic", validator_available=False), "NO_DETERMINISTIC_VALIDATOR"),
        (DecisionContext("semantic", cheap_route_qualified=False), "CHEAP_ROUTE_NOT_QUALIFIED"),
        (DecisionContext("semantic", capability_qualified=False), "UNQUALIFIED_CAPABILITY"),
    ],
)
def test_strong_escalation_requires_auditable_risk_or_qualification_reason(context, reason) -> None:
    route = DecisionRouter().route(context)
    assert route.level is DecisionLevel.STRONG_MODEL
    assert reason in route.reason_codes


def test_missing_evidence_retrieves_before_model_escalation() -> None:
    route = DecisionRouter().route(DecisionContext("semantic", evidence_sufficient=False, uncertainty=0.8))
    assert route.level is DecisionLevel.DETERMINISTIC
    assert route.action == "RETRIEVE_EVIDENCE"


@pytest.mark.parametrize(
    "boundary",
    [
        "KERNEL_AUTHORITY_CHANGE",
        "PRODUCT_DIRECTION_CHANGE",
        "ACCEPTANCE_LOWERING",
        "SECURITY_BOUNDARY_LOWERING",
        "IRREVERSIBLE_MIGRATION",
        "PROVIDER_BUDGET_INCREASE",
        "HIGH_IMPACT_EXTERNAL_ACTION",
    ],
)
def test_critical_boundaries_stop_for_human(boundary) -> None:
    route = DecisionRouter().route(DecisionContext("critical", critical_boundaries=(boundary,)))
    assert route.level is DecisionLevel.HUMAN_STOP
    assert route.action == "STOP_FOR_HUMAN"


def test_unknown_critical_boundary_is_rejected_instead_of_becoming_policy() -> None:
    with pytest.raises(ValueError, match="unknown critical"):
        DecisionRouter().route(DecisionContext("critical", critical_boundaries=("MODEL_SAYS_CRITICAL",)))


def test_validator_drives_containment_and_escalation_without_blind_retries() -> None:
    router = DecisionRouter()
    cheap = router.route(DecisionContext("bounded semantic"))
    assert router.route_after_validation(cheap, ValidationOutcome(ValidationStatus.PASS)).action == "ACCEPT_VALIDATED_RESULT"
    assert router.route_after_validation(cheap, ValidationOutcome(ValidationStatus.EVIDENCE_MISSING)).action == "RETRIEVE_EVIDENCE"
    assert router.route_after_validation(cheap, ValidationOutcome(ValidationStatus.SCOPE_TOO_WIDE)).action == "CONSTRAIN_SCOPE"
    assert router.route_after_validation(cheap, ValidationOutcome(ValidationStatus.AMBIGUOUS)).level is DecisionLevel.STRONG_MODEL
    first = router.route_after_validation(cheap, ValidationOutcome(ValidationStatus.NO_PROGRESS, "same", 1))
    repeated = router.route_after_validation(cheap, ValidationOutcome(ValidationStatus.NO_PROGRESS, "same", 2))
    assert first.action == "CHEAP_BOUNDED_RETRY"
    assert repeated.level is DecisionLevel.STRONG_MODEL
    assert "REPEATED_NO_PROGRESS" in repeated.reason_codes


def test_invalid_strong_result_stops_instead_of_self_approving() -> None:
    router = DecisionRouter()
    strong = router.route(DecisionContext("semantic", uncertainty=0.8))
    stopped = router.route_after_validation(strong, ValidationOutcome(ValidationStatus.INVALID))
    assert stopped.level is DecisionLevel.HUMAN_STOP


def test_model_self_reported_confidence_is_not_an_input_or_authority() -> None:
    route = DecisionRouter().route(DecisionContext("semantic", uncertainty=0.8))
    document = route.as_dict()
    assert document["self_reported_confidence_authority"] is False
    with pytest.raises(TypeError):
        DecisionContext("semantic", model_confidence=1.0)  # type: ignore[call-arg]


def test_risk_and_policy_hashes_are_stable() -> None:
    first = assess_risk(DecisionContext("x", impact=DecisionRiskClass.MEDIUM))
    second = assess_risk(DecisionContext("x", impact=DecisionRiskClass.MEDIUM))
    assert first == second
    assert set(policy_hashes()) == {"decision_policy_hash", "escalation_policy_hash"}
    assert all(value.startswith("sha256:") for value in policy_hashes().values())

