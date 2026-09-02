#!/usr/bin/env python3
"""Persistent supervisor host for CGKN Codex Edition.

This host consumes support checkpoints and resumes one local Codex thread.  It
does not run the Provider route, author a generated candidate, create formal
evidence, package, or deliver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Callable


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
for import_path in (ROOT, SCRIPTS_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import cgkn_supervision_protocol as protocol


DEFAULT_STATE_DIR = ROOT / ".cgkn" / "runtime_supervisor"
DEFAULT_SCHEMA = ROOT / "schemas" / "runtime_supervision_draft.schema.json"
DEFAULT_CODEX_PROFILE_DIR = ROOT / "generated" / "cgkn_editions" / "codex"
SENSITIVE_ARG_MARKERS = ("--token", "--api-key", "--password", "--secret", "authorization")


def _bounded(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[: max(0, limit)]


def _json_thread_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("thread_id", "threadId", "session_id", "sessionId"):
            candidate = str(value.get(key, "") or "").strip()
            if candidate:
                return candidate
        for item in value.values():
            candidate = _json_thread_id(item)
            if candidate:
                return candidate
    elif isinstance(value, list):
        for item in value:
            candidate = _json_thread_id(item)
            if candidate:
                return candidate
    return ""


def _thread_id_from_jsonl(text: str) -> str:
    for raw in str(text or "").splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidate = _json_thread_id(event)
        if candidate:
            return candidate
    return ""


def resolve_codex_command(explicit: str = "") -> str:
    candidate = str(explicit or os.environ.get("CGKN_SUPERVISOR_CODEX_COMMAND", "") or "").strip()
    if candidate:
        path = pathlib.Path(candidate)
        if path.is_file():
            return str(path.resolve())
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        raise RuntimeError(f"Codex command is unavailable: {candidate}")
    resolved = shutil.which("codex") or shutil.which("codex.exe")
    if not resolved:
        raise RuntimeError("Codex command is unavailable; set CGKN_SUPERVISOR_CODEX_COMMAND")
    return resolved


def _checkpoint_prompt(checkpoint: dict[str, Any]) -> str:
    compact = {
        key: checkpoint.get(key)
        for key in (
            "checkpoint_id",
            "checkpoint_sha256",
            "sequence",
            "checkpoint_type",
            "severity",
            "reason",
            "chat_id",
            "project_id",
            "run_id",
            "repository_identity",
            "context_refs",
            "requested_action",
            "authority",
        )
    }
    return (
        "You are the persistent bounded Codex supervisor for CGKN. "
        "CGKN is the long-running system and Telegram is its interface. "
        "Inspect only this identity-bound checkpoint and referenced repository evidence. "
        "Do not run Provider generation, write or patch a sealed generated candidate, claim formal evidence, package, deliver, or expose secrets. "
        "This assessment turn is read-only. Use repair_cgkn only to request a separate governed repair and include only relative CGKN-owned repair targets. "
        "Use resume or observe when the checkpoint may continue, request_user_decision for business/cost/credential/publication authority, and halt when it is unsafe. "
        "Return exactly the JSON object required by the output schema.\n\n"
        f"CHECKPOINT:\n{json.dumps(compact, ensure_ascii=False, sort_keys=True)}"
    )


class CodexCliThreadAdapter:
    """Start or resume one persisted, read-only local Codex CLI thread."""

    def __init__(
        self,
        repository_root: str | pathlib.Path,
        state_dir: str | pathlib.Path,
        *,
        codex_command: str = "",
        schema_path: str | pathlib.Path = DEFAULT_SCHEMA,
        timeout: int = 600,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.repository_root = pathlib.Path(repository_root).resolve()
        self.state_dir = pathlib.Path(state_dir).resolve()
        self.codex_command = codex_command
        self.schema_path = pathlib.Path(schema_path).resolve()
        self.timeout = max(30, min(int(timeout), 1800))
        self.runner = runner

    def run(self, checkpoint: dict[str, Any], thread_id: str = "") -> dict[str, Any]:
        errors = protocol.validate_checkpoint(checkpoint)
        if errors:
            raise ValueError("invalid checkpoint for Codex: " + ",".join(errors))
        command = resolve_codex_command(self.codex_command)
        if not self.schema_path.is_file():
            raise RuntimeError(f"missing Codex output schema: {self.schema_path}")
        output_dir = self.state_dir / "codex_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{checkpoint['checkpoint_id']}.json"
        output_path.unlink(missing_ok=True)
        if thread_id:
            argv = [
                command,
                "exec",
                "resume",
                "--json",
                "--output-schema",
                str(self.schema_path),
                "--output-last-message",
                str(output_path),
                thread_id,
                "-",
            ]
        else:
            argv = [
                command,
                "exec",
                "--json",
                "--sandbox",
                "read-only",
                "--cd",
                str(self.repository_root),
                "--output-schema",
                str(self.schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ]
        completed = self.runner(
            argv,
            input=_checkpoint_prompt(checkpoint),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=self.timeout,
            check=False,
            cwd=self.repository_root,
        )
        if int(completed.returncode) != 0:
            detail = _bounded(completed.stderr or completed.stdout, 1600)
            raise RuntimeError(f"Codex supervision failed ({completed.returncode}): {detail}")
        resolved_thread = str(thread_id or _thread_id_from_jsonl(completed.stdout)).strip()
        if not resolved_thread:
            raise RuntimeError("Codex supervision did not report a resumable thread id")
        if not output_path.is_file():
            raise RuntimeError("Codex supervision did not write its structured result")
        try:
            draft = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Codex supervision result is not valid JSON") from exc
        if not isinstance(draft, dict):
            raise RuntimeError("Codex supervision result must be a JSON object")
        return protocol.build_result(checkpoint, resolved_thread, draft)


def process_is_alive(pid: int) -> bool:
    if int(pid or 0) <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a reliable existence probe on Windows and can
        # surface WinError 87 as a SystemError. Querying a process handle is
        # read-only and works for detached CREATE_NEW_PROCESS_GROUP children.
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        open_process.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        handle = open_process(process_query_limited_information, 0, int(pid))
        if handle:
            get_exit_code = kernel32.GetExitCodeProcess
            get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            get_exit_code.restype = ctypes.c_int
            exit_code = ctypes.c_uint32()
            queried = bool(get_exit_code(handle, ctypes.byref(exit_code)))
            close_handle(handle)
            return queried and exit_code.value == 259  # STILL_ACTIVE
        return ctypes.get_last_error() == 5  # Access denied still means it exists.
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ProcessLookupError):
        return False


def _service_command_hash(argv: list[str]) -> str:
    safe = [pathlib.Path(argv[0]).name] + [str(item) for item in argv[1:]]
    return hashlib.sha256(json.dumps(safe, ensure_ascii=False).encode("utf-8")).hexdigest()


def _validate_service_argv(argv: list[str]) -> None:
    lowered = [str(item).lower() for item in argv]
    if any(any(marker in item for marker in SENSITIVE_ARG_MARKERS) for item in lowered):
        raise ValueError("service command must receive credentials from the environment, not argv")


class SupervisorHost:
    def __init__(
        self,
        repository_root: str | pathlib.Path,
        state_dir: str | pathlib.Path,
        adapter: Any,
        *,
        popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    ) -> None:
        self.repository_root = pathlib.Path(repository_root).resolve()
        self.state_dir = pathlib.Path(state_dir).resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.adapter = adapter
        self.popen_factory = popen_factory
        self.child: subprocess.Popen[Any] | None = None
        self._stdout_handle: Any = None
        self._stderr_handle: Any = None

    def load_state(self) -> dict[str, Any]:
        return protocol.load_supervisor_state(self.state_dir, self.repository_root)

    def save_state(self, state: dict[str, Any]) -> pathlib.Path:
        return protocol.save_supervisor_state(self.state_dir, state)

    def ensure_service(self, argv: list[str], *, supervision_policy: str = "gate") -> dict[str, Any]:
        _validate_service_argv(argv)
        state = self.load_state()
        prior_pid = int(state.get("service_pid", 0) or 0)
        if process_is_alive(prior_pid):
            state["workflow_state"] = "attached"
            state["last_health_at"] = protocol.now()
            self.save_state(state)
            return state
        if prior_pid:
            state["restart_count"] = int(state.get("restart_count", 0) or 0) + 1
        env = dict(os.environ)
        env["CGKN_RUNTIME_SUPERVISOR_DIR"] = str(self.state_dir)
        env["CGKN_SUPERVISION_POLICY"] = str(supervision_policy)
        stdout_path = self.state_dir / "telegram_service.stdout.log"
        stderr_path = self.state_dir / "telegram_service.stderr.log"
        self._stdout_handle = stdout_path.open("a", encoding="utf-8")
        self._stderr_handle = stderr_path.open("a", encoding="utf-8")
        kwargs: dict[str, Any] = {
            "cwd": self.repository_root,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": self._stdout_handle,
            "stderr": self._stderr_handle,
            "text": True,
            "shell": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        else:
            kwargs["start_new_session"] = True
        self.child = self.popen_factory(argv, **kwargs)
        state["service_pid"] = int(self.child.pid)
        state["service_started_at"] = protocol.now()
        state["service_command_sha256"] = _service_command_hash(argv)
        state["workflow_state"] = "service_starting"
        state["last_failure_category"] = ""
        self.save_state(state)
        return state

    def process_next(self) -> dict[str, Any] | None:
        state = self.load_state()
        checkpoints = protocol.load_checkpoints(self.state_dir)
        last_sequence = int(state.get("last_checkpoint_sequence", 0) or 0)
        pending = [item for item in checkpoints if int(item.get("sequence", 0)) > last_sequence]
        if not pending:
            return None
        checkpoint = pending[0]
        if last_sequence:
            expected_previous = str(state.get("last_checkpoint_sha256", ""))
            if checkpoint.get("previous_checkpoint_sha256") != expected_previous:
                state["workflow_state"] = "checkpoint_discontinuity"
                state["last_failure_category"] = "checkpoint_identity_drift"
                self.save_state(state)
                raise RuntimeError("checkpoint continuity mismatch")
        state["workflow_state"] = "supervising"
        self.save_state(state)
        try:
            result = self.adapter.run(checkpoint, str(state.get("thread_id", "")))
            protocol.append_result(self.state_dir, result)
        except Exception:
            state = self.load_state()
            state["workflow_state"] = "supervision_unavailable"
            state["last_failure_category"] = "codex_supervision_failure"
            self.save_state(state)
            raise
        state = self.load_state()
        state["thread_id"] = str(result["thread_id"])
        state["last_checkpoint_sequence"] = int(checkpoint["sequence"])
        state["last_checkpoint_sha256"] = str(checkpoint["checkpoint_sha256"])
        action = str(result["action"])
        state["workflow_state"] = {
            "observe": "ready",
            "resume": "ready",
            "advise": "advisory_pending",
            "repair_cgkn": "waiting_repair_executor",
            "request_user_decision": "waiting_user_decision",
            "halt": "halted",
        }[action]
        state["last_failure_category"] = "" if action in protocol.RELEASE_ACTIONS else action
        self.save_state(state)
        return result

    def status(self) -> dict[str, Any]:
        state = self.load_state()
        checkpoints = protocol.load_checkpoints(self.state_dir)
        results = []
        result_path = self.state_dir / "results.jsonl"
        if result_path.is_file():
            for raw in result_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    results.append(item)
        health = protocol.read_service_health(self.state_dir)
        service_pid = int(state.get("service_pid", 0) or 0)
        return {
            "kind": "CGKNRuntimeSupervisorStatus",
            "schema_version": protocol.SCHEMA_VERSION,
            "workflow_state": state.get("workflow_state", ""),
            "supervisor_instance_id": state.get("supervisor_instance_id", ""),
            "thread_id": state.get("thread_id", ""),
            "service_pid": service_pid,
            "service_process_alive": process_is_alive(service_pid),
            "service_health": health,
            "checkpoint_count": len(checkpoints),
            "result_count": len(results),
            "last_checkpoint_sequence": state.get("last_checkpoint_sequence", 0),
            "pending_checkpoint_count": max(
                0, len(checkpoints) - int(state.get("last_checkpoint_sequence", 0) or 0)
            ),
            "restart_count": state.get("restart_count", 0),
            "last_failure_category": state.get("last_failure_category", ""),
            "formal_evidence_status": "NOT_EVALUATED",
        }

    def close(self, *, terminate_child: bool = False) -> None:
        if terminate_child and self.child is not None and self.child.poll() is None:
            try:
                if os.name == "nt":
                    self.child.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.child.terminate()
                self.child.wait(timeout=10)
            except Exception:
                try:
                    self.child.kill()
                except Exception:
                    pass
        for handle in (self._stdout_handle, self._stderr_handle):
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass


def _default_telegram_argv(args: argparse.Namespace) -> list[str]:
    # Launch as a module from the repository root so both the scripts package
    # and root-level contracts package are importable in the detached child.
    argv = [sys.executable, "-m", "scripts.telegram_live_bridge"]
    if args.chat_id:
        argv.extend(["--chat-id", str(args.chat_id)])
    if args.model:
        argv.extend(["--model", str(args.model)])
    argv.extend(
        [
            "--generation-mode",
            str(args.generation_mode),
            "--generation-timeout",
            str(getattr(args, "generation_timeout", 900)),
            "--codex-design-mode",
            "disabled",
            "--session-dir",
            str(getattr(args, "session_dir", DEFAULT_CODEX_PROFILE_DIR / "sessions")),
            "--log-dir",
            str(getattr(args, "log_dir", DEFAULT_CODEX_PROFILE_DIR / "logs")),
            "--upload-dir",
            str(getattr(args, "upload_dir", DEFAULT_CODEX_PROFILE_DIR / "uploads")),
            "--memory-dir",
            str(getattr(args, "memory_dir", DEFAULT_CODEX_PROFILE_DIR / "memory")),
            "--provider-projects-dir",
            str(getattr(args, "provider_projects_dir", DEFAULT_CODEX_PROFILE_DIR / "provider_projects")),
        ]
    )
    return argv


def run_host(args: argparse.Namespace) -> int:
    state_dir = pathlib.Path(args.state_dir).resolve()
    adapter = CodexCliThreadAdapter(
        ROOT,
        state_dir,
        codex_command=args.codex_command,
        timeout=args.codex_timeout,
    )
    host = SupervisorHost(ROOT, state_dir, adapter)
    stop_path = state_dir / "stop.request"
    stop_path.unlink(missing_ok=True)
    service_argv = _default_telegram_argv(args) if args.start_telegram else []
    if service_argv:
        host.ensure_service(service_argv, supervision_policy=args.supervision_policy)
    processed = 0
    attempted = 0
    try:
        while not stop_path.exists():
            if service_argv:
                current_state = host.load_state()
                service_pid = int(current_state.get("service_pid", 0) or 0)
                if not process_is_alive(service_pid):
                    if int(current_state.get("restart_count", 0) or 0) >= int(args.restart_limit):
                        current_state["workflow_state"] = "service_restart_exhausted"
                        current_state["last_failure_category"] = "service_process_exit"
                        host.save_state(current_state)
                    else:
                        host.ensure_service(service_argv, supervision_policy=args.supervision_policy)
                health = protocol.read_service_health(state_dir)
                if health.get("healthy"):
                    current_state = host.load_state()
                    current_state["last_health_at"] = protocol.now()
                    if current_state.get("workflow_state") in {"service_starting", "attached", "service_degraded"}:
                        current_state["workflow_state"] = "ready"
                    host.save_state(current_state)
                elif process_is_alive(int(host.load_state().get("service_pid", 0) or 0)):
                    current_state = host.load_state()
                    if current_state.get("workflow_state") not in {
                        "supervising",
                        "waiting_repair_executor",
                        "waiting_user_decision",
                        "halted",
                    }:
                        current_state["workflow_state"] = "service_degraded"
                        current_state["last_failure_category"] = str(health.get("reason", "heartbeat_unavailable"))
                        host.save_state(current_state)
            try:
                result = host.process_next()
                if result is not None:
                    attempted += 1
                    processed += 1
                    print(json.dumps({"event": "checkpoint_processed", "result": result}, ensure_ascii=False), flush=True)
            except Exception as exc:
                attempted += 1
                print(
                    json.dumps(
                        {"event": "supervision_error", "error": _bounded(exc, 1600)},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            if args.once or (args.max_events and attempted >= args.max_events):
                break
            time.sleep(max(0.1, min(float(args.poll_interval), 30.0)))
    finally:
        host.close(terminate_child=bool(args.stop_service_on_exit))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent supervisor for CGKN Codex Edition.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the checkpoint supervisor loop.")
    run.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    run.add_argument("--codex-command", default="")
    run.add_argument("--codex-timeout", type=int, default=600)
    run.add_argument("--poll-interval", type=float, default=1.0)
    run.add_argument("--once", action="store_true")
    run.add_argument("--max-events", type=int, default=0)
    run.add_argument("--start-telegram", action="store_true")
    run.add_argument("--stop-service-on-exit", action="store_true")
    run.add_argument("--restart-limit", type=int, default=2)
    run.add_argument("--supervision-policy", choices=["observe", "gate"], default="gate")
    run.add_argument("--chat-id", default="")
    run.add_argument("--model", default="")
    run.add_argument("--generation-mode", choices=["simulator", "api"], default="api")
    run.add_argument("--generation-timeout", type=int, default=900)
    run.add_argument("--session-dir", default=str(DEFAULT_CODEX_PROFILE_DIR / "sessions"))
    run.add_argument("--log-dir", default=str(DEFAULT_CODEX_PROFILE_DIR / "logs"))
    run.add_argument("--upload-dir", default=str(DEFAULT_CODEX_PROFILE_DIR / "uploads"))
    run.add_argument("--memory-dir", default=str(DEFAULT_CODEX_PROFILE_DIR / "memory"))
    run.add_argument(
        "--provider-projects-dir",
        default=str(DEFAULT_CODEX_PROFILE_DIR / "provider_projects"),
    )
    run.set_defaults(func=run_host)

    status = sub.add_parser("status", help="Read supervisor and service status.")
    status.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))

    stop = sub.add_parser("stop", help="Request a running supervisor loop to stop.")
    stop.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))

    emit = sub.add_parser("emit", help="Append one bounded operator checkpoint.")
    emit.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    emit.add_argument("--type", choices=sorted(protocol.CHECKPOINT_TYPES), required=True)
    emit.add_argument("--reason", required=True)
    emit.add_argument("--severity", choices=sorted(protocol.SEVERITIES), default="info")
    emit.add_argument("--requested-action", choices=sorted(protocol.REQUESTED_ACTIONS), default="observe")
    emit.add_argument("--chat-id", default="")
    emit.add_argument("--project-id", default="")
    emit.add_argument("--run-id", default="")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "status":
        host = SupervisorHost(ROOT, args.state_dir, adapter=None)
        print(json.dumps(host.status(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "stop":
        state_dir = pathlib.Path(args.state_dir).resolve()
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "stop.request").write_text(protocol.now() + "\n", encoding="utf-8")
        print(json.dumps({"status": "stop_requested", "state_dir": str(state_dir)}, ensure_ascii=False))
        return 0
    if args.command == "emit":
        checkpoint = protocol.emit_checkpoint(
            args.state_dir,
            args.type,
            repository_root=ROOT,
            reason=args.reason,
            severity=args.severity,
            requested_action=args.requested_action,
            chat_id=args.chat_id,
            project_id=args.project_id,
            run_id=args.run_id,
        )
        print(json.dumps(checkpoint, ensure_ascii=False, indent=2))
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
