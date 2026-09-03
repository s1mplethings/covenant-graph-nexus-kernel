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

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderJob":
        return cls(
            id=str(value.get("id", "")).strip(),
            goal=str(value.get("goal", "")).strip(),
            depends_on=tuple(str(item).strip() for item in value.get("depends_on", []) if str(item).strip()),
            owns=tuple(_normalize_path(item) for item in value.get("owns", []) if _normalize_path(item)),
            interfaces=tuple(str(item).strip() for item in value.get("interfaces", []) if str(item).strip()),
            acceptance=tuple(str(item).strip() for item in value.get("acceptance", []) if str(item).strip()),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "depends_on": list(self.depends_on),
            "owns": list(self.owns),
            "interfaces": list(self.interfaces),
            "acceptance": list(self.acceptance),
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
    jobs: list[ProviderJob] = []
    path_to_id = {
        str(leaf.get("path", "")): str(leaf.get("leaf_id", ""))
        for leaf in graph.get("leaves", [])
        if isinstance(leaf, Mapping)
    }
    for leaf in graph.get("leaves", []):
        if not isinstance(leaf, Mapping):
            continue
        path = str(leaf.get("path", ""))
        jobs.append(
            ProviderJob(
                id=str(leaf.get("leaf_id", "")),
                goal=str(leaf.get("purpose", "")) or f"Build {path} for {component_id}",
                depends_on=tuple(path_to_id[item] for item in leaf.get("depends_on", []) if item in path_to_id),
                owns=(path,),
                interfaces=tuple(str(item) for item in leaf.get("expected_symbols", []) if str(item).strip()),
                acceptance=tuple(str(item) for item in leaf.get("acceptance_checks", []) if str(item).strip()),
            )
        )
    return jobs
