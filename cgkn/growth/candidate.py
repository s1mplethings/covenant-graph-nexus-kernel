from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.capabilities import CapabilityDescriptor


@dataclass(frozen=True)
class CapabilityCandidate:
    candidate_id: str
    proposed_descriptor: CapabilityDescriptor
    implementation_kind: str
    source: str
    identity: str
    version: str
    required_environment: Mapping[str, Any]
    declared_effects: tuple[str, ...]
    generated_adapter_path: str
    trial_plan: tuple[str, ...]
    provenance: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "proposed_descriptor": self.proposed_descriptor.as_dict(),
            "implementation_kind": self.implementation_kind,
            "source": self.source,
            "identity": self.identity,
            "version": self.version,
            "required_environment": dict(self.required_environment),
            "declared_effects": list(self.declared_effects),
            "generated_adapter_path": self.generated_adapter_path,
            "trial_plan": list(self.trial_plan),
            "provenance": dict(self.provenance),
        }
