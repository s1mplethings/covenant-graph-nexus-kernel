from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class BundleKind(str, Enum):
    DOMAIN = "DOMAIN"
    CLI = "CLI"
    DOMAIN_STORE = "DOMAIN_STORE"
    LIBRARY_API = "LIBRARY_API"


@dataclass(frozen=True)
class BundleInterfaceContract:
    module: str
    exports: tuple[str, ...]
    signatures: Mapping[str, str]
    controlled_errors: tuple[str, ...]
    entrypoint: str = ""
    commands: tuple[str, ...] = ()
    stdout_contract: str = ""
    stderr_contract: str = "errors use stderr and a non-zero exit code"
    help_contract: Mapping[str, Any] | None = None
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["signatures"] = dict(sorted(self.signatures.items()))
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BundleInterfaceContract":
        return cls(
            str(value["module"]), tuple(value.get("exports", ())), dict(value.get("signatures", {})),
            tuple(value.get("controlled_errors", ())), str(value.get("entrypoint", "")),
            tuple(value.get("commands", ())), str(value.get("stdout_contract", "")),
            str(value.get("stderr_contract", "errors use stderr and a non-zero exit code")),
            dict(value["help_contract"]) if value.get("help_contract") is not None else None,
            str(value.get("schema_version", "1.0")),
        )

    @property
    def interface_hash(self) -> str:
        return canonical_hash(self.as_dict())


@dataclass(frozen=True)
class BundleSpec:
    bundle_id: str
    bundle_kind: BundleKind
    goal: str
    target_paths: tuple[str, ...]
    depends_on: tuple[str, ...]
    required_interfaces: tuple[str, ...]
    provided_interfaces: tuple[str, ...]
    consumed_interfaces: tuple[str, ...]
    obligation_refs: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    lesson_query: Mapping[str, Any]
    max_output_tokens: int
    max_output_bytes: int
    timeout_seconds: int
    reasoning_effort: str
    interface_contract: BundleInterfaceContract
    bundle_hash: str = ""
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.bundle_id or not self.target_paths:
            raise ValueError("bundle identity and target paths are required")
        if len(self.target_paths) > 3:
            raise ValueError("BUNDLE_SIZE_FILE_LIMIT")
        if self.max_output_tokens < 1 or self.max_output_bytes < 1 or self.timeout_seconds < 1:
            raise ValueError("bundle provider limits must be positive")
        value = self.as_dict(include_hash=False)
        expected = canonical_hash(value)
        if self.bundle_hash and self.bundle_hash != expected:
            raise ValueError("bundle hash mismatch")
        object.__setattr__(self, "bundle_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "bundle_id": self.bundle_id, "bundle_kind": self.bundle_kind.value, "goal": self.goal,
            "target_paths": list(self.target_paths), "depends_on": list(self.depends_on),
            "required_interfaces": list(self.required_interfaces), "provided_interfaces": list(self.provided_interfaces),
            "consumed_interfaces": list(self.consumed_interfaces), "obligation_refs": list(self.obligation_refs),
            "allowed_actions": list(self.allowed_actions), "forbidden_actions": list(self.forbidden_actions),
            "lesson_query": dict(self.lesson_query), "max_output_tokens": self.max_output_tokens,
            "max_output_bytes": self.max_output_bytes, "timeout_seconds": self.timeout_seconds,
            "reasoning_effort": self.reasoning_effort, "interface_contract": self.interface_contract.as_dict(),
            "schema_version": self.schema_version,
        }
        if include_hash:
            value["bundle_hash"] = self.bundle_hash
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BundleSpec":
        return cls(
            str(value["bundle_id"]), BundleKind(str(value["bundle_kind"])), str(value["goal"]),
            tuple(value.get("target_paths", ())), tuple(value.get("depends_on", ())),
            tuple(value.get("required_interfaces", ())), tuple(value.get("provided_interfaces", ())),
            tuple(value.get("consumed_interfaces", ())), tuple(value.get("obligation_refs", ())),
            tuple(value.get("allowed_actions", ())), tuple(value.get("forbidden_actions", ())),
            dict(value.get("lesson_query", {})), int(value["max_output_tokens"]), int(value["max_output_bytes"]),
            int(value["timeout_seconds"]), str(value["reasoning_effort"]),
            BundleInterfaceContract.from_dict(value["interface_contract"]), str(value.get("bundle_hash", "")),
            str(value.get("schema_version", "1.0")),
        )


@dataclass(frozen=True)
class GenerationManifest:
    project_id: str
    project_type: str
    package_name: str
    project_contract_hash: str
    obligation_hash: str
    interface_contract_hash: str
    bundle_specs: tuple[BundleSpec, ...]
    bundle_graph: Mapping[str, tuple[str, ...]]
    deterministic_assets: tuple[str, ...]
    provider_policy: Mapping[str, Any]
    assembly_contract: Mapping[str, Any]
    manifest_hash: str = ""
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        ids = {item.bundle_id for item in self.bundle_specs}
        if len(ids) != len(self.bundle_specs) or set(self.bundle_graph) != ids:
            raise ValueError("bundle graph identity mismatch")
        targets = [path for item in self.bundle_specs for path in item.target_paths]
        if len(targets) != len(set(targets)):
            raise ValueError("OVERLAPPING_BUNDLE_TARGET_PATHS")
        self._assert_acyclic()
        expected = canonical_hash(self.as_dict(include_hash=False))
        if self.manifest_hash and self.manifest_hash != expected:
            raise ValueError("manifest hash mismatch")
        object.__setattr__(self, "manifest_hash", expected)

    def _assert_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("BUNDLE_GRAPH_CYCLE")
            if node in visited:
                return
            visiting.add(node)
            for dependency in self.bundle_graph[node]:
                if dependency not in self.bundle_graph:
                    raise ValueError("UNKNOWN_BUNDLE_DEPENDENCY")
                visit(dependency)
            visiting.remove(node); visited.add(node)
        for node in self.bundle_graph:
            visit(node)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "kind": "GenerationManifest", "schema_version": self.schema_version,
            "project_id": self.project_id, "project_type": self.project_type, "package_name": self.package_name,
            "project_contract_hash": self.project_contract_hash, "obligation_hash": self.obligation_hash,
            "interface_contract_hash": self.interface_contract_hash,
            "bundle_specs": [item.as_dict() for item in self.bundle_specs],
            "bundle_graph": {key: list(value) for key, value in sorted(self.bundle_graph.items())},
            "deterministic_assets": list(self.deterministic_assets), "provider_policy": dict(self.provider_policy),
            "assembly_contract": dict(self.assembly_contract), "contains_credentials": False,
        }
        if include_hash:
            value["manifest_hash"] = self.manifest_hash
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GenerationManifest":
        if value.get("kind") != "GenerationManifest":
            raise ValueError("unsupported generation manifest")
        return cls(
            str(value["project_id"]), str(value["project_type"]), str(value["package_name"]),
            str(value["project_contract_hash"]), str(value["obligation_hash"]), str(value["interface_contract_hash"]),
            tuple(BundleSpec.from_dict(item) for item in value.get("bundle_specs", ())),
            {str(key): tuple(items) for key, items in value.get("bundle_graph", {}).items()},
            tuple(value.get("deterministic_assets", ())), dict(value.get("provider_policy", {})),
            dict(value.get("assembly_contract", {})), str(value.get("manifest_hash", "")),
            str(value.get("schema_version", "1.0")),
        )


@dataclass(frozen=True)
class AssemblyReceipt:
    project_id: str
    manifest_hash: str
    bundle_revision_ids: tuple[str, ...]
    bundle_source_hashes: Mapping[str, str]
    assembled_files: tuple[str, ...]
    assembly_hash: str
    created_at: str
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "AssemblyReceipt", **asdict(self), "contains_credentials": False}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssemblyReceipt":
        return cls(str(value["project_id"]), str(value["manifest_hash"]), tuple(value.get("bundle_revision_ids", ())), dict(value.get("bundle_source_hashes", {})), tuple(value.get("assembled_files", ())), str(value["assembly_hash"]), str(value["created_at"]), str(value.get("schema_version", "1.0")))


@dataclass(frozen=True)
class BundleAttempt:
    bundle_id: str
    attempt_id: str
    status: str
    revision_id: str = ""
    parent_revision_id: str = ""
    failure_class: str = ""
    lesson_snapshot_hash: str = ""
    applied_lesson_ids: tuple[str, ...] = ()
    generation_context_hash: str = ""
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    response_bytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BudgetReservation:
    partition: str
    project_id: str
    initial_calls: int
    repair_calls: int


class CampaignBudgetAllocator:
    """Partitioned call authority; later reserves cannot be spent by earlier phases."""

    LIMITS = {"TARGETED_REAL_4": 12, "CALIBRATION_GENERALIZATION": 16, "HOLDOUT": 6, "SELF_GROWTH_RESERVE": 4, "FRAMEWORK_CANARY": 2}

    def __init__(self) -> None:
        self.used = {key: 0 for key in self.LIMITS}
        self.project_usage: dict[str, int] = {}

    def consume(self, partition: str, project_id: str, *, calls: int = 1) -> None:
        if partition not in self.LIMITS or calls < 1:
            raise ValueError("invalid campaign budget request")
        if self.used[partition] + calls > self.LIMITS[partition]:
            raise RuntimeError(f"PROVIDER_BUDGET_EXHAUSTED:{partition}")
        if sum(self.used.values()) + calls > 40:
            raise RuntimeError("PROVIDER_BUDGET_EXHAUSTED:ITERATION")
        self.used[partition] += calls
        self.project_usage[project_id] = self.project_usage.get(project_id, 0) + calls

    def snapshot(self) -> dict[str, Any]:
        return {"limit": 40, "used": sum(self.used.values()), "partitions": {key: {"limit": self.LIMITS[key], "used": self.used[key], "remaining": self.LIMITS[key] - self.used[key]} for key in self.LIMITS}, "projects": dict(sorted(self.project_usage.items()))}
