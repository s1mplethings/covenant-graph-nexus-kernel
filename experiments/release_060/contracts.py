"""Frozen contracts for ITER-060.

These are evaluation contracts only.  They do not define a second planner,
runtime, state authority, or public delivery route.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import pathlib
import re
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def _safe_id(value: str, name: str) -> str:
    if not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a safe stable identifier")
    return value


def _safe_path(value: str) -> str:
    raw = value.replace("\\", "/")
    path = pathlib.PurePosixPath(raw)
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe project path: {value!r}")
    return path.as_posix()


class ArchitectureBaseline(str, Enum):
    DIRECT_CHEAP = "B0_DIRECT_CHEAP"
    DIRECT_CHEAP_FLAT_STATE = "B1_DIRECT_CHEAP_FLAT_STATE"
    MINIMAL_CGNK = "B2_MINIMAL_CGNK"
    FULL_CGNK = "B3_FULL_CGNK"


class ComplexityTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProjectType(str, Enum):
    CLI_FILE_TOOL = "CLI_FILE_TOOL"
    DATA_PIPELINE = "DATA_PIPELINE"
    CONFIG_MIGRATION = "CONFIGURATION_MIGRATION_TOOL"
    LOG_DIAGNOSTIC = "LOG_DIAGNOSTIC_TOOL"
    DOCUMENT_KNOWLEDGE = "DOCUMENT_KNOWLEDGE_TOOL"
    LOCAL_SERVICE = "LOCAL_SERVICE_BACKEND"
    LIBRARY_PACKAGE = "LIBRARY_PACKAGE"
    MULTI_COMPONENT_AUTOMATION = "MULTI_COMPONENT_AUTOMATION"


class EpisodeMode(str, Enum):
    FROM_SCRATCH = "FROM_SCRATCH"
    FEATURE_EXTENSION = "FEATURE_EXTENSION"
    BUG_REPAIR = "BUG_REPAIR"
    VERSION_CHANGE = "VERSION_CHANGE"
    RESTART_RESUME = "RESTART_RESUME"
    STATEFUL_CONTINUATION = "STATEFUL_CONTINUATION"


@dataclass(frozen=True)
class EpisodeSpec:
    episode_id: str
    mode: str
    public_instruction: str
    required_paths: tuple[str, ...]
    public_acceptance: tuple[str, ...]
    public_cases: tuple[Mapping[str, Any], ...]
    private_cases: tuple[Mapping[str, Any], ...]
    version: str
    state_dependencies: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    controlled_mutation: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _safe_id(self.episode_id, "episode_id")
        EpisodeMode(self.mode)
        if not self.public_instruction.strip() or not self.public_acceptance:
            raise ValueError("episode needs an instruction and public acceptance")
        normalized = tuple(_safe_path(item) for item in self.required_paths)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("episode paths must be non-empty and unique")
        object.__setattr__(self, "required_paths", normalized)
        if not self.public_cases or not self.private_cases:
            raise ValueError("canonical public and private acceptance are both required")

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("private_cases", None)
        return value

    def private_dict(self) -> dict[str, Any]:
        return {"episode_id": self.episode_id, "private_cases": [dict(item) for item in self.private_cases]}


@dataclass(frozen=True)
class ProjectFamilySpec:
    family_id: str
    split: str
    complexity: str
    project_type: str
    language: str
    package_name: str
    public_goal: str
    functional_requirements: tuple[str, ...]
    constraints: tuple[str, ...]
    public_interfaces: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    episodes: tuple[EpisodeSpec, ...]
    raw_complexity: Mapping[str, int]
    provenance_sensitive: bool = False
    capability_heavy: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _safe_id(self.family_id, "family_id")
        if self.split not in {"DEVELOPMENT", "FORMAL_HOLDOUT"}:
            raise ValueError("ITER-060 family split must be DEVELOPMENT or FORMAL_HOLDOUT")
        tier = ComplexityTier(self.complexity)
        ProjectType(self.project_type)
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", self.package_name):
            raise ValueError("package_name must be a safe Python module")
        if not self.episodes or len({item.episode_id for item in self.episodes}) != len(self.episodes):
            raise ValueError("family episodes must be non-empty and unique")
        expected = {"file_count", "loc", "module_count", "dependency_count", "episode_count", "state_dependency_count", "version_count", "repair_rounds", "capability_count", "knowledge_source_count"}
        if set(self.raw_complexity) != expected or any(int(value) < 0 for value in self.raw_complexity.values()):
            raise ValueError("raw complexity metrics are incomplete or invalid")
        if int(self.raw_complexity["episode_count"]) != len(self.episodes):
            raise ValueError("episode_count does not match episode plan")
        if tier is ComplexityTier.LOW and not (1 <= len(self.episodes) <= 2):
            raise ValueError("LOW families require 1-2 episodes")
        if tier is ComplexityTier.MEDIUM and not (3 <= len(self.episodes) <= 4):
            raise ValueError("MEDIUM families require 3-4 episodes")
        if tier is ComplexityTier.HIGH and not (4 <= len(self.episodes) <= 6):
            raise ValueError("HIGH families require 4-6 episodes")

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": "CGNKProjectFamilySpec",
            "schema_version": self.schema_version,
            "family_id": self.family_id,
            "split": self.split,
            "complexity": self.complexity,
            "project_type": self.project_type,
            "language": self.language,
            "package_name": self.package_name,
            "public_goal": self.public_goal,
            "functional_requirements": list(self.functional_requirements),
            "constraints": list(self.constraints),
            "public_interfaces": list(self.public_interfaces),
            "expected_artifacts": list(self.expected_artifacts),
            "episodes": [item.public_dict() for item in self.episodes],
            "raw_complexity": dict(self.raw_complexity),
            "provenance_sensitive": self.provenance_sensitive,
            "capability_heavy": self.capability_heavy,
        }

    def private_evaluator_packet(self) -> dict[str, Any]:
        value = {
            "kind": "CGNKPrivateEvaluatorPacket",
            "schema_version": SCHEMA_VERSION,
            "family_id": self.family_id,
            "episodes": [item.private_dict() for item in self.episodes],
        }
        value["packet_hash"] = canonical_hash(value)
        return value

    @property
    def public_hash(self) -> str:
        return canonical_hash(self.public_dict())

    @property
    def private_hash(self) -> str:
        return canonical_hash(self.private_evaluator_packet())


@dataclass(frozen=True)
class EvaluationPolicy:
    provider: str = "deepseek"
    model: str = "deepseek-flash"
    temperature: float = 0.0
    max_output_tokens: int = 6000
    max_provider_calls_per_family: int = 20
    max_repairs_per_episode: int = 2
    request_timeout_seconds: int = 150
    outer_deadline_seconds: int = 180
    network_enabled: bool = False
    corpus_read_enabled: bool = False
    manual_intervention: int = 0
    random_seed: int = 60027
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.provider != "deepseek" or self.model != "deepseek-flash":
            raise ValueError("ITER-060 primary comparison is frozen to the qualified DeepSeek cheap route")
        if self.temperature != 0 or self.network_enabled or self.corpus_read_enabled or self.manual_intervention:
            raise ValueError("formal fairness controls cannot be relaxed")
        if self.max_provider_calls_per_family < 1 or self.max_repairs_per_episode < 0:
            raise ValueError("evaluation budgets are invalid")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def policy_hash(self) -> str:
        return canonical_hash(self.as_dict())
