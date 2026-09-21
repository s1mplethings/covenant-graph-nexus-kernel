#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import pathlib
import re
import sys
import tempfile
from typing import Any

try:
    from . import check_connectivity
except ImportError:  # pragma: no cover - direct script execution
    import check_connectivity  # type: ignore


ROOT = pathlib.Path(__file__).resolve().parents[1]
CANONICAL_KEY = "CGKN_OPENAI_API_KEY"
CANONICAL_BASE_URL = "CGKN_OPENAI_BASE_URL"
LEGACY_USER_NAMES = (
    "CGNK_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "CGNK_OPENAI_BASE_URL",
    "OPENAI_BASE_URL",
)
MANAGED_USER_NAMES = (CANONICAL_KEY, CANONICAL_BASE_URL, *LEGACY_USER_NAMES)


def _validate_api_key(value: str) -> str:
    key = str(value or "").strip()
    if len(key) < 12 or any(char.isspace() for char in key):
        raise ValueError("API key is empty or malformed")
    return key


def _validate_base_url(value: str) -> str:
    base_url = check_connectivity._normalize_base_url(value)
    if not re.match(r"^https?://", base_url, flags=re.IGNORECASE):
        raise ValueError("base URL must start with http:// or https://")
    return base_url


def _open_user_environment(*, writable: bool):
    if os.name != "nt":
        raise RuntimeError("persistent credential replacement currently requires Windows")
    import winreg  # type: ignore

    access = winreg.KEY_READ | (winreg.KEY_SET_VALUE if writable else 0)
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, access)


def _read_user_values(names: tuple[str, ...] = MANAGED_USER_NAMES) -> dict[str, str | None]:
    import winreg  # type: ignore

    values: dict[str, str | None] = {}
    with _open_user_environment(writable=False) as key:
        for name in names:
            try:
                value, _ = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                values[name] = None
            else:
                values[name] = str(value)
    return values


def _apply_user_values(values: dict[str, str | None]) -> None:
    import winreg  # type: ignore

    with _open_user_environment(writable=True) as key:
        for name, value in values.items():
            if value is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _broadcast_environment_change() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF,
            0x001A,
            0,
            "Environment",
            0x0002,
            5000,
            ctypes.byref(result),
        )
    except Exception:
        pass


def _notes_path() -> pathlib.Path:
    configured = str(os.environ.get("CGKN_LOCAL_NOTES_PATH", "")).strip()
    return pathlib.Path(configured) if configured else check_connectivity.DEFAULT_NOTES_PATH


def scrub_legacy_note_keys(path: pathlib.Path | None = None) -> bool:
    target = path or _notes_path()
    if not target.exists():
        return False
    original = target.read_text(encoding="utf-8", errors="replace")
    scrubbed = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[removed-api-key]", original)
    if scrubbed == original:
        return False
    temp_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            delete=False,
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(scrubbed)
            temp_path = pathlib.Path(handle.name)
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return True


def replace_user_credentials(api_key: str, base_url: str = "") -> dict[str, Any]:
    key = _validate_api_key(api_key)
    resolved = check_connectivity._resolve_api_credentials()
    canonical_base_url = _validate_base_url(base_url or str(resolved.get("base_url") or check_connectivity.EMBEDDED_BASE_URL))
    previous = _read_user_values()
    next_values: dict[str, str | None] = {
        CANONICAL_KEY: key,
        CANONICAL_BASE_URL: canonical_base_url,
        **{name: None for name in LEGACY_USER_NAMES},
    }
    try:
        _apply_user_values(next_values)
        notes_scrubbed = scrub_legacy_note_keys()
    except Exception:
        _apply_user_values(previous)
        raise
    _broadcast_environment_change()
    process_conflict = any(
        str(os.environ.get(name, "")).strip()
        and str(os.environ.get(name, "")).strip() != key
        for name in (CANONICAL_KEY, "CGNK_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    return {
        "status": "replaced",
        "canonical_key_name": CANONICAL_KEY,
        "canonical_base_url_name": CANONICAL_BASE_URL,
        "base_url": canonical_base_url,
        "cleared_user_names": list(LEGACY_USER_NAMES),
        "legacy_notes_scrubbed": notes_scrubbed,
        "restart_recommended": process_conflict,
    }


def credential_status() -> dict[str, Any]:
    creds = check_connectivity._resolve_api_credentials()
    user_values = _read_user_values() if os.name == "nt" else {}
    return {
        "status": "configured" if creds.get("api_key") else "missing",
        "selected_key_source": creds.get("api_key_source", ""),
        "selected_key_mask": check_connectivity._mask_secret(str(creds.get("api_key", ""))),
        "key_conflict_sources": creds.get("api_key_conflict_sources", []),
        "selected_base_url_source": creds.get("base_url_source", ""),
        "base_url": creds.get("base_url", ""),
        "base_url_conflict_sources": creds.get("base_url_conflict_sources", []),
        "user_sources_present": {name: bool(value) for name, value in user_values.items()},
        "notes_key_loading_disabled": True,
    }


def _read_replacement_key(stdin_mode: bool) -> str:
    if stdin_mode:
        return _validate_api_key(sys.stdin.readline())
    return _validate_api_key(getpass.getpass("New API key (input hidden): "))


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace CGKN provider credentials without leaving active legacy copies.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show redacted credential sources and conflicts.")
    replace_parser = subparsers.add_parser("replace", help="Atomically replace the user credential and clear legacy user values.")
    replace_parser.add_argument("--base-url", default="")
    replace_parser.add_argument("--stdin", action="store_true", help="Read the new key from stdin instead of an interactive hidden prompt.")
    replace_parser.add_argument("--live-test", action="store_true")
    replace_parser.add_argument("--model", default=check_connectivity.DEFAULT_TEST_MODEL)
    replace_parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    if args.command == "status":
        result = credential_status()
    else:
        replacement = replace_user_credentials(_read_replacement_key(bool(args.stdin)), args.base_url)
        result = {"replacement": replacement, "status": credential_status()}
        if args.live_test:
            result["live_test"] = check_connectivity.check_api(True, args.timeout, args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
