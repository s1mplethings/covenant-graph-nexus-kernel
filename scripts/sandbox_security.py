#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
from typing import Any

try:
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import base_result


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REPORT_NAME = "security_blocked.json"
ALLOWED_ENV_KEYS = {
    "PATH",
    "SystemRoot",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "NODE_ENV",
    "CI",
}
SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|credential)", re.IGNORECASE)
DANGEROUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("rm -rf", re.compile(r"\brm\s+-rf\b", re.IGNORECASE)),
    ("del /s", re.compile(r"\bdel\s+/(s|q).*", re.IGNORECASE)),
    ("format", re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE)),
    ("shutdown", re.compile(r"\bshutdown\b", re.IGNORECASE)),
    ("unknown powershell download", re.compile(r"powershell.*Invoke-WebRequest", re.IGNORECASE)),
    ("unknown curl", re.compile(r"\bcurl\s+(?!.*(127\.0\.0\.1|localhost))", re.IGNORECASE)),
    ("unknown wget", re.compile(r"\bwget\s+(?!.*(127\.0\.0\.1|localhost))", re.IGNORECASE)),
    ("scp", re.compile(r"\bscp\b", re.IGNORECASE)),
    ("ssh", re.compile(r"\bssh\b", re.IGNORECASE)),
    ("net user", re.compile(r"\bnet\s+user\b", re.IGNORECASE)),
    ("reg delete", re.compile(r"\breg\s+delete\b", re.IGNORECASE)),
    ("Remove-Item -Recurse", re.compile(r"Remove-Item\b.*-Recurse", re.IGNORECASE)),
]


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_runtime_env(env: dict[str, str] | None = None) -> dict[str, str]:
    source = env or dict(os.environ)
    return {key: value for key, value in source.items() if key in ALLOWED_ENV_KEYS and not SECRET_KEY_RE.search(key)}


def _is_relative_to(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def validate_execution_path(path: pathlib.Path, allowed_roots: list[pathlib.Path]) -> dict[str, Any]:
    resolved = pathlib.Path(path).resolve()
    roots = [item.resolve() for item in allowed_roots]
    ok = any(_is_relative_to(resolved, root) for root in roots)
    return base_result(status="pass" if ok else "fail", verdict="path_allowed" if ok else "path_outside_allowed_roots", blockers=[] if ok else [str(resolved)])


def _scan_command(command: str, source: str) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for label, pattern in DANGEROUS_PATTERNS:
        if pattern.search(command):
            hits.append({"source": source, "command": command, "risk": label})
    return hits


def _scan_package_json(path: pathlib.Path) -> list[dict[str, str]]:
    doc = read_json(path)
    scripts = doc.get("scripts", {}) if isinstance(doc.get("scripts"), dict) else {}
    hits: list[dict[str, str]] = []
    for name, command in scripts.items():
        hits.extend(_scan_command(str(command), f"{path.name}:scripts.{name}"))
    return hits


def _scan_script_text(path: pathlib.Path) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    hits: list[dict[str, str]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        hits.extend(_scan_command(line, f"{path.relative_to(path.parents[0]).as_posix()}:{line_no}"))
    return hits


def scan_project(
    project_dir: pathlib.Path,
    *,
    run_dir: pathlib.Path | None = None,
    candidate_dir: pathlib.Path | None = None,
    final_dir: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
    write_block_file: bool = True,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    allowed_roots = [root.resolve() for root in (run_dir, candidate_dir, final_dir, project) if root]
    dangerous_commands: list[dict[str, str]] = []
    unsafe_paths: list[str] = []
    secret_leak_risks: list[str] = []
    network_risks: list[str] = []

    if not project.exists():
        unsafe_paths.append(str(project))
    else:
        for path in project.rglob("*"):
            if not path.is_file():
                continue
            if not any(_is_relative_to(path, root) for root in allowed_roots):
                unsafe_paths.append(str(path))
            if path.name == "package.json":
                dangerous_commands.extend(_scan_package_json(path))
            elif path.suffix.lower() in {".sh", ".ps1", ".bat", ".cmd", ".py", ".js", ".mjs", ".cjs"}:
                dangerous_commands.extend(_scan_script_text(path))
            if path.suffix.lower() in {".env", ".pem", ".key"}:
                secret_leak_risks.append(path.relative_to(project).as_posix())
            else:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    text = ""
                if re.search(r"(OPENAI_API_KEY|sk-[A-Za-z0-9_-]{12,}|BEGIN PRIVATE KEY)", text):
                    secret_leak_risks.append(path.relative_to(project).as_posix())
    for hit in dangerous_commands:
        if hit["risk"] in {"unknown curl", "unknown wget", "unknown powershell download", "scp", "ssh"}:
            network_risks.append(hit["source"])

    runtime_env = safe_runtime_env(env)
    leaked_env = sorted(set((env or os.environ).keys()) - set(runtime_env.keys()))
    status = "fail" if dangerous_commands or unsafe_paths or secret_leak_risks else ("warning" if network_risks else "pass")
    verdict = "SECURITY_BLOCKED" if status == "fail" else "SECURITY_PASS"
    report = {
        "status": status,
        "dangerous_commands": dangerous_commands,
        "unsafe_paths": unsafe_paths,
        "secret_leak_risks": secret_leak_risks,
        "network_risks": network_risks,
        "runtime_env_keys": sorted(runtime_env.keys()),
        "redacted_env_keys": leaked_env,
        "verdict": verdict,
    }
    if write_block_file and status == "fail":
        write_json(project / DEFAULT_REPORT_NAME, report)
    return report


def assert_final_promotion_allowed(security_report: dict[str, Any]) -> dict[str, Any]:
    allowed = security_report.get("verdict") == "SECURITY_PASS" and security_report.get("status") in {"pass", "warning"}
    return base_result(
        status="pass" if allowed else "fail",
        verdict="final_promotion_security_allowed" if allowed else "final_promotion_security_blocked",
        blockers=[] if allowed else ["security_blocked"],
        metadata={"security": security_report},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    report = scan_project(pathlib.Path(args.project_dir))
    if args.report:
        write_json(pathlib.Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] == "SECURITY_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
