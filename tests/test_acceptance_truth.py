from __future__ import annotations

from scripts.acceptance_truth import canonical_verdict, worst_status


def test_not_evaluated_cannot_be_overridden_by_external_pass() -> None:
    verdict = canonical_verdict(
        {
            "requirement": "PASS",
            "tasks": "PASS",
            "tests": "PASS",
            "review": "PASS",
            "ui_public_journey": "PASS",
            "screenshots": "PASS",
            "package": "PASS",
            "clean_start": "PASS",
            "skipped": "PASS",
            "provider": "PASS",
            "side_effects": "PASS",
            "secret_scan": "PASS",
            "telegram_isolation": "PASS",
            "generated_acceptance": "NOT_EVALUATED",
            "external_verdict": "PASS",
        }
    )

    assert verdict["overall_readiness"] == "NOT_EVALUATED"
    assert verdict["conflicts"] == [{"source": "external_verdict", "claimed": "PASS", "canonical": "NOT_EVALUATED"}]


def test_ready_with_warnings_and_skipped_propagate_limits() -> None:
    verdict = canonical_verdict(
        {
            "requirement": "PASS",
            "tasks": "PASS",
            "tests": "PASS",
            "review": "PASS",
            "ui_public_journey": "PASS",
            "screenshots": "PASS",
            "package": "PASS",
            "clean_start": "PASS",
            "skipped": "PASS_WITH_LIMITS",
            "provider": "PASS",
            "side_effects": "PASS",
            "secret_scan": "PASS",
            "telegram_isolation": "PASS",
            "package_manifest": {"status": "ready_with_warnings"},
        }
    )

    assert verdict["overall_readiness"] == "PASS_WITH_LIMITS"
    assert verdict["upstream_statuses"]["package"] == "PASS_WITH_LIMITS"


def test_gui_api_only_duplicate_screenshot_and_package_order_force_rework() -> None:
    verdict = canonical_verdict(
        {
            "requirement": "PASS",
            "tasks": "PASS",
            "tests": "PASS",
            "review": "PASS",
            "ui_public_journey": "PASS",
            "screenshots": "PASS",
            "package": "PASS",
            "clean_start": "PASS",
            "skipped": "PASS",
            "provider": "PASS",
            "side_effects": "PASS",
            "secret_scan": "PASS",
            "telegram_isolation": "PASS",
            "api_only_journey_for_gui": True,
            "duplicate_screenshot_count": 1,
            "package_after_acceptance": False,
        }
    )

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
    verdict = canonical_verdict(
        {
            "requirement": "PASS",
            "tasks": "PASS",
            "tests": "PASS",
            "review": "PASS",
            "ui_public_journey": "PASS",
            "screenshots": "PASS",
            "package": "PASS",
            "clean_start": "PASS",
            "skipped": "PASS",
            "provider": "PASS",
            "side_effects": "PASS",
            "secret_scan": "PASS",
            "telegram_isolation": "PASS",
            "candidate_consistency": "PASS",
            "evidence_provenance": "PASS",
            "browser_profile": "PASS",
            "delivery_profile": "PASS",
            "mixed_candidate_evidence": True,
            "claimed_evidence_used_for_pass": True,
        }
    )

    assert verdict["overall_readiness"] == "NEEDS_REWORK"
    assert verdict["upstream_statuses"]["candidate_consistency"] == "NEEDS_REWORK"
    assert verdict["upstream_statuses"]["evidence_provenance"] == "NEEDS_REWORK"
