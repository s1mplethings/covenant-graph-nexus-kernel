#!/usr/bin/env python3
"""Pure ProviderJob/PatchSet contracts for the production leaf executor.

Scheduling belongs only to ``run_local_pipeline_impl``.  This module validates
job graphs and isolated PatchSets but deliberately owns no worker pool.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
from dataclasses import dataclass
from typing import Any, Mapping

from scripts.work_nodes import WorkNode, validate_work_nodes


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def configured_parallelism() -> int:
    raw = str(os.environ.get("CGKN_PROVIDER_PARALLELISM", "4")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(1, min(value, 16))


@dataclass(frozen=True)
class ProviderJob:
    id: str
    goal: str
    depends_on: tuple[str, ...] = ()
    owns: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()
    tree_node_id: str = ""
    issue_id: str = ""
    expected_behavior: str = ""
    observed_behavior: str = ""
    evidence: tuple[str, ...] = ()
    target_files: tuple[str, ...] = ()
    current_source: str = ""
    affected_behavior_probe: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderJob":
        raw_owns = value.get("owns", value.get("paths", []))
        if not raw_owns and str(value.get("path", "")).strip():
            raw_owns = [value.get("path")]
        return cls(
            id=str(value.get("id", "")).strip(),
            goal=str(value.get("goal", "")).strip(),
            depends_on=tuple(str(item).strip() for item in value.get("depends_on", []) if str(item).strip()),
            owns=tuple(_normalize_path(item) for item in raw_owns if _normalize_path(item)),
            interfaces=tuple(str(item).strip() for item in value.get("interfaces", []) if str(item).strip()),
            acceptance=tuple(str(item).strip() for item in value.get("acceptance", []) if str(item).strip()),
            tree_node_id=str(value.get("tree_node_id", "")).strip(),
            issue_id=str(value.get("issue_id", "")).strip(),
            expected_behavior=str(value.get("expected_behavior", "")).strip(),
            observed_behavior=str(value.get("observed_behavior", "")).strip(),
            evidence=tuple(str(item).strip() for item in value.get("evidence", []) if str(item).strip()),
            target_files=tuple(_normalize_path(item) for item in value.get("target_files", []) if _normalize_path(item)),
            current_source=str(value.get("current_source", "")),
            affected_behavior_probe=tuple(str(item).strip() for item in value.get("affected_behavior_probe", []) if str(item).strip()),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "depends_on": list(self.depends_on),
            "owns": list(self.owns),
            "interfaces": list(self.interfaces),
            "acceptance": list(self.acceptance),
            "tree_node_id": self.tree_node_id,
            "issue_id": self.issue_id,
            "expected_behavior": self.expected_behavior,
            "observed_behavior": self.observed_behavior,
            "evidence": list(self.evidence),
            "target_files": list(self.target_files),
            "current_source": self.current_source,
            "affected_behavior_probe": list(self.affected_behavior_probe),
        }

    @property
    def contract_sha256(self) -> str:
        return _hash(self.as_dict())


@dataclass(frozen=True)
class PatchSet:
    job_id: str
    files: Mapping[str, str]


def _normalize_path(value: Any) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    directory_owner = raw.endswith("/")
    if not raw or raw.startswith("/") or ":" in raw.split("/", 1)[0]:
        return ""
    parts = pathlib.PurePosixPath(raw).parts
    if any(part in {"", ".", ".."} for part in parts):
        return ""
    normalized = pathlib.PurePosixPath(*parts).as_posix()
    return normalized + "/" if directory_owner else normalized


def _owns(job: ProviderJob, path: str) -> bool:
    return any(path == owner or (owner.endswith("/") and path.startswith(owner)) for owner in job.owns)


def validate_jobs(jobs: list[ProviderJob]) -> list[str]:
    errors: list[str] = []
    by_id = {job.id: job for job in jobs if job.id}
    if len(by_id) != len(jobs):
        errors.append("provider_jobs.unique_nonempty_ids")
    for job in jobs:
        if not job.goal:
            errors.append(f"provider_job.goal:{job.id}")
        if not job.owns:
            errors.append(f"provider_job.owns:{job.id}")
        for dependency in job.depends_on:
            if dependency not in by_id:
                errors.append(f"provider_job.unknown_dependency:{job.id}:{dependency}")
            if dependency == job.id:
                errors.append(f"provider_job.self_dependency:{job.id}")
    for index, left in enumerate(jobs):
        for right in jobs[index + 1 :]:
            for left_owner in left.owns:
                for right_owner in right.owns:
                    if left_owner == right_owner or (
                        left_owner.endswith("/") and right_owner.startswith(left_owner)
                    ) or (right_owner.endswith("/") and left_owner.startswith(right_owner)):
                        errors.append(f"provider_job.ownership_conflict:{left.id}:{right.id}:{left_owner}:{right_owner}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(job_id: str) -> None:
        if job_id in visiting:
            errors.append(f"provider_job.cycle:{job_id}")
            return
        if job_id in visited or job_id not in by_id:
            return
        visiting.add(job_id)
        for dependency in by_id[job_id].depends_on:
            visit(dependency)
        visiting.remove(job_id)
        visited.add(job_id)

    for job_id in sorted(by_id):
        visit(job_id)
    return sorted(set(errors))


def provider_job_from_work_node(node: WorkNode, **repair: Any) -> ProviderJob:
    """Adapt canonical planning data to the existing Provider executor contract."""
    if node.executor_type != "agent":
        raise ValueError(f"provider_job.executor_type:{node.id}:{node.executor_type}")
    return ProviderJob(
        id=node.id,
        goal=node.goal,
        depends_on=node.depends_on,
        owns=node.owns,
        interfaces=node.interfaces,
        acceptance=node.acceptance,
        **repair,
    )


def work_node_from_provider_job(job: ProviderJob) -> WorkNode:
    return WorkNode(
        id=job.id,
        goal=job.goal,
        depends_on=job.depends_on,
        interfaces=job.interfaces,
        executor_type="agent",
        owns=job.owns,
        acceptance=job.acceptance,
    )


def validate_repair_job_contract(value: ProviderJob | Mapping[str, Any]) -> list[str]:
    """Validate a repair action without acquiring any scheduling authority."""
    job = value if isinstance(value, ProviderJob) else ProviderJob.from_dict(value)
    errors = validate_jobs([job])
    required = {
        "tree_node_id": job.tree_node_id,
        "issue_id": job.issue_id,
        "expected_behavior": job.expected_behavior,
        "observed_behavior": job.observed_behavior,
        "evidence": job.evidence,
        "target_files": job.target_files,
        "current_source": job.current_source,
        "affected_behavior_probe": job.affected_behavior_probe,
    }
    for field, content in required.items():
        if not content:
            errors.append(f"provider_job.repair_contract.{field}:{job.id}")
    if set(job.target_files) != set(job.owns):
        errors.append(f"provider_job.repair_contract.target_files_match_ownership:{job.id}")
    return sorted(set(errors))


def _coerce_patch(job: ProviderJob, value: PatchSet | Mapping[str, str]) -> PatchSet:
    patch = value if isinstance(value, PatchSet) else PatchSet(job.id, dict(value))
    if patch.job_id != job.id:
        raise ValueError(f"patch_set.job_id:{job.id}")
    normalized: dict[str, str] = {}
    for raw_path, content in patch.files.items():
        path = _normalize_path(raw_path)
        if not path or not _owns(job, path):
            raise ValueError(f"patch_set.ownership:{job.id}:{raw_path}")
        normalized[path] = str(content)
    return PatchSet(job.id, normalized)


def validate_patch_set(job: ProviderJob, value: PatchSet | Mapping[str, str]) -> PatchSet:
    """Public ownership boundary used by the production Provider leaf lane."""
    return _coerce_patch(job, value)


def provider_jobs_from_leaf_graph(component_id: str, graph: Mapping[str, Any]) -> list[ProviderJob]:
    nodes: list[WorkNode] = []
    path_to_id: dict[str, str] = {}
    for leaf in graph.get("leaves", []):
        if not isinstance(leaf, Mapping):
            continue
        raw_paths = leaf.get("paths", leaf.get("owns", []))
        if not raw_paths and str(leaf.get("path", "")).strip():
            raw_paths = [leaf.get("path")]
        for raw_path in raw_paths:
            path = _normalize_path(raw_path)
            if path:
                path_to_id[path] = str(leaf.get("leaf_id", ""))
    for leaf in graph.get("leaves", []):
        if not isinstance(leaf, Mapping):
            continue
        raw_paths = leaf.get("paths", leaf.get("owns", []))
        if not raw_paths and str(leaf.get("path", "")).strip():
            raw_paths = [leaf.get("path")]
        paths = tuple(
            path for path in (_normalize_path(item) for item in raw_paths) if path
        )
        primary_path = paths[0] if paths else ""
        nodes.append(
            WorkNode(
                id=str(leaf.get("leaf_id", "")),
                goal=str(leaf.get("purpose", "")) or f"Build {primary_path} for {component_id}",
                depends_on=tuple(
                    dict.fromkeys(
                        path_to_id[item]
                        for item in leaf.get("depends_on", [])
                        if item in path_to_id
                        and path_to_id[item] != str(leaf.get("leaf_id", ""))
                    )
                ),
                owns=paths,
                interfaces=tuple(str(item) for item in leaf.get("expected_symbols", []) if str(item).strip()),
                acceptance=tuple(str(item) for item in leaf.get("acceptance_checks", []) if str(item).strip()),
            )
        )
    errors = validate_work_nodes(nodes)
    if errors:
        raise ValueError(";".join(errors))
    return [
        provider_job_from_work_node(
            node,
            tree_node_id=f"file.{_normalize_path(node.owns[0] if node.owns else '').replace('/', '_').replace('.', '_').replace('-', '_').lower()}",
        )
        for node in nodes
    ]
