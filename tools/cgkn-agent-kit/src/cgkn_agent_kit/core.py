from __future__ import annotations

import json
import hashlib
import ctypes
import errno
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
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


def resolve_provider_mode(provider_mode: str | None, *, usage_beta: bool = False) -> str:
    mode = str(provider_mode or "").strip().lower()
    if not mode:
        return "codex_surrogate" if usage_beta else "live"
    if mode not in {"live", "codex_surrogate", "deterministic_replay"}:
        raise AgentKitError(f"Unsupported provider_mode: {mode}")
    return mode


def generation_command(
    project_root: pathlib.Path, *, goal: str, brief_path: pathlib.Path,
    out_dir: pathlib.Path | None = None, model: str = "gpt-4.1",
    allow_network: bool = False, resume_run_dir: pathlib.Path | None = None,
    provider_mode: str | None = None, replay_dir: pathlib.Path | None = None,
    usage_beta: bool = False,
) -> list[str]:
    root, config, cgkn_root = load_project(project_root)
    artifact_dir = root / str(config["artifact_dir"])
    out = (out_dir or (artifact_dir / "generated-project")).resolve()
    mode = resolve_provider_mode(provider_mode, usage_beta=usage_beta)
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


def generation_job_path(artifact_dir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(artifact_dir) / "generation_job.json"


def _process_alive(pid: int) -> bool:
    return bool(_process_liveness(pid)["alive"])


def _process_liveness(pid: int) -> dict[str, Any]:
    selected = int(pid or 0)
    if selected <= 0:
        return {"pid": selected, "status": "DEAD", "alive": False, "method": "validation", "error_code": 0, "reason": "INVALID_PID"}
    if os.name == "nt":
        access, still_active = 0x1000, 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes, open_process.restype = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32], ctypes.c_void_p
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes, get_exit_code.restype = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)], ctypes.c_int
        close_handle = kernel32.CloseHandle
        close_handle.argtypes, close_handle.restype = [ctypes.c_void_p], ctypes.c_int
        handle = open_process(access, False, selected)
        if not handle:
            error_code = int(ctypes.get_last_error())
            if error_code == 87:
                return {"pid": selected, "status": "DEAD", "alive": False, "method": "windows_query_exit_code", "error_code": error_code}
            return {"pid": selected, "status": "UNKNOWN", "alive": True, "method": "windows_query_exit_code", "error_code": error_code, "reason": "ACCESS_DENIED" if error_code == 5 else "QUERY_FAILED"}
        try:
            exit_code = ctypes.c_uint32()
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                return {"pid": selected, "status": "UNKNOWN", "alive": True, "method": "windows_query_exit_code", "error_code": int(ctypes.get_last_error()), "reason": "QUERY_FAILED"}
            alive = exit_code.value == still_active
            return {"pid": selected, "status": "ALIVE" if alive else "DEAD", "alive": alive, "method": "windows_query_exit_code", "error_code": 0, "exit_code": int(exit_code.value)}
        finally:
            close_handle(handle)
    try:
        os.kill(selected, 0)
    except ProcessLookupError:
        return {"pid": selected, "status": "DEAD", "alive": False, "method": "posix_signal_zero", "error_code": errno.ESRCH}
    except PermissionError:
        return {"pid": selected, "status": "ALIVE", "alive": True, "method": "posix_signal_zero", "error_code": errno.EPERM}
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return {"pid": selected, "status": "DEAD", "alive": False, "method": "posix_signal_zero", "error_code": exc.errno}
        if exc.errno == errno.EPERM:
            return {"pid": selected, "status": "ALIVE", "alive": True, "method": "posix_signal_zero", "error_code": exc.errno}
        return {"pid": selected, "status": "UNKNOWN", "alive": True, "method": "posix_signal_zero", "error_code": exc.errno}
    return {"pid": selected, "status": "ALIVE", "alive": True, "method": "posix_signal_zero", "error_code": 0}


def reconcile_generation_job_state(artifact_dir: pathlib.Path) -> dict[str, Any]:
    path = generation_job_path(artifact_dir)
    job = read_json(path)
    pid = int(job.get("process_id", 0) or 0)
    liveness = _process_liveness(pid)
    if str(job.get("state", "")).upper() in {"STARTING", "RUNNING", "WAITING"} and liveness["status"] == "DEAD":
        latest = read_json(path)
        if str(latest.get("state", "")).upper() in {"STARTING", "RUNNING", "WAITING"} and int(latest.get("process_id", 0) or 0) == pid:
            timestamp = now()
            job = {**latest, "state": "FAILED", "terminal_reason": "WORKER_PROCESS_NOT_ALIVE", "worker_observed_alive": False, "process_liveness": liveness, "failed_at": timestamp, "updated_at": timestamp}
            write_json(path, job)
    return {**job, "process_liveness": liveness, "worker_observed_alive": bool(liveness["alive"])}


def _run_metrics(run_dir: str | pathlib.Path) -> dict[str, Any]:
    path = pathlib.Path(str(run_dir or "")) / "artifacts" / "provider_execution_metrics.json"
    if not path.is_file():
        return {}
    try:
        return read_json(path)
    except AgentKitError:
        return {}


def _transport_attempt_summary(run_dir: str | pathlib.Path) -> dict[str, int]:
    path = pathlib.Path(str(run_dir or "")) / "provider_phase_log.jsonl"
    summary = {"completed": 0, "successes": 0, "timeouts": 0, "admitted": 0}
    if not path.is_file():
        return summary
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return summary
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("event") == "provider_result_admitted":
            summary["admitted"] += 1
            continue
        if event.get("event") != "provider_transport_attempt":
            continue
        summary["completed"] += 1
        if str(event.get("status", "")).lower() == "ok":
            summary["successes"] += 1
        elif "timeout" in json.dumps(event.get("transport_timing", {}), ensure_ascii=False).lower() or event.get("transport_timing", {}).get("failure_phase") == "connect_or_response_headers":
            summary["timeouts"] += 1
    return summary


def generation_job_status(artifact_dir: pathlib.Path) -> dict[str, Any]:
    """Project one managed worker and its run-local canonical evidence without mutation."""
    path = generation_job_path(artifact_dir)
    if not path.is_file():
        return {"exists": False, "state": "NOT_STARTED", "job_alive": False}
    job = reconcile_generation_job_state(artifact_dir)
    alive = bool(job["process_liveness"]["alive"])
    state = str(job.get("state", "UNKNOWN") or "UNKNOWN").upper()
    terminal = state in {"COMPLETE", "REWORK_BLOCKED", "FAILED", "CANCELLED"}
    terminal_reason = str(job.get("terminal_reason", "") or "")
    metrics = _run_metrics(str(job.get("run_dir", "") or ""))
    result_path = pathlib.Path(str(job.get("result_path", "") or ""))
    result: dict[str, Any] = {}
    if result_path.is_file():
        try:
            candidate = read_json(result_path)
            if not job.get("run_id") or candidate.get("run_id") == job.get("run_id"):
                result = candidate
        except AgentKitError:
            result = {}
    attempts_started = int(metrics.get("provider_api_call_count", 0) or 0)
    attempts = _transport_attempt_summary(str(job.get("run_dir", "") or ""))
    attempts_completed = int(attempts.get("completed", 0) or job.get("provider_attempts_completed", 0) or 0)
    return {
        **job,
        "exists": True,
        "state": state,
        "job_alive": alive,
        "terminal_reason": terminal_reason,
        "provider_attempts_started": attempts_started,
        "provider_attempts_completed": attempts_completed,
        "provider_successes": int(attempts.get("successes", 0) or job.get("provider_successes", 0) or 0),
        "provider_timeouts": int(attempts.get("timeouts", 0) or job.get("provider_timeouts", 0) or 0),
        "admitted_provider_result_present": bool(attempts.get("admitted", 0) or job.get("admitted_provider_result_present")),
        "candidate_present": bool(result.get("candidate_hash")),
        "formal_evidence_status": str(result.get("formal_evidence_status", "NOT_EVALUATED")),
        "resume_safe": bool((result.get("resume", {}) or {}).get("safe", False)),
    }


def start_generation_job(
    argv: list[str],
    *,
    cgkn_root: pathlib.Path,
    artifact_dir: pathlib.Path,
    start_timeout: float = 15.0,
    popen_factory: Any = subprocess.Popen,
) -> dict[str, Any]:
    """Start the canonical CLI as one observable worker independent of the caller."""
    current = generation_job_status(artifact_dir)
    if current.get("state") in {"STARTING", "RUNNING", "WAITING"} and current.get("job_alive"):
        return {**current, "started": False, "deduplicated": True}
    job_id = "generation-job-" + uuid.uuid4().hex
    path = generation_job_path(artifact_dir)
    stdout_path = pathlib.Path(artifact_dir) / "generation_job.stdout.log"
    stderr_path = pathlib.Path(artifact_dir) / "generation_job.stderr.log"
    result_path = pathlib.Path(artifact_dir) / "generation_result.json"
    command = [*argv, "--generation-job-state", str(path), "--generation-job-id", job_id]
    initial = {
        "kind": "CGKNGenerationJob",
        "schema_version": "1.0",
        "job_id": job_id,
        "run_id": "",
        "state": "STARTING",
        "process_id": 0,
        "started_at": now(),
        "updated_at": now(),
        "run_dir": "",
        "result_path": str(result_path.resolve()),
        "stdout_path": str(stdout_path.resolve()),
        "stderr_path": str(stderr_path.resolve()),
        "terminal_reason": "",
    }
    write_json(path, initial)
    creationflags = 0
    popen_kwargs: dict[str, Any] = {"cwd": str(cgkn_root), "close_fds": True}
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True
    try:
        with stdout_path.open("a", encoding="utf-8") as stdout, stderr_path.open("a", encoding="utf-8") as stderr:
            process = popen_factory(command, stdout=stdout, stderr=stderr, **popen_kwargs)
    except OSError as exc:
        failed = {**initial, "state": "FAILED", "terminal_reason": "JOB_START_FAILED", "error": redact(str(exc)), "updated_at": now()}
        write_json(path, failed)
        raise AgentKitError(f"Generation job could not start: {exc}") from exc
    try:
        observed_after_spawn = read_json(path)
    except AgentKitError:
        observed_after_spawn = initial
    started = {**initial, **observed_after_spawn, "process_id": int(process.pid), "updated_at": now()}
    write_json(path, started)
    deadline = time.monotonic() + max(0.0, float(start_timeout))
    while time.monotonic() < deadline:
        observed = generation_job_status(artifact_dir)
        if observed.get("run_id") or observed.get("state") in {"FAILED", "REWORK_BLOCKED", "COMPLETE", "CANCELLED"}:
            return {**observed, "started": True, "deduplicated": False}
        time.sleep(0.05)
    observed = generation_job_status(artifact_dir)
    return {**observed, "started": True, "deduplicated": False}
