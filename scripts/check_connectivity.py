#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Any

try:
    from . import model_policy
except ImportError:  # pragma: no cover - script execution path
    import model_policy  # type: ignore


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "examples" / "test_results" / "connectivity_check_result.json"
DEFAULT_NOTES_PATH = ROOT / ".agent_private" / "NOTES.md"
EMBEDDED_BASE_URL = "https://api.gptsapi.net/v1"
DEFAULT_TEST_MODEL = model_policy.select_model("connectivity")
PROVIDER_PROBE_MAX_OUTPUT_TOKENS = 128
_TRANSPORT_TIMING = threading.local()


def _set_last_transport_timing(value: dict[str, Any]) -> None:
    _TRANSPORT_TIMING.value = dict(value)


def last_transport_timing() -> dict[str, Any]:
    """Return redacted phase timing for the latest request on this worker thread."""
    value = getattr(_TRANSPORT_TIMING, "value", {})
    return dict(value) if isinstance(value, dict) else {}


def _write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mask_secret(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 10:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def _normalize_base_url(value: str) -> str:
    root = str(value or "").strip().rstrip("/")
    return root


def _is_gptsapi_base_url(value: str) -> bool:
    root = _normalize_base_url(value).lower()
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root in {
        "https://api.gptsapi.net",
        "http://api.gptsapi.net",
        "https://gptsapi.net",
        "http://gptsapi.net",
    }


def _is_alibaba_model_studio_base_url(value: str) -> bool:
    hostname = str(urlparse(_normalize_base_url(value)).hostname or "").lower()
    return hostname in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"} or hostname.endswith(
        ".maas.aliyuncs.com"
    )


def _supports_alibaba_qwen_reasoning_none(model: str) -> bool:
    """Return whether the qualified Alibaba Qwen family accepts explicit no-reasoning."""
    return bool(re.match(r"^qwen3\.(?:5|6|7|8)(?:[-.]|$)", str(model or "").strip().lower()))


def _join_endpoint(base_url: str, path: str) -> str:
    root = _normalize_base_url(base_url)
    suffix = "/" + str(path or "").lstrip("/")
    root_lower = root.lower()
    suffix_lower = suffix.lower()
    if root_lower.endswith("/v1") and suffix_lower.startswith("/v1/"):
        suffix = suffix[3:]
    if _is_gptsapi_base_url(root) and not root_lower.endswith("/v1") and not suffix_lower.startswith("/v1/"):
        suffix = "/v1" + suffix
    return root.rstrip("/") + suffix


def _chat_completions_endpoint(base_url: str) -> str:
    return _join_endpoint(base_url, "/chat/completions")


def _responses_endpoint(base_url: str) -> str:
    return _join_endpoint(base_url, "/responses")


def _selected_provider_api_method(base_url: str, model: str = "") -> str:
    del model
    return "chat_completions" if _is_gptsapi_base_url(base_url) else "responses"


def _endpoint_mode_from_method(method: str) -> str:
    return "chat" if method == "chat_completions" else "responses"


def _base_url_domain(base_url: str) -> str:
    return urlparse(str(base_url)).netloc


def _openai_compatible_endpoint(base_url: str, model: str = "", requested_method: str = "") -> str:
    method = str(requested_method or "").strip() or _selected_provider_api_method(base_url, model)
    return _chat_completions_endpoint(base_url) if method == "chat_completions" else _responses_endpoint(base_url)


def _messages_to_input(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{item.get('role', 'user')}: {item.get('content', '')}"
        for item in messages
        if isinstance(item, dict)
    )


def _build_openai_compatible_payload(
    base_url: str,
    payload: dict[str, Any],
    model: str = "",
    *,
    reasoning_effort: str = "",
) -> dict[str, Any]:
    request_payload = dict(payload)
    if _is_gptsapi_base_url(base_url):
        if "input" in request_payload and "messages" not in request_payload:
            request_payload["messages"] = [{"role": "user", "content": str(request_payload.pop("input"))}]
        if "max_output_tokens" in request_payload and "max_tokens" not in request_payload:
            request_payload["max_tokens"] = request_payload.pop("max_output_tokens")
        request_payload.pop("input", None)
    else:
        if "messages" in request_payload and "input" not in request_payload:
            request_payload["input"] = _messages_to_input(request_payload.pop("messages"))
        if "max_tokens" in request_payload and "max_output_tokens" not in request_payload:
            request_payload["max_output_tokens"] = request_payload.pop("max_tokens")
        request_payload.pop("messages", None)
        effort = str(reasoning_effort or "").strip().lower()
        if (
            effort
            and _is_alibaba_model_studio_base_url(base_url)
            and _supports_alibaba_qwen_reasoning_none(model)
        ):
            request_payload["reasoning"] = {"effort": effort}
    return request_payload


def _build_provider_probe_payload(base_url: str, model: str, *, structured: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Reply with exactly one JSON object and no markdown or commentary. "
                    "Use only keys cgkn_probe, project, patch. cgkn_probe must be ok. "
                    "Design project.files with at least four coherent relative paths spanning backend, frontend, and tests for a local CSV web tool; "
                    "project.entrypoint must be one listed file. patch.path must be one listed file and "
                    "patch.replacement must contain a small runnable root-route code change."
                    if structured
                    else "Reply with exactly: pong"
                ),
            }
        ],
        "max_tokens": 256 if structured else PROVIDER_PROBE_MAX_OUTPUT_TOKENS,
    }
    return _build_openai_compatible_payload(
        base_url,
        payload,
        model=model,
        reasoning_effort="none",
    )


def _tls_verify_enabled() -> bool:
    raw = str(os.environ.get("CGKN_API_TLS_VERIFY", os.environ.get("OPENAI_TLS_VERIFY", "1"))).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _urlopen(req: urllib.request.Request, timeout_sec: int):
    context = None if _tls_verify_enabled() else ssl._create_unverified_context()
    return urllib.request.urlopen(req, timeout=timeout_sec, context=context)


def _request_error_summary(exc: BaseException, endpoint: str) -> str:
    kind = type(exc).__name__
    reason = getattr(exc, "reason", None)
    detail = str(reason or exc)
    host_path = re.sub(r"^(https?://[^/]+).*", r"\1", endpoint)
    retryable = isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, ConnectionResetError, ssl.SSLError))
    return f"{kind}: {detail} [endpoint={host_path}, tls_verify={_tls_verify_enabled()}, retryable={str(retryable).lower()}]"


def _http_error_summary(exc: urllib.error.HTTPError, endpoint: str, detail: str) -> str:
    host_path = re.sub(r"^(https?://[^/]+).*", r"\1", endpoint)
    retryable = exc.code in {408, 409, 425, 429} or 500 <= int(exc.code) <= 599
    return f"HTTP {exc.code}: {detail[:400]} [endpoint={host_path}, retryable={str(retryable).lower()}]"


def _error_is_retryable(error: str) -> bool:
    text = str(error or "")
    if "retryable=true" in text:
        return True
    if "retryable=false" in text:
        return False
    match = re.search(r"HTTP\s+(\d+)", text)
    if match:
        code = int(match.group(1))
        return code in {408, 409, 425, 429} or 500 <= code <= 599
    return bool(text)


def _provider_error_type(error: str) -> str:
    text = str(error or "")
    lowered = text.lower()
    if "missing openai-compatible api key" in lowered or "api_generation_mode requires configured" in lowered:
        return "PROVIDER_MISSING_CONFIG"
    if "does not support this api" in lowered or "method unsupported" in lowered:
        return "PROVIDER_METHOD_UNSUPPORTED"
    if "key usage limit exceeded" in lowered or "insufficient_quota" in lowered:
        return "PROVIDER_KEY_USAGE_LIMIT"
    if "http 403" in lowered:
        return "PROVIDER_FORBIDDEN"
    transport_markers = (
        "sslv3_alert_bad_record_mac",
        "sslerror",
        "connection reset",
        "connectionreseterror",
        "connection aborted",
        "unexpected_eof_while_reading",
        "eof occurred in violation",
        "[ssl:",
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
    match = re.search(r"HTTP\s+(\d+)", text, flags=re.IGNORECASE)
    if match:
        code = int(match.group(1))
        if code in {408, 409, 425, 429} or 500 <= code <= 599:
            return "PROVIDER_RETRYABLE_HTTP"
        return "PROVIDER_NON_RETRYABLE_HTTP"
    if "provider_api_request_failed" in lowered:
        return "PROVIDER_API_REQUEST_FAILED"
    return "PROVIDER_UNKNOWN_ERROR"


def _load_local_notes_defaults() -> dict[str, str]:
    path_text = str(os.environ.get("CGKN_LOCAL_NOTES_PATH", "")).strip()
    path = pathlib.Path(path_text) if path_text else DEFAULT_NOTES_PATH
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    out: dict[str, str] = {}
    match_url = re.search(r"`(https?://[^`\s]+)`", text)
    if match_url:
        out["base_url"] = match_url.group(1).strip()
    return out


def _windows_env_value(name: str, target: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg  # type: ignore
    except Exception:
        return ""
    hive, subkey = (
        (winreg.HKEY_CURRENT_USER, "Environment")
        if target == "User"
        else (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
    )
    try:
        with winreg.OpenKey(hive, subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value).strip()


def _first_credential(candidates: list[tuple[str, str]]) -> tuple[str, str]:
    for source, value in candidates:
        text = str(value or "").strip()
        if text:
            return text, source
    return "", ""


def _credential_conflict_sources(candidates: list[tuple[str, str]], selected_value: str) -> list[str]:
    selected = str(selected_value or "").strip()
    populated = [(source, str(value or "").strip()) for source, value in candidates if str(value or "").strip()]
    if len({value for _, value in populated}) <= 1:
        return []
    return [source for source, value in populated if value != selected]


def _resolve_api_credentials() -> dict[str, str]:
    defaults = _load_local_notes_defaults()
    override_key = str(os.environ.get("CGKN_OPENAI_API_KEY_OVERRIDE", "")).strip()
    override_base_url = str(os.environ.get("CGKN_OPENAI_BASE_URL_OVERRIDE", "")).strip()
    env_key = str(os.environ.get("OPENAI_API_KEY", "")).strip()
    env_base_url = str(os.environ.get("OPENAI_BASE_URL", "")).strip()
    compat_key = str(os.environ.get("CGKN_OPENAI_API_KEY", "")).strip()
    compat_base_url = str(os.environ.get("CGKN_OPENAI_BASE_URL", "")).strip()
    legacy_key = str(os.environ.get("CGNK_OPENAI_API_KEY", "")).strip()
    legacy_base_url = str(os.environ.get("CGNK_OPENAI_BASE_URL", "")).strip()
    user_env_key = _windows_env_value("OPENAI_API_KEY", "User")
    user_env_base_url = _windows_env_value("OPENAI_BASE_URL", "User")
    machine_env_key = _windows_env_value("OPENAI_API_KEY", "Machine")
    machine_env_base_url = _windows_env_value("OPENAI_BASE_URL", "Machine")
    user_compat_key = _windows_env_value("CGKN_OPENAI_API_KEY", "User")
    user_compat_base_url = _windows_env_value("CGKN_OPENAI_BASE_URL", "User")
    machine_compat_key = _windows_env_value("CGKN_OPENAI_API_KEY", "Machine")
    machine_compat_base_url = _windows_env_value("CGKN_OPENAI_BASE_URL", "Machine")
    user_legacy_key = _windows_env_value("CGNK_OPENAI_API_KEY", "User")
    user_legacy_base_url = _windows_env_value("CGNK_OPENAI_BASE_URL", "User")
    machine_legacy_key = _windows_env_value("CGNK_OPENAI_API_KEY", "Machine")
    machine_legacy_base_url = _windows_env_value("CGNK_OPENAI_BASE_URL", "Machine")
    notes_base_url = str(defaults.get("base_url", "")).strip()
    key_candidates = [
        ("CGKN_OPENAI_API_KEY_OVERRIDE", override_key),
        ("CGKN_OPENAI_API_KEY(User)", user_compat_key),
        ("CGKN_OPENAI_API_KEY(Machine)", machine_compat_key),
        ("CGKN_OPENAI_API_KEY", compat_key),
        ("OPENAI_API_KEY(User)", user_env_key),
        ("OPENAI_API_KEY(Machine)", machine_env_key),
        ("OPENAI_API_KEY", env_key),
    ]
    key, key_source = _first_credential(key_candidates)
    conflict_candidates = key_candidates + [
        ("CGNK_OPENAI_API_KEY(User)", user_legacy_key),
        ("CGNK_OPENAI_API_KEY(Machine)", machine_legacy_key),
        ("CGNK_OPENAI_API_KEY", legacy_key),
    ]
    base_candidates = [
        ("CGKN_OPENAI_BASE_URL_OVERRIDE", override_base_url),
        ("CGKN_OPENAI_BASE_URL(User)", user_compat_base_url),
        ("CGKN_OPENAI_BASE_URL(Machine)", machine_compat_base_url),
        ("CGKN_OPENAI_BASE_URL", compat_base_url),
        ("OPENAI_BASE_URL(User)", user_env_base_url),
        ("OPENAI_BASE_URL(Machine)", machine_env_base_url),
        ("OPENAI_BASE_URL", env_base_url),
        ("local_notes", notes_base_url),
        ("embedded_default", EMBEDDED_BASE_URL),
    ]
    raw_base_url, base_source = _first_credential(base_candidates)
    base_conflict_candidates = base_candidates[:-1] + [
        ("CGNK_OPENAI_BASE_URL(User)", user_legacy_base_url),
        ("CGNK_OPENAI_BASE_URL(Machine)", machine_legacy_base_url),
        ("CGNK_OPENAI_BASE_URL", legacy_base_url),
    ]
    base_url = _normalize_base_url(raw_base_url)
    return {
        "api_key": key,
        "api_key_source": key_source,
        "api_key_conflict_sources": _credential_conflict_sources(conflict_candidates, key),
        "base_url": base_url,
        "base_url_source": base_source,
        "base_url_conflict_sources": _credential_conflict_sources(base_conflict_candidates, raw_base_url),
    }


def _post_json(endpoint: str, payload: dict[str, Any], token: str, timeout_sec: int) -> tuple[dict[str, Any] | None, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    started = time.monotonic()
    timing: dict[str, Any] = {
        "request_started_at": datetime.now(timezone.utc).isoformat(),
        "request_body_bytes": len(data),
        "timeout_seconds": int(timeout_sec),
        "response_headers_received": False,
        "response_body_received": False,
    }
    _set_last_transport_timing(timing)
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CGNK-Connectivity/1",
            "Connection": "close",
        },
    )
    response_opened = False
    try:
        with _urlopen(req, timeout_sec) as resp:
            response_opened = True
            timing["response_headers_received"] = True
            timing["response_headers_elapsed_ms"] = round(
                (time.monotonic() - started) * 1000
            )
            timing["response_status"] = int(getattr(resp, "status", 0) or 0)
            body = resp.read().decode("utf-8", errors="replace")
            timing["response_body_received"] = bool(body)
            timing["response_body_bytes"] = len(body.encode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        timing["failure_phase"] = "http_response"
        timing["response_headers_received"] = True
        timing["response_status"] = int(getattr(exc, "code", 0) or 0)
        timing["response_body_received"] = bool(detail)
        timing["response_body_bytes"] = len(detail.encode("utf-8"))
        timing["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
        _set_last_transport_timing(timing)
        return None, _http_error_summary(exc, endpoint, detail)
    except (urllib.error.URLError, TimeoutError, ConnectionError, ConnectionResetError, ssl.SSLError) as exc:
        timing["failure_phase"] = (
            "response_body" if response_opened else "connect_or_response_headers"
        )
        timing["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
        _set_last_transport_timing(timing)
        return None, f"request failed: {_request_error_summary(exc, endpoint)}"
    except Exception as exc:
        timing["failure_phase"] = (
            "response_body" if response_opened else "connect_or_response_headers"
        )
        timing["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
        _set_last_transport_timing(timing)
        return None, f"request failed: {_request_error_summary(exc, endpoint)}"
    timing["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
    _set_last_transport_timing(timing)
    try:
        doc = json.loads(body)
    except Exception as exc:
        return None, f"non-json response: {exc}"
    if not isinstance(doc, dict):
        return None, "response is not object"
    return doc, ""


@dataclass
class ProviderTransportAttempt:
    attempt: int
    elapsed_ms: int
    ok: bool
    error: str
    error_type: str
    retryable: bool


@dataclass
class ProviderTransportResult:
    doc: dict[str, Any] | None
    error: str
    attempts: list[ProviderTransportAttempt]
    error_type: str
    recovered: bool


def _post_json_with_retry(
    endpoint: str,
    payload: dict[str, Any],
    token: str,
    timeout_sec: int,
    *,
    max_attempts: int = 3,
    base_delay_sec: float = 0.5,
) -> ProviderTransportResult:
    attempts: list[ProviderTransportAttempt] = []
    doc: dict[str, Any] | None = None
    error = ""
    for number in range(1, max(1, max_attempts) + 1):
        started = time.monotonic()
        doc, error = _post_json(endpoint, payload, token, timeout_sec)
        attempts.append(
            ProviderTransportAttempt(
                attempt=number,
                elapsed_ms=round((time.monotonic() - started) * 1000),
                ok=doc is not None,
                error=error,
                error_type=_provider_error_type(error) if error else "",
                retryable=bool(error and _error_is_retryable(error)),
            )
        )
        if doc is not None or not _error_is_retryable(error):
            break
        if os.environ.get("CGKN_PROVIDER_RETRY_FAST") != "1":
            time.sleep(max(0.0, base_delay_sec) * number)
    return ProviderTransportResult(
        doc=doc,
        error=error,
        attempts=attempts,
        error_type=_provider_error_type(error) if error else "",
        recovered=doc is not None and len(attempts) > 1,
    )


def _extract_text(doc: dict[str, Any]) -> str:
    direct = doc.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    output = doc.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            for chunk in content if isinstance(content, list) else []:
                if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                    parts.append(chunk["text"])
        if parts:
            return "\n".join(parts).strip()
    choices = doc.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"].strip()
    return ""


def _structured_probe_document(text: str) -> tuple[dict[str, Any], bool]:
    candidate = str(text or "").strip()
    strict = not candidate.startswith("```")
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(candidate)
    except Exception:
        return {}, False
    return (parsed, strict) if isinstance(parsed, dict) else ({}, False)


def _structured_probe_valid(text: str) -> bool:
    parsed, _strict = _structured_probe_document(text)
    return parsed.get("cgkn_probe") == "ok"


def check_api(live: bool, timeout_sec: int, model: str, *, structured: bool = False) -> dict[str, Any]:
    creds = _resolve_api_credentials()
    token = creds["api_key"]
    root = creds["base_url"]
    result: dict[str, Any] = {
        "configured": bool(token),
        "api_key_source": creds["api_key_source"],
        "api_key_mask": _mask_secret(token),
        "api_key_conflict_sources": creds.get("api_key_conflict_sources", []),
        "base_url": root,
        "base_url_source": creds["base_url_source"],
        "base_url_conflict_sources": creds.get("base_url_conflict_sources", []),
        "live": live,
        "ok": False,
    }
    if not token:
        result["error"] = "missing API key"
        return result
    if not live:
        result["ok"] = True
        result["status"] = "configured"
        return result
    endpoint_mode = "chat" if _is_gptsapi_base_url(root) else "responses"
    endpoint = _openai_compatible_endpoint(root)
    payload = _build_provider_probe_payload(root, model, structured=structured)
    doc: dict[str, Any] | None = None
    error = ""
    attempts = 0
    for attempts in range(1, 4):
        doc, error = _post_json(endpoint, payload, token, timeout_sec)
        if doc is not None or not _error_is_retryable(error):
            break
        if os.environ.get("CGKN_PROVIDER_RETRY_FAST") != "1":
            time.sleep(float(attempts))
    result["endpoint_mode"] = endpoint_mode
    result["endpoint"] = endpoint
    result["tls_verify"] = _tls_verify_enabled()
    result["attempts"] = attempts
    if doc is None:
        result["error"] = error
        return result
    text = _extract_text(doc)
    result["ok"] = bool(text)
    result["status"] = "connected" if text else "empty_response"
    result["response_preview"] = text[:80]
    if structured:
        structured_doc, strict = _structured_probe_document(text)
        result["structured_output_valid"] = structured_doc.get("cgkn_probe") == "ok"
        result["structured_output_strict"] = strict and bool(structured_doc)
        result["structured_output"] = structured_doc
    result["request_id"] = str(doc.get("id", "")).strip()
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    result = {
        "kind": "ConnectivityCheckResult",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "api": check_api(bool(args.live or args.live_api), args.timeout, args.model),
    }
    result["ok"] = bool(result["api"].get("ok"))
    _write_json(RESULT_PATH, result)
    result["result_path"] = str(RESULT_PATH)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Run live OpenAI-compatible API probe.")
    parser.add_argument("--live-api", action="store_true", help="Run live OpenAI-compatible API probe.")
    parser.add_argument("--model", default="", help="Optional explicit model; omit to auto-select configured models.")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.model:
        try:
            import provider_resilience
        except ModuleNotFoundError:  # pragma: no cover - package import path
            from scripts import provider_resilience
        report = provider_resilience.provider_preflight(
            goal="connectivity and structured output capability",
            live=bool(args.live or args.live_api),
            required_role="generation",
            timeout=max(1, args.timeout),
        )
        provider_resilience.write_health_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("metadata", {}).get("live_generation_allowed") else 1
    result = run(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"CONNECTIVITY: {'OK' if result['ok'] else 'CHECK'}")
        print(f"api={result['api'].get('status', result['api'].get('error', 'unknown'))}")
        print(f"result={result['result_path']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
