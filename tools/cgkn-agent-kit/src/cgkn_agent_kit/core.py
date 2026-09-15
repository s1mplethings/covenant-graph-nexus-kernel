from __future__ import annotations

import json
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from importlib import resources
from typing import Any, Iterable


CONFIG_KIND = "CGKNAgentKitProject"
CONFIG_VERSION = "1.0"
SUPPORT_DIR = pathlib.Path(".cgkn") / "agent-kit"
CONFIG_PATH = pathlib.Path(".cgkn") / "agent-kit.json"
# Retained support/experimental lane identity; generation_command uses the
# formal conversation entrypoint below and never executes this path.
SUPPORT_PIPELINE_PATH = pathlib.Path(".") / "scripts" / "run_local_pipeline.py"
IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".cgkn", ".idea", ".vscode", "__pycache__",
    "node_modules", "vendor", "dist", "build", "coverage", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".venv", "venv", "env",
}
TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html",
    ".java", ".js", ".json", ".jsx", ".kt", ".md", ".php", ".ps1",
    ".py", ".rb", ".rs", ".sh", ".sql", ".svelte", ".toml", ".ts",
    ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml",
}
SENSITIVE_NAMES = {
    "credentials", "credentials.json", "secrets", "secrets.json", "auth.json",
    ".npmrc", ".pypirc", "id_rsa", "id_ed25519",
}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".keystore"}
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?im)^\s*(?:OPENAI|CODEX|API)[A-Z0-9_]*(?:KEY|TOKEN)\s*=.*$"),
)


class AgentKitError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AgentKitError(f"Cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentKitError(f"JSON object required: {path}")
    return value


def write_json(path: pathlib.Path, value: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    )
    temp_path = pathlib.Path(handle.name)
    try:
        with handle:
            handle.write(data)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return path


def _valid_cgkn_root(path: pathlib.Path) -> bool:
    return all((path / relative).is_file() for relative in (
        "scripts/codex_capability_supervisor.py",
        "scripts/run_local_pipeline.py",
    ))


def resolve_cgkn_root(explicit: str = "") -> pathlib.Path:
    if explicit:
        resolved = pathlib.Path(explicit).expanduser().resolve()
        if _valid_cgkn_root(resolved):
            return resolved
        raise AgentKitError(f"Not a compatible CGKN checkout: {resolved}")
    candidates: list[pathlib.Path] = []
    if os.environ.get("CGKN_ROOT"):
        candidates.append(pathlib.Path(os.environ["CGKN_ROOT"]))
    candidates.extend(pathlib.Path(__file__).resolve().parents)
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if _valid_cgkn_root(resolved):
            return resolved
    raise AgentKitError(
        "CGKN root not found. Pass --cgkn-root during init or set CGKN_ROOT for this process."
    )


def initialize_project(project_root: pathlib.Path, cgkn_root: pathlib.Path, *, force: bool = False) -> dict[str, Any]:
    project_root = project_root.resolve()
    config_path = project_root / CONFIG_PATH
    if config_path.exists() and not force:
        raise AgentKitError(f"Project is already initialized: {config_path}")
    if not _valid_cgkn_root(cgkn_root):
        raise AgentKitError(f"Not a compatible CGKN checkout: {cgkn_root}")
    support_dir = project_root / SUPPORT_DIR
    support_dir.mkdir(parents=True, exist_ok=True)
    ignore_path = support_dir / ".gitignore"
    if not ignore_path.exists():
        ignore_path.write_text("*\n!.gitignore\n", encoding="utf-8", newline="\n")
    config = {
        "kind": CONFIG_KIND,
        "schema_version": CONFIG_VERSION,
        "created_at": now(),
        "cgkn_root": str(cgkn_root.resolve()),
        "artifact_dir": SUPPORT_DIR.as_posix(),
        "agent_backend": "codex",
        "provider_entrypoint": "scripts/run_codex_conversation_generation.py",
        "stores_secrets": False,
    }
    write_json(config_path, config)
    return config


def load_project(project_root: pathlib.Path) -> tuple[pathlib.Path, dict[str, Any], pathlib.Path]:
    root = project_root.resolve()
    config = read_json(root / CONFIG_PATH)
    if config.get("kind") != CONFIG_KIND or config.get("schema_version") != CONFIG_VERSION:
        raise AgentKitError("Unsupported .cgkn/agent-kit.json contract")
    artifact_dir = pathlib.PurePosixPath(str(config.get("artifact_dir", "")).replace("\\", "/"))
    if artifact_dir.is_absolute() or ".." in artifact_dir.parts or not artifact_dir.parts or artifact_dir.parts[0] != ".cgkn":
        raise AgentKitError("artifact_dir must remain a relative path under .cgkn")
    cgkn_root = resolve_cgkn_root(str(config.get("cgkn_root", "")))
    return root, config, cgkn_root


def redact(text: str) -> str:
    result = text
    for pattern in SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _sensitive_path(path: pathlib.Path) -> bool:
    name = path.name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name in SENSITIVE_NAMES
        or path.suffix.lower() in SENSITIVE_SUFFIXES
    )


def scan_project(project_root: pathlib.Path, *, max_items: int = 8, max_file_bytes: int = 65536) -> dict[str, Any]:
    root = project_root.resolve()
    selected: list[dict[str, Any]] = []
    excluded = 0
    preferred = {
        "readme.md": 0, "agents.md": 1, "pyproject.toml": 2, "package.json": 2,
        "cargo.toml": 2, "go.mod": 2, "requirements.txt": 2,
    }
    candidates: list[pathlib.Path] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name.lower() not in IGNORED_DIRS)
        for name in sorted(files):
            path = pathlib.Path(current) / name
            relative = path.relative_to(root)
            if path.is_symlink() or _sensitive_path(relative) or path.suffix.lower() not in TEXT_SUFFIXES:
                excluded += 1
                continue
            try:
                if path.stat().st_size > max_file_bytes:
                    excluded += 1
                    continue
            except OSError:
                excluded += 1
                continue
            candidates.append(path)
    candidates.sort(key=lambda path: (
        preferred.get(path.name.lower(), 5),
        len(path.relative_to(root).parts),
        path.relative_to(root).as_posix().lower(),
    ))
    for path in candidates:
        if len(selected) >= max_items:
            excluded += 1
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            excluded += 1
            continue
        relative = path.relative_to(root).as_posix()
        selected.append({
            "id": f"project-file-{len(selected) + 1}",
            "kind": "project_file_excerpt",
            "path": relative,
            "summary": redact(raw[:1200]),
        })
    return {
        "kind": "CGKNLibrarianContextPack",
        "project_root_name": root.name,
        "selected_items": selected,
        "excluded_count": excluded,
        "bounded": True,
    }


def _run(argv: list[str], *, cwd: pathlib.Path, input_text: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            argv, cwd=cwd, input=input_text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentKitError(f"Command could not run: {argv[0]}: {exc}") from exc
    if completed.returncode != 0:
        detail = redact((completed.stderr or completed.stdout).strip())[-2000:]
        raise AgentKitError(f"Command failed ({completed.returncode}): {argv[0]}: {detail}")
    return completed


def supervisor_command(cgkn_root: pathlib.Path, *args: str) -> list[str]:
    return [sys.executable, str(cgkn_root / "scripts" / "codex_capability_supervisor.py"), *args]


def prepare_request(
    project_root: pathlib.Path, *, goal: str, gap: str, category: str,
) -> pathlib.Path:
    root, config, cgkn_root = load_project(project_root)
    artifact_dir = root / str(config["artifact_dir"])
    context_path = write_json(artifact_dir / "librarian_context.json", scan_project(root))
    request_path = artifact_dir / "codex_request.json"
    session_path = artifact_dir / "agent_session.jsonl"
    _run(supervisor_command(
        cgkn_root, "prepare", "--goal", goal, "--gap", gap, "--category", category,
        "--librarian-json", str(context_path), "--output", str(request_path),
        "--session", str(session_path),
    ), cwd=cgkn_root)
    return request_path


def seal_draft(project_root: pathlib.Path, request_path: pathlib.Path, draft_path: pathlib.Path) -> pathlib.Path:
    root, config, cgkn_root = load_project(project_root)
    artifact_dir = root / str(config["artifact_dir"])
    response_path = artifact_dir / "codex_response.json"
    brief_path = artifact_dir / "codex_capability_brief.json"
    whiteboard_path = artifact_dir / "whiteboard_patch.json"
    session_path = artifact_dir / "agent_session.jsonl"
    _run(supervisor_command(
        cgkn_root, "respond", "--request", str(request_path.resolve()),
        "--draft", str(draft_path.resolve()), "--output", str(response_path),
        "--session", str(session_path),
    ), cwd=cgkn_root)
    _run(supervisor_command(
        cgkn_root, "validate", "--request", str(request_path.resolve()),
        "--response", str(response_path), "--output", str(brief_path),
        "--whiteboard-patch", str(whiteboard_path), "--session", str(session_path),
    ), cwd=cgkn_root)
    return brief_path


def locate_codex(explicit: str = "") -> str:
    candidate = explicit or shutil.which("codex") or ""
    if not candidate:
        raise AgentKitError("Codex CLI was not found on PATH; use a manual draft or install/authenticate Codex CLI.")
    return candidate


def codex_draft(project_root: pathlib.Path, request_path: pathlib.Path, *, codex_command: str = "", timeout: int = 600) -> pathlib.Path:
    root, config, _ = load_project(project_root)
    artifact_dir = root / str(config["artifact_dir"])
    draft_path = artifact_dir / "codex_draft.json"
    schema = resources.files("cgkn_agent_kit").joinpath("schemas/supervisor_draft.schema.json")
    executable = locate_codex(codex_command)
    prompt = (
        "Act only as the external advisory CGKN capability supervisor. Use only the bounded request "
        "piped to stdin; do not inspect other repository files. Do not edit files, write a generated candidate, "
        "claim formal evidence, package, or deliver. Return exactly the requested JSON draft schema."
    )
    argv = [
        executable, "exec", "--ephemeral", "--sandbox", "read-only",
        "--output-schema", str(schema), "--output-last-message", str(draft_path), prompt,
    ]
    request_text = request_path.read_text(encoding="utf-8")
    _run(argv, cwd=root, input_text=request_text, timeout=timeout)
    read_json(draft_path)
    return draft_path


def doctor(project_root: pathlib.Path, *, codex_command: str = "") -> dict[str, Any]:
    root, config, cgkn_root = load_project(project_root)
    report: dict[str, Any] = {
        "kind": "CGKNAgentKitDoctorReport",
        "project_root": str(root),
        "cgkn_root": str(cgkn_root),
        "provider_mainline_available": _valid_cgkn_root(cgkn_root),
        "secrets_stored": bool(config.get("stores_secrets", True)),
        "codex": {"found": False, "usable": False, "detail": "not found"},
    }
    try:
        executable = locate_codex(codex_command)
        report["codex"] = {"found": True, "usable": False, "path": executable, "detail": "probe failed"}
        completed = subprocess.run(
            [executable, "--version"], cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, check=False,
        )
        report["codex"]["usable"] = completed.returncode == 0
        report["codex"]["detail"] = redact((completed.stdout or completed.stderr).strip())[:500]
    except (AgentKitError, OSError, subprocess.TimeoutExpired) as exc:
        report["codex"]["detail"] = redact(str(exc))[:500]
    report["ready_for_manual_agent"] = report["provider_mainline_available"] and not report["secrets_stored"]
    report["ready_for_codex_automation"] = report["ready_for_manual_agent"] and report["codex"]["usable"]
    return report


def generation_command(
    project_root: pathlib.Path, *, goal: str, brief_path: pathlib.Path,
    out_dir: pathlib.Path | None = None, model: str = "gpt-4.1",
    allow_network: bool = False, resume_run_dir: pathlib.Path | None = None,
    provider_mode: str = "live", replay_dir: pathlib.Path | None = None,
) -> list[str]:
    root, config, cgkn_root = load_project(project_root)
    artifact_dir = root / str(config["artifact_dir"])
    out = (out_dir or (artifact_dir / "generated-project")).resolve()
    mode = str(provider_mode or "live").strip().lower()
    if mode not in {"live", "codex_surrogate", "deterministic_replay"}:
        raise AgentKitError(f"Unsupported provider_mode: {mode}")
    if mode != "deterministic_replay" and replay_dir is not None:
        raise AgentKitError("replay_dir is valid only for deterministic_replay")
    result_path = (artifact_dir / "generation_result.json").resolve()
    argv = [
        sys.executable, str(cgkn_root / "scripts" / "run_codex_conversation_generation.py"),
        "--project-root", str(root), "--goal", goal, "--out-dir", str(out),
        "--result", str(result_path), "--codex-capability-brief", str(brief_path.resolve()),
        "--provider-mode", mode, "--model", model,
        "--small-model", model, "--large-model", model, "--json",
    ]
    if mode == "live":
        argv.extend(["--use-api", "--allow-provider"])
        if allow_network:
            argv.append("--allow-network")
    elif allow_network:
        raise AgentKitError(f"{mode} cannot enable live network access")
    if mode == "deterministic_replay":
        if replay_dir is None:
            raise AgentKitError("deterministic_replay requires replay_dir")
        argv.extend(["--replay-dir", str(replay_dir.expanduser().resolve())])
    if resume_run_dir is not None:
        argv.extend(["--resume-run-dir", str(pathlib.Path(resume_run_dir).expanduser().resolve())])
    return argv


def _load_surrogate_adapter(cgkn_root: pathlib.Path):
    scripts = cgkn_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import surrogate_provider_adapter

    return surrogate_provider_adapter


def surrogate_status(project_root: pathlib.Path, *, run_dir: pathlib.Path | None = None) -> dict[str, Any]:
    root, config, cgkn_root = load_project(project_root)
    artifact_dir = root / str(config["artifact_dir"])
    selected = pathlib.Path(run_dir).resolve() if run_dir else _latest_surrogate_run(artifact_dir)
    return _load_surrogate_adapter(cgkn_root).status(selected)


def _latest_surrogate_run(artifact_dir: pathlib.Path) -> pathlib.Path:
    result = read_json(artifact_dir / "generation_result.json")
    declared = str(result.get("provider_run_dir") or result.get("run_dir") or "").strip()
    if declared:
        candidate = pathlib.Path(declared).resolve()
        if (candidate / "artifacts" / "provider_handshake" / "provider_mode_state.json").is_file():
            return candidate
    runs_root = artifact_dir / "runs"
    candidates = [
        path.parent.parent.parent
        for path in runs_root.glob("*/artifacts/provider_handshake/provider_mode_state.json")
    ] if runs_root.exists() else []
    if not candidates:
        direct = runs_root / "artifacts" / "provider_handshake" / "provider_mode_state.json"
        if direct.is_file():
            return runs_root.resolve()
        raise AgentKitError("No surrogate Provider run exists for this project")
    return max(candidates, key=lambda path: path.stat().st_mtime).resolve()


def submit_surrogate_response(
    project_root: pathlib.Path,
    *,
    job_id: str,
    attempt_id: str,
    payload: Any,
    surrogate_identity: str = "codex",
    run_dir: pathlib.Path | None = None,
) -> dict[str, Any]:
    root, config, cgkn_root = load_project(project_root)
    artifact_dir = root / str(config["artifact_dir"])
    selected = pathlib.Path(run_dir).resolve() if run_dir else _latest_surrogate_run(artifact_dir)
    adapter = _load_surrogate_adapter(cgkn_root)
    report = adapter.status(selected)
    match = next(
        (
            item for item in report.get("requests", [])
            if item.get("job_id") == job_id and item.get("attempt_id") == attempt_id
        ),
        None,
    )
    if not match:
        raise AgentKitError("No scheduler-created surrogate request matches job_id and attempt_id")
    request = read_json(pathlib.Path(str(match["request_path"])))
    response = adapter.build_response(request, payload, surrogate_identity=surrogate_identity)
    try:
        return adapter.submit_response(selected, response, expected_mode="codex_surrogate")
    except ValueError as exc:
        raise AgentKitError(str(exc)) from exc


def run_generation(argv: list[str], *, cgkn_root: pathlib.Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return _run(argv, cwd=cgkn_root, timeout=timeout)
