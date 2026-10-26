from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


SCHEMA_VERSION = "1.0"
_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")


def _freeze(value: Any) -> Any:
    if isinstance(value, FrozenMapping):
        return value
    if isinstance(value, Mapping):
        return FrozenMapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"semantic values must be JSON-compatible, got {type(value).__name__}")


def thaw(value: Any) -> Any:
    if isinstance(value, FrozenMapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


class FrozenMapping(Mapping[str, Any]):
    """Small recursively immutable and hashable JSON object."""

    __slots__ = ("_items", "_lookup")

    def __init__(self, value: Mapping[str, Any] | None = None):
        items = tuple(sorted((str(key), _freeze(item)) for key, item in (value or {}).items()))
        self._items = items
        self._lookup = dict(items)

    def __getitem__(self, key: str) -> Any:
        return self._lookup[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._lookup)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return hash(self._items)

    def __repr__(self) -> str:
        return f"FrozenMapping({dict(self._items)!r})"


def canonical_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(thaw(FrozenMapping(value)), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class ObligationKind(str, Enum):
    BEHAVIOR = "BEHAVIOR"
    ERROR_SEMANTICS = "ERROR_SEMANTICS"
    INTERFACE = "INTERFACE"
    DEPENDENCY_POLICY = "DEPENDENCY_POLICY"
    STATE_TRANSITION = "STATE_TRANSITION"
    PERSISTENCE = "PERSISTENCE"
    SECURITY = "SECURITY"
    RUNTIME = "RUNTIME"
    DOCUMENTATION = "DOCUMENTATION"
    TESTABILITY = "TESTABILITY"
    RESOURCE_BOUNDARY = "RESOURCE_BOUNDARY"


class RequirementSourceType(str, Enum):
    USER_EXPLICIT = "USER_EXPLICIT"
    PRODUCT_DEFAULT = "PRODUCT_DEFAULT"
    PLATFORM_POLICY = "PLATFORM_POLICY"
    DERIVED = "DERIVED"
    HARNESS_INTERNAL = "HARNESS_INTERNAL"


class RequirementExplicitness(str, Enum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    INTERNAL = "INTERNAL"


@dataclass(frozen=True)
class RequirementSource:
    source_id: str
    raw_text: str
    source_type: RequirementSourceType
    priority: int = 100
    scope: tuple[str, ...] = ("project",)
    explicitness: RequirementExplicitness = RequirementExplicitness.EXPLICIT
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", tuple(str(item) for item in self.scope))
        if not _ID.fullmatch(self.source_id):
            raise ValueError("requirement source_id must be a stable uppercase identifier")
        if not self.raw_text.strip() or not self.scope or self.priority < 0:
            raise ValueError("requirement source requires text, scope, and non-negative priority")
        if self.source_type is RequirementSourceType.HARNESS_INTERNAL and self.explicitness is not RequirementExplicitness.INTERNAL:
            raise ValueError("HARNESS_INTERNAL sources must be INTERNAL")

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "raw_text": self.raw_text,
            "source_type": self.source_type.value,
            "priority": self.priority,
            "scope": list(self.scope),
            "explicitness": self.explicitness.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequirementSource":
        return cls(
            source_id=str(value["source_id"]), raw_text=str(value["raw_text"]),
            source_type=RequirementSourceType(str(value["source_type"])),
            priority=int(value.get("priority", 100)), scope=tuple(value.get("scope", ("project",))),
            explicitness=RequirementExplicitness(str(value.get("explicitness", "EXPLICIT"))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(frozen=True)
class Obligation:
    obligation_id: str
    kind: ObligationKind
    subject: str
    source_requirement_refs: tuple[str, ...]
    preconditions: FrozenMapping = field(default_factory=FrozenMapping)
    operation: FrozenMapping = field(default_factory=FrozenMapping)
    expected: FrozenMapping = field(default_factory=FrozenMapping)
    forbidden: FrozenMapping = field(default_factory=FrozenMapping)
    side_effects: FrozenMapping = field(default_factory=FrozenMapping)
    dependency_policy: Any = None
    severity: str = "MUST"
    verification_method: tuple[str, ...] = ()
    scope: tuple[str, ...] = ("project",)
    provenance: FrozenMapping = field(default_factory=FrozenMapping)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        from .policy import DependencyPolicy

        object.__setattr__(self, "source_requirement_refs", tuple(str(item) for item in self.source_requirement_refs))
        object.__setattr__(self, "verification_method", tuple(str(item) for item in self.verification_method))
        object.__setattr__(self, "scope", tuple(str(item) for item in self.scope))
        for name in ("preconditions", "operation", "expected", "forbidden", "side_effects", "provenance"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        if not _ID.fullmatch(self.obligation_id):
            raise ValueError("obligation_id must be a stable uppercase identifier")
        if not self.subject.strip() or not self.source_requirement_refs:
            raise ValueError("obligation requires subject and source requirement refs")
        if self.severity not in {"MUST", "SHOULD", "MAY"}:
            raise ValueError("invalid obligation severity")
        if self.dependency_policy is not None and not isinstance(self.dependency_policy, DependencyPolicy):
            raise TypeError("dependency_policy must be DependencyPolicy")

    def as_dict(self) -> dict[str, Any]:
        value = {
            "obligation_id": self.obligation_id, "kind": self.kind.value, "subject": self.subject,
            "source_requirement_refs": list(self.source_requirement_refs), "preconditions": thaw(self.preconditions),
            "operation": thaw(self.operation), "expected": thaw(self.expected), "forbidden": thaw(self.forbidden),
            "side_effects": thaw(self.side_effects),
            "dependency_policy": self.dependency_policy.as_dict() if self.dependency_policy else None,
            "severity": self.severity, "verification_method": list(self.verification_method),
            "scope": list(self.scope), "provenance": thaw(self.provenance), "schema_version": self.schema_version,
        }
        return value | {"obligation_hash": canonical_hash(value)}

    @property
    def obligation_hash(self) -> str:
        return self.as_dict()["obligation_hash"]

    def __hash__(self) -> int:
        return hash(self.obligation_hash)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Obligation":
        from .policy import DependencyPolicy

        policy = value.get("dependency_policy")
        result = cls(
            obligation_id=str(value["obligation_id"]), kind=ObligationKind(str(value["kind"])),
            subject=str(value["subject"]), source_requirement_refs=tuple(value.get("source_requirement_refs", ())),
            preconditions=FrozenMapping(value.get("preconditions", {})), operation=FrozenMapping(value.get("operation", {})),
            expected=FrozenMapping(value.get("expected", {})), forbidden=FrozenMapping(value.get("forbidden", {})),
            side_effects=FrozenMapping(value.get("side_effects", {})),
            dependency_policy=DependencyPolicy.from_dict(policy) if isinstance(policy, Mapping) else None,
            severity=str(value.get("severity", "MUST")), verification_method=tuple(value.get("verification_method", ())),
            scope=tuple(value.get("scope", ("project",))), provenance=FrozenMapping(value.get("provenance", {})),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )
        supplied = value.get("obligation_hash")
        if supplied is not None and supplied != result.obligation_hash:
            raise ValueError("obligation hash mismatch")
        return result


@dataclass(frozen=True)
class ObligationSet:
    obligations: tuple[Obligation, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.obligations, key=lambda item: item.obligation_id))
        if len({item.obligation_id for item in ordered}) != len(ordered):
            raise ValueError("duplicate obligation_id")
        object.__setattr__(self, "obligations", ordered)

    def as_dict(self) -> dict[str, Any]:
        value = {"schema_version": self.schema_version, "obligations": [item.as_dict() for item in self.obligations]}
        return value | {"obligation_set_hash": canonical_hash(value)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObligationSet":
        result = cls(tuple(Obligation.from_dict(item) for item in value.get("obligations", ())), str(value.get("schema_version", SCHEMA_VERSION)))
        supplied = value.get("obligation_set_hash")
        if supplied is not None and supplied != result.as_dict()["obligation_set_hash"]:
            raise ValueError("obligation set hash mismatch")
        return result
