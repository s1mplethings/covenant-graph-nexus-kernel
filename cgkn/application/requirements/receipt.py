from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
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
    ambiguous_behaviors: tuple[str, ...] = ()
    dependency_policies: tuple[dict[str, Any], ...] = ()
    error_semantics: tuple[dict[str, Any], ...] = ()
    hidden_coverage: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        value = {
            "kind": "CGKNObligationPreflightReceipt", "schema_version": "1.0",
            "status": "COMPLETE" if self.validation.status == "COMPLETE" and self.traceability.status == "PASS" else self.traceability.status if self.traceability.status == "HARNESS_CONTRACT_GAP" else "REQUIREMENT_INCOMPLETE",
            "requirements_total": self.requirements_total, "obligations_total": self.obligations_total,
            "unmapped_requirements": list(self.validation.unmapped_public_acceptance),
            "unverifiable_obligations": list(self.validation.unverifiable_obligations),
            "ambiguous_behaviors": list(self.ambiguous_behaviors),
            "dependency_policies": list(self.dependency_policies),
            "error_semantics": list(self.error_semantics),
            "hidden_coverage": self.hidden_coverage or {
                "coverage": self.traceability.hidden_acceptance_coverage,
                "status": self.traceability.status,
            },
            "validation": self.validation.as_dict(), "traceability": self.traceability.as_dict(),
        }
        return value | {"receipt_hash": canonical_hash(value)}

    @classmethod
    def build(
        cls,
        requirements: NormalizedRequirements,
        obligations: ObligationSet,
        validation: ObligationValidation,
        traceability: TraceabilityResult,
        *,
        ambiguous_behaviors: tuple[str, ...] = (),
        hidden_coverage: dict[str, Any] | None = None,
    ) -> "ObligationPreflightReceipt":
        policies = {item.dependency_policy.policy_id: item.dependency_policy.as_dict() for item in obligations.obligations if item.dependency_policy}
        errors = tuple(
            {
                "obligation_id": item.obligation_id,
                "preconditions": dict(item.preconditions),
                "expected": dict(item.expected),
                "forbidden": dict(item.forbidden),
            }
            for item in obligations.obligations
            if item.kind.value == "ERROR_SEMANTICS"
        )
        return cls(
            validation,
            traceability,
            len(requirements.sources),
            len(obligations.obligations),
            tuple(ambiguous_behaviors),
            tuple(policies[key] for key in sorted(policies)),
            errors,
            hidden_coverage,
        )


def write_obligation_preflight(path: str | Path, receipt: ObligationPreflightReceipt) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
