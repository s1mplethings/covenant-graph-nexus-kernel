#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
import shlex
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


SkillFn = Callable[[pathlib.Path, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    keywords: tuple[str, ...]
    fn: SkillFn


def inside(base: pathlib.Path, path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def project_path(project_dir: str | pathlib.Path, raw: str) -> pathlib.Path:
    base = pathlib.Path(project_dir).resolve()
    rel = pathlib.Path(str(raw or ""))
    path = rel if rel.is_absolute() else base / rel
    resolved = path.resolve()
    if not inside(base, resolved):
        raise PermissionError(f"path outside project_dir is not allowed: {raw}")
    return resolved


def _error(skill: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "skill": skill, "error": message, **extra}


def _safe_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(name or "").strip().lower()).strip(".-")
    return safe[:80] or "unnamed-skill"


def _tail(text: str, limit: int = 12000) -> str:
    return str(text or "")[-limit:]


def _patch_file(project_dir: pathlib.Path, args: dict[str, Any]) -> dict[str, Any]:
    skill = "patch_file"
    try:
        path = project_path(project_dir, str(args.get("path", "")))
        find = str(args.get("find", ""))
        replace = str(args.get("replace", ""))
        if not find:
            return _error(skill, "find must not be empty")
        if not path.exists() or not path.is_file():
            return _error(skill, "file does not exist", path=str(path))
        text = path.read_text(encoding="utf-8", errors="replace")
        count = text.count(find)
        if count < 1:
            return _error(skill, "find text not found", path=str(path))
        path.write_text(text.replace(find, replace, 1), encoding="utf-8")
        return {"ok": True, "skill": skill, "path": str(path), "changed": True, "replacements": 1}
    except Exception as exc:
        return _error(skill, str(exc))


def _delete_file(project_dir: pathlib.Path, args: dict[str, Any]) -> dict[str, Any]:
    skill = "delete_file"
    try:
        path = project_path(project_dir, str(args.get("path", "")))
        if not path.exists():
            return _error(skill, "file does not exist", path=str(path))
        if path.is_dir():
            return _error(skill, "directories cannot be deleted by delete_file", path=str(path))
        path.unlink()
        return {"ok": True, "skill": skill, "path": str(path), "deleted": True}
    except Exception as exc:
        return _error(skill, str(exc))


def _copy_file(project_dir: pathlib.Path, args: dict[str, Any]) -> dict[str, Any]:
    skill = "copy_file"
    try:
        source = project_path(project_dir, str(args.get("source", "")))
        target = project_path(project_dir, str(args.get("target", "")))
        if not source.exists() or not source.is_file():
            return _error(skill, "source file does not exist", source=str(source))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return {"ok": True, "skill": skill, "source": str(source), "target": str(target), "bytes": target.stat().st_size}
    except Exception as exc:
        return _error(skill, str(exc))


def _write_json(project_dir: pathlib.Path, args: dict[str, Any]) -> dict[str, Any]:
    skill = "write_json"
    try:
        path = project_path(project_dir, str(args.get("path", "")))
        value = args.get("value")
        if not isinstance(value, dict):
            return _error(skill, "value must be a JSON object")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "skill": skill, "path": str(path), "bytes": path.stat().st_size}
    except Exception as exc:
        return _error(skill, str(exc))


def _command_allowed(command: str) -> bool:
    compact = re.sub(r"\s+", " ", command.strip())
    allowed_prefixes = (
        "python ",
        "python3 ",
        "py ",
        "pytest",
        "npm test",
        "npm run ",
        "node ",
        "pnpm test",
        "pnpm run ",
    )
    return compact in {"pytest", "npm test", "pnpm test"} or compact.startswith(allowed_prefixes)


def _run_tests(project_dir: pathlib.Path, args: dict[str, Any]) -> dict[str, Any]:
    skill = "run_tests"
    try:
        command = str(args.get("command", "")).strip()
        timeout = int(args.get("timeout", 120) or 120)
        if not command:
            return _error(skill, "command is required")
        if re.search(r"[;|`\n\r]", command):
            return _error(skill, "shell chaining characters are not allowed")
        if not _command_allowed(command):
            return _error(skill, "command prefix is not approved")
        argv = shlex.split(command)
        if not argv:
            return _error(skill, "command is required")
        proc = subprocess.run(
            argv,
            cwd=str(project_dir),
            shell=False,
            capture_output=True,
            text=True,
            timeout=max(1, min(timeout, 600)),
        )
        return {
            "ok": proc.returncode == 0,
            "skill": skill,
            "command": command,
            "argv": argv,
            "returncode": proc.returncode,
            "stdout_tail": _tail(proc.stdout),
            "stderr_tail": _tail(proc.stderr),
        }
    except Exception as exc:
        return _error(skill, str(exc))


def _localhost_url(url: str) -> tuple[bool, str]:
    parsed = urllib.parse.urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"}:
        return False, "only http/https URLs are supported"
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return False, "only localhost URLs are allowed"
    return True, ""


def _http_request(project_dir: pathlib.Path, args: dict[str, Any]) -> dict[str, Any]:
    skill = "http_request"
    try:
        method = str(args.get("method", "GET")).strip().upper()
        url = str(args.get("url", "")).strip()
        ok, reason = _localhost_url(url)
        if not ok:
            return _error(skill, reason)
        if method not in {"GET", "POST"}:
            return _error(skill, "only GET and POST are supported")
        body = str(args.get("body", ""))
        data = body.encode("utf-8") if method == "POST" else None
        request = urllib.request.Request(url, data=data, method=method)
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read(20000).decode("utf-8", errors="replace")
            return {"ok": True, "skill": skill, "method": method, "url": url, "status_code": response.status, "body_excerpt": text[:4000]}
    except urllib.error.HTTPError as exc:
        body = exc.read(4000).decode("utf-8", errors="replace")
        return {"ok": False, "skill": skill, "method": method, "url": url, "status_code": exc.code, "body_excerpt": body, "error": str(exc)}
    except Exception as exc:
        return _error(skill, str(exc))


def _browser_screenshot(project_dir: pathlib.Path, args: dict[str, Any]) -> dict[str, Any]:
    skill = "browser_screenshot"
    try:
        url = str(args.get("url", "")).strip()
        ok, reason = _localhost_url(url)
        if not ok:
            return _error(skill, reason)
        output = project_path(project_dir, str(args.get("output_path", "artifacts/screenshot.png")))
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception:
            return {
                "ok": False,
                "skill": skill,
                "error": "playwright is not installed or browser is missing",
                "actionable": "Install Playwright and browsers, or continue with package_project using a warning.",
            }
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=15000)
                page.screenshot(path=str(output), full_page=True)
                browser.close()
            return {"ok": True, "skill": skill, "url": url, "output_path": str(output), "bytes": output.stat().st_size}
        except Exception as exc:
            return _error(
                skill,
                "playwright is not installed or browser is missing",
                actionable="Install Playwright and browsers, or continue with package_project using a warning.",
                detail=str(exc),
            )
    except Exception as exc:
        return _error(skill, str(exc))


APPROVED_SKILLS: dict[str, SkillSpec] = {}


def _register(spec: SkillSpec) -> None:
    APPROVED_SKILLS[spec.name] = spec


_register(SkillSpec("patch_file", "Replace text inside one project file.", ("patch", "replace", "edit", "small edit", "file"), _patch_file))
_register(SkillSpec("delete_file", "Delete one file inside the project.", ("delete", "remove", "file", "cleanup"), _delete_file))
_register(SkillSpec("copy_file", "Copy one project file to another project path.", ("copy", "asset", "file"), _copy_file))
_register(SkillSpec("write_json", "Write a JSON object to a project file.", ("json", "config", "write"), _write_json))
_register(SkillSpec("run_tests", "Run an approved local test or build command.", ("test", "build", "pytest", "npm", "node"), _run_tests))
_register(SkillSpec("http_request", "Call a localhost API endpoint.", ("http", "api", "localhost", "health", "post", "get"), _http_request))
_register(SkillSpec("browser_screenshot", "Capture a screenshot of a localhost web page.", ("browser", "screenshot", "web", "localhost", "preview"), _browser_screenshot))


def search_skills(query: str) -> dict[str, Any]:
    try:
        terms = set(re.findall(r"[a-zA-Z0-9_+#.-]+|[\u4e00-\u9fff]{2,}", str(query or "").lower()))
        rows: list[dict[str, Any]] = []
        for spec in APPROVED_SKILLS.values():
            haystack = {spec.name.lower(), *[item.lower() for item in spec.keywords], *re.findall(r"[a-zA-Z0-9_+#.-]+", spec.description.lower())}
            score = len(terms & haystack) if terms else 0
            if score > 0 or not terms:
                rows.append({"name": spec.name, "description": spec.description, "keywords": list(spec.keywords), "score": score})
        rows.sort(key=lambda item: (-int(item["score"]), str(item["name"])))
        return {"ok": True, "type": "search_skills", "skills": rows}
    except Exception as exc:
        return {"ok": False, "type": "search_skills", "error": str(exc), "skills": []}


def use_skill(project_dir: str | pathlib.Path, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    skill_name = str(name or "").strip()
    try:
        spec = APPROVED_SKILLS.get(skill_name)
        if spec is None:
            return _error(skill_name or "use_skill", "skill is not approved")
        clean_args = args if isinstance(args, dict) else {}
        return spec.fn(pathlib.Path(project_dir).resolve(), clean_args)
    except Exception as exc:
        return _error(skill_name or "use_skill", str(exc))


def propose_skill(
    project_dir: str | pathlib.Path,
    name: str,
    description: str,
    manifest: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    skill = "propose_skill"
    try:
        safe = _safe_name(name)
        if safe in APPROVED_SKILLS or str(name or "").strip() in APPROVED_SKILLS:
            return _error(skill, "approved skills cannot be overwritten", name=str(name or ""))
        draft_dir = project_path(project_dir, f"skills/_drafts/{safe}")
        draft_dir.mkdir(parents=True, exist_ok=True)
        draft = {
            "name": safe,
            "requested_name": str(name or ""),
            "description": str(description or ""),
            "manifest": manifest if isinstance(manifest, dict) else {},
            "approved": False,
            "dynamic_execution_enabled": False,
        }
        draft_path = draft_dir / "skill_draft.json"
        draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        notes_path = ""
        if str(notes or "").strip():
            note_file = draft_dir / "notes.md"
            note_file.write_text(str(notes), encoding="utf-8")
            notes_path = str(note_file)
        return {
            "ok": True,
            "skill": skill,
            "name": safe,
            "draft_path": str(draft_path),
            "notes_path": notes_path,
            "next_step": "A human must review and approve this draft before it can be added to APPROVED_SKILLS.",
        }
    except Exception as exc:
        return _error(skill, str(exc))


def approved_skill_names() -> list[str]:
    return sorted(APPROVED_SKILLS)
