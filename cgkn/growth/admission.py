from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .candidate import CapabilityCandidate
from .sandbox import SandboxTrialResult


@dataclass(frozen=True)
class CapabilityAdmissionReceipt:
    candidate_id: str
    verdict: str
    checks: Mapping[str, bool]
    test_refs: tuple[str, ...]
    provenance: Mapping[str, Any]
    admitted_descriptor_ref: str | None
    reason: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, "verdict": self.verdict, "checks": dict(self.checks), "test_refs": list(self.test_refs), "provenance": dict(self.provenance), "admitted_descriptor_ref": self.admitted_descriptor_ref, "reason": self.reason, "created_at": self.created_at}


def evaluate_admission(candidate: CapabilityCandidate, trial: SandboxTrialResult) -> CapabilityAdmissionReceipt:
    descriptor = candidate.proposed_descriptor
    checks = dict(trial.checks)
    checks.update({
        "component_contract_declared": bool(descriptor.component_ref and descriptor.input_ports and descriptor.output_ports),
        "effects_match": tuple(descriptor.declared_effects) == tuple(candidate.declared_effects) == (),
        "provenance_complete": bool(candidate.provenance and descriptor.provenance),
        "low_risk": descriptor.risk_level.upper() == "LOW",
        "not_kernel_modification": trial.checks.get("kernel_files_unchanged") is True,
    })
    verdict = "ADMITTED" if trial.passed and all(checks.values()) else "REJECTED"
    return CapabilityAdmissionReceipt(candidate.candidate_id, verdict, checks, descriptor.test_refs, {**candidate.provenance, "module_identity": trial.module_identity}, descriptor.ref if verdict == "ADMITTED" else None, "all bounded local admission checks passed" if verdict == "ADMITTED" else "one or more admission checks failed")
