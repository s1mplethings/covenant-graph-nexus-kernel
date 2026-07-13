from __future__ import annotations

from contracts.status import EvidenceStatus


LEGACY_TO_CANONICAL = {
    "PARTIAL": EvidenceStatus.PASS_WITH_LIMITS.value,
    "READY": EvidenceStatus.PASS.value,
    "REWORK": EvidenceStatus.NEEDS_REWORK.value,
    "SKIPPED_WITH_REASON": EvidenceStatus.NOT_EVALUATED.value,
    "ready": EvidenceStatus.PASS.value,
    "ready_with_warnings": EvidenceStatus.PASS_WITH_LIMITS.value,
    "PASS_FINAL": EvidenceStatus.PASS.value,
    "DELIVER_WITH_WARNINGS": EvidenceStatus.PASS_WITH_LIMITS.value,
    "ASK_USER_REVIEW": EvidenceStatus.NOT_EVALUATED.value,
    "FACT_BLOCKED": EvidenceStatus.BLOCKED.value,
}


def canonicalize_legacy_status(status: str) -> str:
    return LEGACY_TO_CANONICAL.get(str(status), str(status))
