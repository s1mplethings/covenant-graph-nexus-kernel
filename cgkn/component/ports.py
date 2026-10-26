from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "artifactType": self.artifact_type,
            "required": self.required,
            "multi": self.multi,
            "projection": list(self.projection),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PortSpec":
        allowed = {"name", "artifactType", "required", "multi", "projection"}
        if set(value) - allowed:
            raise ValueError("unknown PortSpec fields")
        return cls(
            name=str(value["name"]),
            artifact_type=str(value["artifactType"]),
            required=bool(value.get("required", True)),
            multi=bool(value.get("multi", False)),
            projection=tuple(str(item) for item in value.get("projection", ())),
        )
