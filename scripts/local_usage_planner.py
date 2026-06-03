#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exists(project_dir: pathlib.Path, name: str) -> bool:
    return (project_dir / name).exists()


def _required_file_status(project_dir: pathlib.Path, names: list[str]) -> list[dict[str, Any]]:
    return [{"path": name, "exists": _exists(project_dir, name)} for name in names]


def create_usage_plan(project_dir: pathlib.Path, project_type: str | None = None) -> dict[str, Any]:
    project_dir = pathlib.Path(project_dir)
    plan: dict[str, Any] = {
        "kind": "LocalUsagePlan",
        "created_at": now(),
        "planner": "local_deterministic",
        "uses_model": False,
        "uses_provider": False,
        "uses_network": False,
        "project_dir": str(project_dir),
        "project_type": project_type or "",
        "status": "PARTIAL",
        "run_mode": "unknown",
        "open_instruction": "",
        "possible_commands": [],
        "screenshot_strategy": "",
        "required_files": [],
        "reason": "",
    }
    if _exists(project_dir, "index.html"):
        required = ["index.html", "styles.css", "app.js", "README.md"]
        plan.update(
            {
                "status": "PARTIAL",
                "run_mode": "static_html",
                "open_instruction": "open index.html in browser",
                "possible_commands": [],
                "screenshot_strategy": "static_svg_preview or browser_capture_if_available",
                "required_files": _required_file_status(project_dir, required),
                "reason": "recognized static HTML entrypoint",
            }
        )
        return plan
    if _exists(project_dir, "package.json"):
        required = ["package.json", "README.md"]
        plan.update(
            {
                "status": "PARTIAL",
                "run_mode": "node_project",
                "open_instruction": "run npm commands locally if dependencies are available",
                "possible_commands": [["npm", "install"], ["npm", "test"], ["npm", "start"]],
                "screenshot_strategy": "browser_capture_if_start_command_serves_ui",
                "required_files": _required_file_status(project_dir, required),
                "reason": "recognized Node project entrypoint",
            }
        )
        return plan
    if _exists(project_dir, "pyproject.toml") or _exists(project_dir, "requirements.txt"):
        required = ["README.md"]
        if _exists(project_dir, "pyproject.toml"):
            required.append("pyproject.toml")
        if _exists(project_dir, "requirements.txt"):
            required.append("requirements.txt")
        plan.update(
            {
                "status": "PARTIAL",
                "run_mode": "python_project",
                "open_instruction": "run a local Python smoke test",
                "possible_commands": [["python", "-m", "pytest"], ["python", "-m", "compileall", "."]],
                "screenshot_strategy": "not_applicable_unless_project_serves_ui",
                "required_files": _required_file_status(project_dir, required),
                "reason": "recognized Python project entrypoint",
            }
        )
        return plan
    plan["reason"] = "no recognized local entrypoint"
    return plan


def create_runtime_check(project_dir: pathlib.Path, usage_plan: dict[str, Any]) -> dict[str, Any]:
    required = usage_plan.get("required_files", [])
    missing = [row.get("path") for row in required if isinstance(row, dict) and not row.get("exists")]
    return {
        "kind": "LocalRuntimeCheck",
        "created_at": now(),
        "status": "PARTIAL" if usage_plan.get("run_mode") != "unknown" else "PARTIAL",
        "run_mode": usage_plan.get("run_mode", "unknown"),
        "project_dir": str(pathlib.Path(project_dir)),
        "checks": [
            "recognized local entrypoint" if usage_plan.get("run_mode") != "unknown" else "no recognized local entrypoint",
            "required file inventory completed",
        ],
        "missing_required_files": missing,
        "reason": usage_plan.get("reason", ""),
    }


def create_visual_evidence_plan(project_dir: pathlib.Path, usage_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "LocalVisualEvidencePlan",
        "created_at": now(),
        "status": "PARTIAL",
        "project_dir": str(pathlib.Path(project_dir)),
        "run_mode": usage_plan.get("run_mode", "unknown"),
        "screenshot_strategy": usage_plan.get("screenshot_strategy", ""),
        "artifacts_to_collect": ["README excerpt", "static HTML screenshot"] if usage_plan.get("run_mode") == "static_html" else ["README excerpt"],
        "uses_model": False,
        "uses_provider": False,
        "uses_network": False,
    }


def write_usage_plan(project_dir: pathlib.Path, usage_plan: dict[str, Any]) -> pathlib.Path:
    path = pathlib.Path(project_dir) / "usage_plan.json"
    path.write_text(json.dumps(usage_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
