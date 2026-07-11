#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

PipelineStatus = Literal["pass", "warning", "fail"]


class PipelineResultDict(TypedDict, total=False):
    status: str
    verdict: str
    artifacts: list[str]
    warnings: list[str]
    blockers: list[str]
    next_actions: list[str]
    metadata: dict[str, Any]


@dataclass
class ContractResult:
    status: str = "pass"
    verdict: str = ""
    artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> PipelineResultDict:
        return {
            "status": self.status,
            "verdict": self.verdict,
            "artifacts": list(self.artifacts),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
            "metadata": dict(self.metadata),
        }


@dataclass
class GenerationResult(ContractResult):
    files: list[dict[str, str]] = field(default_factory=list)


@dataclass
class CandidateMaterializationResult(ContractResult):
    candidate_dir: str = ""


@dataclass
class SanitizeResult(ContractResult):
    files: list[dict[str, str]] = field(default_factory=list)


@dataclass
class RepairPlan(ContractResult):
    target_files: list[str] = field(default_factory=list)
    provider_actions: list[dict[str, Any]] = field(default_factory=list)
    deterministic_actions: list[dict[str, Any]] = field(default_factory=list)
    validation_commands: list[list[str]] = field(default_factory=list)
    must_disappear_failures: list[str] = field(default_factory=list)


@dataclass
class RepairResult(ContractResult):
    changed_files: list[str] = field(default_factory=list)


@dataclass
class PostBuildResult(ContractResult):
    test_result: dict[str, Any] = field(default_factory=dict)


@dataclass
class VisualEvidenceResult(ContractResult):
    screenshots: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)


@dataclass
class CandidateReviewDeliveryResult(ContractResult):
    sent: bool = False


@dataclass
class FinalDeliveryResult(ContractResult):
    delivery_allowed: bool = False


@dataclass
class PipelineRunResult(ContractResult):
    run_dir: str = ""
    project_dir: str = ""
    candidate_project_dir: str = ""


REPLACEABLE_MODULES = {
    "provider_generation",
    "post_build_repair",
    "visual_evidence",
    "candidate_review_delivery",
}

TRUTH_MODULES = {
    "final_delivery_truth",
    "artifact_integrity",
    "path_safety",
    "fake_artifact_scanner",
    "local_packager",
    "public_final_delivery_gate",
}

MODULE_MUTATION_CONTRACT = (
    "CGNK pipeline changes are made by directly modifying, generating, or deleting bounded modules. "
    "Agents must not bypass module contracts by mutating final truth artifacts, forging evidence, or "
    "creating hidden compatibility routes."
)


def base_result(
    *,
    status: str = "pass",
    verdict: str = "",
    artifacts: list[str] | None = None,
    warnings: list[str] | None = None,
    blockers: list[str] | None = None,
    next_actions: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> PipelineResultDict:
    return {
        "status": status,
        "verdict": verdict,
        "artifacts": list(artifacts or []),
        "warnings": list(warnings or []),
        "blockers": list(blockers or []),
        "next_actions": list(next_actions or []),
        "metadata": dict(metadata or {}),
    }
