from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .compiler import NormalizedRequirements
from .obligation import ObligationKind, ObligationSet


@dataclass(frozen=True)
class ObligationValidation:
    status: str
    errors: tuple[str, ...]
    mapped_public_acceptance: tuple[str, ...]
    unmapped_public_acceptance: tuple[str, ...]
    unverifiable_obligations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "errors": list(self.errors),
            "mapped_public_acceptance": list(self.mapped_public_acceptance),
            "unmapped_public_acceptance": list(self.unmapped_public_acceptance),
            "unverifiable_obligations": list(self.unverifiable_obligations),
        }


class ObligationCompletenessValidator:
    def validate(self, requirements: NormalizedRequirements, obligations: ObligationSet) -> ObligationValidation:
        known = {item.source_id for item in requirements.sources}
        mapped = {ref for item in obligations.obligations for ref in item.source_requirement_refs if ref in requirements.public_acceptance_refs}
        unmapped = sorted(set(requirements.public_acceptance_refs) - mapped)
        unverifiable = sorted(item.obligation_id for item in obligations.obligations if not item.verification_method)
        errors: list[str] = [f"unmapped_public_acceptance:{item}" for item in unmapped]
        errors.extend(f"unverifiable_obligation:{item}" for item in unverifiable)
        for item in obligations.obligations:
            unknown = set(item.source_requirement_refs) - known
            if unknown:
                errors.append(f"unknown_source_ref:{item.obligation_id}:{','.join(sorted(unknown))}")
            if item.kind is ObligationKind.ERROR_SEMANTICS and (not item.preconditions or not item.expected):
                errors.append(f"incomplete_error_semantics:{item.obligation_id}")
            if item.kind is ObligationKind.DEPENDENCY_POLICY and item.dependency_policy is None:
                errors.append(f"missing_dependency_policy:{item.obligation_id}")
            if item.kind in {ObligationKind.RUNTIME, ObligationKind.INTERFACE} and not item.expected:
                errors.append(f"unspecified_expected:{item.obligation_id}")
        return ObligationValidation(
            "COMPLETE" if not errors else "REQUIREMENT_INCOMPLETE", tuple(sorted(set(errors))),
            tuple(sorted(mapped)), tuple(unmapped), tuple(unverifiable),
        )
