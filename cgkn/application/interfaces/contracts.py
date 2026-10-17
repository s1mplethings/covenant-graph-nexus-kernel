from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from cgkn.application.requirements.obligation import FrozenMapping, canonical_hash, thaw


SCHEMA_VERSION = "1.0"
_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")


class InterfaceKind(str, Enum):
    PYTHON_FUNCTION = "PYTHON_FUNCTION"
    PYTHON_MODULE = "PYTHON_MODULE"
    CLI = "CLI"


def _mapping(value: Mapping[str, Any] | FrozenMapping | None) -> FrozenMapping:
    return value if isinstance(value, FrozenMapping) else FrozenMapping(value or {})


@dataclass(frozen=True)
class ExecutableInterfaceContract:
    contract_id: str
    interface_kind: InterfaceKind
    subject_ref: str
    source_obligation_ids: tuple[str, ...]
    required: FrozenMapping
    optional: FrozenMapping = field(default_factory=FrozenMapping)
    forbidden: FrozenMapping = field(default_factory=FrozenMapping)
    compatibility_policy: FrozenMapping = field(default_factory=FrozenMapping)
    scope: tuple[str, ...] = ("project",)
    provenance: FrozenMapping = field(default_factory=FrozenMapping)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.contract_id):
            raise ValueError("contract_id must be a stable uppercase identifier")
        ids = tuple(sorted(str(item) for item in self.source_obligation_ids))
        if not ids or len(ids) != len(set(ids)) or any(not _ID.fullmatch(item) for item in ids):
            raise ValueError("source_obligation_ids must be unique stable identifiers")
        object.__setattr__(self, "source_obligation_ids", ids)
        object.__setattr__(self, "scope", tuple(str(item) for item in self.scope))
        for name in ("required", "optional", "forbidden", "compatibility_policy", "provenance"):
            object.__setattr__(self, name, _mapping(getattr(self, name)))
        if not self.subject_ref.strip() or not self.required or not self.scope:
            raise ValueError("interface contract requires subject_ref, required facts, and scope")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported interface contract schema_version")

    def as_dict(self) -> dict[str, Any]:
        value = {
            "contract_id": self.contract_id,
            "interface_kind": self.interface_kind.value,
            "subject_ref": self.subject_ref,
            "source_obligation_ids": list(self.source_obligation_ids),
            "required": thaw(self.required),
            "optional": thaw(self.optional),
            "forbidden": thaw(self.forbidden),
            "compatibility_policy": thaw(self.compatibility_policy),
            "scope": list(self.scope),
            "schema_version": self.schema_version,
            "provenance": thaw(self.provenance),
        }
        return value | {"contract_hash": canonical_hash(value)}

    @property
    def contract_hash(self) -> str:
        return self.as_dict()["contract_hash"]

    def __hash__(self) -> int:
        return hash(self.contract_hash)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutableInterfaceContract":
        result = cls(
            contract_id=str(value["contract_id"]),
            interface_kind=InterfaceKind(str(value["interface_kind"])),
            subject_ref=str(value["subject_ref"]),
            source_obligation_ids=tuple(value.get("source_obligation_ids", ())),
            required=_mapping(value.get("required")),
            optional=_mapping(value.get("optional")),
            forbidden=_mapping(value.get("forbidden")),
            compatibility_policy=_mapping(value.get("compatibility_policy")),
            scope=tuple(value.get("scope", ("project",))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            provenance=_mapping(value.get("provenance")),
        )
        supplied = value.get("contract_hash")
        if supplied is not None and supplied != result.contract_hash:
            raise ValueError("interface contract hash mismatch")
        return result


@dataclass(frozen=True)
class ExecutableInterfaceContractSet:
    contracts: tuple[ExecutableInterfaceContract, ...]
    source_obligation_set_hash: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        contracts = tuple(sorted(self.contracts, key=lambda item: item.contract_id))
        if not contracts or len({item.contract_id for item in contracts}) != len(contracts):
            raise ValueError("interface contract set requires unique contracts")
        if not self.source_obligation_set_hash.startswith("sha256:"):
            raise ValueError("interface contract set requires source obligation hash")
        object.__setattr__(self, "contracts", contracts)

    def as_dict(self) -> dict[str, Any]:
        value = {
            "contracts": [item.as_dict() for item in self.contracts],
            "source_obligation_set_hash": self.source_obligation_set_hash,
            "schema_version": self.schema_version,
        }
        return value | {"interface_contract_set_hash": canonical_hash(value)}

    @property
    def interface_contract_set_hash(self) -> str:
        return self.as_dict()["interface_contract_set_hash"]

    def by_id(self, contract_id: str) -> ExecutableInterfaceContract:
        return next(item for item in self.contracts if item.contract_id == contract_id)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutableInterfaceContractSet":
        result = cls(
            tuple(ExecutableInterfaceContract.from_dict(item) for item in value.get("contracts", ())),
            str(value["source_obligation_set_hash"]),
            str(value.get("schema_version", SCHEMA_VERSION)),
        )
        supplied = value.get("interface_contract_set_hash")
        if supplied is not None and supplied != result.interface_contract_set_hash:
            raise ValueError("interface contract set hash mismatch")
        return result
