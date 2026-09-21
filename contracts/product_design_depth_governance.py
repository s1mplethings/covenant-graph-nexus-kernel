from __future__ import annotations


SCHEMA_VERSION = "1.0"
SCHEMA_FILE = "product_design_depth_governance_v1.schema.json"
PRODUCER = "scripts.product_design_depth_governance"

COMPLEXITY_LEVELS = ("SIMPLE", "STANDARD", "COMPLEX", "HIGH_RISK")
DESIGN_REVIEW_VERDICTS = (
    "DESIGN_READY",
    "DESIGN_READY_WITH_DECLARED_PROXY",
    "REPLAN_CORE_CAPABILITY",
    "BLOCKED_MISSING_EVIDENCE",
)
MATURITY_LEVELS = (
    "DEMO",
    "PROTOTYPE",
    "FUNCTIONAL_MVP",
    "TARGET_VALIDATED",
    "PRODUCTION_READY",
)
MATURITY_VERDICTS = (
    "DEMO_PASS",
    "PROTOTYPE_PASS",
    "FUNCTIONAL_MVP_PASS",
    "TARGET_VALIDATED_PASS",
    "PRODUCTION_READY_PASS",
)

PREIMPLEMENTATION_ARTIFACTS = (
    "goal_fidelity_contract.json",
    "project_complexity_profile.json",
    "core_difficulty_lock.json",
    "test_realism_contract.json",
    "challenge_matrix.json",
    "design_adequacy_report.json",
    "product_challenge_review.json",
    "overengineering_check_report.json",
)

POSTBUILD_ARTIFACTS = (
    "proxy_solution_report.json",
    "product_maturity_report.json",
    "public_claim_policy_report.json",
    "design_replan_report.json",
)
