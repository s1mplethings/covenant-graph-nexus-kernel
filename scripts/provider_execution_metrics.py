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
        "provider_jobs_repaired": 0,
        "provider_jobs_reused_after_pass": 0,
        "wall_clock_stage_timing": {},
        "_active": 0,
        "_job_ids": [],
        "_repaired_ids": [],
        "_reused_ids": [],
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
