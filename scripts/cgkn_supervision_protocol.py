#!/usr/bin/env python3
"""Durable support protocol for the persistent Codex-CGKN supervisor.

The protocol owns workflow/support state only.  It cannot create formal
evidence, write a Provider candidate, package, deliver, or authorize those
actions.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


CHECKPOINT_KIND = "CGKNRuntimeSupervisionCheckpoint"
RESULT_KIND = "CGKNRuntimeSupervisionResult"
STATE_KIND = "CGKNRuntimeSupervisorState"
HEARTBEAT_KIND = "CGKNRuntimeServiceHeartbeat"
SCHEMA_VERSION = "1.0"

CHECKPOINT_TYPES = {
    "service_startup",
    "service_reattachment",
    "requirements_frozen",
    "interface_design_frozen",
    "pre_provider_generation",
    "provider_output_received",
    "provider_failure",
    "integration_complete",
    "test_runtime_visual_failure",
    "pre_packaging",
    "pre_public_delivery",
    "service_crash",
}
SEVERITIES = {"info", "warning", "blocking"}
REQUESTED_ACTIONS = {"observe", "advise", "resume", "repair_cgkn"}
RESULT_ACTIONS = {
    "observe",
    "advise",
    "repair_cgkn",
    "request_user_decision",
    "resume",
    "halt",
}
RELEASE_ACTIONS = {"observe", "resume"}

AUTHORITY = {
    "advisory_only": True,
    "formal_evidence_authorized": False,
    "candidate_write_authorized": False,
    "package_authorized": False,
    "delivery_authorized": False,
}

SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
    "cookie",
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"),
)
FORBIDDEN_RESULT_KEYS = {
    "delivery_allowed",
    "formal_status",
    "formal_evidence_status",
    "evidence_status",
    "final_verdict",
    "package_path",
    "candidate_files",
    "source_code",
    "patch",
}
ALLOWED_REPAIR_PREFIXES = (
    "scripts/",
    "tests/",
    "docs/",
    "schemas/",
    "skills/",
    "tools/",
    "project_management/",
    "configs/",
)
ALLOWED_REPAIR_FILES = {"AGENTS.md", "README.md", ".gitignore", "pytest.ini"}
FORBIDDEN_REPAIR_PREFIXES = (
    ".cgkn/",
    ".git/",
    "artifacts/",
    "generated/",
    "runs/",
    "workspaces/",
    "examples/project_memory/",
    "examples/local_studio/",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _without_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result.pop(field, None)
    return result


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[: max(0, limit)]


def _contains_secret(value: Any, *, parent_key: str = "") -> bool:
    if any(marker in parent_key.lower() for marker in SENSITIVE_MARKERS):
        return bool(value not in (None, "", False, [], {}))
    if isinstance(value, dict):
        return any(_contains_secret(item, parent_key=str(key)) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret(item, parent_key=parent_key) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    return False


def _atomic_write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


@contextmanager
def _state_lock(state_dir: pathlib.Path, *, timeout: float = 10.0) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / ".protocol.lock"
    deadline = time.monotonic() + max(0.1, timeout)
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()} {time.time()}".encode("ascii", errors="ignore"))
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > 60:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"runtime supervision protocol lock timeout: {lock_path}")
            time.sleep(0.02)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def repository_identity(repository_root: str | pathlib.Path) -> dict[str, str]:
    root = pathlib.Path(repository_root).resolve()
    commit = ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()[:64]
    except (OSError, subprocess.SubprocessError):
        commit = ""
    return {
        "root": str(root),
        "root_sha256": hashlib.sha256(str(root).lower().encode("utf-8")).hexdigest(),
        "commit_sha": commit,
    }


def _journal_path(state_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(state_dir).resolve() / "checkpoints.jsonl"


def _results_path(state_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(state_dir).resolve() / "results.jsonl"


def _state_path(state_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(state_dir).resolve() / "supervisor_state.json"


def _heartbeat_path(state_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(state_dir).resolve() / "service_heartbeat.json"


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    values: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def validate_checkpoint(checkpoint: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if checkpoint.get("kind") != CHECKPOINT_KIND:
        errors.append("checkpoint.kind")
    if checkpoint.get("schema_version") != SCHEMA_VERSION:
        errors.append("checkpoint.schema_version")
    if checkpoint.get("checkpoint_type") not in CHECKPOINT_TYPES:
        errors.append("checkpoint.checkpoint_type")
    if checkpoint.get("severity") not in SEVERITIES:
        errors.append("checkpoint.severity")
    if checkpoint.get("requested_action") not in REQUESTED_ACTIONS:
        errors.append("checkpoint.requested_action")
    try:
        if int(checkpoint.get("sequence", 0)) < 1:
            errors.append("checkpoint.sequence")
    except (TypeError, ValueError):
        errors.append("checkpoint.sequence")
    if checkpoint.get("authority") != AUTHORITY:
        errors.append("checkpoint.authority")
    identity = checkpoint.get("repository_identity")
    if not isinstance(identity, dict) or not identity.get("root_sha256"):
        errors.append("checkpoint.repository_identity")
    expected = canonical_hash(_without_hash(checkpoint, "checkpoint_sha256"))
    if checkpoint.get("checkpoint_sha256") != expected:
        errors.append("checkpoint.checkpoint_sha256")
    if _contains_secret(checkpoint):
        errors.append("checkpoint.secret")
    return errors


def load_checkpoints(state_dir: str | pathlib.Path, *, validate_chain: bool = True) -> list[dict[str, Any]]:
    values = _read_jsonl(_journal_path(state_dir))
    previous_hash = ""
    for index, value in enumerate(values, start=1):
        errors = validate_checkpoint(value)
        if int(value.get("sequence", 0) or 0) != index:
            errors.append("checkpoint.chain_sequence")
        if validate_chain and str(value.get("previous_checkpoint_sha256", "")) != previous_hash:
            errors.append("checkpoint.previous_checkpoint_sha256")
        if errors:
            raise ValueError("invalid runtime checkpoint: " + ",".join(sorted(set(errors))))
        previous_hash = str(value["checkpoint_sha256"])
    return values


def emit_checkpoint(
    state_dir: str | pathlib.Path,
    checkpoint_type: str,
    *,
    repository_root: str | pathlib.Path,
    reason: str,
    severity: str = "info",
    requested_action: str = "observe",
    conversation_id: Any = "",
    project_id: Any = "",
    run_id: Any = "",
    context_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(state_dir).resolve()
    clean_refs: list[dict[str, str]] = []
    for item in list(context_refs or [])[:12]:
        if not isinstance(item, dict):
            continue
        clean_refs.append(
            {
                "role": _bounded_text(item.get("role"), 80),
                "ref": _bounded_text(item.get("ref"), 600),
                "sha256": _bounded_text(item.get("sha256"), 64),
            }
        )
    with _state_lock(root):
        existing = load_checkpoints(root)
        sequence = len(existing) + 1
        previous_hash = str(existing[-1]["checkpoint_sha256"]) if existing else ""
        core = {
            "kind": CHECKPOINT_KIND,
            "schema_version": SCHEMA_VERSION,
            "created_at": now(),
            "sequence": sequence,
            "previous_checkpoint_sha256": previous_hash,
            "checkpoint_type": str(checkpoint_type or "").strip(),
            "severity": str(severity or "info").strip(),
            "reason": _bounded_text(reason, 2000),
            "conversation_id": _bounded_text(conversation_id, 120),
            "project_id": _bounded_text(project_id, 160),
            "run_id": _bounded_text(run_id, 160),
            "repository_identity": repository_identity(repository_root),
            "context_refs": clean_refs,
            "requested_action": str(requested_action or "observe").strip(),
            "authority": dict(AUTHORITY),
        }
        checkpoint_id = f"checkpoint-{sequence:08d}-{canonical_hash(core)[:12]}"
        checkpoint = {**core, "checkpoint_id": checkpoint_id}
        checkpoint["checkpoint_sha256"] = canonical_hash(checkpoint)
        errors = validate_checkpoint(checkpoint)
        if errors:
            raise ValueError("invalid runtime checkpoint: " + ",".join(errors))
        journal = _journal_path(root)
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(checkpoint, ensure_ascii=False, sort_keys=True) + "\n")
    return checkpoint


def _safe_repair_target(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return ""
    parts = pathlib.PurePosixPath(raw).parts
    if ".." in parts or "." in parts:
        return ""
    normalized = pathlib.PurePosixPath(*parts).as_posix()
    lowered = normalized.lower()
    if any(lowered.startswith(prefix.lower()) for prefix in FORBIDDEN_REPAIR_PREFIXES):
        return ""
    if normalized in ALLOWED_REPAIR_FILES:
        return normalized
    if any(normalized.startswith(prefix) for prefix in ALLOWED_REPAIR_PREFIXES):
        return normalized
    return ""


def _string_list(value: Any, *, limit: int, chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = _bounded_text(item, chars)
        if text and text not in output:
            output.append(text)
        if len(output) >= limit:
            break
    return output


def build_result(
    checkpoint: dict[str, Any],
    thread_id: str,
    draft: dict[str, Any],
) -> dict[str, Any]:
    action = str(draft.get("action", "")).strip()
    raw_targets = _string_list(draft.get("repair_targets", []), limit=12, chars=400)
    repair_targets = [_safe_repair_target(item) for item in raw_targets]
    if any(not item for item in repair_targets):
        raise ValueError("unsafe repair target")
    result = {
        "kind": RESULT_KIND,
        "schema_version": SCHEMA_VERSION,
        "created_at": now(),
        "checkpoint_id": str(checkpoint.get("checkpoint_id", "")),
        "checkpoint_sha256": str(checkpoint.get("checkpoint_sha256", "")),
        "thread_id": _bounded_text(thread_id, 160),
        "action": action,
        "summary": _bounded_text(draft.get("summary"), 1600),
        "diagnosis": _string_list(draft.get("diagnosis", []), limit=8, chars=800),
        "guidance": _string_list(draft.get("guidance", []), limit=8, chars=800),
        "repair_targets": repair_targets,
        "acceptance_checks": _string_list(draft.get("acceptance_checks", []), limit=8, chars=800),
        "known_limits": _string_list(draft.get("known_limits", []), limit=8, chars=800),
        "authority": dict(AUTHORITY),
    }
    result["result_sha256"] = canonical_hash(result)
    errors = validate_result(result, checkpoint)
    if errors:
        raise ValueError("invalid runtime supervision result: " + ",".join(errors))
    return result


def validate_result(result: dict[str, Any], checkpoint: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    if result.get("kind") != RESULT_KIND:
        errors.append("result.kind")
    if result.get("schema_version") != SCHEMA_VERSION:
        errors.append("result.schema_version")
    if result.get("action") not in RESULT_ACTIONS:
        errors.append("result.action")
    if not str(result.get("thread_id", "")).strip():
        errors.append("result.thread_id")
    if result.get("authority") != AUTHORITY:
        errors.append("result.authority")
    if checkpoint is not None:
        if result.get("checkpoint_id") != checkpoint.get("checkpoint_id"):
            errors.append("result.checkpoint_id")
        if result.get("checkpoint_sha256") != checkpoint.get("checkpoint_sha256"):
            errors.append("result.checkpoint_sha256")
    targets = result.get("repair_targets", [])
    if not isinstance(targets, list):
        errors.append("result.repair_targets")
        targets = []
    for target in targets:
        if _safe_repair_target(target) != target:
            errors.append("result.repair_target_scope")
    if result.get("action") == "repair_cgkn" and not targets:
        errors.append("result.repair_targets_required")
    if result.get("action") != "repair_cgkn" and targets:
        errors.append("result.repair_targets_unexpected")
    if any(key in result for key in FORBIDDEN_RESULT_KEYS):
        errors.append("result.forbidden_authority_field")
    expected = canonical_hash(_without_hash(result, "result_sha256"))
    if result.get("result_sha256") != expected:
        errors.append("result.result_sha256")
    if _contains_secret(result):
        errors.append("result.secret")
    return sorted(set(errors))


def append_result(state_dir: str | pathlib.Path, result: dict[str, Any]) -> pathlib.Path:
    root = pathlib.Path(state_dir).resolve()
    checkpoints = {item["checkpoint_id"]: item for item in load_checkpoints(root)}
    checkpoint = checkpoints.get(result.get("checkpoint_id"))
    if checkpoint is None:
        raise ValueError("result checkpoint is not present in the journal")
    errors = validate_result(result, checkpoint)
    if errors:
        raise ValueError("invalid runtime supervision result: " + ",".join(errors))
    with _state_lock(root):
        path = _results_path(root)
        existing = _read_jsonl(path)
        if any(item.get("checkpoint_id") == result.get("checkpoint_id") for item in existing):
            raise ValueError("checkpoint already has a supervision result")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def result_for_checkpoint(state_dir: str | pathlib.Path, checkpoint_id: str) -> dict[str, Any] | None:
    checkpoints = {item["checkpoint_id"]: item for item in load_checkpoints(state_dir)}
    checkpoint = checkpoints.get(str(checkpoint_id))
    if checkpoint is None:
        return None
    for result in reversed(_read_jsonl(_results_path(state_dir))):
        if result.get("checkpoint_id") != checkpoint_id:
            continue
        if validate_result(result, checkpoint):
            return None
        return result
    return None


def await_checkpoint_release(
    state_dir: str | pathlib.Path,
    checkpoint_id: str,
    timeout: float,
    *,
    poll_interval: float = 0.1,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        result = result_for_checkpoint(state_dir, checkpoint_id)
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            return None
        time.sleep(max(0.02, min(float(poll_interval), 1.0)))


def default_supervisor_state(repository_root: str | pathlib.Path) -> dict[str, Any]:
    return {
        "kind": STATE_KIND,
        "schema_version": SCHEMA_VERSION,
        "supervisor_instance_id": f"supervisor-{uuid.uuid4().hex}",
        "thread_id": "",
        "service_pid": 0,
        "service_started_at": "",
        "repository_identity": repository_identity(repository_root),
        "last_checkpoint_sequence": 0,
        "last_checkpoint_sha256": "",
        "workflow_state": "initialized",
        "last_health_at": "",
        "restart_count": 0,
        "last_failure_category": "",
        "updated_at": now(),
    }


def load_supervisor_state(
    state_dir: str | pathlib.Path,
    repository_root: str | pathlib.Path,
) -> dict[str, Any]:
    path = _state_path(state_dir)
    if not path.is_file():
        return default_supervisor_state(repository_root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_supervisor_state(repository_root)
    if not isinstance(value, dict) or value.get("kind") != STATE_KIND:
        return default_supervisor_state(repository_root)
    return value


def save_supervisor_state(state_dir: str | pathlib.Path, state: dict[str, Any]) -> pathlib.Path:
    value = dict(state)
    value["kind"] = STATE_KIND
    value["schema_version"] = SCHEMA_VERSION
    value["updated_at"] = now()
    if _contains_secret(value):
        raise ValueError("supervisor state contains a secret")
    path = _state_path(state_dir)
    _atomic_write_json(path, value)
    return path


def write_service_heartbeat(
    state_dir: str | pathlib.Path,
    *,
    service_pid: int | None = None,
    service_kind: str = "codex_conversation",
) -> pathlib.Path:
    heartbeat = {
        "kind": HEARTBEAT_KIND,
        "schema_version": SCHEMA_VERSION,
        "service_kind": _bounded_text(service_kind, 100),
        "service_pid": int(service_pid or os.getpid()),
        "observed_at": now(),
    }
    path = _heartbeat_path(state_dir)
    _atomic_write_json(path, heartbeat)
    return path


def read_service_health(state_dir: str | pathlib.Path, *, max_age_seconds: float = 90.0) -> dict[str, Any]:
    path = _heartbeat_path(state_dir)
    if not path.is_file():
        return {"healthy": False, "reason": "heartbeat_missing", "heartbeat": {}}
    try:
        heartbeat = json.loads(path.read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(str(heartbeat.get("observed_at", "")))
        age = max(0.0, (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds())
    except (OSError, ValueError, json.JSONDecodeError):
        return {"healthy": False, "reason": "heartbeat_invalid", "heartbeat": {}}
    return {
        "healthy": age <= max(1.0, float(max_age_seconds)),
        "reason": "healthy" if age <= max(1.0, float(max_age_seconds)) else "heartbeat_stale",
        "age_seconds": age,
        "heartbeat": heartbeat,
    }
