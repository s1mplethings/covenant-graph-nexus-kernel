from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from cgkn.application.learning import canonical_hash


@dataclass(frozen=True)
class ProjectCase:
    project_id: str
    wave: str
    project_type: str
    package_name: str
    public_goal: str
    interface_contract: Mapping[str, Any]
    behavior_contract: Mapping[str, Any]
    target_paths: tuple[str, ...]
    public_cases: tuple[Mapping[str, Any], ...]
    hidden_cases: tuple[Mapping[str, Any], ...]
    required_capabilities: tuple[str, ...] = ("project.python.pyproject.render@1",)
    initial_files: Mapping[str, str] = None  # type: ignore[assignment]
    allowed_paths: tuple[str, ...] = ()
    existing_repo: bool = False
    schema_version: str = "1.0"
    cli_contract: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.wave not in {"A", "B", "C"}:
            raise ValueError("wave must be A, B, or C")
        if len(self.target_paths) < 1 or len(self.target_paths) > 8:
            raise ValueError("project target paths must contain 1-8 files")
        if self.initial_files is None:
            object.__setattr__(self, "initial_files", {})
        if self.existing_repo and not self.allowed_paths:
            raise ValueError("existing repository case requires an ImpactSet")

    @property
    def case_hash(self) -> str:
        return canonical_hash({key: value for key, value in self.as_dict().items() if key != "hidden_cases"})

    @property
    def hidden_hash(self) -> str:
        return canonical_hash(self.hidden_cases)

    def as_dict(self, *, include_hidden: bool = True) -> dict[str, Any]:
        value = asdict(self)
        if not include_hidden:
            value.pop("hidden_cases", None)
        return value


@dataclass(frozen=True)
class ProjectRunReceipt:
    project_id: str
    wave: str
    project_type: str
    goal_hash: str
    contract_hash: str
    obligation_hash: str
    lesson_snapshot_hash: str
    applied_lesson_ids: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    grown_capabilities: tuple[str, ...]
    reused_capabilities: tuple[str, ...]
    provider_calls: int
    input_tokens: int
    output_tokens: int
    repair_rounds: int
    candidate_revisions: int
    tests: Mapping[str, Any]
    oracle: Mapping[str, Any]
    hidden: Mapping[str, Any]
    package: Mapping[str, Any]
    runtime_smoke: Mapping[str, Any]
    failure_domain: str
    final_status: str
    source_commit: str
    wall_time_seconds: float
    manual_candidate_edits: int = 0
    whole_project_replans: int = 0
    unsafe_admissions: int = 0
    accepted_interface_breaks: int = 0
    contains_credentials: bool = False
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CampaignState:
    campaign_id: str
    source_commit: str
    current_wave: str
    current_project: str
    completed_projects: tuple[str, ...]
    failed_projects: tuple[str, ...]
    blocked_projects: tuple[str, ...]
    provider_calls: int
    input_tokens: int
    output_tokens: int
    cost_in_usd_ticks: int
    framework_fixes: tuple[str, ...]
    lesson_snapshot_hash: str
    critical_stop: str
    updated_at: str
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
