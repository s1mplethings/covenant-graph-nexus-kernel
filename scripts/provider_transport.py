from __future__ import annotations

import json
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

PROVIDER_API_CHAT_COMPLETIONS = "chat_completions"
PROVIDER_API_RESPONSES = "responses"
PROVIDER_API_METHODS = {PROVIDER_API_CHAT_COMPLETIONS, PROVIDER_API_RESPONSES}


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


def _is_alibaba_model_studio_base_url(value: str) -> bool:
    hostname = str(urllib.parse.urlparse(str(value or "").strip()).hostname or "").lower()
    return hostname in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"} or hostname.endswith(
        ".maas.aliyuncs.com"
    )


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
    del model
    if _is_gptsapi_base_url(base_url) or _is_alibaba_model_studio_base_url(base_url):
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
