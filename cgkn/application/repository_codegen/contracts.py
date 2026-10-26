from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ChangeKind(str, Enum):
    BUG_FIX = "BUG_FIX"
    FEATURE = "FEATURE"
    REFACTOR = "REFACTOR"
    INTEGRATION = "INTEGRATION"


@dataclass(frozen=True)
class RepositorySnapshot:
    repository_id: str
    source_hash: str
    files: Mapping[str, str]
    language_summary: Mapping[str, int]
    entrypoints: tuple[str, ...]
    test_roots: tuple[str, ...]
    public_interfaces: Mapping[str, tuple[str, ...]]
    dependency_manifest: tuple[str, ...]
    module_graph: Mapping[str, tuple[str, ...]]
    protected_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))
        object.__setattr__(self, "language_summary", MappingProxyType(dict(self.language_summary)))
        object.__setattr__(self, "public_interfaces", MappingProxyType(dict(self.public_interfaces)))
        object.__setattr__(self, "module_graph", MappingProxyType(dict(self.module_graph)))


@dataclass(frozen=True)
class ChangeRequest:
    change_id: str
    goal: str
    change_kind: ChangeKind
    requirements: tuple[str, ...]
    preserved_behavior: tuple[str, ...]
    forbidden_changes: tuple[str, ...]
    acceptance: tuple[str, ...]
    scope_hint: tuple[str, ...]


@dataclass(frozen=True)
class ImpactSet:
    affected_modules: tuple[str, ...]
    affected_tests: tuple[str, ...]
    reason: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class ChangeContract:
    change_id: str
    affected_modules: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    read_paths: tuple[str, ...]
    required_interfaces: Mapping[str, tuple[str, ...]]
    preserved_interfaces: Mapping[str, tuple[str, ...]]
    forbidden_paths: tuple[str, ...]
    obligation_refs: tuple[str, ...]
    test_requirements: tuple[str, ...]
    dependency_policy: str
    risk: str


@dataclass(frozen=True)
class RepositoryCodegenReceipt:
    change_id: str
    change_kind: str
    provider_id: str
    mode: str
    routing_frozen: bool
    fallback: str
    calls: int
    repairs: int
    modified_files: tuple[str, ...]
    unrelated_edits: tuple[str, ...]
    interface_breaks: tuple[str, ...]
    tests_passed: bool
    status: str
    wall_time_ms: int
    usage: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "RepositoryCodegenReceipt", "schema_version": "1.0", **self.__dict__, "modified_files": list(self.modified_files), "unrelated_edits": list(self.unrelated_edits), "interface_breaks": list(self.interface_breaks), "usage": dict(self.usage), "contains_credentials": False}

