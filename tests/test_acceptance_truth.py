from __future__ import annotations

from scripts.acceptance_truth import REQUIRED_GATES, canonical_verdict, worst_status


def _all_pass() -> dict[str, str]:
    return {gate: "PASS" for gate in REQUIRED_GATES}


def test_not_evaluated_cannot_be_overridden_by_external_pass() -> None:
    inputs = _all_pass()
    inputs.update({"generated_acceptance": "NOT_EVALUATED", "external_verdict": "PASS"})
    verdict = canonical_verdict(inputs)

    assert verdict["overall_readiness"] == "NEEDS_REWORK"
    assert verdict["conflicts"] == [{"source": "external_verdict", "claimed": "PASS", "canonical": "NEEDS_REWORK"}]


def test_ready_with_warnings_and_skipped_propagate_limits() -> None:
    inputs = _all_pass()
    inputs.update({"test_profiles": "PASS_WITH_LIMITS", "package_manifest": {"status": "ready_with_warnings"}})
    verdict = canonical_verdict(inputs)

    assert verdict["overall_readiness"] == "PASS_WITH_LIMITS"
    assert verdict["upstream_statuses"]["package"] == "PASS_WITH_LIMITS"


def test_gui_api_only_duplicate_screenshot_and_package_order_force_rework() -> None:
    inputs = _all_pass()
    inputs.update({"api_only_journey_for_gui": True, "duplicate_screenshot_count": 1, "package_after_acceptance": False})
    verdict = canonical_verdict(inputs)

    assert verdict["overall_readiness"] == "NEEDS_REWORK"
    assert verdict["upstream_statuses"]["ui_public_journey"] == "NEEDS_REWORK"
    assert verdict["upstream_statuses"]["screenshots"] == "NEEDS_REWORK"
    assert verdict["upstream_statuses"]["package"] == "NEEDS_REWORK"


def test_status_priority_order() -> None:
    assert worst_status(["PASS", "PASS_WITH_LIMITS"]) == "PASS_WITH_LIMITS"
    assert worst_status(["PASS_WITH_LIMITS", "NOT_EVALUATED"]) == "NOT_EVALUATED"
    assert worst_status(["BLOCKED", "NEEDS_REWORK"]) == "NEEDS_REWORK"
    assert worst_status(["NEEDS_REWORK", "FAIL"]) == "FAIL"


def test_candidate_and_provenance_failures_propagate_to_canonical_verdict() -> None:
    inputs = _all_pass()
    inputs.update(
        {
            "candidate_consistency": "PASS",
            "evidence_provenance": "PASS",
            "browser_profile": "PASS",
            "delivery_profile": "PASS",
            "mixed_candidate_evidence": True,
            "claimed_evidence_used_for_pass": True,
        }
    )
    verdict = canonical_verdict(inputs)

    assert verdict["overall_readiness"] == "NEEDS_REWORK"
    assert verdict["upstream_statuses"]["candidate_consistency"] == "NEEDS_REWORK"
    assert verdict["upstream_statuses"]["evidence_provenance"] == "NEEDS_REWORK"
