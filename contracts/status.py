from __future__ import annotations

from enum import StrEnum


class EvidenceStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_LIMITS = "PASS_WITH_LIMITS"
    NOT_EVALUATED = "NOT_EVALUATED"
    BLOCKED = "BLOCKED"
    BLOCKED_PROVIDER = "BLOCKED_PROVIDER"
    BLOCKED_LOCAL_MODEL = "BLOCKED_LOCAL_MODEL"
    BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
    NEEDS_REWORK = "NEEDS_REWORK"
    FAIL = "FAIL"


class WorkflowState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    WAITING_USER_REVIEW = "waiting_user_review"
    PACKAGING = "packaging"
    DELIVERY_SENDING = "delivery_sending"
    DELIVERY_SEND_FAILED = "delivery_send_failed"
    REWORK_BLOCKED = "rework_blocked"
    FINAL_DELIVERED = "final_delivered"


EVIDENCE_STATUSES = tuple(status.value for status in EvidenceStatus)
WORKFLOW_STATES = tuple(state.value for state in WorkflowState)


def is_evidence_status(value: object) -> bool:
    return str(value) in EVIDENCE_STATUSES


def is_workflow_state(value: object) -> bool:
    return str(value) in WORKFLOW_STATES
