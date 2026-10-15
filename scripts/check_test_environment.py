#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "examples" / "test_results" / "test_environment_report.json"
DEFAULT_CANDIDATE_DIR = ROOT / "generated" / "cgnk_generated_project_candidate"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def command_version(argv: list[str], timeout: int = 10) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return f"unavailable: {exc}"
    text = (proc.stdout or proc.stderr or "").strip().splitlines()
    return text[0][:300] if text else f"returncode={proc.returncode}"


def executable_report(name: str, version_args: list[str] | None = None) -> dict[str, Any]:
    path = shutil.which(name) or ""
    return {
        "path": path,
        "version": command_version([path, *(version_args or ["--version"])]) if path else "",
        "available": bool(path),
    }


def free_port() -> tuple[bool, int]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return True, int(sock.getsockname()[1])
    except Exception:
        return False, 0


def localhost_http_server_ok() -> bool:
    ok, port = free_port()
    if not ok:
        return False
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        (root / "index.html").write_text("ok", encoding="utf-8")
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                cwd=str(root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html", timeout=1) as response:
                        return response.status == 200
                except Exception:
                    time.sleep(0.1)
            return False
        finally:
            if proc is not None:
                proc.terminate()
                try:
                    proc.communicate(timeout=3)
                except Exception:
                    proc.kill()


def writable(path: pathlib.Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".cgnk_write_probe_{os.getpid()}_{time.time_ns()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def browser_report() -> dict[str, Any]:
    result: dict[str, Any] = {
        "playwright_available": False,
        "chromium_available": False,
        "chromium_executable": "",
        "chrome_path": shutil.which("chrome") or "",
        "msedge_path": shutil.which("msedge") or "",
        "error": "",
    }
    try:
        from playwright.sync_api import sync_playwright

        result["playwright_available"] = True
        with sync_playwright() as pw:
            executable = pathlib.Path(str(pw.chromium.executable_path))
            result["chromium_executable"] = str(executable)
            result["chromium_available"] = executable.exists()
    except Exception as exc:
        result["error"] = str(exc)
    return result


def check_environment(
    candidate_dir: pathlib.Path = DEFAULT_CANDIDATE_DIR,
    *,
    require_node: bool = True,
    require_browser: bool = True,
    require_ffmpeg: bool = False,
) -> dict[str, Any]:
    warnings: list[str] = []
    failures: list[str] = []
    node = executable_report("node") if require_node else {"path": shutil.which("node") or "", "version": "not_checked", "available": bool(shutil.which("node"))}
    npm = executable_report("npm") if require_node else {"path": shutil.which("npm") or "", "version": "not_checked", "available": bool(shutil.which("npm"))}
    npx = executable_report("npx") if require_node else {"path": shutil.which("npx") or "", "version": "not_checked", "available": bool(shutil.which("npx"))}
    git = {"path": shutil.which("git") or "", "version": "not_checked", "available": bool(shutil.which("git"))}
    ffmpeg = executable_report("ffmpeg") if require_ffmpeg else {"path": shutil.which("ffmpeg") or "", "version": "not_checked", "available": bool(shutil.which("ffmpeg"))}
    browser = browser_report() if require_browser else {
        "playwright_available": False,
        "chromium_available": False,
        "chromium_executable": "",
        "chrome_path": "",
        "msedge_path": "",
        "error": "not_checked",
    }
    port_ok, port = free_port()
    server_ok = localhost_http_server_ok() if require_browser else True
    filesystem = {
        "repo_writable": writable(ROOT),
        "temp_writable": writable(pathlib.Path(tempfile.gettempdir())),
        "candidate_dir_writable": writable(candidate_dir),
    }
    long_path_warning = sys.platform.startswith("win") and len(str(candidate_dir.resolve())) > 180

    if require_node and not node["available"]:
        failures.append("node unavailable")
    if require_node and not npm["available"]:
        failures.append("npm unavailable")
    if require_node and not npx["available"]:
        warnings.append("npx unavailable")
    if require_browser and (not browser["playwright_available"] or not browser["chromium_available"]):
        failures.append("browser automation unavailable")
    if require_ffmpeg and not ffmpeg["available"]:
        warnings.append("ffmpeg unavailable")
    if not port_ok:
        failures.append("free TCP port unavailable")
    if not server_ok:
        failures.append("localhost HTTP server failed")
    for key, value in filesystem.items():
        if not value:
            failures.append(f"{key} false")
    if long_path_warning:
        warnings.append("candidate path may approach Windows long path limits")
    if not git["available"]:
        warnings.append("git unavailable")

    status = "fail" if failures else ("warn" if warnings else "pass")
    return {
        "status": status,
        "created_at": now(),
        "platform": platform.platform(),
        "python": {"path": sys.executable, "version": sys.version.split()[0]},
        "node": node,
        "npm": npm,
        "npx": npx,
        "git": git,
        "browser": browser,
        "ffmpeg": ffmpeg,
        "network": {
            "localhost_http_server_ok": server_ok,
            "free_port_ok": port_ok,
            "free_port": port,
        },
        "filesystem": filesystem,
        "required_capabilities": {
            "node": require_node,
            "browser": require_browser,
            "ffmpeg": require_ffmpeg,
        },
        "warnings": warnings,
        "failures": failures,
    }


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    report = check_environment()
    write_json(DEFAULT_REPORT, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
