#!/usr/bin/env python3
"""Minimal deterministic ProviderJob DAG executor.

Provider workers receive immutable inputs and return PatchSets.  Only this
executor validates ownership and merges successful outputs into the candidate.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


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


@dataclass
class ProviderJobResult:
    job_id: str
    status: str
    job_sha256: str
    patch_set: PatchSet | None = None
    error: str = ""
    reused: bool = False
    repaired: bool = False
    started_at_monotonic: float = 0.0
    finished_at_monotonic: float = 0.0


@dataclass
class ProviderExecutionResult:
    status: str
    files: dict[str, str]
    jobs: dict[str, ProviderJobResult]
    metrics: dict[str, Any]
    merge_order: list[str] = field(default_factory=list)


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


def execute_provider_jobs(
    jobs: list[ProviderJob | Mapping[str, Any]],
    worker: Callable[[ProviderJob, Mapping[str, str]], PatchSet | Mapping[str, str]],
    *,
    base_candidate: Mapping[str, str] | None = None,
    prior_results: Mapping[str, ProviderJobResult] | None = None,
    retry_job_ids: set[str] | None = None,
    parallelism: int | None = None,
) -> ProviderExecutionResult:
    normalized_jobs = [item if isinstance(item, ProviderJob) else ProviderJob.from_dict(item) for item in jobs]
    errors = validate_jobs(normalized_jobs)
    if errors:
        raise ValueError("invalid ProviderJob DAG: " + ",".join(errors))
    by_id = {job.id: job for job in normalized_jobs}
    prior = dict(prior_results or {})
    retry = set(retry_job_ids or set())
    cap = max(1, min(int(parallelism or configured_parallelism()), 16))
    results: dict[str, ProviderJobResult] = {}
    completed: set[str] = set()
    failed: set[str] = set()
    active = 0
    peak = 0
    lock = threading.Lock()
    provider_calls = 0
    jobs_reused = 0
    jobs_repaired = 0
    started = time.monotonic()

    for job in normalized_jobs:
        old = prior.get(job.id)
        if (
            job.id not in retry
            and old is not None
            and old.status == "PASS"
            and old.job_sha256 == job.contract_sha256
            and old.patch_set is not None
        ):
            results[job.id] = ProviderJobResult(
                job_id=job.id,
                status="PASS",
                job_sha256=job.contract_sha256,
                patch_set=_coerce_patch(job, old.patch_set),
                reused=True,
            )
            completed.add(job.id)
            jobs_reused += 1

    def run_one(job: ProviderJob, context: Mapping[str, str]) -> ProviderJobResult:
        nonlocal active, peak, provider_calls
        began = time.monotonic()
        with lock:
            active += 1
            peak = max(peak, active)
            provider_calls += 1
        try:
            patch = _coerce_patch(job, worker(job, dict(context)))
            return ProviderJobResult(
                job_id=job.id,
                status="PASS",
                job_sha256=job.contract_sha256,
                patch_set=patch,
                repaired=job.id in retry,
                started_at_monotonic=began,
                finished_at_monotonic=time.monotonic(),
            )
        except Exception as exc:
            return ProviderJobResult(
                job_id=job.id,
                status="FAIL",
                job_sha256=job.contract_sha256,
                error=str(exc),
                repaired=job.id in retry,
                started_at_monotonic=began,
                finished_at_monotonic=time.monotonic(),
            )
        finally:
            with lock:
                active -= 1

    while len(completed | failed) < len(normalized_jobs):
        ready = [
            job
            for job in normalized_jobs
            if job.id not in completed | failed
            and all(dependency in completed for dependency in job.depends_on)
        ]
        blocked = [
            job for job in normalized_jobs
            if job.id not in completed | failed and any(dependency in failed for dependency in job.depends_on)
        ]
        for job in blocked:
            results[job.id] = ProviderJobResult(job.id, "BLOCKED", job.contract_sha256, error="dependency_failed")
            failed.add(job.id)
        if not ready:
            if len(completed | failed) < len(normalized_jobs):
                raise RuntimeError("ProviderJob scheduler made no progress")
            break
        context = dict(base_candidate or {})
        for job_id in sorted(completed):
            patch = results[job_id].patch_set
            if patch:
                for path in sorted(patch.files):
                    context[path] = patch.files[path]
        with ThreadPoolExecutor(max_workers=min(cap, len(ready)), thread_name_prefix="cgkn-provider") as executor:
            futures = {executor.submit(run_one, job, context): job for job in ready}
            wave_results: dict[str, ProviderJobResult] = {}
            for future in as_completed(futures):
                item = future.result()
                wave_results[item.job_id] = item
        for job in ready:
            item = wave_results[job.id]
            results[job.id] = item
            if item.status == "PASS":
                completed.add(job.id)
                if item.repaired:
                    jobs_repaired += 1
            else:
                failed.add(job.id)

    files = dict(base_candidate or {})
    merge_order: list[str] = []
    for job_id in sorted(completed):
        patch = results[job_id].patch_set
        if patch is None:
            continue
        for path in sorted(patch.files):
            files[path] = patch.files[path]
            merge_order.append(f"{job_id}:{path}")
    elapsed = time.monotonic() - started
    metrics = {
        "provider_api_call_count": provider_calls,
        "provider_peak_concurrency": peak,
        "provider_jobs_total": len(normalized_jobs),
        "provider_jobs_repaired": jobs_repaired,
        "provider_jobs_reused_after_pass": jobs_reused,
        "wall_clock_stage_timing": {"provider_jobs_seconds": round(elapsed, 6)},
    }
    return ProviderExecutionResult(
        status="PASS" if not failed else "NEEDS_REWORK",
        files=files,
        jobs=results,
        metrics=metrics,
        merge_order=merge_order,
    )


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
