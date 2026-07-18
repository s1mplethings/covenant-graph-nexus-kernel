#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import ssl
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


def _build_openai_compatible_payload(base_url: str, payload: dict[str, Any], model: str = "") -> dict[str, Any]:
    del model
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
    return request_payload


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
    match_key = re.search(r"`(sk-[^`\s]+)`", text)
    if match_key:
        out["api_key"] = match_key.group(1).strip()
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


def _resolve_api_credentials() -> dict[str, str]:
    defaults = _load_local_notes_defaults()
    env_key = str(os.environ.get("OPENAI_API_KEY", "")).strip()
    env_base_url = str(os.environ.get("OPENAI_BASE_URL", "")).strip()
    compat_key = str(os.environ.get("CGKN_OPENAI_API_KEY", "")).strip()
    compat_base_url = str(os.environ.get("CGKN_OPENAI_BASE_URL", "")).strip()
    user_env_key = _windows_env_value("OPENAI_API_KEY", "User")
    user_env_base_url = _windows_env_value("OPENAI_BASE_URL", "User")
    machine_env_key = _windows_env_value("OPENAI_API_KEY", "Machine")
    machine_env_base_url = _windows_env_value("OPENAI_BASE_URL", "Machine")
    user_compat_key = _windows_env_value("CGKN_OPENAI_API_KEY", "User")
    user_compat_base_url = _windows_env_value("CGKN_OPENAI_BASE_URL", "User")
    machine_compat_key = _windows_env_value("CGKN_OPENAI_API_KEY", "Machine")
    machine_compat_base_url = _windows_env_value("CGKN_OPENAI_BASE_URL", "Machine")
    notes_key = str(defaults.get("api_key", "")).strip()
    notes_base_url = str(defaults.get("base_url", "")).strip()
    key, key_source = _first_credential(
        [
            ("CGKN_OPENAI_API_KEY", compat_key),
            ("CGKN_OPENAI_API_KEY(User)", user_compat_key),
            ("CGKN_OPENAI_API_KEY(Machine)", machine_compat_key),
            ("local_notes", notes_key),
            ("OPENAI_API_KEY(User)", user_env_key),
            ("OPENAI_API_KEY(Machine)", machine_env_key),
            ("OPENAI_API_KEY", env_key),
        ]
    )
    raw_base_url, base_source = _first_credential(
        [
            ("CGKN_OPENAI_BASE_URL", compat_base_url),
            ("CGKN_OPENAI_BASE_URL(User)", user_compat_base_url),
            ("CGKN_OPENAI_BASE_URL(Machine)", machine_compat_base_url),
            ("local_notes", notes_base_url),
            ("OPENAI_BASE_URL(User)", user_env_base_url),
            ("OPENAI_BASE_URL(Machine)", machine_env_base_url),
            ("OPENAI_BASE_URL", env_base_url),
            ("embedded_default", EMBEDDED_BASE_URL),
        ]
    )
    base_url = _normalize_base_url(raw_base_url)
    return {"api_key": key, "api_key_source": key_source, "base_url": base_url, "base_url_source": base_source}


def _post_json(endpoint: str, payload: dict[str, Any], token: str, timeout_sec: int) -> tuple[dict[str, Any] | None, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
    try:
        with _urlopen(req, timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        return None, _http_error_summary(exc, endpoint, detail)
    except (urllib.error.URLError, TimeoutError, ConnectionError, ConnectionResetError, ssl.SSLError) as exc:
        return None, f"request failed: {_request_error_summary(exc, endpoint)}"
    except Exception as exc:
        return None, f"request failed: {_request_error_summary(exc, endpoint)}"
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


def check_api(live: bool, timeout_sec: int, model: str) -> dict[str, Any]:
    creds = _resolve_api_credentials()
    token = creds["api_key"]
    root = creds["base_url"]
    result: dict[str, Any] = {
        "configured": bool(token),
        "api_key_source": creds["api_key_source"],
        "api_key_mask": _mask_secret(token),
        "base_url": root,
        "base_url_source": creds["base_url_source"],
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
    payload = _build_openai_compatible_payload(root, {"model": model, "messages": [{"role": "user", "content": "Reply with exactly: pong"}], "max_tokens": 8})
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
    parser.add_argument("--model", default=model_policy.select_model("connectivity"))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
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
