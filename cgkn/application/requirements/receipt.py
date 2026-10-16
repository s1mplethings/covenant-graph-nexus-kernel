from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .compiler import NormalizedRequirements
from .obligation import ObligationSet, canonical_hash
from .traceability import TraceabilityResult
from .validator import ObligationValidation


@dataclass(frozen=True)
class ObligationPreflightReceipt:
    validation: ObligationValidation
    traceability: TraceabilityResult
    requirements_total: int
    obligations_total: int

    def as_dict(self) -> dict[str, Any]:
        value = {
            "kind": "CGKNObligationPreflightReceipt", "schema_version": "1.0",
            "status": "COMPLETE" if self.validation.status == "COMPLETE" and self.traceability.status == "PASS" else self.traceability.status if self.traceability.status == "HARNESS_CONTRACT_GAP" else "REQUIREMENT_INCOMPLETE",
            "requirements_total": self.requirements_total, "obligations_total": self.obligations_total,
            "validation": self.validation.as_dict(), "traceability": self.traceability.as_dict(),
        }
        return value | {"receipt_hash": canonical_hash(value)}

    @classmethod
    def build(cls, requirements: NormalizedRequirements, obligations: ObligationSet, validation: ObligationValidation, traceability: TraceabilityResult) -> "ObligationPreflightReceipt":
        return cls(validation, traceability, len(requirements.sources), len(obligations.obligations))
