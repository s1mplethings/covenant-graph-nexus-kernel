#!/usr/bin/env python3
"""Thread-safe, durable Provider execution metrics for one generation run."""

from __future__ import annotations

import json
import pathlib
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator


_LOCK = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}


def _key(phase_log_path: pathlib.Path | str | None) -> str:
    raw = str(phase_log_path or "").strip()
    return str(pathlib.Path(raw).resolve()) if raw else "memory"


def _receipt_path(key: str) -> pathlib.Path | None:
    if key == "memory":
        return None
    phase_log = pathlib.Path(key)
    return phase_log.parent / "artifacts" / "provider_execution_metrics.json"


def _default() -> dict[str, Any]:
    return {
        "kind": "CGKNProviderExecutionMetrics",
        "provider_api_call_count": 0,
        "provider_peak_concurrency": 0,
        "provider_jobs_total": 0,
        "provider_owned_files_total": 0,
        "provider_avg_files_per_job": 0.0,
        "provider_dag_wave_widths": [],
        "provider_dag_critical_path_waves": 0,
        "provider_fragmentation_ratio": 0.0,
        "provider_jobs_repaired": 0,
        "provider_jobs_reused_after_pass": 0,
        "wall_clock_stage_timing": {},
        "_active": 0,
        "_job_ids": [],
        "_repaired_ids": [],
        "_reused_ids": [],
        "_job_owns": {},
        "_component_waves": {},
    }


def _persist(key: str) -> None:
    path = _receipt_path(key)
    if path is None:
        return
    state = dict(_STATE[key])
    for private in [item for item in state if item.startswith("_")]:
        state.pop(private, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def declare_jobs(phase_log_path: pathlib.Path | str | None, job_ids: list[str]) -> None:
    key = _key(phase_log_path)
    with _LOCK:
        state = _STATE.setdefault(key, _default())
        known = set(state["_job_ids"])
        known.update(str(item) for item in job_ids if str(item).strip())
        state["_job_ids"] = sorted(known)
        state["provider_jobs_total"] = len(known)
        _persist(key)


def declare_job_graph(
    phase_log_path: pathlib.Path | str | None,
    *,
    component_id: str,
    jobs: list[dict[str, Any]],
    wave_widths: list[int],
) -> None:
    """Persist diagnostic DAG quality metrics without granting PASS authority."""
    key = _key(phase_log_path)
    with _LOCK:
        state = _STATE.setdefault(key, _default())
        job_owns = state["_job_owns"]
        for job in jobs:
            job_id = str(job.get("id", "")).strip()
            if job_id:
                job_owns[job_id] = list(
                    dict.fromkeys(
                        str(path).replace("\\", "/").strip()
                        for path in job.get("owns", [])
                        if str(path).strip()
                    )
                )
        state["_job_ids"] = sorted(job_owns)
        state["_component_waves"][str(component_id)] = [
            max(0, int(width)) for width in wave_widths
        ]
        owned_paths = {
            path for paths in job_owns.values() for path in paths
        }
        job_count = len(job_owns)
        owned_count = len(owned_paths)
        component_waves = state["_component_waves"]
        combined_waves = [
            width
            for component in component_waves
            for width in component_waves[component]
        ]
        state["provider_jobs_total"] = job_count
        state["provider_owned_files_total"] = owned_count
        state["provider_avg_files_per_job"] = round(
            owned_count / job_count, 3
        ) if job_count else 0.0
        state["provider_dag_wave_widths"] = combined_waves
        state["provider_dag_critical_path_waves"] = len(combined_waves)
        state["provider_fragmentation_ratio"] = round(
            job_count / owned_count, 3
        ) if owned_count else 0.0
        _persist(key)


def record_job(phase_log_path: pathlib.Path | str | None, job_id: str, *, repaired: bool = False, reused: bool = False) -> None:
    key = _key(phase_log_path)
    with _LOCK:
        state = _STATE.setdefault(key, _default())
        if repaired and job_id not in state["_repaired_ids"]:
            state["_repaired_ids"].append(job_id)
        if reused and job_id not in state["_reused_ids"]:
            state["_reused_ids"].append(job_id)
        state["provider_jobs_repaired"] = len(state["_repaired_ids"])
        state["provider_jobs_reused_after_pass"] = len(state["_reused_ids"])
        _persist(key)


@contextmanager
def provider_api_call(phase_log_path: pathlib.Path | str | None, *, stage: str) -> Iterator[None]:
    key = _key(phase_log_path)
    began = time.monotonic()
    with _LOCK:
        state = _STATE.setdefault(key, _default())
        state["provider_api_call_count"] += 1
        state["_active"] += 1
        state["provider_peak_concurrency"] = max(state["provider_peak_concurrency"], state["_active"])
        _persist(key)
    try:
        yield
    finally:
        elapsed = time.monotonic() - began
        with _LOCK:
            state = _STATE.setdefault(key, _default())
            state["_active"] = max(0, int(state["_active"]) - 1)
            timing = state["wall_clock_stage_timing"]
            timing[stage] = round(float(timing.get(stage, 0.0)) + elapsed, 6)
            _persist(key)


def snapshot(phase_log_path: pathlib.Path | str | None) -> dict[str, Any]:
    key = _key(phase_log_path)
    with _LOCK:
        state = dict(_STATE.setdefault(key, _default()))
    for private in [item for item in state if item.startswith("_")]:
        state.pop(private, None)
    return state
