#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import local_agent_skills
import local_packager


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inside(base: pathlib.Path, path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _project_path(project_dir: pathlib.Path, raw: str) -> pathlib.Path:
    rel = pathlib.Path(str(raw or "."))
    path = rel if rel.is_absolute() else project_dir / rel
    resolved = path.resolve()
    if not _inside(project_dir, resolved):
        raise PermissionError(f"path outside project_dir is not allowed: {raw}")
    return resolved


def _command_is_dangerous(command: str) -> bool:
    lowered = command.lower()
    dangerous_patterns = [
        r"\brm\s+-[^\n;]*r[^\n;]*f\s+[/\\]",
        r"\bformat\s+[a-z]:",
        r"\bdel\s+(/[sq]\s+)*[a-z]:\\",
        r"\brmdir\s+(/[sq]\s+)*[a-z]:\\",
        r"\bremove-item\b[^\n;]*(c:\\windows|c:\\program files|/windows|/system32)",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bmkfs\b",
        r"\bdiskpart\b",
    ]
    if ".." in pathlib.PurePosixPath(command.replace("\\", "/")).parts:
        return True
    return any(re.search(pattern, lowered) for pattern in dangerous_patterns)


class LocalAgentActionExecutor:
    def __init__(self, project_dir: str | pathlib.Path, *, command_timeout: int = 120) -> None:
        self.project_dir = pathlib.Path(project_dir).resolve()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.command_timeout = command_timeout

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        action_type = str(action.get("type") or action.get("action") or "").strip()
        try:
            if action_type == "write_file":
                result = self.write_file(str(action.get("path", "")), str(action.get("content", "")))
            elif action_type == "read_file":
                result = self.read_file(str(action.get("path", "")))
            elif action_type == "list_files":
                result = self.list_files(str(action.get("path", ".")))
            elif action_type == "run_command":
                result = self.run_command(str(action.get("command", "")))
            elif action_type == "capture_screenshot":
                result = self.capture_screenshot(action)
            elif action_type == "package_project":
                result = self.package_project(action)
            elif action_type == "search_skills":
                result = self.search_skills(str(action.get("query", "")))
            elif action_type == "use_skill":
                result = self.use_skill(str(action.get("name", "")), action.get("args", {}))
            elif action_type == "propose_skill":
                result = self.propose_skill(action)
            else:
                raise ValueError(f"unsupported action type: {action_type}")
            ok = not (action_type == "run_command" and int(result.get("returncode", 0)) != 0)
            return {"ok": ok, "type": action_type, "created_at": now(), **result}
        except Exception as exc:
            return {"ok": False, "type": action_type, "created_at": now(), "error": str(exc)}

    def write_file(self, raw_path: str, content: str) -> dict[str, Any]:
        if not raw_path.strip():
            raise ValueError("write_file requires path")
        path = _project_path(self.project_dir, raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": str(path), "bytes": len(content.encode("utf-8"))}

    def read_file(self, raw_path: str) -> dict[str, Any]:
        path = _project_path(self.project_dir, raw_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(raw_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"path": str(path), "content": text[:20000], "truncated": len(text) > 20000}

    def list_files(self, raw_path: str = ".") -> dict[str, Any]:
        path = _project_path(self.project_dir, raw_path or ".")
        if not path.exists():
            raise FileNotFoundError(raw_path)
        files: list[str] = []
        base = path if path.is_dir() else path.parent
        for item in sorted(base.rglob("*")):
            if item.is_file():
                files.append(str(item.relative_to(self.project_dir)))
            if len(files) >= 500:
                break
        return {"path": str(path), "files": files}

    def run_command(self, command: str) -> dict[str, Any]:
        if not command.strip():
            raise ValueError("run_command requires command")
        if _command_is_dangerous(command):
            raise PermissionError("dangerous command rejected")
        env = os.environ.copy()
        env["CGNK_PROJECT_DIR"] = str(self.project_dir)
        proc = subprocess.run(
            command,
            cwd=str(self.project_dir),
            shell=True,
            capture_output=True,
            text=True,
            timeout=self.command_timeout,
            env=env,
        )
        return {
            "command": command,
            "cwd": str(self.project_dir),
            "returncode": proc.returncode,
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-12000:],
        }

    def capture_screenshot(self, action: dict[str, Any]) -> dict[str, Any]:
        path = _project_path(self.project_dir, str(action.get("path") or "screenshot.txt"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "Screenshot capture was requested, but no browser capture backend is wired in this local executor.\n",
            encoding="utf-8",
        )
        return {"path": str(path), "warning": "screenshot capture unavailable; recorded warning only"}

    def package_project(self, action: dict[str, Any]) -> dict[str, Any]:
        output_dir = action.get("output_dir") or self.project_dir
        if output_dir:
            output_path = _project_path(self.project_dir, str(output_dir))
        else:
            output_path = self.project_dir
        run_log_path = _project_path(self.project_dir, str(action["run_log_path"])) if action.get("run_log_path") else None
        screenshot_path = _project_path(self.project_dir, str(action["screenshot_path"])) if action.get("screenshot_path") else None
        manifest = local_packager.package_project(
            self.project_dir,
            output_dir=output_path,
            startup_command=str(action.get("startup_command", "")),
            run_log_path=run_log_path,
            screenshot_path=screenshot_path,
            known_limits=[str(item) for item in action.get("known_limits", []) if str(item).strip()]
            if isinstance(action.get("known_limits"), list)
            else [],
        )
        return {"manifest": manifest, "package_path": manifest.get("package_path"), "manifest_path": manifest.get("manifest_path")}

    def search_skills(self, query: str) -> dict[str, Any]:
        return local_agent_skills.search_skills(query)

    def use_skill(self, name: str, args: Any) -> dict[str, Any]:
        clean_args = args if isinstance(args, dict) else {}
        return local_agent_skills.use_skill(self.project_dir, name, clean_args)

    def propose_skill(self, action: dict[str, Any]) -> dict[str, Any]:
        manifest = action.get("manifest", {})
        return local_agent_skills.propose_skill(
            self.project_dir,
            str(action.get("name", "")),
            str(action.get("description", "")),
            manifest if isinstance(manifest, dict) else {},
            str(action.get("notes", "")),
        )


def execute_action(project_dir: str | pathlib.Path, action: dict[str, Any]) -> dict[str, Any]:
    return LocalAgentActionExecutor(project_dir).execute(action)


def result_to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)
