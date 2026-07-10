from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_commands(project_dir: str | pathlib.Path) -> list[list[str]]:
    project = pathlib.Path(project_dir)
    if (project / "tests").exists() and ((project / "pyproject.toml").exists() or (project / "requirements.txt").exists() or (project / "app.py").exists() or (project / "main.py").exists()):
        return [["python", "-m", "pytest", "tests"]]
    if (project / "package.json").exists():
        return [["npm", "test"]]
    if (project / "index.html").exists():
        return [["python", "-c", "from pathlib import Path; assert Path('index.html').read_text(encoding='utf-8').strip()"]]
    if (project / "app.py").exists():
        return [["python", "app.py"]]
    if (project / "main.py").exists():
        return [["python", "main.py"]]
    return []


def run_tests(project_dir: str | pathlib.Path, *, timeout: int = 60) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    started = _now()
    commands = detect_commands(project)
    executions: list[dict[str, Any]] = []
    if not commands:
        result = {
            "verdict": "FAIL",
            "commands_run": [],
            "executions": [],
            "started_at": started,
            "finished_at": _now(),
            "reason": "NO REAL TEST EXECUTION",
        }
    else:
        for command in commands[:1]:
            item_started = _now()
            try:
                env = os.environ.copy()
                python_paths = [str(project)]
                if env.get("PYTHONPATH"):
                    python_paths.append(env["PYTHONPATH"])
                env["PYTHONPATH"] = os.pathsep.join(python_paths)
                env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
                if command[:3] == ["python", "-m", "pytest"]:
                    command = [sys.executable, "-m", "pytest", *command[3:]]
                proc = subprocess.run(command, cwd=project, capture_output=True, text=True, timeout=timeout, env=env)
                executions.append(
                    {
                        "command": " ".join(command),
                        "exit_code": proc.returncode,
                        "stdout_summary": (proc.stdout or "")[-4000:],
                        "stderr_summary": (proc.stderr or "")[-4000:],
                        "started_at": item_started,
                        "finished_at": _now(),
                    }
                )
            except Exception as exc:
                executions.append(
                    {
                        "command": " ".join(command),
                        "exit_code": -1,
                        "stdout_summary": "",
                        "stderr_summary": str(exc),
                        "started_at": item_started,
                        "finished_at": _now(),
                    }
                )
        result = {
            "verdict": "PASS" if executions and all(int(item.get("exit_code", 1)) == 0 for item in executions) else "FAIL",
            "commands_run": [item["command"] for item in executions],
            "executions": executions,
            "started_at": started,
            "finished_at": _now(),
        }
    (project / "test_execution.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_test_report(project, result)
    return result


def write_test_report(project: pathlib.Path, result: dict[str, Any]) -> pathlib.Path:
    lines = ["# Test Report", "", "commands_run:"]
    commands = result.get("commands_run", []) if isinstance(result.get("commands_run"), list) else []
    if commands:
        lines.extend(f"- {cmd}" for cmd in commands)
    else:
        lines.append("- NO REAL TEST EXECUTION")
    first = result.get("executions", [{}])[0] if isinstance(result.get("executions"), list) and result.get("executions") else {}
    lines.extend(
        [
            "",
            f"exit_code: {first.get('exit_code', 'none')}",
            f"stdout_summary: {str(first.get('stdout_summary', ''))[:1000]}",
            f"stderr_summary: {str(first.get('stderr_summary', ''))[:1000]}",
            f"started_at: {result.get('started_at', '')}",
            f"finished_at: {result.get('finished_at', '')}",
            f"verdict: {result.get('verdict', 'FAIL')}",
        ]
    )
    if not commands:
        lines.append("NO REAL TEST EXECUTION")
    path = project / "TEST_REPORT.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def inspect_test_report(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    execution = project / "test_execution.json"
    report = project / "TEST_REPORT.md"
    if execution.exists():
        try:
            doc = json.loads(execution.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            doc = {}
        return {"verdict": "PASS" if doc.get("verdict") == "PASS" else "FAIL", "source": "test_execution.json", "details": doc}
    if not report.exists():
        return {"verdict": "FAIL", "source": "", "missing": ["TEST_REPORT.md"]}
    text = report.read_text(encoding="utf-8", errors="replace")
    has_command = "commands_run" in text and "exit_code" in text
    fake = "NO TEST EXECUTED" in text.upper() or "NO REAL TEST EXECUTION" in text.upper()
    return {"verdict": "PASS" if has_command and not fake else "FAIL", "source": "TEST_REPORT.md", "missing": [] if has_command and not fake else ["real_test_execution"]}
