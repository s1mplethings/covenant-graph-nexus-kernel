#!/usr/bin/env python3
"""Auditable file-backed Provider transport for Codex surrogate and replay modes.

This module is a transport adapter only.  It neither schedules project work nor
materializes candidates.  The production scheduler continues to call
``provider_text``; that boundary delegates here when a non-live mode was chosen.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


PROVIDER_MODES = ("live", "codex_surrogate", "deterministic_replay")
SCHEMA_VERSION = "1.0"
HANDSHAKE_DIR = pathlib.Path("artifacts") / "provider_handshake"
_LOCK = threading.RLock()
_CONTEXT: "AdapterContext | None" = None


class SurrogateResponseRequired(BaseException):
    """Control-flow signal that safely returns ownership to the Codex caller."""

    def __init__(self, request_path: pathlib.Path):
        super().__init__(f"WAITING_SURROGATE_RESPONSE:{request_path}")
        self.request_path = request_path


class SurrogateSubmissionError(ValueError):
    pass


@dataclass(frozen=True)
class AdapterContext:
    mode: str
    run_dir: pathlib.Path
    run_id: str
    project_id: str
    source_sha: str
    benchmark_hash: str = ""
    replay_dir: pathlib.Path | None = None

    @property
    def root(self) -> pathlib.Path:
        return self.run_dir / HANDSHAKE_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _write_json(path: pathlib.Path, value: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    )
    temporary = pathlib.Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SurrogateSubmissionError(f"invalid JSON envelope: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SurrogateSubmissionError(f"JSON object envelope required: {path}")
    return value


def _safe_id(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", text):
        raise SurrogateSubmissionError(f"unsafe {field}")
    return text


def _safe_relative_path(value: Any) -> bool:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", raw):
        return False
    return ".." not in pathlib.PurePosixPath(raw).parts


def _payload_security_error(payload: Any) -> str:
    candidate = payload
    if isinstance(payload, str):
        try:
            candidate = json.loads(payload)
        except ValueError:
            candidate = None
    if isinstance(candidate, dict):
        if candidate.get("modify_cgkn_kernel") is True or candidate.get("kernel_write_authorized") is True:
            return "payload requests a CGKN kernel modification"
        files = candidate.get("files", [])
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                raw_path = item.get("path", "")
                if not _safe_relative_path(raw_path):
                    return f"unsafe candidate path: {raw_path}"
                normalized = str(raw_path).replace("\\", "/").lower()
                if normalized.startswith((".cgkn/", "cgkn/", "d:/cgkn/")):
                    return f"kernel path is outside Provider candidate ownership: {raw_path}"
    return ""


def configure(
    *, mode: str, run_dir: pathlib.Path, run_id: str, project_id: str,
    source_sha: str, benchmark_hash: str = "", replay_dir: pathlib.Path | None = None,
) -> AdapterContext:
    global _CONTEXT
    normalized = str(mode or "live").strip().lower()
    if normalized not in PROVIDER_MODES:
        raise ValueError(f"unsupported provider_mode: {normalized}")
    if normalized != "deterministic_replay" and replay_dir is not None:
        raise ValueError("replay_dir is valid only for deterministic_replay")
    context = AdapterContext(
        mode=normalized,
        run_dir=pathlib.Path(run_dir).resolve(),
        run_id=_safe_id(run_id, "run_id"),
        project_id=_safe_id(project_id, "project_id"),
        source_sha=str(source_sha or "unknown"),
        benchmark_hash=str(benchmark_hash or ""),
        replay_dir=pathlib.Path(replay_dir).resolve() if replay_dir else None,
    )
    with _LOCK:
        _CONTEXT = context
        if normalized != "live":
            context.root.mkdir(parents=True, exist_ok=True)
            state_path = context.root / "provider_mode_state.json"
            if state_path.exists():
                state = _read_json(state_path)
                immutable = ("run_id", "project_id", "provider_mode")
                expected = {
                    "run_id": context.run_id,
                    "project_id": context.project_id,
                    "provider_mode": context.mode,
                }
                if any(state.get(key) != expected[key] for key in immutable):
                    raise ValueError("provider mode state does not match the resumed run")
            else:
                _write_json(state_path, {
                    "kind": "CGKNProviderModeState",
                    "schema_version": SCHEMA_VERSION,
                    "run_id": context.run_id,
                    "project_id": context.project_id,
                    "provider_mode": context.mode,
                    "provider_schedulers": 1,
                    "real_provider_calls": 0,
                    "network_attempts": 0,
                    "created_at": _now(),
                })
    return context


def current() -> AdapterContext | None:
    return _CONTEXT


def _logical_job_id(stage: str, component: str, target_file: str, requested_role: str) -> str:
    label = "|".join((stage, component, target_file, requested_role))
    return f"job-{stable_hash(label)[:24]}"


def _request_paths(context: AdapterContext, job_id: str) -> list[pathlib.Path]:
    directory = context.root / "requests"
    return sorted(directory.glob(f"{job_id}.attempt-*.json")) if directory.exists() else []


def _response_path(context: AdapterContext, job_id: str, attempt_id: str) -> pathlib.Path:
    return context.root / "responses" / f"{job_id}.{attempt_id}.json"


def _consumption_path(context: AdapterContext, job_id: str, attempt_id: str) -> pathlib.Path:
    return context.root / "consumed" / f"{job_id}.{attempt_id}.json"


def _receipt_path(context: AdapterContext, job_id: str, attempt_id: str) -> pathlib.Path:
    return context.root / "receipts" / f"{job_id}.{attempt_id}.json"


def _validate_expected_payload(payload: Any, schema: dict[str, Any]) -> bool:
    expected = schema.get("type")
    if expected == "string":
        return isinstance(payload, str)
    if expected == "object":
        return isinstance(payload, dict)
    if expected == "array":
        return isinstance(payload, list)
    return payload is not None


def _find_or_create_request(
    context: AdapterContext,
    *, messages: list[dict[str, str]], stage: str, component: str,
    target_file: str, requested_role: str, expected_response_schema: dict[str, Any],
) -> tuple[dict[str, Any], pathlib.Path]:
    job_id = _logical_job_id(stage, component, target_file, requested_role)
    context_doc = {
        "messages": messages,
        "stage": stage,
        "component": component,
        "target_file": target_file,
    }
    context_hash = stable_hash(context_doc)
    existing = _request_paths(context, job_id)
    for path in existing:
        request = _read_json(path)
        if request.get("context_hashes", {}).get("provider_messages") == context_hash:
            return request, path
    # Restarted orchestration may rebuild contextual indexes around the same
    # scheduler-owned attempt.  A pending or accepted-but-not-yet-consumed
    # attempt remains authoritative and must be resumed before any new attempt
    # can be created from the refreshed projection.
    for path in reversed(existing):
        request = _read_json(path)
        response_path = _response_path(context, str(request["job_id"]), str(request["attempt_id"]))
        consumed_path = _consumption_path(context, str(request["job_id"]), str(request["attempt_id"]))
        if not response_path.exists() or not consumed_path.exists():
            return request, path
    attempt_number = len(existing) + 1
    attempt_id = f"attempt-{attempt_number}"
    context_path = context.root / "contexts" / f"{job_id}.{attempt_id}.json"
    _write_json(context_path, context_doc)
    envelope: dict[str, Any] = {
        "kind": "CGKNProviderJobRequest",
        "schema_version": SCHEMA_VERSION,
        "run_id": context.run_id,
        "project_id": context.project_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "stage": stage,
        "provider_mode": context.mode,
        "requested_role": requested_role,
        "request_schema": {"type": "object", "required": ["messages", "stage"]},
        "expected_response_schema": expected_response_schema,
        "context_refs": [context_path.relative_to(context.run_dir).as_posix()],
        "context_hashes": {"provider_messages": context_hash},
        "source_sha": context.source_sha,
        "benchmark_hash": context.benchmark_hash,
        "created_at": _now(),
    }
    envelope["request_hash"] = stable_hash(envelope)
    path = context.root / "requests" / f"{job_id}.attempt-{attempt_number:04d}.json"
    _write_json(path, envelope)
    return envelope, path


def _load_response_for_request(context: AdapterContext, request: dict[str, Any]) -> dict[str, Any] | None:
    job_id = str(request["job_id"])
    attempt_id = str(request["attempt_id"])
    canonical_path = _response_path(context, job_id, attempt_id)
    if canonical_path.exists():
        return _read_json(canonical_path)
    if context.mode == "deterministic_replay" and context.replay_dir is not None:
        replay_path = context.replay_dir / f"{job_id}.{attempt_id}.json"
        if replay_path.is_file():
            response = _read_json(replay_path)
            receipt = submit_response(context.run_dir, response, expected_mode="deterministic_replay")
            if not receipt["accepted"]:
                raise SurrogateSubmissionError(str(receipt["rejection_reason"]))
            return _read_json(canonical_path)
    return None


def provider_text(
    messages: list[dict[str, str]], *, stage: str, component: str = "",
    target_file: str = "", requested_role: str = "provider",
) -> str:
    context = _CONTEXT
    if context is None or context.mode == "live":
        raise RuntimeError("surrogate adapter is not active")
    with _LOCK:
        request, request_path = _find_or_create_request(
            context,
            messages=messages,
            stage=str(stage or "provider_text"),
            component=str(component or ""),
            target_file=str(target_file or ""),
            requested_role=str(requested_role or "provider"),
            expected_response_schema={"type": "string", "minLength": 1},
        )
        response = _load_response_for_request(context, request)
        if response is None:
            if context.mode == "deterministic_replay":
                raise SurrogateSubmissionError(f"deterministic replay response missing: {request['job_id']}:{request['attempt_id']}")
            raise SurrogateResponseRequired(request_path)
        consumption_path = _consumption_path(context, str(request["job_id"]), str(request["attempt_id"]))
        if not consumption_path.exists():
            _write_json(consumption_path, {
                "kind": "CGKNProviderResponseConsumption",
                "schema_version": SCHEMA_VERSION,
                "run_id": context.run_id,
                "project_id": context.project_id,
                "job_id": request["job_id"],
                "attempt_id": request["attempt_id"],
                "stage": request["stage"],
                "provider_mode": context.mode,
                "request_hash": request["request_hash"],
                "payload_hash": response["payload_hash"],
                "consumed_once": True,
                "consumed_at": _now(),
            })
            with (context.root / "accounting.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(_canonical({
                    "run_id": context.run_id,
                    "project_id": context.project_id,
                    "job_id": request["job_id"],
                    "attempt_id": request["attempt_id"],
                    "stage": request["stage"],
                    "provider_mode": context.mode,
                    "real_provider_calls": 0,
                    "network_attempts": 0,
                    "surrogate_response_consumed": 1,
                }) + "\n")
        payload = response["payload"]
        return payload if isinstance(payload, str) else _canonical(payload)


def _locate_request(run_dir: pathlib.Path, job_id: str, attempt_id: str) -> tuple[dict[str, Any], pathlib.Path]:
    root = pathlib.Path(run_dir).resolve() / HANDSHAKE_DIR
    matches = list((root / "requests").glob(f"{_safe_id(job_id, 'job_id')}.attempt-*.json"))
    for path in matches:
        request = _read_json(path)
        if request.get("attempt_id") == attempt_id:
            return request, path
    raise SurrogateSubmissionError("orphan response: scheduler-created request not found")


def submit_response(
    run_dir: pathlib.Path, response: dict[str, Any], *, expected_mode: str = "codex_surrogate",
) -> dict[str, Any]:
    """Validate and atomically accept one response; rejected attempts also get receipts."""
    resolved_run = pathlib.Path(run_dir).resolve()
    root = resolved_run / HANDSHAKE_DIR
    state = _read_json(root / "provider_mode_state.json")
    job_id = _safe_id(str(response.get("job_id", "")), "job_id")
    attempt_id = _safe_id(str(response.get("attempt_id", "")), "attempt_id")
    request, _ = _locate_request(resolved_run, job_id, attempt_id)
    required = {
        "schema_version", "run_id", "project_id", "job_id", "attempt_id", "stage",
        "provider_mode", "surrogate_identity", "request_hash", "payload", "payload_hash", "created_at",
    }
    schema_valid = required.issubset(response) and response.get("schema_version") == SCHEMA_VERSION
    identity_valid = all(response.get(key) == request.get(key) for key in (
        "run_id", "project_id", "job_id", "attempt_id", "stage", "provider_mode",
    )) and response.get("provider_mode") == expected_mode == state.get("provider_mode")
    request_hash_valid = response.get("request_hash") == request.get("request_hash")
    payload_hash_valid = response.get("payload_hash") == stable_hash(response.get("payload"))
    payload_schema_valid = _validate_expected_payload(
        response.get("payload"), request.get("expected_response_schema", {})
    )
    security_error = _payload_security_error(response.get("payload"))
    canonical_response = _response_path(
        AdapterContext(
            mode=str(state["provider_mode"]), run_dir=resolved_run,
            run_id=str(state["run_id"]), project_id=str(state["project_id"]),
            source_sha=str(request.get("source_sha", "")),
        ), job_id, attempt_id,
    )
    duplicate = canonical_response.exists()
    rejection = ""
    if duplicate:
        existing = _read_json(canonical_response)
        if existing.get("payload_hash") != response.get("payload_hash"):
            rejection = "different duplicate response for a closed job"
    elif not schema_valid:
        rejection = "response schema mismatch"
    elif not identity_valid:
        rejection = "run/project/job/attempt/stage/provider identity mismatch"
    elif not request_hash_valid:
        rejection = "request hash mismatch"
    elif not payload_hash_valid:
        rejection = "payload hash mismatch"
    elif not payload_schema_valid:
        rejection = "payload does not match expected response schema"
    elif security_error:
        rejection = security_error
    accepted = not rejection
    receipt = {
        "kind": "CGKNProviderResponseReceipt",
        "schema_version": SCHEMA_VERSION,
        "run_id": request["run_id"],
        "project_id": request["project_id"],
        "job_id": job_id,
        "attempt_id": attempt_id,
        "stage": request["stage"],
        "provider_mode": request["provider_mode"],
        "accepted": accepted,
        "rejection_reason": rejection,
        "schema_valid": schema_valid and payload_schema_valid,
        "identity_valid": identity_valid,
        "request_hash_valid": request_hash_valid,
        "payload_hash_valid": payload_hash_valid,
        "duplicate": duplicate,
        "submitted_at": _now(),
    }
    with _LOCK:
        if accepted and not duplicate:
            _write_json(canonical_response, response)
        receipt_path = _receipt_path(
            AdapterContext(
                mode=str(state["provider_mode"]), run_dir=resolved_run,
                run_id=str(state["run_id"]), project_id=str(state["project_id"]), source_sha="",
            ), job_id, attempt_id,
        )
        if duplicate or receipt_path.exists() and not accepted:
            suffix = stable_hash({"response": response, "submitted_at": receipt["submitted_at"]})[:12]
            receipt_path = receipt_path.with_name(f"{receipt_path.stem}.{suffix}.json")
        _write_json(receipt_path, receipt)
    return receipt


def build_response(request: dict[str, Any], payload: Any, *, surrogate_identity: str = "codex") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": request["run_id"],
        "project_id": request["project_id"],
        "job_id": request["job_id"],
        "attempt_id": request["attempt_id"],
        "stage": request["stage"],
        "provider_mode": request["provider_mode"],
        "surrogate_identity": _safe_id(surrogate_identity, "surrogate_identity"),
        "request_hash": request["request_hash"],
        "payload": payload,
        "payload_hash": stable_hash(payload),
        "created_at": _now(),
    }


def status(run_dir: pathlib.Path) -> dict[str, Any]:
    resolved = pathlib.Path(run_dir).resolve()
    root = resolved / HANDSHAKE_DIR
    if not root.exists():
        return {"provider_mode": "live", "waiting": False, "requests": [], "accounting": []}
    state = _read_json(root / "provider_mode_state.json")
    requests: list[dict[str, Any]] = []
    for path in sorted((root / "requests").glob("*.json")):
        request = _read_json(path)
        response_path = root / "responses" / f"{request['job_id']}.{request['attempt_id']}.json"
        consumed_path = root / "consumed" / f"{request['job_id']}.{request['attempt_id']}.json"
        requests.append({
            "request_path": str(path),
            "response_path": str(response_path),
            "job_id": request["job_id"],
            "attempt_id": request["attempt_id"],
            "stage": request["stage"],
            "request_hash": request["request_hash"],
            "responded": response_path.exists(),
            "consumed": consumed_path.exists(),
        })
    accounting: list[dict[str, Any]] = []
    accounting_path = root / "accounting.jsonl"
    if accounting_path.exists():
        for line in accounting_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                accounting.append(item)
    return {
        **state,
        "waiting": any(not item["responded"] for item in requests),
        "requests": requests,
        "accounting": accounting,
        "accepted_attempts": sum(1 for item in requests if item["responded"]),
        "consumed_attempts": sum(1 for item in requests if item["consumed"]),
    }


def waiting_result(*, run_dir: pathlib.Path, result_path: pathlib.Path, goal: str, project_dir: pathlib.Path) -> dict[str, Any]:
    report = status(run_dir)
    result = {
        "kind": "RuntimeExecutionResult",
        "status": "WAITING_SURROGATE_RESPONSE",
        "workflow_state": "WAITING_SURROGATE_RESPONSE",
        "formal_evidence_status": "NOT_EVALUATED",
        "generated_at": _now(),
        "goal": goal,
        "project_dir": str(pathlib.Path(project_dir).resolve()),
        "run_dir": str(pathlib.Path(run_dir).resolve()),
        "provider_mode": report.get("provider_mode", "codex_surrogate"),
        "provider_schedulers": 1,
        "real_provider_calls": 0,
        "network_attempts": 0,
        "pending_requests": [item for item in report.get("requests", []) if not item.get("responded")],
        "message": "Submit every pending canonical response, then resume this same run.",
    }
    _write_json(pathlib.Path(result_path).resolve(), result)
    return result
