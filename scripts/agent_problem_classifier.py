#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


PROBLEM_TYPES = {
    "NO_ISSUE_DETECTED",
    "PROVIDER_QUOTA_OR_TRANSPORT",
    "LOCAL_MODEL_UNAVAILABLE",
    "FORMAL_MODEL_EVIDENCE_MISSING",
    "DIRECTOR_LOOP_NOT_USED",
    "AGENT_DECISION_LEDGER_MISSING",
    "FORMAL_GENERATION_NOT_MATERIALIZED",
    "CANDIDATE_NEEDS_REWORK",
    "FINAL_PROMOTION_FAILED",
    "DELIVERY_MANIFEST_MISSING",
    "FINAL_BUNDLE_MISSING",
    "SCREENSHOT_EVIDENCE_MISSING",
    "PUBLIC_DELIVERY_NOT_READY",
    "COMPLEXITY_INSUFFICIENT",
    "PRODUCT_ACCEPTANCE_FAILED",
    "PRODUCT_ACCEPTANCE_POLLUTION",
    "LOW_UX_SCORE",
    "COMMERCIAL_READINESS_BETA",
    "TEST_REGRESSION",
    "ARTIFACT_INTEGRITY_FAILED",
    "SECURITY_FAILED",
    "UNKNOWN",
}

INTERNAL_ACCEPTANCE_TERMS = {"commercial", "readiness", "commercial_readiness", "beta", "release_label"}


def _nested(state: dict[str, Any], key: str) -> dict[str, Any]:
    value = state.get(key)
    return value if isinstance(value, dict) else {}


def _status(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    return bool(value)


def _refs(*items: Any) -> list[str]:
    refs: list[str] = []
    for item in items:
        if isinstance(item, str) and item:
            refs.append(item)
        elif isinstance(item, list):
            refs.extend(str(value) for value in item if value)
    return refs


def _result(
    *,
    problem_type: str,
    confidence: float,
    evidence_refs: list[str],
    why: str,
    why_not: list[str],
    action: str,
    selected_tool: str,
    expected_outputs: list[str],
    rejected_tools: list[str] | None = None,
    status: str = "pass",
    remaining_blockers: list[str] | None = None,
    required_external_action: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "problem_type": problem_type,
        "confidence": confidence,
        "evidence_refs": evidence_refs,
        "why_this_problem": why,
        "why_not_other_problems": why_not,
        "recommended_action": action,
        "selected_tool": selected_tool,
        "rejected_tools": rejected_tools or [],
        "expected_outputs": expected_outputs,
        "remaining_blockers": remaining_blockers or [],
        "required_external_action": required_external_action,
    }


def _all_green(state: dict[str, Any]) -> bool:
    latest = _nested(state, "latest_report_status")
    agent = _nested(state, "agent_led")
    generation = _nested(state, "generation")
    delivery = _nested(state, "delivery")
    quality = _nested(state, "quality")
    tests = _nested(state, "tests")
    verify_ok = latest.get("agent_led_verify") == "pass" or _truthy(agent.get("director_loop_used"))
    benchmark_ok = latest.get("large_project_benchmark") == "pass" or quality.get("complexity_status") == "pass"
    tests_ok = tests.get("last_pytest_status") in {"pass", "missing", "", None}
    return (
        verify_ok
        and benchmark_ok
        and _truthy(agent.get("director_loop_used"))
        and _truthy(agent.get("decision_ledger_exists"))
        and _truthy(generation.get("formal_generation_materialized"))
        and _truthy(generation.get("writable_project_files_exist"))
        and _truthy(generation.get("final_project_exists"))
        and _truthy(delivery.get("delivery_manifest_exists"))
        and _truthy(delivery.get("final_bundle_exists"))
        and _truthy(delivery.get("screenshot_evidence_exists"))
        and delivery.get("public_gate_status") == "READY"
        and quality.get("complexity_status") in {"pass", "missing", "", None}
        and quality.get("product_acceptance_status") in {"pass", "missing", "", None}
        and quality.get("commercial_status") == "COMMERCIAL_READY"
        and not quality.get("remaining_blockers")
        and quality.get("artifact_integrity_status") not in {"fail", "failed"}
        and quality.get("security_status") not in {"fail", "failed"}
        and tests_ok
    )


def classify_problem(state: dict[str, Any]) -> dict[str, Any]:
    latest_reports = _nested(state, "latest_reports")
    agent = _nested(state, "agent_led")
    provider = _nested(state, "provider")
    generation = _nested(state, "generation")
    delivery = _nested(state, "delivery")
    quality = _nested(state, "quality")
    tests = _nested(state, "tests")
    ledgers = _nested(state, "ledgers")
    latest_status = _nested(state, "latest_report_status")
    evidence_base = _refs(latest_reports.get("agent_led_verify"), latest_reports.get("large_project_benchmark"))

    if tests.get("last_pytest_status") == "fail" or tests.get("failed_tests"):
        return _result(
            problem_type="TEST_REGRESSION",
            confidence=0.97,
            evidence_refs=_refs(tests.get("pytest_result"), tests.get("failed_tests")),
            why="The latest test observation has failed tests, so regression inspection takes priority over generation-chain changes.",
            why_not=["Provider and delivery state must not be changed before the failing tests are inspected."],
            action="Inspect the failing tests and rerun the smallest targeted set.",
            selected_tool="run_targeted_tests",
            expected_outputs=["pytest_result", "failed_test_summary"],
            rejected_tools=["repair_provider_fallback", "repair_product_acceptance", "repair_complexity_generation"],
        )

    if quality.get("artifact_integrity_status") in {"fail", "failed"}:
        return _result(
            problem_type="ARTIFACT_INTEGRITY_FAILED",
            confidence=0.9,
            evidence_refs=evidence_base,
            why="Artifact integrity status is failing.",
            why_not=["Do not patch commercial readiness while package integrity is failing."],
            action="Repair artifact integrity.",
            selected_tool="repair_delivery_evidence",
            expected_outputs=["artifact_integrity_report"],
        )

    if quality.get("security_status") in {"fail", "failed"}:
        return _result(
            problem_type="SECURITY_FAILED",
            confidence=0.9,
            evidence_refs=evidence_base,
            why="Security status is failing.",
            why_not=["Security failures are not generation quota or UX failures."],
            action="Inspect and repair security findings.",
            selected_tool="inspect_latest_reports",
            expected_outputs=["security_report"],
        )

    if _all_green(state):
        return _result(
            problem_type="NO_ISSUE_DETECTED",
            confidence=0.93,
            evidence_refs=_refs(evidence_base, ledgers.get("agent_decision_ledger"), delivery.get("delivery_manifest")),
            why="The latest agent-led verify and large-project benchmark are passing with final artifacts, public delivery evidence, decision ledger, and commercial readiness present.",
            why_not=[
                "Provider quota is mitigated by local formal generation fallback when final artifacts are materialized.",
                "Older closure beta reports are not treated as current failures when newer agent-led verify and benchmark reports pass.",
            ],
            action="Record the diagnosis and avoid modifying already passing modules.",
            selected_tool="stability_rerun",
            expected_outputs=["diagnosis_report"],
        )

    if provider.get("provider_quota_exceeded") or provider.get("provider_error_type") in {"PROVIDER_QUOTA_EXCEEDED", "PROVIDER_TRANSPORT_ERROR"}:
        if provider.get("local_model_available"):
            return _result(
                problem_type="PROVIDER_QUOTA_OR_TRANSPORT",
                confidence=0.95,
                evidence_refs=evidence_base,
                why="The API provider reports quota or transport failure, and local model fallback is available.",
                why_not=["This is not product acceptance, UX, or package integrity because the evidence is provider transport status."],
                action="Run agent-led verify or formal_generation with local_only provider strategy.",
                selected_tool="run_agent_led_verify",
                expected_outputs=["agent_led_verify_report", "agent_decision_ledger"],
                rejected_tools=["repair_product_acceptance", "repair_complexity_generation"],
            )
        return _result(
            problem_type="PROVIDER_QUOTA_OR_TRANSPORT",
            confidence=0.98,
            evidence_refs=evidence_base,
            why="The API provider is quota/transport blocked and no local formal model is available.",
            why_not=["No local repair can honestly materialize formal generation without either provider capacity or a local model."],
            action="Wait for provider quota or enable a local model before formal generation.",
            selected_tool="BLOCKED",
            expected_outputs=[],
            rejected_tools=["final_promotion", "repair_product_acceptance", "repair_complexity_generation"],
            status="blocked",
            remaining_blockers=["WAITING_FOR_PROVIDER_QUOTA_AND_LOCAL_MODEL_UNAVAILABLE"],
            required_external_action="Restore provider quota or configure a local model.",
        )

    if provider.get("local_model_available") is False and latest_status.get("agent_led_verify") != "pass":
        return _result(
            problem_type="LOCAL_MODEL_UNAVAILABLE",
            confidence=0.82,
            evidence_refs=evidence_base,
            why="Local model is unavailable while current verify evidence is not passing.",
            why_not=["No product repair is justified before a formal generation provider is available."],
            action="Configure local model availability or use API provider when quota is restored.",
            selected_tool="BLOCKED",
            expected_outputs=[],
            status="blocked",
            remaining_blockers=["LOCAL_MODEL_UNAVAILABLE"],
            required_external_action="Start or configure local_model_router.",
        )

    if not agent.get("director_loop_used"):
        return _result(
            problem_type="DIRECTOR_LOOP_NOT_USED",
            confidence=0.94,
            evidence_refs=evidence_base,
            why="Latest verify evidence does not show the agent director loop as the entrypoint.",
            why_not=["Delivery or product fixes should not be attempted until the architecture entrypoint is correct."],
            action="Run agent-led verify or repair the verify entrypoint.",
            selected_tool="repair_verify_entry",
            expected_outputs=["agent_led_verify_report"],
            rejected_tools=["formal_live_delivery_closure"],
        )

    if not agent.get("decision_ledger_exists"):
        return _result(
            problem_type="AGENT_DECISION_LEDGER_MISSING",
            confidence=0.96,
            evidence_refs=evidence_base,
            why="Agent-led verification cannot be accepted without an agent decision ledger.",
            why_not=["A passing final artifact alone is not enough evidence that agent-led control was used."],
            action="Inspect or regenerate the decision ledger through the agent-led entrypoint.",
            selected_tool="inspect_decision_ledger",
            expected_outputs=["agent_decision_ledger"],
            rejected_tools=["commercial_readiness"],
        )

    if quality.get("model_participation_status") == "fail":
        return _result(
            problem_type="FORMAL_MODEL_EVIDENCE_MISSING",
            confidence=0.9,
            evidence_refs=_refs(ledgers.get("model_call_ledger"), evidence_base),
            why="Formal model participation evidence is missing or failing.",
            why_not=["Promotion and commercial readiness cannot repair missing formal model evidence."],
            action="Inspect model_call_ledger and rerun formal generation with model evidence.",
            selected_tool="inspect_model_ledger",
            expected_outputs=["model_call_ledger_summary"],
            rejected_tools=["commercial_readiness", "final_promotion"],
        )

    if not generation.get("formal_generation_materialized") or not generation.get("writable_project_files_exist"):
        return _result(
            problem_type="FORMAL_GENERATION_NOT_MATERIALIZED",
            confidence=0.95,
            evidence_refs=evidence_base,
            why="No writable candidate project files were materialized.",
            why_not=["Final promotion, packaging, screenshot, and commercial readiness are not allowed before formal generation materializes files."],
            action="Run formal generation through the agent director.",
            selected_tool="run_agent_led_verify",
            expected_outputs=["candidate_project_dir", "model_call_ledger"],
            rejected_tools=["final_promotion", "commercial_readiness"],
        )

    if generation.get("semantic_review_status") == "needs_rework":
        return _result(
            problem_type="CANDIDATE_NEEDS_REWORK",
            confidence=0.93,
            evidence_refs=evidence_base,
            why="The materialized candidate exists but semantic review requires rework.",
            why_not=["Promotion is explicitly rejected while semantic review is not passing."],
            action="Repair the candidate before promotion.",
            selected_tool="repair_candidate",
            expected_outputs=["repair_report", "updated_candidate_project_dir"],
            rejected_tools=["final_promotion"],
        )

    if generation.get("final_promotion_status") == "fail":
        return _result(
            problem_type="FINAL_PROMOTION_FAILED",
            confidence=0.88,
            evidence_refs=evidence_base,
            why="Final promotion is explicitly recorded as failed.",
            why_not=["Generation already materialized, so the next layer is promotion repair."],
            action="Repair final promotion.",
            selected_tool="repair_final_promotion",
            expected_outputs=["final_project_dir", "final_project_manifest"],
        )

    if generation.get("final_project_exists") and not delivery.get("delivery_manifest_exists"):
        return _result(
            problem_type="DELIVERY_MANIFEST_MISSING",
            confidence=0.94,
            evidence_refs=evidence_base,
            why="Final project exists but delivery_manifest.json is missing.",
            why_not=["Commercial readiness cannot be forced without delivery manifest evidence."],
            action="Repair delivery evidence through local_packager/final promotion.",
            selected_tool="repair_delivery_evidence",
            expected_outputs=["delivery_manifest"],
            rejected_tools=["commercial_readiness"],
        )

    if generation.get("final_project_exists") and not delivery.get("final_bundle_exists"):
        return _result(
            problem_type="FINAL_BUNDLE_MISSING",
            confidence=0.94,
            evidence_refs=evidence_base,
            why="Final project exists but final_project_bundle.zip is missing.",
            why_not=["This is a delivery artifact issue, not product acceptance or provider fallback."],
            action="Repair delivery packaging.",
            selected_tool="repair_delivery_evidence",
            expected_outputs=["final_project_bundle"],
            rejected_tools=["commercial_readiness"],
        )

    if generation.get("final_project_exists") and not delivery.get("screenshot_evidence_exists"):
        return _result(
            problem_type="SCREENSHOT_EVIDENCE_MISSING",
            confidence=0.92,
            evidence_refs=evidence_base,
            why="Final project exists but screenshot evidence is missing.",
            why_not=["Commercial readiness should not be upgraded without visual evidence."],
            action="Capture or repair screenshot evidence.",
            selected_tool="repair_delivery_evidence",
            expected_outputs=["screenshot_evidence"],
            rejected_tools=["commercial_readiness"],
        )

    if delivery.get("delivery_manifest_exists") and delivery.get("final_bundle_exists") and delivery.get("public_gate_status") not in {"READY", "missing", ""}:
        return _result(
            problem_type="PUBLIC_DELIVERY_NOT_READY",
            confidence=0.91,
            evidence_refs=evidence_base,
            why="Delivery artifacts exist but the public delivery gate is not ready.",
            why_not=["This should be fixed at the evidence/gate layer, not by loosening commercial readiness."],
            action="Repair public delivery evidence.",
            selected_tool="repair_delivery_evidence",
            expected_outputs=["public_delivery_gate_report"],
            rejected_tools=["commercial_readiness"],
        )

    if quality.get("complexity_status") not in {"pass", "missing", "", None}:
        return _result(
            problem_type="COMPLEXITY_INSUFFICIENT",
            confidence=0.92,
            evidence_refs=_refs(latest_reports.get("large_project_benchmark")),
            why="Complexity audit is not passing.",
            why_not=["The audit should not be weakened; generation or feature expansion must satisfy it."],
            action="Repair complexity generation.",
            selected_tool="repair_complexity_generation",
            expected_outputs=["expanded_project", "complexity_audit_report"],
            rejected_tools=["commercial_readiness"],
        )

    missing_features = quality.get("missing_core_features") or []
    if isinstance(missing_features, list) and INTERNAL_ACCEPTANCE_TERMS.intersection({str(item).strip().lower() for item in missing_features}):
        return _result(
            problem_type="PRODUCT_ACCEPTANCE_POLLUTION",
            confidence=0.93,
            evidence_refs=_refs(latest_reports.get("product_acceptance"), latest_reports.get("large_project_benchmark")),
            why="Product acceptance missing features include internal release-readiness terms.",
            why_not=["The project should not implement commercial/readiness as user-facing product features."],
            action="Repair product acceptance feature-source filtering.",
            selected_tool="repair_product_acceptance",
            expected_outputs=["product_acceptance_report"],
            rejected_tools=["repair_generation", "repair_provider_fallback"],
        )

    if quality.get("product_acceptance_status") not in {"pass", "missing", "", None}:
        return _result(
            problem_type="PRODUCT_ACCEPTANCE_FAILED",
            confidence=0.88,
            evidence_refs=_refs(latest_reports.get("product_acceptance"), latest_reports.get("large_project_benchmark")),
            why="Product acceptance status is not passing.",
            why_not=["Provider fallback and packaging should not be changed unless their evidence is failing."],
            action="Inspect product acceptance report and repair the relevant product layer.",
            selected_tool="repair_product_acceptance",
            expected_outputs=["product_acceptance_report"],
        )

    if isinstance(quality.get("ux_score"), (int, float)) and quality.get("ux_score") < 70:
        return _result(
            problem_type="LOW_UX_SCORE",
            confidence=0.85,
            evidence_refs=_refs(latest_reports.get("product_acceptance")),
            why="UX score is below release threshold.",
            why_not=["This is not a provider quota or package integrity root cause."],
            action="Repair user-facing UX issues.",
            selected_tool="repair_candidate",
            expected_outputs=["updated_candidate_project_dir", "product_acceptance_report"],
        )

    if quality.get("commercial_status") in {"COMMERCIAL_BETA", "COMMERCIAL_BLOCKED", "COMMERCIAL_FAIL"}:
        return _result(
            problem_type="COMMERCIAL_READINESS_BETA",
            confidence=0.82,
            evidence_refs=_refs(latest_reports.get("commercial_readiness"), latest_reports.get("agent_led_verify")),
            why="Commercial readiness is not ready after lower-level evidence checks.",
            why_not=["This is only evaluated after artifact, complexity, and product acceptance checks."],
            action="Inspect commercial readiness beta reasons.",
            selected_tool="run_agent_led_verify",
            expected_outputs=["commercial_readiness_report"],
        )

    return _result(
        problem_type="UNKNOWN",
        confidence=0.35,
        evidence_refs=evidence_base,
        why="The available evidence does not match a known diagnosis class.",
        why_not=["No targeted repair is justified without stronger evidence."],
        action="Inspect latest reports and ledgers manually.",
        selected_tool="inspect_latest_reports",
        expected_outputs=["diagnosis_report"],
        status="blocked",
        remaining_blockers=["UNKNOWN_DIAGNOSIS"],
    )
