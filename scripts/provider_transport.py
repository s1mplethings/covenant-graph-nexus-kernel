from __future__ import annotations

import json
import hashlib
import os
import pathlib
import random
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

PROVIDER_API_CHAT_COMPLETIONS = "chat_completions"
PROVIDER_API_RESPONSES = "responses"
PROVIDER_API_METHODS = {PROVIDER_API_CHAT_COMPLETIONS, PROVIDER_API_RESPONSES}
BLOCKED_API_BUDGET = "BLOCKED_API_BUDGET"


API_BUDGET_PROFILES: dict[str, dict[str, int | float]] = {
    "off": {
        "max_calls_per_run": 0,
        "max_calls_per_agent": 0,
        "max_repair_calls_per_task": 0,
        "max_prompt_chars": 0,
        "max_output_tokens": 0,
        "timeout": 1,
        "retry_cap": 0,
        "concurrency_cap": 0,
    },
    "low": {
        "max_calls_per_run": 6,
        "max_calls_per_agent": 2,
        "max_repair_calls_per_task": 1,
        "max_prompt_chars": 6000,
        "max_output_tokens": 1800,
        "timeout": 30,
        "retry_cap": 1,
        "concurrency_cap": 1,
    },
    "standard": {
        "max_calls_per_run": 20,
        "max_calls_per_agent": 5,
        "max_repair_calls_per_task": 2,
        "max_prompt_chars": 12000,
        "max_output_tokens": 3500,
        "timeout": 60,
        "retry_cap": 2,
        "concurrency_cap": 2,
    },
    "high": {
        "max_calls_per_run": 60,
        "max_calls_per_agent": 10,
        "max_repair_calls_per_task": 3,
        "max_prompt_chars": 24000,
        "max_output_tokens": 7000,
        "timeout": 90,
        "retry_cap": 3,
        "concurrency_cap": 4,
    },
}


REQUEST_TYPE_POLICIES: dict[str, dict[str, int | str]] = {
    "connectivity": {"model_task": "connectivity", "max_output_tokens": 40, "max_prompt_chars": 1200},
    "dialogue_analysis": {"model_task": "planning", "max_output_tokens": 900, "max_prompt_chars": 6000},
    "pipeline_planning": {"model_task": "planning", "max_output_tokens": 1800, "max_prompt_chars": 8000},
    "leaf_generation": {"model_task": "provider_generation", "max_output_tokens": 3500, "max_prompt_chars": 12000},
    "repair": {"model_task": "repair", "max_output_tokens": 2200, "max_prompt_chars": 7000},
    "review": {"model_task": "review", "max_output_tokens": 1200, "max_prompt_chars": 6000},
    "evidence_summary": {"model_task": "review", "max_output_tokens": 900, "max_prompt_chars": 4000},
}


@dataclass(frozen=True)
class ProviderTransportAttempt:
    attempt: int
    ok: bool
    error: str = ""
    error_type: str = ""
    retryable: bool = False
    elapsed_ms: int = 0


@dataclass(frozen=True)
class ProviderTransportResult:
    ok: bool
    doc: dict[str, Any] | None
    error: str
    error_type: str
    attempts: list[ProviderTransportAttempt]
    recovered: bool


def _redact(text: str, token: str = "") -> str:
    safe = str(text or "")
    if token:
        safe = safe.replace(token, "<redacted>")
    safe = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "<redacted>", safe)
    safe = re.sub(r"(Bearer\s+)[A-Za-z0-9_.-]+", r"\1<redacted>", safe, flags=re.IGNORECASE)
    return safe


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_api_budget(value: str | None) -> str:
    profile = str(value or "low").strip().lower()
    return profile if profile in API_BUDGET_PROFILES else "low"


def api_budget_profile(value: str | None) -> dict[str, int | float]:
    return dict(API_BUDGET_PROFILES[normalize_api_budget(value)])


def request_type_policy(request_type: str, budget_profile: str | None = None) -> dict[str, int | str]:
    profile = api_budget_profile(budget_profile)
    policy = dict(REQUEST_TYPE_POLICIES.get(str(request_type or "").strip(), REQUEST_TYPE_POLICIES["leaf_generation"]))
    policy["max_prompt_chars"] = min(int(policy["max_prompt_chars"]), int(profile["max_prompt_chars"]))
    policy["max_output_tokens"] = min(int(policy["max_output_tokens"]), int(profile["max_output_tokens"]))
    return policy


def estimate_tokens(chars: int) -> int:
    return max(1, int((max(0, chars) + 3) / 4))


def _payload_text(payload: dict[str, Any]) -> str:
    if "messages" in payload:
        return json.dumps(payload.get("messages", []), ensure_ascii=False, sort_keys=True)
    if "input" in payload:
        return json.dumps(payload.get("input", ""), ensure_ascii=False, sort_keys=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def request_fingerprint(
    *,
    project_id: str,
    task_id: str,
    agent_id: str,
    request_type: str,
    model: str,
    endpoint_method: str,
    payload: dict[str, Any],
    contract_version: str = "provider_request_governance_v1",
    policy_version: str = "provider_policy_v1",
    context_hash: str = "",
) -> str:
    body = {
        "project_id": project_id,
        "task_id": task_id,
        "agent_id": agent_id,
        "request_type": request_type,
        "model": model,
        "endpoint_method": endpoint_method,
        "payload": payload,
        "contract_version": contract_version,
        "policy_version": policy_version,
        "context_hash": context_hash,
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def build_context_pack(
    *,
    frozen_facts: dict[str, Any] | None = None,
    current_task: dict[str, Any] | None = None,
    allowed_scope: list[str] | None = None,
    required_outputs: list[str] | None = None,
    relevant_dependencies: list[dict[str, Any]] | None = None,
    previous_failure_delta: dict[str, Any] | None = None,
    relevant_file_excerpts: dict[str, str] | None = None,
    acceptance_criteria: list[str] | None = None,
    max_prompt_chars: int | None = None,
    contract_version: str = "context_pack_v1",
) -> dict[str, Any]:
    pack = {
        "contract_version": contract_version,
        "frozen_facts": frozen_facts or {},
        "current_task": current_task or {},
        "allowed_scope": list(allowed_scope or []),
        "required_outputs": list(required_outputs or []),
        "relevant_dependencies": list(relevant_dependencies or []),
        "previous_failure_delta": previous_failure_delta or {},
        "relevant_file_excerpts": {path: str(text)[:3000] for path, text in (relevant_file_excerpts or {}).items()},
        "acceptance_criteria": list(acceptance_criteria or []),
    }
    if max_prompt_chars is not None:
        pack["priority_order"] = [
            "frozen_facts",
            "current_task",
            "allowed_scope",
            "required_outputs",
            "acceptance_criteria",
            "previous_failure_delta",
            "relevant_dependencies",
            "relevant_file_excerpts",
        ]
        pack["prompt"] = render_priority_context_prompt(pack, max_chars=int(max_prompt_chars))
    pack["fingerprint"] = hashlib.sha256(json.dumps(pack, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return pack


def render_priority_context_prompt(pack: dict[str, Any], *, max_chars: int) -> str:
    priority = [
        "frozen_facts",
        "current_task",
        "allowed_scope",
        "required_outputs",
        "acceptance_criteria",
        "previous_failure_delta",
        "relevant_dependencies",
        "relevant_file_excerpts",
    ]
    sections: list[str] = []
    remaining = max(0, int(max_chars))
    for key in priority:
        text = json.dumps({key: pack.get(key)}, ensure_ascii=False, sort_keys=True, default=str)
        if key in {"frozen_facts", "current_task", "allowed_scope", "required_outputs", "acceptance_criteria"}:
            sections.append(text)
            remaining -= len(text)
            continue
        if remaining <= 0:
            continue
        if len(text) > remaining:
            text = text[: max(0, remaining - 20)] + "...[truncated]"
        sections.append(text)
        remaining -= len(text)
    return "\n".join(sections)[: max(0, int(max_chars)) + 500]


def _append_jsonl(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def _write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def usage_ledger_path(run_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(run_dir) / "api_usage_ledger.jsonl"


def api_budget_reservations_path(run_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(run_dir) / "api_budget_reservations.jsonl"


def cache_path(run_dir: str | pathlib.Path, fingerprint: str) -> pathlib.Path:
    return pathlib.Path(run_dir) / "provider_request_cache" / f"{fingerprint}.json"


def circuit_path(run_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(run_dir) / "provider_circuit_state.json"


def readiness_cache_path(run_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(run_dir) / "provider_readiness_cache.json"


def request_counts(run_dir: str | pathlib.Path) -> dict[str, Any]:
    counts: dict[str, Any] = {"total": 0, "by_agent": {}, "repair_by_task": {}}
    for event in _read_jsonl(usage_ledger_path(run_dir)):
        if event.get("cache_hit"):
            continue
        if event.get("result_classification") == BLOCKED_API_BUDGET:
            continue
        counts["total"] += 1
        agent_id = str(event.get("agent_id", ""))
        task_id = str(event.get("task_id", ""))
        counts["by_agent"][agent_id] = int(counts["by_agent"].get(agent_id, 0)) + 1
        if event.get("request_type") == "repair":
            counts["repair_by_task"][task_id] = int(counts["repair_by_task"].get(task_id, 0)) + 1
    reservations: dict[str, dict[str, Any]] = {}
    for event in _read_jsonl(api_budget_reservations_path(run_dir)):
        reservation_id = str(event.get("reservation_id", ""))
        if reservation_id:
            reservations[reservation_id] = event
    for event in reservations.values():
        if event.get("status") != "reserved":
            continue
        counts["total"] += 1
        agent_id = str(event.get("agent_id", ""))
        task_id = str(event.get("task_id", ""))
        counts["by_agent"][agent_id] = int(counts["by_agent"].get(agent_id, 0)) + 1
        if event.get("request_type") == "repair":
            counts["repair_by_task"][task_id] = int(counts["repair_by_task"].get(task_id, 0)) + 1
    return counts


def _iso_age_seconds(value: str) -> float:
    try:
        opened = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - opened).total_seconds())
    except Exception:
        return 0.0


def circuit_state(run_dir: str | pathlib.Path, *, half_open_after_seconds: int = 60) -> dict[str, Any]:
    path = circuit_path(run_dir)
    if not path.exists():
        return {"state": "closed", "reason": "", "opened_at": ""}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "closed", "reason": "", "opened_at": ""}
    if not isinstance(value, dict):
        return {"state": "closed", "reason": "", "opened_at": ""}
    if value.get("state") == "open" and not value.get("half_open_probe_in_progress"):
        age = _iso_age_seconds(str(value.get("opened_at", "")))
        if age >= max(0, int(half_open_after_seconds)):
            out = dict(value)
            out["state"] = "half_open"
            out["age_seconds"] = round(age, 3)
            return out
    return value


def open_circuit(run_dir: str | pathlib.Path, *, reason: str, provider_key: str) -> dict[str, Any]:
    state = {"state": "open", "reason": reason, "provider_key": provider_key, "opened_at": utc_now()}
    _write_json(circuit_path(run_dir), state)
    return state


def reserve_half_open_probe(run_dir: str | pathlib.Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("state") != "half_open":
        return state
    reserved = dict(state)
    reserved["state"] = "half_open"
    reserved["half_open_probe_in_progress"] = True
    reserved["probe_reserved_at"] = utc_now()
    _write_json(circuit_path(run_dir), reserved)
    return reserved


def close_circuit(run_dir: str | pathlib.Path, *, provider_key: str) -> dict[str, Any]:
    state = {"state": "closed", "reason": "", "provider_key": provider_key, "closed_at": utc_now()}
    _write_json(circuit_path(run_dir), state)
    return state


def should_open_circuit(error_type: str) -> bool:
    return error_type in {"PROVIDER_KEY_USAGE_LIMIT", "PROVIDER_METHOD_UNSUPPORTED", "PROVIDER_FORBIDDEN", "PROVIDER_NON_RETRYABLE_HTTP"}


def append_usage_event(
    run_dir: str | pathlib.Path,
    *,
    request_id: str,
    request_fingerprint_value: str = "",
    reservation_id: str = "",
    project_id: str,
    task_id: str,
    agent_id: str,
    request_type: str,
    model: str,
    endpoint_method: str,
    prompt_chars: int,
    requested_output_tokens: int,
    actual_usage: dict[str, Any] | None = None,
    attempt_count: int = 0,
    retry_count: int = 0,
    cache_hit: bool = False,
    circuit_state_value: str = "closed",
    latency_ms: int = 0,
    result_classification: str = "",
    error_type: str = "",
    redacted: bool = True,
) -> dict[str, Any]:
    event = {
        "request_id": request_id,
        "request_fingerprint": request_fingerprint_value,
        "reservation_id": reservation_id,
        "project_id": project_id,
        "task_id": task_id,
        "agent_id": agent_id,
        "request_type": request_type,
        "model": model,
        "endpoint_method": endpoint_method,
        "prompt_chars": int(prompt_chars),
        "estimated_input_tokens": estimate_tokens(int(prompt_chars)),
        "requested_output_tokens": int(requested_output_tokens),
        "actual_usage": actual_usage or {},
        "actual_usage_present": bool(actual_usage),
        "attempt_count": int(attempt_count),
        "retry_count": int(retry_count),
        "cache_hit": bool(cache_hit),
        "circuit_state": circuit_state_value,
        "latency_ms": int(latency_ms),
        "result_classification": result_classification,
        "error_type": error_type,
        "redacted": bool(redacted),
        "created_at": utc_now(),
    }
    safe = json.loads(_redact(json.dumps(event, ensure_ascii=False)))
    _append_jsonl(usage_ledger_path(run_dir), safe)
    return safe


def reserve_api_budget(
    run_dir: str | pathlib.Path,
    *,
    request_id: str,
    api_budget: str,
    agent_id: str,
    task_id: str,
    request_type: str,
    request_fingerprint_value: str,
) -> dict[str, Any]:
    check = guarded_budget_check(run_dir, api_budget=api_budget, agent_id=agent_id, task_id=task_id, request_type=request_type)
    if not check["allowed"]:
        return {**check, "reservation_id": "", "status": "blocked"}
    reservation_id = f"res_{request_id}"
    event = {
        "reservation_id": reservation_id,
        "request_id": request_id,
        "request_fingerprint": request_fingerprint_value,
        "api_budget": normalize_api_budget(api_budget),
        "agent_id": agent_id,
        "task_id": task_id,
        "request_type": request_type,
        "status": "reserved",
        "created_at": utc_now(),
    }
    _append_jsonl(api_budget_reservations_path(run_dir), event)
    return {**check, "reservation_id": reservation_id, "status": "reserved"}


def complete_api_budget_reservation(run_dir: str | pathlib.Path, reservation_id: str, *, status: str = "completed") -> None:
    if not reservation_id:
        return
    _append_jsonl(
        api_budget_reservations_path(run_dir),
        {
            "reservation_id": reservation_id,
            "status": status,
            "created_at": utc_now(),
        },
    )


def _provider_usage(doc: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {}
    usage = doc.get("usage")
    return usage if isinstance(usage, dict) else {}


def guarded_budget_check(
    run_dir: str | pathlib.Path,
    *,
    api_budget: str,
    agent_id: str,
    task_id: str,
    request_type: str,
) -> dict[str, Any]:
    profile_name = normalize_api_budget(api_budget)
    profile = api_budget_profile(profile_name)
    counts = request_counts(run_dir)
    if int(profile["max_calls_per_run"]) <= 0:
        return {"allowed": False, "reason": BLOCKED_API_BUDGET, "profile": profile_name, "limit": "max_calls_per_run"}
    if counts["total"] >= int(profile["max_calls_per_run"]):
        return {"allowed": False, "reason": BLOCKED_API_BUDGET, "profile": profile_name, "limit": "max_calls_per_run"}
    if int(counts["by_agent"].get(agent_id, 0)) >= int(profile["max_calls_per_agent"]):
        return {"allowed": False, "reason": BLOCKED_API_BUDGET, "profile": profile_name, "limit": "max_calls_per_agent"}
    if request_type == "repair" and int(counts["repair_by_task"].get(task_id, 0)) >= int(profile["max_repair_calls_per_task"]):
        return {"allowed": False, "reason": BLOCKED_API_BUDGET, "profile": profile_name, "limit": "max_repair_calls_per_task"}
    return {"allowed": True, "reason": "", "profile": profile_name, "limit": ""}


def _is_gptsapi_base_url(value: str) -> bool:
    root = str(value or "").strip().rstrip("/").lower()
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root in {
        "https://api.gptsapi.net",
        "http://api.gptsapi.net",
        "https://gptsapi.net",
        "http://gptsapi.net",
    }


def normalize_provider_api_method(value: str | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "": "",
        "chat": PROVIDER_API_CHAT_COMPLETIONS,
        "chat_completion": PROVIDER_API_CHAT_COMPLETIONS,
        "chat_completions": PROVIDER_API_CHAT_COMPLETIONS,
        "responses": PROVIDER_API_RESPONSES,
        "response": PROVIDER_API_RESPONSES,
    }
    normalized = aliases.get(text, text)
    if normalized and normalized not in PROVIDER_API_METHODS:
        raise ValueError(f"unsupported provider api method: {value}")
    return normalized


def select_provider_api_method(base_url: str, model: str, requested_method: str | None = None) -> str:
    requested = normalize_provider_api_method(requested_method)
    if requested:
        return requested
    model_name = str(model or "").strip().lower()
    if _is_gptsapi_base_url(base_url):
        if model_name.startswith("gpt-5"):
            return PROVIDER_API_RESPONSES
        return PROVIDER_API_CHAT_COMPLETIONS
    return PROVIDER_API_RESPONSES


def tls_verify_enabled() -> bool:
    raw = str(os.environ.get("CGKN_API_TLS_VERIFY", os.environ.get("OPENAI_TLS_VERIFY", "1"))).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _urlopen(request: urllib.request.Request, timeout_sec: int):
    context = None if tls_verify_enabled() else ssl._create_unverified_context()
    return urllib.request.urlopen(request, timeout=timeout_sec, context=context)


def _safe_response_headers(headers: Any) -> dict[str, str]:
    allowed = {"cf-ray", "x-trace-id", "x-request-id", "request-id", "date", "server"}
    try:
        items = headers.items()
    except Exception:
        return {}
    return {
        str(key).strip().lower(): str(value).strip()[:300]
        for key, value in items
        if str(key).strip().lower() in allowed
    }


def is_retryable_error(error: str) -> bool:
    text = str(error or "")
    lowered = text.lower()
    if "retryable=true" in lowered:
        return True
    if "retryable=false" in lowered:
        return False
    match = re.search(r"http\s+(\d+)", lowered)
    if match:
        code = int(match.group(1))
        return code in {408, 409, 425, 429} or 500 <= code <= 599
    markers = (
        "ssl",
        "unexpected eof",
        "unexpected_eof",
        "connection reset",
        "connectionreseterror",
        "connection aborted",
        "remotedisconnected",
        "urlerror",
        "timeout",
        "timed out",
        "empty response",
    )
    return any(marker in lowered for marker in markers)


def classify_provider_error(error: str) -> str:
    lowered = str(error or "").lower()
    if "key usage limit exceeded" in lowered or "insufficient_quota" in lowered:
        return "PROVIDER_KEY_USAGE_LIMIT"
    method_markers = (
        "does not support this api",
        "call_methods must include",
        "unsupported api",
        "unsupported method",
        "method unsupported",
        "not support this api",
    )
    if any(marker in lowered for marker in method_markers):
        return "PROVIDER_METHOD_UNSUPPORTED"
    if re.search(r"http\s+403\b", lowered):
        return "PROVIDER_FORBIDDEN"
    transport_markers = (
        "sslv3_alert_bad_record_mac",
        "tlsv1_alert_protocol_version",
        "sslerror",
        "[ssl:",
        "unexpected eof",
        "unexpected_eof",
        "connection reset",
        "connectionreseterror",
        "connection aborted",
        "remotedisconnected",
        "urlerror",
        "timeout",
        "timed out",
        "empty response",
        "http 520",
        "http 502",
        "http 503",
        "http 504",
    )
    if any(marker in lowered for marker in transport_markers):
        return "PROVIDER_TRANSPORT_UNSTABLE"
    match = re.search(r"http\s+(\d+)", lowered)
    if match:
        code = int(match.group(1))
        if code in {408, 409, 425, 429} or 500 <= code <= 599:
            return "PROVIDER_RETRYABLE_HTTP"
        return "PROVIDER_NON_RETRYABLE_HTTP"
    if "non-json response" in lowered or "response is not object" in lowered:
        return "PROVIDER_INVALID_RESPONSE"
    return "PROVIDER_UNKNOWN_ERROR"


def post_json_once(
    endpoint: str,
    payload: dict[str, Any],
    token: str,
    timeout_sec: int,
) -> tuple[dict[str, Any] | None, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CGKN-Provider-Transport/1",
            "Connection": "close",
        },
    )
    try:
        with _urlopen(request, timeout_sec) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        host = re.sub(r"^(https?://[^/]+).*", r"\1", endpoint)
        retryable = exc.code in {408, 409, 425, 429} or 500 <= int(exc.code) <= 599
        headers = _safe_response_headers(getattr(exc, "headers", {}))
        header_text = f", provider_headers={json.dumps(headers, ensure_ascii=False, sort_keys=True)}" if headers else ""
        return None, _redact(
            f"HTTP {exc.code}: {detail[:400]} [endpoint={host}, retryable={str(retryable).lower()}{header_text}]",
            token,
        )
    except Exception as exc:
        host = re.sub(r"^(https?://[^/]+).*", r"\1", endpoint)
        detail = str(getattr(exc, "reason", None) or exc)
        error_probe = f"{type(exc).__name__}: {detail}"
        error = (
            f"request failed: {error_probe} "
            f"[endpoint={host}, tls_verify={tls_verify_enabled()}, retryable={str(is_retryable_error(error_probe)).lower()}]"
        )
        return None, _redact(error, token)
    try:
        doc = json.loads(body)
    except Exception as exc:
        return None, _redact(f"non-json response: {exc}", token)
    if not isinstance(doc, dict):
        return None, "response is not object"
    return doc, ""


def post_json_with_retry(
    endpoint: str,
    payload: dict[str, Any],
    token: str,
    timeout_sec: int,
    *,
    max_attempts: int = 3,
    base_delay_sec: float = 1.2,
    sleep_fn: Callable[[float], None] = time.sleep,
    jitter_fn: Callable[[], float] = random.random,
    post_once_fn: Callable[[str, dict[str, Any], str, int], tuple[dict[str, Any] | None, str]] | None = None,
) -> ProviderTransportResult:
    attempts: list[ProviderTransportAttempt] = []
    count = max(1, int(max_attempts))
    last_error = ""
    for attempt in range(1, count + 1):
        started = time.monotonic()
        doc, error = (post_once_fn or post_json_once)(endpoint, payload, token, timeout_sec)
        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
        safe_error = _redact(error, token)
        error_type = "" if doc is not None and not safe_error else classify_provider_error(safe_error)
        retryable = bool(safe_error and is_retryable_error(safe_error))
        attempts.append(
            ProviderTransportAttempt(
                attempt=attempt,
                ok=doc is not None and not safe_error,
                error=safe_error,
                error_type=error_type,
                retryable=retryable,
                elapsed_ms=elapsed_ms,
            )
        )
        if doc is not None and not safe_error:
            return ProviderTransportResult(True, doc, "", "", attempts, recovered=attempt > 1)
        last_error = safe_error or "empty provider response"
        if not retryable or attempt >= count:
            break
        delay = min(5.0, max(0.0, float(base_delay_sec)) * attempt)
        jitter = min(0.2, max(0.0, float(jitter_fn())) * 0.2) if delay else 0.0
        sleep_fn(delay + jitter)
    return ProviderTransportResult(
        False,
        None,
        last_error,
        classify_provider_error(last_error),
        attempts,
        recovered=False,
    )


def governed_post_json_with_retry(
    endpoint: str,
    payload: dict[str, Any],
    token: str,
    timeout_sec: int,
    *,
    run_dir: str | pathlib.Path,
    project_id: str,
    task_id: str,
    agent_id: str,
    request_type: str,
    model: str,
    endpoint_method: str,
    api_budget: str = "low",
    request_id: str | None = None,
    contract_version: str = "provider_request_governance_v1",
    policy_version: str = "provider_policy_v1",
    context_hash: str = "",
    cache_enabled: bool = True,
    cache_ttl_seconds: int = 86400,
    max_attempts: int | None = None,
    base_delay_sec: float = 1.2,
    sleep_fn: Callable[[float], None] = time.sleep,
    jitter_fn: Callable[[], float] = random.random,
    post_once_fn: Callable[[str, dict[str, Any], str, int], tuple[dict[str, Any] | None, str]] | None = None,
) -> ProviderTransportResult:
    run = pathlib.Path(run_dir)
    policy = request_type_policy(request_type, api_budget)
    requested_tokens = int(payload.get("max_output_tokens") or payload.get("max_tokens") or policy["max_output_tokens"] or 0)
    prompt_chars = len(_payload_text(payload))
    fingerprint = request_fingerprint(
        project_id=project_id,
        task_id=task_id,
        agent_id=agent_id,
        request_type=request_type,
        model=model,
        endpoint_method=endpoint_method,
        payload=payload,
        contract_version=contract_version,
        policy_version=policy_version,
        context_hash=context_hash,
    )
    rid = request_id or f"req_{fingerprint[:16]}"
    state = circuit_state(run)
    if state.get("state") == "open":
        append_usage_event(
            run,
            request_id=rid,
            request_fingerprint_value=fingerprint,
            project_id=project_id,
            task_id=task_id,
            agent_id=agent_id,
            request_type=request_type,
            model=model,
            endpoint_method=endpoint_method,
            prompt_chars=prompt_chars,
            requested_output_tokens=requested_tokens,
            cache_hit=False,
            circuit_state_value="open",
            result_classification="BLOCKED_PROVIDER_CIRCUIT_OPEN",
            error_type=str(state.get("reason", "")),
        )
        return ProviderTransportResult(False, None, "BLOCKED_PROVIDER_CIRCUIT_OPEN", str(state.get("reason", "")), [], recovered=False)
    if state.get("state") == "half_open":
        state = reserve_half_open_probe(run, state)
    budget = reserve_api_budget(
        run,
        request_id=rid,
        api_budget=api_budget,
        agent_id=agent_id,
        task_id=task_id,
        request_type=request_type,
        request_fingerprint_value=fingerprint,
    )
    reservation_id = str(budget.get("reservation_id", ""))
    if not budget["allowed"]:
        append_usage_event(
            run,
            request_id=rid,
            request_fingerprint_value=fingerprint,
            project_id=project_id,
            task_id=task_id,
            agent_id=agent_id,
            request_type=request_type,
            model=model,
            endpoint_method=endpoint_method,
            prompt_chars=prompt_chars,
            requested_output_tokens=requested_tokens,
            cache_hit=False,
            circuit_state_value=str(state.get("state", "closed")),
            result_classification=BLOCKED_API_BUDGET,
            error_type=str(budget.get("limit", "")),
        )
        return ProviderTransportResult(False, None, BLOCKED_API_BUDGET, BLOCKED_API_BUDGET, [], recovered=False)
    cache_file = cache_path(run, fingerprint)
    if cache_enabled and request_type != "connectivity" and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cached = {}
        doc = cached.get("doc") if isinstance(cached, dict) else None
        provenance = cached.get("provenance") if isinstance(cached, dict) else {}
        age = _iso_age_seconds(str(cached.get("created_at", ""))) if isinstance(cached, dict) else 999999999.0
        cache_valid = (
            isinstance(cached, dict)
            and cached.get("schema_version") == "provider_cache_v2"
            and cached.get("fingerprint") == fingerprint
            and isinstance(provenance, dict)
            and provenance.get("policy_version") == policy_version
            and age <= max(0, int(cache_ttl_seconds))
        )
        if isinstance(doc, dict) and cache_valid:
            complete_api_budget_reservation(run, reservation_id, status="cache_hit")
            append_usage_event(
                run,
                request_id=rid,
                request_fingerprint_value=fingerprint,
                reservation_id=reservation_id,
                project_id=project_id,
                task_id=task_id,
                agent_id=agent_id,
                request_type=request_type,
                model=model,
                endpoint_method=endpoint_method,
                prompt_chars=prompt_chars,
                requested_output_tokens=requested_tokens,
                actual_usage=_provider_usage(doc),
                attempt_count=0,
                retry_count=0,
                cache_hit=True,
                circuit_state_value=str(state.get("state", "closed")),
                result_classification="cache_hit",
            )
            return ProviderTransportResult(True, doc, "", "", [], recovered=False)
    profile = api_budget_profile(api_budget)
    attempt_cap = int(max_attempts if max_attempts is not None else int(profile["retry_cap"]) + 1)
    attempt_cap = max(1, min(attempt_cap, int(profile["retry_cap"]) + 1))
    started = time.monotonic()
    result = post_json_with_retry(
        endpoint,
        payload,
        token,
        timeout_sec,
        max_attempts=attempt_cap,
        base_delay_sec=base_delay_sec,
        sleep_fn=sleep_fn,
        jitter_fn=jitter_fn,
        post_once_fn=post_once_fn,
    )
    latency_ms = max(0, int((time.monotonic() - started) * 1000))
    if result.ok and result.doc is not None:
        if state.get("state") == "half_open":
            state = close_circuit(run, provider_key=f"{endpoint_method}:{model}")
        if cache_enabled and request_type != "connectivity":
            _write_json(
                cache_file,
                {
                    "schema_version": "provider_cache_v2",
                    "doc": result.doc,
                    "request_id": rid,
                    "fingerprint": fingerprint,
                    "created_at": utc_now(),
                    "provenance": {
                        "project_id": project_id,
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "request_type": request_type,
                        "model": model,
                        "contract_version": contract_version,
                        "policy_version": policy_version,
                        "context_hash": context_hash,
                    },
                },
            )
        complete_api_budget_reservation(run, reservation_id)
        append_usage_event(
            run,
            request_id=rid,
            request_fingerprint_value=fingerprint,
            reservation_id=reservation_id,
            project_id=project_id,
            task_id=task_id,
            agent_id=agent_id,
            request_type=request_type,
            model=model,
            endpoint_method=endpoint_method,
            prompt_chars=prompt_chars,
            requested_output_tokens=requested_tokens,
            actual_usage=_provider_usage(result.doc),
            attempt_count=len(result.attempts),
            retry_count=max(0, len(result.attempts) - 1),
            cache_hit=False,
            circuit_state_value=str(state.get("state", "closed")),
            latency_ms=latency_ms,
            result_classification="ok",
        )
        return result
    if should_open_circuit(result.error_type):
        state = open_circuit(run, reason=result.error_type, provider_key=f"{endpoint_method}:{model}")
    complete_api_budget_reservation(run, reservation_id, status="error")
    append_usage_event(
        run,
        request_id=rid,
        request_fingerprint_value=fingerprint,
        reservation_id=reservation_id,
        project_id=project_id,
        task_id=task_id,
        agent_id=agent_id,
        request_type=request_type,
        model=model,
        endpoint_method=endpoint_method,
        prompt_chars=prompt_chars,
        requested_output_tokens=requested_tokens,
        attempt_count=len(result.attempts),
        retry_count=max(0, len(result.attempts) - 1),
        cache_hit=False,
        circuit_state_value=str(state.get("state", "closed")),
        latency_ms=latency_ms,
        result_classification="error",
        error_type=result.error_type,
    )
    return result


def cached_readiness(
    *,
    run_dir: str | pathlib.Path,
    provider_key: str,
    ttl_seconds: int = 300,
    compute_fn: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    path = readiness_cache_path(run_dir)
    now_ts = time.time()
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cached = {}
        if isinstance(cached, dict) and cached.get("provider_key") == provider_key:
            age = now_ts - float(cached.get("created_ts", 0) or 0)
            if age <= max(0, ttl_seconds):
                doc = dict(cached.get("result") or {})
                doc["readiness_cache_hit"] = True
                return doc
    result = dict(compute_fn())
    result["readiness_cache_hit"] = False
    _write_json(path, {"provider_key": provider_key, "created_ts": now_ts, "created_at": utc_now(), "result": result})
    return result
