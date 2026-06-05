#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "examples" / "test_results" / "connectivity_check_result.json"
DEFAULT_NOTES_PATH = ROOT / ".agent_private" / "NOTES.md"
EMBEDDED_BASE_URL = "https://api.gptsapi.net"


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
    if root.lower() in {"https://api.gptsapi.net/v1", "http://api.gptsapi.net/v1", "https://gptsapi.net/v1", "http://gptsapi.net/v1"}:
        return root[:-3].rstrip("/")
    return root


def _is_gptsapi_base_url(value: str) -> bool:
    return _normalize_base_url(value).lower() in {
        "https://api.gptsapi.net",
        "http://api.gptsapi.net",
        "https://gptsapi.net",
        "http://gptsapi.net",
    }


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
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        return None, f"HTTP {exc.code}: {detail[:400]}"
    except (urllib.error.URLError, TimeoutError, ConnectionError, ConnectionResetError, ssl.SSLError) as exc:
        return None, f"request failed: {exc}"
    except Exception as exc:
        return None, f"request failed: {exc}"
    try:
        doc = json.loads(body)
    except Exception as exc:
        return None, f"non-json response: {exc}"
    if not isinstance(doc, dict):
        return None, "response is not object"
    return doc, ""


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
    if endpoint_mode == "responses":
        endpoint = root.rstrip("/") + "/responses"
        payload = {"model": model, "input": "Reply with exactly: pong", "max_output_tokens": 8}
    else:
        endpoint = root.rstrip("/") + "/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
            "max_tokens": 8,
        }
    doc, error = _post_json(endpoint, payload, token, timeout_sec)
    result["endpoint_mode"] = endpoint_mode
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
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
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
