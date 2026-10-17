#!/usr/bin/env python3
"""Process-safe external Provider API budget and privacy-safe call ledger."""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator


class ProviderBudgetExhausted(RuntimeError):
    """Raised before transport when a configured run-level API budget is exhausted."""


TERMINAL_CALL_STATES = frozenset(
    {"SUCCEEDED", "FAILED", "INTERRUPTED_UNKNOWN", "CANCELLED_BEFORE_SEND"}
)
NONTERMINAL_CALL_STATES = frozenset(
    {"RESERVED", "REQUEST_STARTED", "RESPONSE_RECEIVED"}
)
PROCESS_INSTANCE_ID = uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _int_env(name: str) -> int | None:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"invalid external Provider budget value: {name}") from exc
    return max(0, value)


def _float_env(name: str) -> float | None:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"invalid external Provider budget value: {name}") from exc
    return max(0.0, value)


def configured_ledger_path() -> pathlib.Path | None:
    raw = str(os.environ.get("CGKN_PROVIDER_BUDGET_LEDGER", "")).strip()
    return pathlib.Path(raw).resolve() if raw else None


def configured_limits() -> dict[str, int | float | None]:
    return {
        "max_api_calls": _int_env("CGKN_PROVIDER_MAX_API_CALLS"),
        "max_planning_calls": _int_env("CGKN_PROVIDER_MAX_PLANNING_CALLS"),
        "max_generation_calls": _int_env("CGKN_PROVIDER_MAX_GENERATION_CALLS"),
        "max_repair_calls": _int_env("CGKN_PROVIDER_MAX_REPAIR_CALLS"),
        "max_benchmark_calls": _int_env("CGKN_PROVIDER_MAX_BENCHMARK_CALLS"),
        "max_auth_probe_calls": _int_env("CGKN_PROVIDER_MAX_AUTH_PROBE_CALLS"),
        "max_capability_build_calls": _int_env("CGKN_PROVIDER_MAX_CAPABILITY_BUILD_CALLS"),
        "max_total_input_tokens": _int_env("CGKN_PROVIDER_MAX_INPUT_TOKENS"),
        "max_total_output_tokens": _int_env("CGKN_PROVIDER_MAX_OUTPUT_TOKENS"),
        "max_estimated_cost": _float_env("CGKN_PROVIDER_MAX_ESTIMATED_COST"),
        "input_cost_per_million": _float_env("CGKN_PROVIDER_INPUT_COST_PER_MILLION"),
        "output_cost_per_million": _float_env("CGKN_PROVIDER_OUTPUT_COST_PER_MILLION"),
    }


def budget_configured() -> bool:
    limits = configured_limits()
    return all(limits[name] is not None for name in (
        "max_api_calls",
        "max_total_input_tokens",
        "max_total_output_tokens",
        "max_estimated_cost",
    ))


def _empty_ledger(limits: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "CGKNExternalProviderCostLedger",
        "schema_version": "1.0",
        "execution_mode": "external_api",
        "created_at": _now(),
        "updated_at": _now(),
        "limits": limits,
        "totals": {
            "api_calls": 0,
            "reserved_calls": 0,
            "started_calls": 0,
            "confirmed_calls": 0,
            "unknown_calls": 0,
            "completed_calls": 0,
            "cancelled_before_send_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "actual_token_usage_complete": True,
            "estimated_cost": 0.0,
        },
        "calls": [],
        "contains_credentials": False,
    }


@contextlib.contextmanager
def _locked(path: pathlib.Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        handle.seek(0)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - exercised on POSIX CI
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - exercised on POSIX CI
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _read(path: pathlib.Path, limits: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return _empty_ledger(limits)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) and isinstance(value.get("calls"), list) else _empty_ledger(limits)


def _write(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _estimated_cost(input_tokens: int, output_tokens: int, limits: dict[str, Any]) -> float:
    input_rate = limits.get("input_cost_per_million")
    output_rate = limits.get("output_cost_per_million")
    if input_rate is None or output_rate is None:
        return 0.0
    return round((input_tokens * float(input_rate) + output_tokens * float(output_rate)) / 1_000_000, 8)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _actual_token(value: Any) -> int | None:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _recompute_totals(ledger: dict[str, Any], limits: dict[str, Any]) -> None:
    calls = [item for item in ledger.get("calls", []) if isinstance(item, dict)]
    active_budget_calls = [
        item for item in calls if str(item.get("status", "")) != "CANCELLED_BEFORE_SEND"
    ]
    actual_inputs = [_actual_token(item.get("input_tokens")) for item in active_budget_calls]
    actual_outputs = [_actual_token(item.get("output_tokens")) for item in active_budget_calls]
    budget_inputs = [
        value if value is not None else int(item.get("reserved_input_tokens", 0) or 0)
        for item, value in zip(active_budget_calls, actual_inputs)
    ]
    budget_outputs = [
        value if value is not None else int(item.get("reserved_output_tokens", 0) or 0)
        for item, value in zip(active_budget_calls, actual_outputs)
    ]
    completed = [item for item in calls if str(item.get("status", "")) in {"SUCCEEDED", "FAILED"}]
    unknown = [item for item in calls if str(item.get("status", "")) == "INTERRUPTED_UNKNOWN"]
    started = [
        item for item in calls
        if str(item.get("status", "")) in {
            "REQUEST_STARTED", "RESPONSE_RECEIVED", "SUCCEEDED", "FAILED", "INTERRUPTED_UNKNOWN"
        }
    ]
    ledger["totals"] = {
        "api_calls": len(active_budget_calls),
        "reserved_calls": sum(str(item.get("status", "")) == "RESERVED" for item in calls),
        "started_calls": len(started),
        "confirmed_calls": len(completed),
        "unknown_calls": len(unknown),
        "completed_calls": len(completed),
        "cancelled_before_send_calls": sum(
            str(item.get("status", "")) == "CANCELLED_BEFORE_SEND" for item in calls
        ),
        "input_tokens": sum(budget_inputs),
        "output_tokens": sum(budget_outputs),
        "actual_input_tokens": sum(value for value in actual_inputs if value is not None),
        "actual_output_tokens": sum(value for value in actual_outputs if value is not None),
        "actual_token_usage_complete": all(value is not None for value in actual_inputs + actual_outputs),
        "estimated_cost": round(
            sum(
                _estimated_cost(input_tokens, output_tokens, limits)
                for input_tokens, output_tokens in zip(budget_inputs, budget_outputs)
            ),
            8,
        ),
    }


def _purpose_family(purpose: str) -> str:
    value = str(purpose or "").strip().upper()
    if value.startswith("BENCHMARK"):
        return "BENCHMARK"
    if value.startswith("AUTH_PROBE"):
        return "AUTH_PROBE"
    if value.startswith("CAPABILITY_BUILD"):
        return "CAPABILITY_BUILD"
    if value.startswith("PLANNING"):
        return "PLANNING"
    if value.startswith("REPAIR"):
        return "REPAIR"
    return "GENERATION"


def call_purpose(stage: str, fallback: str = "") -> str:
    normalized = str(stage or "").strip().lower()
    if normalized in {"requirements_planning", "requirement_replan"}:
        return "PLANNING"
    if "repair" in normalized:
        configured = str(os.environ.get("CGKN_PROVIDER_CALL_PHASE", "")).strip().upper()
        return configured if configured.startswith("REPAIR_") else "REPAIR"
    return "GENERATION" if normalized else str(fallback or "GENERATION").strip().upper()


def reconcile_incomplete_calls(
    path: pathlib.Path | str | None = None,
    *,
    process_alive: Any = None,
) -> dict[str, Any] | None:
    """Close abandoned non-terminal calls without inventing Provider outcomes."""
    ledger_path = pathlib.Path(path).resolve() if path is not None else configured_ledger_path()
    if ledger_path is None:
        return None
    alive = process_alive or _process_alive
    limits = configured_limits()
    with _locked(ledger_path):
        ledger = _read(ledger_path, limits)
        changed = False
        for call in ledger.get("calls", []):
            if not isinstance(call, dict) or str(call.get("status", "")) not in NONTERMINAL_CALL_STATES:
                continue
            owner_pid = int(call.get("owner_pid", 0) or 0)
            if owner_pid and alive(owner_pid):
                continue
            status = str(call.get("status", ""))
            if status == "RESERVED":
                call["status"] = "CANCELLED_BEFORE_SEND"
                call["cancelled_at"] = _now()
                call["terminal_reason"] = "reservation_owner_ended_before_request_started"
            elif status == "REQUEST_STARTED":
                call["status"] = "INTERRUPTED_UNKNOWN"
                call["interrupted_at"] = _now()
                call["terminal_reason"] = "request_owner_ended_without_terminal_response"
                call["input_tokens"] = "TOKEN_USAGE_UNAVAILABLE"
                call["output_tokens"] = "TOKEN_USAGE_UNAVAILABLE"
                call["total_tokens"] = "TOKEN_USAGE_UNAVAILABLE"
                call["estimated_cost"] = "PRICE_NOT_AVAILABLE"
            else:
                call["status"] = "FAILED"
                call["finished_at"] = _now()
                call["terminal_reason"] = "response_received_but_owner_ended_before_finalization"
            changed = True
        _recompute_totals(ledger, limits)
        if changed:
            ledger["updated_at"] = _now()
            ledger["last_reconciliation"] = {"at": _now(), "process_id": os.getpid()}
            _write(ledger_path, ledger)
        return ledger


def reserve_call(
    *,
    case_id: str,
    purpose: str,
    model: str,
    request_identity: str,
    estimated_input_tokens: int,
    requested_output_tokens: int,
    retry_count: int,
    run_id: str | None = None,
    provider: str | None = None,
) -> dict[str, Any] | None:
    """Reserve one live transport call before it is sent."""
    path = configured_ledger_path()
    if path is None:
        return None
    limits = configured_limits()
    if not budget_configured():
        raise ProviderBudgetExhausted("PROVIDER_BUDGET_EXHAUSTED: complete run-level limits are required")
    with _locked(path):
        ledger = _read(path, limits)
        for existing in ledger.get("calls", []):
            if (
                isinstance(existing, dict)
                and existing.get("request_identity") == str(request_identity or "")
                and str(existing.get("status", "")) not in TERMINAL_CALL_STATES
            ):
                raise ProviderBudgetExhausted(
                    "PROVIDER_CALL_IDENTITY_ALREADY_NONTERMINAL: reconcile before retry"
                )
        _recompute_totals(ledger, limits)
        totals = dict(ledger.get("totals", {}))
        next_calls = int(totals.get("api_calls", 0)) + 1
        next_input = int(totals.get("input_tokens", 0)) + max(0, int(estimated_input_tokens))
        next_output = int(totals.get("output_tokens", 0)) + max(0, int(requested_output_tokens))
        next_cost = round(float(totals.get("estimated_cost", 0.0)) + _estimated_cost(
            max(0, int(estimated_input_tokens)), max(0, int(requested_output_tokens)), limits
        ), 8)
        checks = (
            ("max_api_calls", next_calls),
            ("max_total_input_tokens", next_input),
            ("max_total_output_tokens", next_output),
            ("max_estimated_cost", next_cost),
        )
        purpose_family = _purpose_family(purpose)
        family_limit_name = {
            "PLANNING": "max_planning_calls",
            "GENERATION": "max_generation_calls",
            "REPAIR": "max_repair_calls",
            "BENCHMARK": "max_benchmark_calls",
            "AUTH_PROBE": "max_auth_probe_calls",
            "CAPABILITY_BUILD": "max_capability_build_calls",
        }[purpose_family]
        family_calls = sum(
            _purpose_family(str(item.get("purpose", ""))) == purpose_family
            and str(item.get("status", "")) != "CANCELLED_BEFORE_SEND"
            for item in ledger.get("calls", [])
        ) + 1
        checks = (*checks, (family_limit_name, family_calls))
        exceeded = [name for name, value in checks if limits.get(name) is not None and value > limits[name]]
        if exceeded:
            ledger["updated_at"] = _now()
            ledger["last_block"] = {"at": _now(), "case_id": case_id, "purpose": purpose, "limits": exceeded}
            _write(path, ledger)
            raise ProviderBudgetExhausted("PROVIDER_BUDGET_EXHAUSTED: " + ",".join(exceeded))
        call = {
            "call_id": uuid.uuid4().hex,
            "run_id": str(run_id if run_id is not None else os.environ.get("CGKN_BENCHMARK_RUN_ID", "")),
            "case_id": str(case_id or ""),
            "purpose": str(purpose or "provider_call"),
            "provider": str(provider if provider is not None else (os.environ.get("CGKN_PROVIDER_NAME", "qwen") or "qwen")),
            "model": str(model or ""),
            "reserved_at": _now(),
            "request_started_at": None,
            "response_received_at": None,
            "duration_seconds": None,
            "reserved_input_tokens": max(0, int(estimated_input_tokens)),
            "reserved_output_tokens": max(0, int(requested_output_tokens)),
            "input_tokens": "TOKEN_USAGE_UNAVAILABLE",
            "output_tokens": "TOKEN_USAGE_UNAVAILABLE",
            "total_tokens": "TOKEN_USAGE_UNAVAILABLE",
            "http_status": None,
            "retry_count": max(0, int(retry_count)),
            "estimated_cost": _estimated_cost(estimated_input_tokens, requested_output_tokens, limits),
            "request_identity": str(request_identity or ""),
            "call_mode": "LIVE_CALL",
            "status": "RESERVED",
            "owner_pid": os.getpid(),
            "owner_process_instance_id": PROCESS_INSTANCE_ID,
        }
        ledger["limits"] = limits
        ledger["calls"].append(call)
        _recompute_totals(ledger, limits)
        ledger["updated_at"] = _now()
        _write(path, ledger)
        return {"path": str(path), "call_id": call["call_id"], "started_monotonic": time.monotonic()}


def mark_request_started(reservation: dict[str, Any] | None) -> None:
    if not reservation:
        return
    path = pathlib.Path(str(reservation["path"]))
    with _locked(path):
        limits = configured_limits()
        ledger = _read(path, limits)
        target = next((item for item in ledger["calls"] if item.get("call_id") == reservation["call_id"]), None)
        if target is None or target.get("status") != "RESERVED":
            raise RuntimeError("provider call must be RESERVED before REQUEST_STARTED")
        target["status"] = "REQUEST_STARTED"
        target["request_started_at"] = _now()
        target["owner_pid"] = os.getpid()
        target["owner_process_instance_id"] = PROCESS_INSTANCE_ID
        _recompute_totals(ledger, limits)
        ledger["updated_at"] = _now()
        _write(path, ledger)


def mark_response_received(
    reservation: dict[str, Any] | None,
    *,
    response: dict[str, Any] | None,
    http_status: int | str | None,
) -> None:
    if not reservation:
        return
    path = pathlib.Path(str(reservation["path"]))
    with _locked(path):
        limits = configured_limits()
        ledger = _read(path, limits)
        target = next((item for item in ledger["calls"] if item.get("call_id") == reservation["call_id"]), None)
        if target is None or target.get("status") != "REQUEST_STARTED":
            raise RuntimeError("provider call must be REQUEST_STARTED before RESPONSE_RECEIVED")
        target["status"] = "RESPONSE_RECEIVED"
        target["response_received_at"] = _now()
        target["duration_seconds"] = round(time.monotonic() - float(reservation["started_monotonic"]), 6)
        target["http_status"] = http_status
        request_id = str((response or {}).get("id", "")).strip()
        if request_id:
            target["provider_request_id"] = request_id
        actual_input, actual_output = _usage_tokens((response or {}).get("usage", {}))
        if actual_input is not None:
            target["input_tokens"] = actual_input
        if actual_output is not None:
            target["output_tokens"] = actual_output
        if actual_input is not None and actual_output is not None:
            target["total_tokens"] = actual_input + actual_output
        _recompute_totals(ledger, limits)
        ledger["updated_at"] = _now()
        _write(path, ledger)


def _usage_tokens(usage: dict[str, Any] | None) -> tuple[int | None, int | None]:
    doc = usage if isinstance(usage, dict) else {}
    input_value = doc.get("input_tokens", doc.get("prompt_tokens"))
    output_value = doc.get("output_tokens", doc.get("completion_tokens"))
    try:
        input_tokens = int(input_value) if input_value is not None else None
    except (TypeError, ValueError):
        input_tokens = None
    try:
        output_tokens = int(output_value) if output_value is not None else None
    except (TypeError, ValueError):
        output_tokens = None
    return input_tokens, output_tokens


def finalize_call(
    reservation: dict[str, Any] | None,
    *,
    usage: dict[str, Any] | None,
    http_status: int | str | None,
    status: str,
) -> None:
    if not reservation:
        return
    path = pathlib.Path(str(reservation["path"]))
    call_id = str(reservation["call_id"])
    with _locked(path):
        limits = configured_limits()
        ledger = _read(path, limits)
        target = next((item for item in ledger["calls"] if item.get("call_id") == call_id), None)
        if target is None:
            return
        prior_status = str(target.get("status", ""))
        if prior_status == "RESERVED":
            target["status"] = "CANCELLED_BEFORE_SEND"
            target["cancelled_at"] = _now()
            target["terminal_reason"] = "transport_not_started"
            target["input_tokens"] = "TOKEN_USAGE_UNAVAILABLE"
            target["output_tokens"] = "TOKEN_USAGE_UNAVAILABLE"
            target["total_tokens"] = "TOKEN_USAGE_UNAVAILABLE"
            target["estimated_cost"] = "PRICE_NOT_AVAILABLE"
            _recompute_totals(ledger, limits)
            ledger["updated_at"] = _now()
            _write(path, ledger)
            return
        actual_input, actual_output = _usage_tokens(usage)
        if actual_input is not None:
            target["input_tokens"] = max(0, actual_input)
        if actual_output is not None:
            target["output_tokens"] = max(0, actual_output)
        if actual_input is not None and actual_output is not None:
            target["total_tokens"] = actual_input + actual_output
            target["estimated_cost"] = _estimated_cost(actual_input, actual_output, limits)
        else:
            target["input_tokens"] = "TOKEN_USAGE_UNAVAILABLE"
            target["output_tokens"] = "TOKEN_USAGE_UNAVAILABLE"
            target["total_tokens"] = "TOKEN_USAGE_UNAVAILABLE"
            target["estimated_cost"] = "PRICE_NOT_AVAILABLE"
        target["duration_seconds"] = round(time.monotonic() - float(reservation["started_monotonic"]), 6)
        target["http_status"] = http_status
        requested_status = str(status or "FAILED").upper()
        target["status"] = "SUCCEEDED" if requested_status in {"PASS", "SUCCEEDED"} else "FAILED"
        target["finished_at"] = _now()
        _recompute_totals(ledger, limits)
        ledger["updated_at"] = _now()
        _write(path, ledger)


def http_status_from_error(error: str) -> int | None:
    match = re.search(r"\bHTTP\s+(\d{3})\b", str(error or ""), flags=re.I)
    return int(match.group(1)) if match else None


def configured_cache_mode() -> str:
    mode = str(os.environ.get("CGKN_PROVIDER_CACHE_MODE", "off")).strip().lower() or "off"
    if mode not in {"off", "read_write", "replay_only"}:
        raise RuntimeError("invalid external Provider cache mode")
    return mode


def _cache_path(request_identity: str) -> pathlib.Path | None:
    root = str(os.environ.get("CGKN_PROVIDER_RESPONSE_CACHE_DIR", "")).strip()
    if not root:
        return None
    identity = str(request_identity or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise RuntimeError("external Provider cache identity must be SHA-256")
    return pathlib.Path(root).resolve() / identity[:2] / f"{identity}.json"


def load_cached_response(request_identity: str) -> dict[str, Any] | None:
    """Load an exact response replay without counting it as a live API call."""
    mode = configured_cache_mode()
    path = _cache_path(request_identity)
    if mode == "off" or path is None or not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if envelope.get("request_identity") != request_identity or envelope.get("call_mode") != "CACHE_REPLAY":
        return None
    response = envelope.get("response")
    return dict(response) if isinstance(response, dict) else None


def store_cached_response(request_identity: str, response: dict[str, Any]) -> None:
    """Persist an exact Provider response only when read-write cache is explicit."""
    if configured_cache_mode() != "read_write":
        return
    path = _cache_path(request_identity)
    if path is None:
        return
    with _locked(path):
        _write(path, {
            "kind": "CGKNExternalProviderResponseCacheEntry",
            "schema_version": "1.0",
            "request_identity": request_identity,
            "call_mode": "CACHE_REPLAY",
            "created_at": _now(),
            "response": response,
            "contains_credentials": False,
        })

