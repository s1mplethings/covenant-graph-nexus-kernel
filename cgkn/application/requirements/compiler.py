from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .obligation import Obligation, ObligationKind, ObligationSet, RequirementSource, RequirementSourceType, canonical_hash


@dataclass(frozen=True)
class NormalizedRequirements:
    sources: tuple[RequirementSource, ...]
    public_acceptance_refs: tuple[str, ...]
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.sources, key=lambda item: (item.priority, item.source_id)))
        if len({item.source_id for item in ordered}) != len(ordered):
            raise ValueError("duplicate requirement source_id")
        unknown = set(self.public_acceptance_refs) - {item.source_id for item in ordered}
        if unknown:
            raise ValueError(f"unknown public acceptance refs: {sorted(unknown)}")
        object.__setattr__(self, "sources", ordered)
        object.__setattr__(self, "public_acceptance_refs", tuple(sorted(set(self.public_acceptance_refs))))

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "sources": [item.as_dict() for item in self.sources], "public_acceptance_refs": list(self.public_acceptance_refs)}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


class RequirementCompiler:
    """Deterministic authority boundary; Agent proposals remain source-bound specs."""

    def normalize(self, sources: Iterable[RequirementSource], public_acceptance_refs: Iterable[str]) -> NormalizedRequirements:
        normalized = tuple(
            RequirementSource(item.source_id, normalize_text(item.raw_text), item.source_type, item.priority, item.scope, item.explicitness, item.schema_version)
            for item in sources
        )
        return NormalizedRequirements(normalized, tuple(public_acceptance_refs))

    def compile(self, requirements: NormalizedRequirements, specs: Iterable[Mapping[str, Any]]) -> ObligationSet:
        known = {item.source_id: item for item in requirements.sources}
        obligations: list[Obligation] = []
        for spec in specs:
            refs = tuple(str(item) for item in spec.get("source_requirement_refs", ()))
            if not refs or set(refs) - set(known):
                raise ValueError("compiled obligation has missing or unknown source refs")
            if any(known[ref].source_type is RequirementSourceType.HARNESS_INTERNAL for ref in refs):
                raise ValueError("HARNESS_INTERNAL cannot produce a project obligation")
            if any(known[ref].source_type is RequirementSourceType.DERIVED for ref in refs) and not any(
                known[ref].source_type not in {RequirementSourceType.DERIVED, RequirementSourceType.HARNESS_INTERNAL}
                for ref in refs
            ):
                raise ValueError("derived obligations must retain a non-derived source ref")
            kind = ObligationKind(str(spec["kind"]))
            identifier = str(spec.get("obligation_id", "")).strip()
            if not identifier:
                identity = canonical_hash({"kind": kind.value, "subject": normalize_text(str(spec["subject"])), "source_requirement_refs": sorted(refs)})
                identifier = f"OBL-{kind.value.replace('_', '-')}-{identity[-12:].upper()}"
            obligations.append(Obligation.from_dict({**dict(spec), "obligation_id": identifier, "kind": kind.value, "subject": normalize_text(str(spec["subject"])), "source_requirement_refs": refs}))
        return ObligationSet(tuple(obligations))
