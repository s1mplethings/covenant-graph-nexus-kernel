#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "scripts" / "telegram_new_config.example.json"


def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_path(raw: str | pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def inside_root(path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def load_config(path: pathlib.Path) -> dict[str, Any]:
    config = read_json(path)
    config.setdefault("state_dir", "generated/telegram_new_listener")
    config.setdefault("archive_dir", "generated/telegram_new_archives")
    config.setdefault("history_mode", "archive")
    config.setdefault("history_globs", [])
    config.setdefault("processes", [])
    return config


def parse_admin_ids(raw: str) -> set[int]:
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        text = part.strip()
        if text:
            out.add(int(text))
    return out


def netstat_pids_for_port(port: int) -> set[int]:
    if os.name != "nt":
        return set()
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
            f"Where-Object {{ $_.LocalPort -eq {int(port)} }} | "
            "Select-Object -ExpandProperty OwningProcess"
        ),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    pids: set[int] = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.add(int(line))
    return pids


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        proc = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=10)
        return str(pid) in proc.stdout
    proc = subprocess.run(["kill", "-0", str(pid)], capture_output=True, text=True, timeout=10)
    return proc.returncode == 0


def stop_pid(pid: int) -> dict[str, Any]:
    if not pid_is_running(pid):
        return {"pid": pid, "status": "not_running"}
    if os.name == "nt":
        proc = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=20)
    else:
        proc = subprocess.run(["kill", "-TERM", str(pid)], capture_output=True, text=True, timeout=20)
    return {
        "pid": pid,
        "status": "stopped" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-1000:],
        "stderr": proc.stderr[-1000:],
    }


def stop_process(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name") or "process")
    raw_pid_file = str(spec.get("pid_file") or "").strip()
    pid_file = resolve_path(raw_pid_file) if raw_pid_file else None
    pids: set[int] = set()
    if pid_file and pid_file.exists():
        text = pid_file.read_text(encoding="utf-8", errors="replace").strip()
        if text.isdigit():
            pids.add(int(text))
    for port in spec.get("stop_ports", []):
        pids.update(netstat_pids_for_port(int(port)))
    stopped = [stop_pid(pid) for pid in sorted(pids)]
    if pid_file and pid_file.is_file():
        pid_file.unlink()
    return {"name": name, "pids": sorted(pids), "results": stopped}


def start_process(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name") or "process")
    command = [str(part) for part in spec.get("start_command", [])]
    if not command or not bool(spec.get("restart", True)):
        return {"name": name, "status": "skipped", "reason": "restart disabled or start_command empty"}
    cwd = resolve_path(str(spec.get("cwd") or "."))
    if not cwd.exists():
        return {"name": name, "status": "failed", "reason": f"cwd does not exist: {cwd}"}
    stdout_log = resolve_path(str(spec.get("stdout_log") or f"generated/telegram_new_listener/{name}.out.log"))
    stderr_log = resolve_path(str(spec.get("stderr_log") or f"generated/telegram_new_listener/{name}.err.log"))
    pid_file = resolve_path(str(spec.get("pid_file") or f"generated/telegram_new_listener/{name}.pid"))
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    out = stdout_log.open("ab")
    err = stderr_log.open("ab")
    proc = subprocess.Popen(command, cwd=str(cwd), stdout=out, stderr=err, close_fds=True)
    out.close()
    err.close()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    return {"name": name, "status": "started", "pid": proc.pid, "command": command, "cwd": str(cwd)}


def stop_all(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [stop_process(dict(spec)) for spec in config.get("processes", [])]


def start_all(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [start_process(dict(spec)) for spec in config.get("processes", [])]


def clear_history(config: dict[str, Any]) -> dict[str, Any]:
    mode = str(config.get("history_mode") or "archive").lower()
    archive_root = resolve_path(str(config.get("archive_dir") or "generated/telegram_new_archives")) / now_slug()
    paths: list[pathlib.Path] = []
    for pattern in config.get("history_globs", []):
        paths.extend(ROOT.glob(str(pattern)))
    unique = sorted({path.resolve() for path in paths if path.exists() and path.is_file()})
    cleared: list[str] = []
    skipped: list[str] = []
    for path in unique:
        if not inside_root(path):
            skipped.append(str(path))
            continue
        if mode == "delete":
            path.unlink()
        else:
            rel = path.relative_to(ROOT.resolve())
            target = archive_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        cleared.append(str(path))
    return {"mode": mode, "cleared": cleared, "skipped": skipped, "archive_dir": str(archive_root) if cleared and mode != "delete" else ""}


def reset_stack(config: dict[str, Any]) -> dict[str, Any]:
    stopped = stop_all(config)
    history = clear_history(config)
    started = start_all(config)
    result = {
        "kind": "TelegramNewResetResult",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stopped": stopped,
        "history": history,
        "started": started,
    }
    state_dir = resolve_path(str(config.get("state_dir") or "generated/telegram_new_listener"))
    write_json(state_dir / "last_reset.json", result)
    return result


def plan_reset(config: dict[str, Any]) -> dict[str, Any]:
    history_paths: list[str] = []
    for pattern in config.get("history_globs", []):
        history_paths.extend(str(path.resolve()) for path in ROOT.glob(str(pattern)) if path.exists() and path.is_file())
    process_plan = []
    for spec in config.get("processes", []):
        process_plan.append(
            {
                "name": str(spec.get("name") or "process"),
                "restart": bool(spec.get("restart", True)),
                "cwd": str(resolve_path(str(spec.get("cwd") or "."))),
                "start_command": spec.get("start_command", []),
                "stop_ports": spec.get("stop_ports", []),
                "pid_file": str(resolve_path(str(spec.get("pid_file") or ""))) if str(spec.get("pid_file") or "").strip() else "",
            }
        )
    return {
        "kind": "TelegramNewResetPlan",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "would_stop_or_restart": process_plan,
        "history_mode": str(config.get("history_mode") or "archive"),
        "history_file_count": len(set(history_paths)),
        "history_files": sorted(set(history_paths))[:200],
    }


def summarize_reset(result: dict[str, Any]) -> str:
    stopped_count = sum(len(item.get("pids", [])) for item in result.get("stopped", []))
    started = [item for item in result.get("started", []) if item.get("status") == "started"]
    cleared_count = len(result.get("history", {}).get("cleared", []))
    lines = [
        "/new 已执行。",
        f"停止进程: {stopped_count}",
        f"清理历史: {cleared_count}",
        f"启动服务: {len(started)}",
    ]
    archive_dir = result.get("history", {}).get("archive_dir")
    if archive_dir:
        lines.append(f"历史已归档: {archive_dir}")
    return "\n".join(lines)


def message_text(update: dict[str, Any]) -> tuple[int | None, int | None, str]:
    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    return chat.get("id"), user.get("id"), str(message.get("text") or "").strip()


def run_listener(args: argparse.Namespace) -> int:
    print(
        "telegram_new_listener long-polling output is disabled. "
        "Use scripts/telegram_live_bridge.py as the single Telegram customer-service output.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Listen for Telegram /new and reset local frontend/backend state.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--poll-timeout", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--dry-run-reset", action="store_true", help="Print what would be reset without stopping processes or moving files.")
    parser.add_argument("--reset-now", action="store_true", help="Execute one reset immediately, then exit.")
    args = parser.parse_args()
    config = load_config(resolve_path(args.config))
    if args.dry_run_reset:
        result = plan_reset(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.reset_now:
        result = reset_stack(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(
        "telegram_new_listener long-polling output is disabled. "
        "Use scripts/telegram_live_bridge.py as the single Telegram customer-service output, "
        "or pass --dry-run-reset / --reset-now for local reset maintenance.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
