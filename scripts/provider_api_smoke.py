#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import check_connectivity


DEFAULT_RESULT = ROOT / "examples" / "test_results" / "provider_api_smoke_result.json"
DEFAULT_SMOKE_MODEL = "gpt-5.4-nano"


def _proxy_summary() -> dict[str, bool]:
    return {
        "HTTP_PROXY": bool(os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")),
        "HTTPS_PROXY": bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")),
        "NO_PROXY": bool(os.environ.get("NO_PROXY") or os.environ.get("no_proxy")),
    }


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    candidates = [raw]
    first = raw.find("{")
    last = raw.rfind("}")
    if first >= 0 and last > first:
        candidates.append(raw[first : last + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    return None


def run_smoke(model: str, timeout: int, attempts: int) -> dict[str, Any]:
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    root = str(creds.get("base_url", "")).strip()
    selected_method = check_connectivity._selected_provider_api_method(root, model)
    endpoint_mode = check_connectivity._endpoint_mode_from_method(selected_method)
    endpoint = check_connectivity._openai_compatible_endpoint(root, model=model)
    result: dict[str, Any] = {
        "kind": "ProviderApiSmokeResult",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": False,
        "model": model,
        "configured": bool(token and root),
        "api_key_source": creds.get("api_key_source", ""),
        "api_key_mask": check_connectivity._mask_secret(token),
        "base_url": root,
        "base_url_source": creds.get("base_url_source", ""),
        "endpoint_mode": endpoint_mode,
        "selected_method": selected_method,
        "base_url_domain": check_connectivity._base_url_domain(root),
        "endpoint": endpoint,
        "timeout_seconds": timeout,
        "max_attempts": attempts,
        "tls_verify": check_connectivity._tls_verify_enabled(),
        "proxy_env_present": _proxy_summary(),
        "attempts": [],
    }
    if not token:
        result["error_code"] = "missing_api_key"
        result["error_summary"] = "No OpenAI-compatible API key was resolved."
        return result
    if not root:
        result["error_code"] = "missing_base_url"
        result["error_summary"] = "No OpenAI-compatible base URL was resolved."
        return result

    payload = check_connectivity._build_openai_compatible_payload(
        root,
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return only strict JSON. No markdown."},
                {"role": "user", "content": "Return exactly this JSON object with no extra text: {\"smoke\":true}"},
            ],
            "temperature": 0,
            "max_tokens": 40,
        },
        model=model,
    )

    transport = check_connectivity._post_json_with_retry(
        endpoint,
        payload,
        token,
        timeout,
        max_attempts=max(1, attempts),
        base_delay_sec=1.5,
    )
    result["attempts"] = [
        {
            "attempt": item.attempt,
            "elapsed_seconds": round(item.elapsed_ms / 1000, 3),
            "ok": item.ok,
            "error": item.error,
            "error_type": item.error_type,
            "retryable": item.retryable,
        }
        for item in transport.attempts
    ]
    result["transport_recovered"] = transport.recovered
    if transport.doc is not None:
        text = check_connectivity._extract_text(transport.doc)
        parsed = _extract_json(text)
        result["response_preview"] = text[:200]
        result["request_id"] = str(transport.doc.get("id", "")).strip()
        result["parsed_json"] = parsed or {}
        result["ok"] = bool(parsed and parsed.get("smoke") is True)
        if result["ok"]:
            result["status"] = "provider_smoke_passed"
            return result
        result["error_code"] = "invalid_smoke_response"
        result["error_summary"] = "Provider returned content, but it was not the expected JSON object."
        return result

    result["error_code"] = "provider_request_failed"
    result["error_summary"] = transport.error or "Provider request failed without a detailed error."
    result["provider_error_type"] = transport.error_type
    if transport.error_type == "PROVIDER_METHOD_UNSUPPORTED":
        result["error_code"] = "provider_method_unsupported"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Live OpenAI-compatible provider smoke test.")
    parser.add_argument("--model", default=DEFAULT_SMOKE_MODEL)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--result", default=str(DEFAULT_RESULT))
    args = parser.parse_args()

    result = run_smoke(args.model, args.timeout, args.attempts)
    path = pathlib.Path(args.result).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
