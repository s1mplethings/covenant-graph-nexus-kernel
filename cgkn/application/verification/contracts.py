from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Mapping

from cgkn.application.requirements.obligation import FrozenMapping, canonical_hash, thaw


SCHEMA_VERSION = "1.0"
_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")


class OracleKind(str, Enum):
    COMMAND = "COMMAND"
    FILE = "FILE"
    CSV = "CSV"
    CLI = "CLI"
    DEPENDENCY = "DEPENDENCY"
    STATIC_PYTHON = "STATIC_PYTHON"
    DOCUMENTATION = "DOCUMENTATION"


class OracleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
    HARNESS_FAILURE = "HARNESS_FAILURE"


def _mapping(value: Mapping[str, Any] | FrozenMapping | None) -> FrozenMapping:
    return value if isinstance(value, FrozenMapping) else FrozenMapping(value or {})


def _ids(values: tuple[str, ...] | list[str], *, name: str, required: bool = True) -> tuple[str, ...]:
    result = tuple(sorted(str(item) for item in values))
    if required and not result:
        raise ValueError(f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate {name}")
    if any(not _ID.fullmatch(item) for item in result):
        raise ValueError(f"invalid {name}")
    return result


@dataclass(frozen=True)
class OracleSpec:
    oracle_id: str
    obligation_ids: tuple[str, ...]
    oracle_kind: OracleKind
    subject_ref: str
    setup: FrozenMapping = field(default_factory=FrozenMapping)
    operation: FrozenMapping = field(default_factory=FrozenMapping)
    expected: FrozenMapping = field(default_factory=FrozenMapping)
    forbidden: FrozenMapping = field(default_factory=FrozenMapping)
    side_effect_assertions: FrozenMapping = field(default_factory=FrozenMapping)
    dependency_policy_refs: tuple[str, ...] = ()
    timeout_seconds: float = 10.0
    scope: tuple[str, ...] = ("project",)
    provenance: FrozenMapping = field(default_factory=FrozenMapping)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.oracle_id):
            raise ValueError("oracle_id must be a stable uppercase identifier")
        object.__setattr__(self, "obligation_ids", _ids(self.obligation_ids, name="obligation_ids"))
        object.__setattr__(self, "dependency_policy_refs", _ids(self.dependency_policy_refs, name="dependency_policy_refs", required=False))
        object.__setattr__(self, "scope", tuple(str(item) for item in self.scope))
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))
        for name in ("setup", "operation", "expected", "forbidden", "side_effect_assertions", "provenance"):
            object.__setattr__(self, name, _mapping(getattr(self, name)))
        if not self.subject_ref.strip() or not self.scope:
            raise ValueError("OracleSpec requires subject_ref and scope")
        if not self.expected:
            raise ValueError("OracleSpec expected must not be empty")
        if not 0 < float(self.timeout_seconds) <= 300:
            raise ValueError("OracleSpec timeout_seconds must be within (0, 300]")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported OracleSpec schema_version")

    def as_dict(self) -> dict[str, Any]:
        value = {
            "oracle_id": self.oracle_id,
            "obligation_ids": list(self.obligation_ids),
            "oracle_kind": self.oracle_kind.value,
            "subject_ref": self.subject_ref,
            "setup": thaw(self.setup),
            "operation": thaw(self.operation),
            "expected": thaw(self.expected),
            "forbidden": thaw(self.forbidden),
            "side_effect_assertions": thaw(self.side_effect_assertions),
            "dependency_policy_refs": list(self.dependency_policy_refs),
            "timeout_seconds": self.timeout_seconds,
            "scope": list(self.scope),
            "provenance": thaw(self.provenance),
            "schema_version": self.schema_version,
        }
        return value | {"oracle_hash": canonical_hash(value)}

    @property
    def oracle_hash(self) -> str:
        return self.as_dict()["oracle_hash"]

    def __hash__(self) -> int:
        return hash(self.oracle_hash)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OracleSpec":
        result = cls(
            oracle_id=str(value["oracle_id"]),
            obligation_ids=tuple(value.get("obligation_ids", ())),
            oracle_kind=OracleKind(str(value["oracle_kind"])),
            subject_ref=str(value["subject_ref"]),
            setup=_mapping(value.get("setup")),
            operation=_mapping(value.get("operation")),
            expected=_mapping(value.get("expected")),
            forbidden=_mapping(value.get("forbidden")),
            side_effect_assertions=_mapping(value.get("side_effect_assertions")),
            dependency_policy_refs=tuple(value.get("dependency_policy_refs", ())),
            timeout_seconds=float(value.get("timeout_seconds", 10.0)),
            scope=tuple(value.get("scope", ("project",))),
            provenance=_mapping(value.get("provenance")),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )
        supplied = value.get("oracle_hash")
        if supplied is not None and supplied != result.oracle_hash:
            raise ValueError("OracleSpec hash mismatch")
        return result


@dataclass(frozen=True)
class OraclePlan:
    plan_id: str
    source_obligation_ids: tuple[str, ...]
    obligation_set_hash: str
    specs: tuple[OracleSpec, ...]
    required_oracle_ids: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.plan_id):
            raise ValueError("plan_id must be a stable uppercase identifier")
        source_ids = _ids(self.source_obligation_ids, name="source_obligation_ids")
        specs = tuple(sorted(self.specs, key=lambda item: item.oracle_id))
        if len({item.oracle_id for item in specs}) != len(specs):
            raise ValueError("duplicate oracle_id")
        dangling = sorted({item for spec in specs for item in spec.obligation_ids} - set(source_ids))
        if dangling:
            raise ValueError("unknown obligation references: " + ",".join(dangling))
        required = _ids(self.required_oracle_ids or tuple(item.oracle_id for item in specs), name="required_oracle_ids", required=False)
        unknown_required = sorted(set(required) - {item.oracle_id for item in specs})
        if unknown_required:
            raise ValueError("dangling required oracle references: " + ",".join(unknown_required))
        if not self.obligation_set_hash.startswith("sha256:"):
            raise ValueError("OraclePlan requires obligation_set_hash")
        object.__setattr__(self, "source_obligation_ids", source_ids)
        object.__setattr__(self, "specs", specs)
        object.__setattr__(self, "required_oracle_ids", required)

    def as_dict(self) -> dict[str, Any]:
        value = {
            "plan_id": self.plan_id,
            "source_obligation_ids": list(self.source_obligation_ids),
            "obligation_set_hash": self.obligation_set_hash,
            "specs": [item.as_dict() for item in self.specs],
            "required_oracle_ids": list(self.required_oracle_ids),
            "schema_version": self.schema_version,
        }
        return value | {"plan_hash": canonical_hash(value)}

    @property
    def plan_hash(self) -> str:
        return self.as_dict()["plan_hash"]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OraclePlan":
        result = cls(
            plan_id=str(value["plan_id"]),
            source_obligation_ids=tuple(value.get("source_obligation_ids", ())),
            obligation_set_hash=str(value["obligation_set_hash"]),
            specs=tuple(OracleSpec.from_dict(item) for item in value.get("specs", ())),
            required_oracle_ids=tuple(value.get("required_oracle_ids", ())),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )
        supplied = value.get("plan_hash")
        if supplied is not None and supplied != result.plan_hash:
            raise ValueError("OraclePlan hash mismatch")
        return result


@dataclass(frozen=True)
class OracleEvidence:
    evidence_id: str
    oracle_id: str
    obligation_ids: tuple[str, ...]
    status: OracleStatus
    expected: FrozenMapping
    observed: FrozenMapping
    return_code: int | None = None
    stdout_summary: str = ""
    stderr_summary: str = ""
    artifacts: tuple[FrozenMapping, ...] = ()
    duration_ms: int = 0
    failure_class: str | None = None
    owner_hint: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.evidence_id) or not _ID.fullmatch(self.oracle_id):
            raise ValueError("evidence_id and oracle_id must be stable uppercase identifiers")
        object.__setattr__(self, "obligation_ids", _ids(self.obligation_ids, name="obligation_ids"))
        object.__setattr__(self, "expected", _mapping(self.expected))
        object.__setattr__(self, "observed", _mapping(self.observed))
        object.__setattr__(self, "artifacts", tuple(_mapping(item) for item in self.artifacts))
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        if self.status is OracleStatus.PASS and self.failure_class is not None:
            raise ValueError("PASS evidence cannot have a failure_class")

    def as_dict(self) -> dict[str, Any]:
        value = {
            "evidence_id": self.evidence_id,
            "oracle_id": self.oracle_id,
            "obligation_ids": list(self.obligation_ids),
            "status": self.status.value,
            "expected": thaw(self.expected),
            "observed": thaw(self.observed),
            "return_code": self.return_code,
            "stdout_summary": self.stdout_summary,
            "stderr_summary": self.stderr_summary,
            "artifacts": [thaw(item) for item in self.artifacts],
            "duration_ms": self.duration_ms,
            "failure_class": self.failure_class,
            "owner_hint": self.owner_hint,
            "schema_version": self.schema_version,
        }
        return value | {"evidence_hash": canonical_hash(value)}

    @property
    def evidence_hash(self) -> str:
        return self.as_dict()["evidence_hash"]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OracleEvidence":
        result = cls(
            evidence_id=str(value["evidence_id"]), oracle_id=str(value["oracle_id"]),
            obligation_ids=tuple(value.get("obligation_ids", ())), status=OracleStatus(str(value["status"])),
            expected=_mapping(value.get("expected")), observed=_mapping(value.get("observed")),
            return_code=value.get("return_code"), stdout_summary=str(value.get("stdout_summary", "")),
            stderr_summary=str(value.get("stderr_summary", "")),
            artifacts=tuple(_mapping(item) for item in value.get("artifacts", ())),
            duration_ms=int(value.get("duration_ms", 0)), failure_class=value.get("failure_class"),
            owner_hint=value.get("owner_hint"), schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )
        supplied = value.get("evidence_hash")
        if supplied is not None and supplied != result.evidence_hash:
            raise ValueError("OracleEvidence hash mismatch")
        return result
