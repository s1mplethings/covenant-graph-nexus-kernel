from __future__ import annotations

from dataclasses import dataclass

from .lifecycle_contracts import ActionDecision, BuildLifecycleState, FailureDomain, RecommendedAction


@dataclass(frozen=True)
class CapabilityBuildActionPolicy:
    """The sole authority that may authorize candidate repair."""

    version: str = "1.0"
    allow_safe_policy_repair: bool = False

    def decide(
        self,
        failure_domain: FailureDomain | None,
        *,
        candidate_exists: bool,
        repair_budget: int = 0,
        provider_operation: str = "GENERATION",
    ) -> ActionDecision:
        if failure_domain is None:
            return ActionDecision(RecommendedAction.ADMIT_CANDIDATE, BuildLifecycleState.ADMISSION_PENDING, "all required local validation passed")
        if failure_domain is FailureDomain.CANDIDATE_DEFECT:
            if candidate_exists and repair_budget > 0:
                return ActionDecision(RecommendedAction.REPAIR_CANDIDATE, BuildLifecycleState.REPAIR_REQUIRED, "candidate-local defect with explicit repair budget")
            return ActionDecision(RecommendedAction.REJECT_CANDIDATE, BuildLifecycleState.REJECTED, "candidate defect cannot be repaired within policy")
        if failure_domain is FailureDomain.CANDIDATE_POLICY_DEFECT:
            if self.allow_safe_policy_repair and candidate_exists and repair_budget > 0:
                return ActionDecision(RecommendedAction.REPAIR_CANDIDATE, BuildLifecycleState.REPAIR_REQUIRED, "explicit safe policy repair")
            return ActionDecision(RecommendedAction.REJECT_CANDIDATE, BuildLifecycleState.REJECTED, "candidate violates policy")
        if failure_domain in {FailureDomain.FRAMEWORK_VALIDATOR_DEFECT, FailureDomain.FRAMEWORK_HARNESS_DEFECT}:
            return ActionDecision(RecommendedAction.REVALIDATE_EXISTING, BuildLifecycleState.BLOCKED_FRAMEWORK, "framework evidence invalidates validation, not candidate")
        if failure_domain in {FailureDomain.PROVIDER_TRANSPORT_FAILURE, FailureDomain.PROVIDER_TIMEOUT, FailureDomain.PROVIDER_SCHEMA_FAILURE}:
            if candidate_exists and provider_operation == "REPAIR":
                return ActionDecision(RecommendedAction.RETRY_TRANSPORT, BuildLifecycleState.PROVIDER_BLOCKED, "repair transport failed; preserve parent revision")
            return ActionDecision(RecommendedAction.RETRY_GENERATION, BuildLifecycleState.PROVIDER_BLOCKED, "provider did not create a candidate revision")
        if failure_domain is FailureDomain.EXTERNAL_DEPENDENCY_FAILURE:
            return ActionDecision(RecommendedAction.WAIT_EXTERNAL, BuildLifecycleState.BLOCKED_EXTERNAL, "external availability is separate from local candidate validity")
        if failure_domain is FailureDomain.ENVIRONMENT_BLOCKED:
            return ActionDecision(RecommendedAction.BLOCK_ENVIRONMENT, BuildLifecycleState.BLOCKED_ENVIRONMENT, "required local environment is unavailable")
        if failure_domain is FailureDomain.DEPENDENCY_DRIFT:
            return ActionDecision(RecommendedAction.REVALIDATE_DEPENDENCY, BuildLifecycleState.REVALIDATION_REQUIRED, "dependency evidence changed")
        if failure_domain in {FailureDomain.CONTRACT_GAP, FailureDomain.UNKNOWN_FAILURE}:
            return ActionDecision(RecommendedAction.ESCALATE_REVIEW, BuildLifecycleState.NEEDS_REVIEW, "failure is not safe for automatic repair")
        return ActionDecision(RecommendedAction.ESCALATE_REVIEW, BuildLifecycleState.NEEDS_REVIEW, "unmapped failure fails closed")
