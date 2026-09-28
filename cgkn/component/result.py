from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from cgkn.artifacts.models import ArtifactRef


@dataclass(frozen=True)
class ComponentResult:
    """Execution output before canonical ArtifactInstance materialization."""

    output_contents: Mapping[str, dict[str, Any]] = field(default_factory=dict)
    output_refs: tuple[ArtifactRef, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_contents", MappingProxyType(dict(self.output_contents)))
        object.__setattr__(self, "output_refs", tuple(self.output_refs))
        object.__setattr__(self, "diagnostics", tuple(dict(item) for item in self.diagnostics))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
