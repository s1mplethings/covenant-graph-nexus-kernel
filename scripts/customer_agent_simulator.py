#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


CUSTOMER_PERSONA = {
    "role": "independent creator / small content team lead",
    "traits": [
        "non-engineer",
        "starts with vague requirements",
        "local-first and privacy-sensitive",
        "wants proof that AI claims are honest",
        "expects screenshots, a runnable package, and clear setup notes",
    ],
}

ORIGINAL_VAGUE_GOAL = (
    "I want a local-first media production and review workbench. It should help me import "
    "video, audio, or assets, organize material, find review-worthy moments, generate "
    "reviewable results, and export reports and a package. I may connect local AI later, "
    "but do not use cloud services or pretend AI is already real."
)

REQUIRED_JOURNEY_EVENTS = [
    "customer_initial_goal",
    "cgkn_requirement_discovery",
    "customer_answers_clarifying_questions",
    "cgkn_candidate_requirements",
    "customer_pushes_back_on_scope",
    "cgkn_selected_requirement",
    "cgkn_mvp_scope_and_non_goals",
    "customer_accepts_scope_with_condition",
    "cgkn_product_contract",
    "cgkn_implementation_generation",
    "cgkn_delivery_evidence",
    "customer_opens_readme",
    "customer_checks_screenshot",
    "customer_checks_zip",
    "customer_runs_or_reviews_smoke",
    "customer_inspects_artifacts",
    "customer_asks_is_this_real_ai",
    "cgkn_explains_degraded_capabilities",
    "customer_requests_rework",
    "cgkn_rework_iteration",
    "customer_retests",
    "customer_checks_commercial_readiness",
    "cgkn_commercial_gate_explanation",
    "customer_final_acceptance_or_rejection",
    "customer_satisfaction_score",
    "independent_gap_report",
]

CUSTOMER_CHALLENGES = [
    "This is not just a demo, right?",
    "Has it really been run locally?",
    "Which capabilities are real, and which are placeholder, fixture, or contract-only?",
    "Why can this not be called commercial ready yet?",
    "If I give this to my team, what is still missing?",
]

DEFAULT_REWORK_REQUEST = (
    "Please make the README and delivery notes clearer about degraded mode, the ASR evidence tier, "
    "what is inside the zip, and the exact command that was actually run."
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def entry(
    turn: int,
    actor: str,
    event: str,
    message: str,
    *,
    evidence_refs: list[str] | None = None,
    customer_satisfaction_delta: int = 0,
    known_gaps: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "turn": turn,
        "actor": actor,
        "event": event,
        "message": message,
        "evidence_refs": evidence_refs or [],
        "customer_satisfaction_delta": customer_satisfaction_delta,
        "known_gaps": known_gaps or [],
    }


def build_dialogue(trial_result: dict[str, Any], *, rework_request: str = DEFAULT_REWORK_REQUEST, rework_completed: bool = False) -> list[dict[str, Any]]:
    project = str(trial_result.get("generated_project_path", ""))
    run_dir = str(trial_result.get("run_dir", ""))
    selected = trial_result.get("selected_requirement", {})
    selected_name = str(selected.get("selected_requirement_name") or selected.get("name") or selected.get("selected_requirement_id") or "")
    known_gaps = [str(item) for item in trial_result.get("known_gaps", [])]
    screenshot = str(trial_result.get("artifact_integrity", {}).get("screenshot_path", ""))
    zip_path = str(trial_result.get("artifact_integrity", {}).get("zip_path", ""))
    commercial = trial_result.get("commercial_readiness", {})
    capability = trial_result.get("capability_manifest", {})

    rows = [
        ("customer", "customer_initial_goal", ORIGINAL_VAGUE_GOAL, [], 0, []),
        ("cgkn", "cgkn_requirement_discovery", "CGKN asks about local-first expectations, privacy, acceptable degraded AI behavior, install difficulty, visual proof, and report/export evidence.", [f"{run_dir}/requirement_decision/customer_goal_brief.md"], 4, []),
        ("customer", "customer_answers_clarifying_questions", "Keep it local, make it easy to run, do not depend on cloud AI, and show what evidence was actually produced.", [], 3, []),
        ("cgkn", "cgkn_candidate_requirements", "CGKN compares candidate requirements and explains why a local media operations workbench is the strongest MVP direction.", [f"{run_dir}/requirement_decision/candidate_requirements.json", f"{run_dir}/requirement_decision/requirement_scorecard.json"], 5, []),
        ("customer", "customer_pushes_back_on_scope", "I do not want a tiny clip demo, but I also do not want a fake full AI suite. Freeze a useful first version.", [], 1, []),
        ("cgkn", "cgkn_selected_requirement", f"CGKN selects `{selected_name}` and rejects less useful directions.", [f"{run_dir}/requirement_decision/selected_requirement.json", f"{run_dir}/requirement_decision/rejected_requirements.md"], 6, []),
        ("cgkn", "cgkn_mvp_scope_and_non_goals", "CGKN freezes MVP scope, non-goals, and acceptance criteria before implementation evidence is treated as success.", [f"{run_dir}/requirement_decision/mvp_scope.md", f"{run_dir}/requirement_decision/non_goals.md", f"{run_dir}/requirement_decision/acceptance_contract.json"], 5, []),
        ("customer", "customer_accepts_scope_with_condition", "I accept this scope if you are explicit about what is degraded and do not sell fixture ASR as production AI.", [], 3, []),
        ("cgkn", "cgkn_product_contract", "CGKN writes product brief, technical plan, interaction design, and acceptance matrix tied to the selected requirement.", [f"{project}/product_brief.md", f"{project}/technical_plan.md", f"{project}/interaction_design.md", f"{project}/acceptance_matrix.md"], 5, []),
        ("cgkn", "cgkn_implementation_generation", "CGKN generates a shared local pipeline with orchestrator, stages, CLI, GUI, stage artifacts, schemas, and upstream/downstream traceability.", [f"{project}/orchestrator.py", f"{project}/stages.py", f"{project}/cli.py", f"{project}/gui_app.py"], 6, []),
        ("cgkn", "cgkn_delivery_evidence", "CGKN produces README, TEST_REPORT, DELIVERY_NOTES, screenshot evidence, smoke logs, delivery manifest, capability manifest, and final zip.", [f"{project}/README.md", f"{project}/TEST_REPORT.md", f"{project}/DELIVERY_NOTES.md", screenshot, zip_path, f"{project}/delivery_manifest.json", f"{project}/capability_manifest.json"], 8, []),
        ("customer", "customer_opens_readme", "I opened the README to check the run command, package contents, and known limits.", [f"{project}/README.md"], 2, []),
        ("customer", "customer_checks_screenshot", CUSTOMER_CHALLENGES[0], [screenshot], 2 if screenshot else -8, [] if screenshot else ["screenshot_missing"]),
        ("customer", "customer_checks_zip", "I checked whether there is a real final_project_bundle.zip and not only internal reports.", [zip_path], 2 if zip_path else -8, [] if zip_path else ["zip_missing"]),
        ("customer", "customer_runs_or_reviews_smoke", CUSTOMER_CHALLENGES[1], [f"{project}/run_logs/delivery_smoke_command.log"], 4, []),
        ("customer", "customer_inspects_artifacts", "I inspected requirement decision docs, product contract docs, stage artifacts, capability manifest, and delivery manifest.", [f"{run_dir}/requirement_decision", f"{project}/stage_plan.json", f"{project}/delivery_manifest.json", f"{project}/capability_manifest.json"], 5, []),
        ("customer", "customer_challenge_capability_truth", CUSTOMER_CHALLENGES[2], [f"{project}/capability_manifest.json", f"{project}/TEST_REPORT.md"], 0, []),
        ("customer", "customer_asks_is_this_real_ai", "Is this real AI, or are transcription and ASR still degraded?", [f"{project}/capability_manifest.json"], 0, []),
        ("cgkn", "cgkn_explains_degraded_capabilities", f"CGKN states ASR status `{capability.get('asr_status')}`, evidence tier `{capability.get('asr_evidence_tier')}`, transcription `{capability.get('transcription_status')}`, and commercial_ready remains false.", [f"{project}/DELIVERY_NOTES.md", f"{project}/capability_manifest.json"], 5, []),
        ("customer", "customer_challenge_team_handoff", CUSTOMER_CHALLENGES[4], [f"{project}/DELIVERY_NOTES.md"], 0, known_gaps[:4]),
        ("customer", "customer_requests_rework", rework_request, [f"{project}/README.md", f"{project}/DELIVERY_NOTES.md"], -3, ["readme_degraded_mode_needs_customer_facing_clarity"]),
        ("cgkn", "cgkn_rework_iteration", "CGKN updates customer-facing README/DELIVERY_NOTES evidence and repackages through the local packager; the customer agent does not edit CGKN code or generated project files.", [f"{project}/README.md", f"{project}/DELIVERY_NOTES.md", f"{project}/final_project_bundle.zip"], 6 if rework_completed else -5, [] if rework_completed else ["rework_not_completed"]),
        ("customer", "customer_retests", "I retested by reviewing the updated README, delivery notes, manifest, smoke log, screenshot, and zip package.", [f"{project}/README.md", f"{project}/delivery_manifest.json", f"{project}/run_logs/delivery_smoke_command.log"], 5 if rework_completed else -4, []),
        ("customer", "customer_challenge_commercial_ready", CUSTOMER_CHALLENGES[3], [f"{project}/commercial_ready_report.json", f"{project}/production_asr_verification_report.json"], 0, []),
        ("customer", "customer_checks_commercial_readiness", "I need a direct answer: can I sell this or roll it out to my team as production software today?", [f"{project}/commercial_ready_report.json"], 0, []),
        ("cgkn", "cgkn_commercial_gate_explanation", f"CGKN reports `{commercial.get('status')}` and commercial_ready `{commercial.get('commercial_ready')}` because production ASR, reliability runs, human review, and release operations are not complete.", [f"{project}/commercial_ready_report.json", f"{project}/production_reliability_report.json"], 4, []),
        ("customer", "customer_final_acceptance_or_rejection", "I can accept the scoped local-first delivery only if the final score and evidence checks pass; that does not mean commercial readiness.", [], 0, []),
        ("auditor", "customer_satisfaction_score", "The independent scorecard computes the customer score from requirement, product, implementation, delivery, rework, degraded honesty, and commercial readiness separation.", [], 0, []),
        ("auditor", "independent_gap_report", "The independent gap report lists remaining gaps without letting the customer agent change code or fabricate artifacts.", [], 0, known_gaps[:8]),
    ]
    return [
        entry(index + 1, actor, event, message, evidence_refs=refs, customer_satisfaction_delta=delta, known_gaps=gaps)
        for index, (actor, event, message, refs, delta, gaps) in enumerate(rows)
    ]
