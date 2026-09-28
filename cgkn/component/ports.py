from __future__ import annotations

import re
from dataclasses import dataclass


_ARTIFACT_REF = re.compile(r"^artifact\.[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class PortSpec:
    """Immutable declaration of one typed component boundary."""

    name: str
    artifact_type: str
    required: bool = True
    multi: bool = False
    projection: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("port name is required")
        if not _ARTIFACT_REF.fullmatch(self.artifact_type):
            raise ValueError("artifact_type must be a versioned artifact ref")
        object.__setattr__(self, "projection", tuple(str(item) for item in self.projection))
