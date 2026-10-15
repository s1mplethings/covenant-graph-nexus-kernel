#!/usr/bin/env python3
"""Thread-safe, durable Provider execution metrics for one generation run."""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator


_LOCK = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}
_CALL_CONTEXT = threading.local()


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
        "primary_provider_calls": 0,
        "provider_generation_calls": 0,
        "provider_completion_calls": 0,
        "provider_contract_repair_calls": 0,
        "provider_transport_retries": 0,
        "fallback_provider_calls": 0,
        "fallback_executed": 0,
        "fallback_selected": 0,
        "files_authored_by_primary": [],
        "files_authored_by_fallback": [],
        "provider_peak_concurrency": 0,
        "provider_jobs_total": 0,
        "provider_owned_files_total": 0,
        "provider_avg_files_per_job": 0.0,
        "provider_dag_wave_widths": [],
        "provider_dag_critical_path_waves": 0,
        "provider_fragmentation_ratio": 0.0,
        "provider_jobs_repaired": 0,
        "provider_jobs_reused_after_pass": 0,
        "provider_job_reuse_events": 0,
        "provider_jobs_repaired_ids": [],
        "provider_jobs_reused_ids": [],
        "wall_clock_stage_timing": {},
        "_active": 0,
        "_job_ids": [],
        "_repaired_ids": [],
        "_reused_ids": [],
        "_job_owns": {},
        "_component_waves": {},
        "_primary_authored_paths": [],
        "_fallback_authored_paths": [],
    }


def _state(key: str) -> dict[str, Any]:
    if key in _STATE:
        return _STATE[key]
    state = _default()
    path = _receipt_path(key)
    if path is not None and path.exists():
        try:
            persisted = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            persisted = {}
        if isinstance(persisted, dict):
            for field in state:
                if not field.startswith("_") and field in persisted:
                    state[field] = persisted[field]
            state["_repaired_ids"] = list(
                dict.fromkeys(str(item) for item in state["provider_jobs_repaired_ids"])
            )
            state["_reused_ids"] = list(
                dict.fromkeys(str(item) for item in state["provider_jobs_reused_ids"])
            )
            state["_primary_authored_paths"] = list(state["files_authored_by_primary"])
            state["_fallback_authored_paths"] = list(state["files_authored_by_fallback"])
    _STATE[key] = state
    return state


def _persist(key: str) -> None:
    path = _receipt_path(key)
    if path is None:
        return
    state = dict(_STATE[key])
    for private in [item for item in state if item.startswith("_")]:
        state.pop(private, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        for attempt in range(5):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _reconcile_phase_log(state: dict[str, Any], key: str) -> None:
    """Backfill durable call/reuse counters from their append-only run evidence."""
    if key == "memory":
        return
    phase_log = pathlib.Path(key)
    try:
        events = [
            json.loads(line)
            for line in phase_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return
    requests = [
        (index, event)
        for index, event in enumerate(events)
        if isinstance(event, dict) and event.get("event") == "provider_request"
    ]
    if requests:
        contract_ordinals = {
            ordinal
            for ordinal, (_index, event) in enumerate(requests)
            if str(event.get("metric_call_kind") or event.get("payload_mode", ""))
            == "contract_repair"
        }
        retry_ordinals: set[int] = set()
        retry_markers = [
            (index, event)
            for index, event in enumerate(events)
            if isinstance(event, dict)
            and event.get("event") == "provider_retry_model_route"
        ]
        for marker_index, marker in retry_markers:
            match = next(
                (
                    ordinal
                    for ordinal, (request_index, request) in enumerate(requests)
                    if request_index > marker_index
                    and request.get("stage") == marker.get("stage")
                    and request.get("component") == marker.get("component")
                ),
                None,
            )
            if match is not None:
                retry_ordinals.add(match)
        completion_ordinals: set[int] = set()
        for event_index, event in enumerate(events):
            if not isinstance(event, dict) or event.get("event") != "provider_job_missing_path_completion":
                continue
            requested_paths = {
                str(item).replace("\\", "/").strip()
                for item in event.get("requested_paths", [])
                if str(item).strip()
            }
            match = next(
                (
                    ordinal
                    for ordinal in range(len(requests) - 1, -1, -1)
                    if requests[ordinal][0] < event_index
                    and requests[ordinal][1].get("component") == event.get("component")
                    and str(requests[ordinal][1].get("target_file", "")) in requested_paths
                    and ordinal not in contract_ordinals
                    and ordinal not in completion_ordinals
                ),
                None,
            )
            if match is not None:
                completion_ordinals.add(match)
        total = len(requests)
        contract = len(contract_ordinals - retry_ordinals)
        completion = len(completion_ordinals - retry_ordinals)
        retries = len(retry_ordinals)
        state["provider_api_call_count"] = total
        state["primary_provider_calls"] = total
        state["provider_contract_repair_calls"] = contract
        state["provider_completion_calls"] = completion
        state["provider_transport_retries"] = retries
        state["provider_generation_calls"] = max(
            0, total - contract - completion - retries
        )

    reused_ids: set[str] = set(state.get("_reused_ids", []))
    reuse_events = 0
    graph_root = phase_log.parent / "artifacts" / "provider_components" / "leaf_work_graphs"
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("event") == "provider_job_reused":
            job_id = str(event.get("provider_job_id", "")).strip()
            if job_id:
                reused_ids.add(job_id)
                reuse_events += 1
        elif event.get("event") == "upstream_component_resume_checkpoint_reused":
            component_id = str(event.get("component", "")).strip()
            graph_path = graph_root / f"{component_id}.json"
            try:
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            job_ids = [
                str(item.get("id", "")).strip()
                for item in graph.get("provider_jobs", [])
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            ]
            reused_ids.update(job_ids)
            reuse_events += len(job_ids)
    if reuse_events:
        state["_reused_ids"] = sorted(reused_ids)
        state["provider_jobs_reused_ids"] = sorted(reused_ids)
        state["provider_jobs_reused_after_pass"] = len(reused_ids)
        state["provider_job_reuse_events"] = reuse_events


def declare_jobs(phase_log_path: pathlib.Path | str | None, job_ids: list[str]) -> None:
    key = _key(phase_log_path)
    with _LOCK:
        state = _state(key)
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
        state = _state(key)
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
        state = _state(key)
        if repaired and job_id not in state["_repaired_ids"]:
            state["_repaired_ids"].append(job_id)
        if reused:
            state["provider_job_reuse_events"] = int(
                state.get("provider_job_reuse_events", 0)
            ) + 1
            if job_id not in state["_reused_ids"]:
                state["_reused_ids"].append(job_id)
        state["provider_jobs_repaired"] = len(state["_repaired_ids"])
        state["provider_jobs_reused_after_pass"] = len(state["_reused_ids"])
        state["provider_jobs_repaired_ids"] = sorted(state["_repaired_ids"])
        state["provider_jobs_reused_ids"] = sorted(state["_reused_ids"])
        _persist(key)


def mark_call_origin(origin: str) -> None:
    normalized = str(origin or "").strip().lower()
    _CALL_CONTEXT.origin = normalized if normalized in {"primary", "fallback"} else ""


def last_call_origin() -> str:
    return str(getattr(_CALL_CONTEXT, "origin", "") or "")


def record_fallback_event(
    phase_log_path: pathlib.Path | str | None,
    *,
    selected: bool = False,
) -> None:
    key = _key(phase_log_path)
    with _LOCK:
        state = _state(key)
        field = "fallback_selected" if selected else "fallback_executed"
        state[field] = int(state.get(field, 0)) + 1
        _persist(key)


def record_authored_files(
    phase_log_path: pathlib.Path | str | None,
    paths_by_origin: dict[str, str],
) -> None:
    key = _key(phase_log_path)
    with _LOCK:
        state = _state(key)
        for path, origin in paths_by_origin.items():
            normalized_path = str(path).replace("\\", "/").strip()
            normalized_origin = str(origin).strip().lower()
            if not normalized_path or normalized_origin not in {"primary", "fallback"}:
                continue
            private_field = (
                "_fallback_authored_paths"
                if normalized_origin == "fallback"
                else "_primary_authored_paths"
            )
            if normalized_path not in state[private_field]:
                state[private_field].append(normalized_path)
        state["files_authored_by_primary"] = sorted(state["_primary_authored_paths"])
        state["files_authored_by_fallback"] = sorted(state["_fallback_authored_paths"])
        _persist(key)


@contextmanager
def provider_api_call(
    phase_log_path: pathlib.Path | str | None,
    *,
    stage: str,
    payload_mode: str = "generation",
    transport_retry: bool = False,
) -> Iterator[None]:
    key = _key(phase_log_path)
    began = time.monotonic()
    with _LOCK:
        state = _state(key)
        state["provider_api_call_count"] += 1
        state["primary_provider_calls"] += 1
        if transport_retry:
            state["provider_transport_retries"] += 1
        elif payload_mode == "contract_repair":
            state["provider_contract_repair_calls"] += 1
        elif payload_mode == "completion":
            state["provider_completion_calls"] += 1
        else:
            state["provider_generation_calls"] += 1
        state["_active"] += 1
        state["provider_peak_concurrency"] = max(state["provider_peak_concurrency"], state["_active"])
        _persist(key)
    try:
        yield
    finally:
        elapsed = time.monotonic() - began
        with _LOCK:
            state = _state(key)
            state["_active"] = max(0, int(state["_active"]) - 1)
            timing = state["wall_clock_stage_timing"]
            timing[stage] = round(float(timing.get(stage, 0.0)) + elapsed, 6)
            _persist(key)


@contextmanager
def fallback_provider_call(
    phase_log_path: pathlib.Path | str | None,
    *,
    stage: str,
) -> Iterator[None]:
    key = _key(phase_log_path)
    began = time.monotonic()
    with _LOCK:
        state = _state(key)
        state["fallback_provider_calls"] += 1
        _persist(key)
    try:
        yield
    finally:
        elapsed = time.monotonic() - began
        with _LOCK:
            state = _state(key)
            timing = state["wall_clock_stage_timing"]
            metric = f"fallback:{stage}"
            timing[metric] = round(float(timing.get(metric, 0.0)) + elapsed, 6)
            _persist(key)


def snapshot(phase_log_path: pathlib.Path | str | None) -> dict[str, Any]:
    key = _key(phase_log_path)
    with _LOCK:
        live_state = _state(key)
        _reconcile_phase_log(live_state, key)
        _persist(key)
        state = dict(live_state)
    for private in [item for item in state if item.startswith("_")]:
        state.pop(private, None)
    return state
