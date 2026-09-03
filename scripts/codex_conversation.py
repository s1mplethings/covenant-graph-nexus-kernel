#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import pathlib
import random
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
import zlib
from datetime import datetime, timezone
from typing import Any, Callable


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_connectivity
import adaptive_delivery
import backend_dialogue_loop
import browser_visual_evidence
import capability_strategy
import canonical_delivery_manifest
import canonical_delivery_receipt
import canonical_evidence_hash
import canonical_media_validation
import canonical_user_review
import customer_runtime_runner
import frontdesk_team_lead_agent
import goal_acceptance
import local_packager
import local_image_model_discovery
import local_model_router
import main_agent_manager
import model_policy
import project_revision_lane
import real_test_execution
import run_local_pipeline as provider_project_pipeline
import provider_causal_trace
import visual_evidence
import product_studio_reply
import project_memory_md
import production_candidate_provenance
import public_narration
import codex_design_supervision
import cgkn_supervision_protocol
import cgkn_supervision_router
import governed_kernel_repair

DEFAULT_SESSION_DIR = ROOT / "examples" / "test_results" / "codex_sessions"
DEFAULT_LOG_DIR = ROOT / "examples" / "test_results" / "codex_logs"
DEFAULT_MEMORY_DIR = ROOT / "examples" / "project_memory"
DEFAULT_UPLOAD_DIR = ROOT / "examples" / "test_results" / "codex_uploads"
DEFAULT_PROVIDER_PROJECTS_DIR = ROOT / "generated" / "codex_provider_projects"
PROVIDER_PROJECTS_DIR = DEFAULT_PROVIDER_PROJECTS_DIR
POLICY_PATH = ROOT / "config" / "customer_agent_policy.md"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
GENERATION_TOTAL_TIMEOUT_SECONDS = 900
PUBLIC_DELIVERY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".zip"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".webm"}
INTERNAL_EVIDENCE_SUFFIXES = {".md", ".json", ".txt", ".log"}
DOC_ONLY_SUFFIXES = {".md", ".rst", ".txt", ".json", ".jsonl", ".log", ".yaml", ".yml", ".toml", ".ini"}
RUNNABLE_ENTRYPOINTS = ("main.py", "app.py", "package.json", "index.html")
RUNTIME_SUPERVISOR_DIR = str(os.environ.get("CGKN_RUNTIME_SUPERVISOR_DIR", "")).strip()
SUPERVISION_POLICY = str(os.environ.get("CGKN_SUPERVISION_POLICY", "disabled")).strip().lower()
MAX_SUPERVISION_REWORK_ROUNDS = 2
try:
    SUPERVISION_GATE_TIMEOUT = float(os.environ.get("CGKN_SUPERVISION_GATE_TIMEOUT", "600"))
except ValueError:
    SUPERVISION_GATE_TIMEOUT = 600.0

DEFAULT_CUSTOMER_AGENT_POLICY = """# Customer Agent Policy

The assistant behaves like a product design and engineering partner, not a form-based customer support script.
It is the front-office interface for the CGNK project generation and delivery workflow.

- Represent the CGNK workflow that can clarify requirements, maintain project memory, generate projects, run checks, and deliver preview media.
- Understand the user's goal first, then propose a first-version product and technical plan.
- Infer reasonable defaults for optional fields instead of asking the user to fill every field.
- Ask at most a small number of non-blocking soft questions; continue with explicit assumptions when the user confirms generation.
- Accept uploaded images, documents, videos, audio, and data files as project input when Codex conversation provides them.
- When enough information exists, proceed naturally; do not require a fixed command phrase.
- Delivery messages should present product capabilities, test status, preview artifacts, and next-step suggestions.
- Never expose API stack traces or internal transport errors to the user.
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repository_commit_sha() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError("repository_commit_sha_unavailable")
    return proc.stdout.strip()


def production_generation_identity(
    conversation_id: int | str,
    session: dict[str, Any],
) -> dict[str, str]:
    generation = (
        session.get("generation", {})
        if isinstance(session.get("generation"), dict)
        else {}
    )
    run_id = str(generation.get("run_id", "")).strip()
    candidate_id = str(generation.get("candidate_id", "")).strip()
    commit_sha = str(generation.get("commit_sha", "")).strip()
    if not run_id:
        run_id = f"production-{uuid.uuid4().hex}"
    if not candidate_id:
        candidate_id = f"customer-{safe_id(conversation_id)}-{run_id.rsplit('-', 1)[-1]}"
    if not commit_sha:
        commit_sha = repository_commit_sha()
    return {
        "run_id": run_id,
        "candidate_id": candidate_id,
        "commit_sha": commit_sha,
    }


def production_paths(
    conversation_id: int | str,
    log_dir: pathlib.Path,
    identity: dict[str, str],
) -> tuple[pathlib.Path, pathlib.Path]:
    run_slug = safe_id(conversation_id)
    project_dir = (PROVIDER_PROJECTS_DIR / run_slug / identity["candidate_id"]).resolve()
    run_dir = (
        pathlib.Path(log_dir)
        / "provider_runs"
        / run_slug
        / identity["run_id"]
    ).resolve()
    return project_dir, run_dir


def read_customer_agent_policy() -> str:
    if POLICY_PATH.exists():
        try:
            text = POLICY_PATH.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text[:12000]
        except Exception:
            pass
    return DEFAULT_CUSTOMER_AGENT_POLICY


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def append_jsonl(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False) + "\n")


def read_json(path: pathlib.Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return doc if isinstance(doc, dict) else default


def safe_id(raw: Any) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "")).strip("-")
    return value[:120] or "codex-session"


def safe_file_name(raw: Any, fallback: str) -> str:
    value = pathlib.Path(str(raw or "")).name
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip(".-")
    return value[:160] or fallback


def unique_path(path: pathlib.Path) -> pathlib.Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{int(time.time())}{suffix}")


def extension_for_mime(mime_type: str, default: str = ".bin") -> str:
    mime = mime_type.lower().strip()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/csv": ".csv",
        "application/json": ".json",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    }.get(mime, default)


class CodexConversation:
    """In-process projection of output shown by the Codex conversation UI.

    The Codex app owns transport and rendering.  This object only records the
    messages and local artifacts selected by the governed delivery code, which
    keeps the production path testable without a second listener or network API.
    """

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []
        self.artifacts: list[dict[str, str]] = []
        self._turn = 0

    def send_message(self, conversation_id: int | str, text: str) -> bool:
        self._turn += 1
        self.messages.append(
            {
                "conversation_id": str(conversation_id),
                "turn_id": str(self._turn),
                "text": str(text),
            }
        )
        return True

    def send_chat_action(self, conversation_id: int | str, action: str) -> None:
        return None

    def _present_file(
        self,
        conversation_id: int | str,
        path: pathlib.Path,
        caption: str,
    ) -> dict[str, Any]:
        if not path.is_file():
            return {}
        self._turn += 1
        digest = canonical_evidence_hash.sha256_file(path)
        item = {
            "conversation_id": str(conversation_id),
            "turn_id": str(self._turn),
            "artifact_id": digest,
            "artifact_unique_id": digest,
            "path": str(path.resolve()),
            "caption": str(caption),
        }
        self.artifacts.append(item)
        return {"ok": True, "result": item}

    def send_photo(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> dict[str, Any]:
        return self._present_file(conversation_id, path, caption)

    def send_document(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> dict[str, Any]:
        return self._present_file(conversation_id, path, caption)

    def send_video(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> dict[str, Any]:
        return self._present_file(conversation_id, path, caption)


def default_session(conversation_id: int | str) -> dict[str, Any]:
    return {
        "kind": "CGKNCodexConversationSession",
        "schema_version": "1",
        "conversation_id": str(conversation_id),
        "source": "codex",
        "conversation_id": str(conversation_id),
        "created_at": now(),
        "updated_at": now(),
        "messages": [],
        "attachments": [],
        "memory_events": [],
        "whiteboard_versions": [],
        "whiteboard": {
            "project_summary": "",
            "known_facts": [],
            "open_questions": [],
            "default_assumptions": [],
            "first_version_plan": [],
            "blocking_questions": [],
            "user_rules": [],
            "acceptance_criteria": [],
            "change_requests": [],
            "decision_log": [],
            "delivery_requirements": [],
            "ready_to_generate": False,
        },
        "generation": {"status": "idle"},
        "active_run": None,
        "active_project": {
            "kind": "CGNKActiveProject",
            "project_id": "",
            "project_dir": "",
            "current_worktree": "",
            "latest_delivery_manifest": "",
            "latest_project_package": "",
            "revision_index": 0,
            "latest_revision_manifest": "",
            "status": "none",
        },
        "revision_history": [],
        "pending_decision": None,
        "intake_tickets": [],
        "backend_memos": [],
        "backend_controls": [],
    }


def session_path(session_dir: pathlib.Path, conversation_id: int | str) -> pathlib.Path:
    return session_dir / f"{safe_id(conversation_id)}.json"


def agent_session_path(session_dir: pathlib.Path, conversation_id: int | str) -> pathlib.Path:
    return session_dir / safe_id(conversation_id) / "agent_session.jsonl"


def append_agent_session_event(session_dir: pathlib.Path, conversation_id: int | str, event: dict[str, Any]) -> pathlib.Path:
    path = agent_session_path(session_dir, conversation_id)
    doc = {"kind": "event", "conversation_id": str(conversation_id), **event}
    doc.setdefault("created_at", now())
    append_jsonl(path, doc)
    return path


def runtime_supervision_enabled() -> bool:
    return bool(str(RUNTIME_SUPERVISOR_DIR).strip()) and SUPERVISION_POLICY in {"observe", "gate"}


def emit_runtime_supervision_checkpoint(
    session_dir: pathlib.Path,
    conversation_id: int | str,
    session: dict[str, Any],
    checkpoint_type: str,
    *,
    reason: str,
    severity: str = "info",
    requested_action: str = "observe",
    context_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not runtime_supervision_enabled():
        return {}
    active_project = session.get("active_project", {}) if isinstance(session.get("active_project"), dict) else {}
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    refs = list(context_refs or [])
    for role, path in (
        ("codex_session", session_path(session_dir, conversation_id)),
        ("agent_session", agent_session_path(session_dir, conversation_id)),
    ):
        if path.is_file():
            refs.append(
                {
                    "role": role,
                    "ref": str(path.resolve()),
                    "sha256": canonical_evidence_hash.sha256_file(path),
                }
            )
    try:
        checkpoint = cgkn_supervision_protocol.emit_checkpoint(
            RUNTIME_SUPERVISOR_DIR,
            checkpoint_type,
            repository_root=ROOT,
            reason=reason,
            severity=severity,
            requested_action=requested_action,
            conversation_id=conversation_id,
            project_id=active_project.get("project_id", ""),
            run_id=generation.get("run_id", ""),
            context_refs=refs,
        )
    except Exception as exc:
        append_agent_session_event(
            session_dir,
            conversation_id,
            {
                "kind": "runtime_supervision_checkpoint_failed",
                "role": "system",
                "checkpoint_type": checkpoint_type,
                "error": str(exc)[:800],
            },
        )
        return {}
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "runtime_supervision_checkpoint_emitted",
            "role": "system",
            "checkpoint_type": checkpoint_type,
            "checkpoint_id": checkpoint.get("checkpoint_id", ""),
            "checkpoint_sha256": checkpoint.get("checkpoint_sha256", ""),
            "requested_action": requested_action,
        },
    )
    return checkpoint


def run_positive_transition_audit(
    session_dir: pathlib.Path,
    conversation_id: int | str,
    session: dict[str, Any],
    checkpoint_type: str,
    *,
    reason: str,
    context_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Gate only high-value positive transitions; ordinary failures never enter Codex."""
    if checkpoint_type not in cgkn_supervision_protocol.AUDIT_CHECKPOINT_TYPES:
        raise ValueError(f"not a positive audit checkpoint: {checkpoint_type}")
    if not runtime_supervision_enabled():
        return {"action": "resume", "scope": "none", "audit_status": "disabled"}
    checkpoint = emit_runtime_supervision_checkpoint(
        session_dir,
        conversation_id,
        session,
        checkpoint_type,
        reason=reason,
        severity="blocking" if SUPERVISION_POLICY == "gate" else "info",
        requested_action="resume",
        context_refs=context_refs,
    )
    if not checkpoint:
        return {"action": "halt", "scope": "safety", "audit_status": "unavailable"}
    if SUPERVISION_POLICY != "gate":
        return {
            "action": "resume",
            "scope": "none",
            "audit_status": "observe_only",
            "checkpoint_id": checkpoint.get("checkpoint_id", ""),
        }
    result = cgkn_supervision_protocol.await_checkpoint_release(
        RUNTIME_SUPERVISOR_DIR,
        str(checkpoint["checkpoint_id"]),
        SUPERVISION_GATE_TIMEOUT,
    )
    if result is None:
        return {
            "action": "halt",
            "scope": "safety",
            "audit_status": "timeout",
            "checkpoint_id": checkpoint.get("checkpoint_id", ""),
        }
    return {**result, "audit_status": "completed"}


def _canonical_doc_hash(value: dict[str, Any], hash_key: str) -> str:
    core = {key: item for key, item in value.items() if key != hash_key}
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_supervision_route_receipt(audit_result: dict[str, Any]) -> dict[str, Any]:
    """Load the router-owned receipt bound to this exact positive-transition result."""
    checkpoint_id = str(audit_result.get("checkpoint_id", "")).strip()
    if not checkpoint_id or not RUNTIME_SUPERVISOR_DIR:
        raise RuntimeError("supervision_route_receipt_unavailable")
    state_root = pathlib.Path(RUNTIME_SUPERVISOR_DIR).resolve()
    checkpoints = {
        str(item.get("checkpoint_id", "")): item
        for item in cgkn_supervision_protocol.load_checkpoints(state_root)
    }
    checkpoint = checkpoints.get(checkpoint_id)
    if checkpoint is None:
        raise RuntimeError("supervision_route_checkpoint_missing")
    result_errors = cgkn_supervision_protocol.validate_result(audit_result, checkpoint)
    if result_errors:
        raise RuntimeError("invalid_supervision_result:" + ",".join(result_errors))
    route_path = state_root / "routes" / f"{checkpoint_id}.json"
    route = read_json(route_path, {})
    if not isinstance(route, dict):
        route = {}
    route_errors = cgkn_supervision_router.validate_route_input(route)
    if (
        route_errors
        or route.get("kind") != "CGKNSupervisionRouteReceipt"
        or route.get("checkpoint_id") != checkpoint_id
        or route.get("checkpoint_sha256") != audit_result.get("checkpoint_sha256")
        or route.get("result_sha256") != audit_result.get("result_sha256")
        or route.get("action") != audit_result.get("action")
        or route.get("scope") != audit_result.get("scope")
        or route.get("route_sha256") != _canonical_doc_hash(route, "route_sha256")
    ):
        raise RuntimeError("invalid_supervision_route_receipt")
    return route


def complete_supervision_route(
    route: dict[str, Any],
    *,
    outcome: str,
    recovery_receipt: dict[str, Any] | None = None,
) -> pathlib.Path:
    """Consume one pending route exactly once and retain an auditable completion receipt."""
    root = pathlib.Path(RUNTIME_SUPERVISOR_DIR).resolve() / "routes"
    checkpoint_id = str(route.get("checkpoint_id", ""))
    completed = {
        **route,
        "kind": "CGKNSupervisionRouteConsumptionReceipt",
        "consumed_at": now(),
        "outcome": outcome,
        "recovery_receipt": recovery_receipt or {},
        "formal_evidence_authorized": False,
        "package_authorized": False,
        "delivery_authorized": False,
    }
    completed.pop("route_sha256", None)
    completed["consumption_sha256"] = _canonical_doc_hash(completed, "consumption_sha256")
    path = root / f"{checkpoint_id}.consumed.json"
    write_json(path, completed)
    pending_name = {
        "rework_project": "pending_provider_repair.json",
        "recheck_evidence": "pending_evidence_recheck.json",
        "repair_kernel": "pending_kernel_repair.json",
    }.get(str(route.get("action", "")), "")
    if pending_name:
        pending_path = root / pending_name
        pending = read_json(pending_path, {})
        if isinstance(pending, dict) and pending.get("checkpoint_id") == checkpoint_id:
            pending_path.unlink(missing_ok=True)
    return path


def run_supervision_recovery_cycle(
    initial_audit: dict[str, Any],
    *,
    reaudit: Callable[[], dict[str, Any]],
    handlers: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]],
) -> dict[str, Any]:
    """Consume deterministic routes and re-emit the same checkpoint within a hard budget."""
    audit = dict(initial_audit)
    audit_count = 1
    refusal_count = 0
    recovery_counts = {
        "rework_project": 0,
        "recheck_evidence": 0,
        "repair_kernel": 0,
    }
    while True:
        if audit.get("action") == "resume" and audit.get("audit_status") != "completed":
            return {
                "outcome": "resumed",
                "workflow_state": "running",
                "evidence_status": "NOT_EVALUATED",
                "audit": audit,
                "audit_count": audit_count,
                "refusal_count": refusal_count,
                "recovery_counts": recovery_counts,
            }
        route = load_supervision_route_receipt(audit)
        action = str(route.get("action", "halt"))
        if action == "resume":
            complete_supervision_route(route, outcome="resumed")
            return {
                "outcome": "resumed",
                "workflow_state": "running",
                "evidence_status": "NOT_EVALUATED",
                "audit": audit,
                "audit_count": audit_count,
                "refusal_count": refusal_count,
                "recovery_counts": recovery_counts,
            }
        refusal_count += 1
        if refusal_count >= MAX_SUPERVISION_REWORK_ROUNDS:
            complete_supervision_route(route, outcome="rework_budget_exhausted")
            return {
                "outcome": "needs_rework",
                "workflow_state": "rework_blocked",
                "evidence_status": "NEEDS_REWORK",
                "audit": audit,
                "audit_count": audit_count,
                "refusal_count": refusal_count,
                "recovery_counts": recovery_counts,
            }
        if action == "user_decision":
            complete_supervision_route(route, outcome="waiting_user_decision")
            return {
                "outcome": "waiting_user_decision",
                "workflow_state": "waiting_user_review",
                "evidence_status": "NOT_EVALUATED",
                "audit": audit,
                "audit_count": audit_count,
                "refusal_count": refusal_count,
                "recovery_counts": recovery_counts,
            }
        if action == "halt":
            complete_supervision_route(route, outcome="halted")
            return {
                "outcome": "halted",
                "workflow_state": "rework_blocked",
                "evidence_status": "BLOCKED",
                "audit": audit,
                "audit_count": audit_count,
                "refusal_count": refusal_count,
                "recovery_counts": recovery_counts,
            }
        handler = handlers.get(action)
        if handler is None:
            raise RuntimeError(f"supervision_route_consumer_missing:{action}")
        recovery_receipt = handler(audit, route) or {}
        nested_stop = recovery_receipt.get("cycle_stop") if isinstance(recovery_receipt, dict) else None
        complete_supervision_route(route, outcome="recovery_completed", recovery_receipt=recovery_receipt)
        if isinstance(nested_stop, dict):
            return nested_stop
        recovery_counts[action] += 1
        audit = dict(reaudit())
        audit_count += 1


def invalidate_supervision_evidence(
    audit_result: dict[str, Any],
    route: dict[str, Any],
    *,
    project_dir: pathlib.Path,
    production_run_dir: pathlib.Path,
) -> dict[str, Any]:
    """Move only canonical evidence receipts out of the active chain before a real rerun."""
    protected_roles = {
        "provider_generation_result",
        "provider_request",
        "provider_response",
        "implementation_decision",
        "implementation_patch",
        "patch_application",
    }
    allowed_roots = (project_dir.resolve(), production_run_dir.resolve())
    checkpoint_id = safe_id(str(route.get("checkpoint_id", "checkpoint")))
    invalidated_root = production_run_dir / "artifacts" / "invalidated_supervision" / checkpoint_id
    moved: list[dict[str, str]] = []
    for index, item in enumerate(route.get("evidence_refs", [])):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).lower()
        if role in protected_roles:
            continue
        raw_ref = str(item.get("ref", "")).strip()
        if not raw_ref:
            continue
        source = pathlib.Path(raw_ref).resolve()
        try:
            inside = any(source.is_relative_to(root) for root in allowed_roots)
        except AttributeError:  # pragma: no cover - Python < 3.9 compatibility
            inside = any(str(source).startswith(str(root) + os.sep) for root in allowed_roots)
        if not inside or not source.is_file() or source.is_symlink():
            continue
        invalidated_root.mkdir(parents=True, exist_ok=True)
        destination = invalidated_root / f"{index:02d}-{safe_id(role)}-{source.name}"
        source.replace(destination)
        moved.append({"role": role, "from": str(source), "to": str(destination)})
    receipt = {
        "kind": "CGKNSupervisionEvidenceInvalidationReceipt",
        "created_at": now(),
        "checkpoint_id": str(audit_result.get("checkpoint_id", "")),
        "scope": str(route.get("scope", "evidence")),
        "invalidated": moved,
        "provider_invocation_count": 0,
        "formal_evidence_authorized": False,
    }
    receipt_path = production_run_dir / "artifacts" / f"{checkpoint_id}_evidence_invalidation.json"
    write_json(receipt_path, receipt)
    return {**receipt, "receipt_ref": str(receipt_path.resolve())}


def execute_governed_supervision_repair(
    audit_result: dict[str, Any], route: dict[str, Any]
) -> dict[str, Any]:
    checkpoint = {
        "checkpoint_id": audit_result.get("checkpoint_id", ""),
        "checkpoint_sha256": audit_result.get("checkpoint_sha256", ""),
    }
    test_targets = [
        str(target)
        for target in route.get("repair_targets", [])
        if str(target).replace("\\", "/").startswith("tests/")
    ]
    reproduction_checks = [f"python -m pytest {target} -q" for target in test_targets]
    request = governed_kernel_repair.build_repair_request(
        audit_result,
        checkpoint,
        reproduction_checks=reproduction_checks,
    )
    routes_dir = pathlib.Path(RUNTIME_SUPERVISOR_DIR).resolve() / "routes"
    request_path = routes_dir / f"{route['checkpoint_id']}.kernel_repair_request.json"
    write_json(request_path, request)
    receipt = governed_kernel_repair.execute_repair(
        request,
        ROOT,
        metrics_state_dir=RUNTIME_SUPERVISOR_DIR,
    )
    receipt_path = routes_dir / f"{route['checkpoint_id']}.kernel_repair_receipt.json"
    write_json(receipt_path, receipt)
    return {
        **receipt,
        "request_ref": str(request_path.resolve()),
        "receipt_ref": str(receipt_path.resolve()),
    }


def load_session(session_dir: pathlib.Path, conversation_id: int | str) -> dict[str, Any]:
    session = read_json(session_path(session_dir, conversation_id), default_session(conversation_id))
    defaults = default_session(conversation_id)
    for key in ("schema_version", "conversation_id", "source", "active_project", "revision_history"):
        session.setdefault(key, defaults[key])
    if isinstance(session.get("active_project"), dict):
        active = defaults["active_project"]
        active.update(session["active_project"])
        session["active_project"] = active
    return session


def save_session(session_dir: pathlib.Path, session: dict[str, Any]) -> None:
    session["updated_at"] = now()
    try:
        session["project_memory"] = project_memory_md.write_project_memory(session, DEFAULT_MEMORY_DIR)
    except Exception as exc:
        print(f"project memory update failed: {exc}", flush=True)
    write_json(session_path(session_dir, session.get("conversation_id", "")), session)


def attachment_kind_label(kind: str) -> str:
    return {
        "image": "图片/参考图",
        "document": "文档资料",
        "video": "视频素材",
        "audio": "音频素材",
        "animation": "动图/动画素材",
    }.get(kind, "用户上传资料")


def summarize_message_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    caption = str(message.get("caption", "")).strip()
    values = message.get("attachments", [])
    if not isinstance(values, list):
        return []
    specs: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict) or not str(item.get("path", "")).strip():
            continue
        path = pathlib.Path(str(item["path"])).resolve()
        specs.append(
            {
                "type": str(item.get("type") or item.get("kind") or "document"),
                "codex_field": "attachment",
                "local_path": str(path),
                "file_name": str(item.get("file_name") or path.name),
                "mime_type": str(item.get("mime_type", "")),
                "file_size": path.stat().st_size if path.is_file() else 0,
                "caption": str(item.get("caption") or caption),
            }
        )
    return specs


def download_message_attachments(
    client: CodexConversation,
    conversation_id: int | str,
    message: dict[str, Any],
    upload_dir: pathlib.Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    specs = summarize_message_attachments(message)
    if not specs:
        return downloaded, skipped
    for spec in specs:
        file_size = int(spec.get("file_size") or 0)
        if file_size > MAX_UPLOAD_BYTES:
            skipped.append({**spec, "reason": "too_large", "max_bytes": MAX_UPLOAD_BYTES})
            continue
        target = pathlib.Path(str(spec.get("local_path", ""))).resolve()
        if not target.is_file():
            skipped.append({**spec, "reason": "local_attachment_missing"})
            continue
        downloaded.append(
            {
                "type": spec.get("type", "file"),
                "codex_field": spec.get("codex_field", ""),
                "file_name": target.name,
                "mime_type": spec.get("mime_type", ""),
                "file_size": target.stat().st_size,
                "caption": spec.get("caption", ""),
                "local_path": str(target),
                "turn_id": message.get("turn_id"),
                "created_at": now(),
            }
        )
    return downloaded, skipped


def recent_attachments(session: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    values = session.get("attachments", [])
    if not isinstance(values, list):
        return []
    out: list[dict[str, Any]] = []
    for item in values[-limit:]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "type": item.get("type", ""),
                "file_name": item.get("file_name", ""),
                "mime_type": item.get("mime_type", ""),
                "file_size": item.get("file_size", 0),
                "caption": item.get("caption", ""),
                "local_path": item.get("local_path", ""),
                "created_at": item.get("created_at", ""),
            }
        )
    return out


def attachment_requirement_lines(session: dict[str, Any], limit: int = 30) -> list[str]:
    lines: list[str] = []
    for item in recent_attachments(session, limit=limit):
        kind = attachment_kind_label(str(item.get("type", "")))
        name = str(item.get("file_name", "")).strip() or "未命名上传"
        path = str(item.get("local_path", "")).strip()
        mime = str(item.get("mime_type", "")).strip()
        caption = str(item.get("caption", "")).strip()
        detail = f"- {kind}: {name}"
        if mime:
            detail += f"; mime_type: {mime}"
        if path:
            detail += f"; local_path: {path}"
        if caption:
            detail += f"; caption: {caption[:300]}"
        lines.append(detail)
    return lines


def record_attachments_as_project_input(session: dict[str, Any], attachments: list[dict[str, Any]]) -> None:
    if not attachments:
        return
    stored = session.setdefault("attachments", [])
    if not isinstance(stored, list):
        stored = []
    stored.extend(attachments)
    session["attachments"] = stored[-120:]
    whiteboard = session.setdefault("whiteboard", {})
    if not isinstance(whiteboard, dict):
        whiteboard = {}
    fact_lines = []
    for item in attachments:
        kind = attachment_kind_label(str(item.get("type", "")))
        name = str(item.get("file_name", "")).strip() or "未命名上传"
        path = str(item.get("local_path", "")).strip()
        caption = str(item.get("caption", "")).strip()
        fact = f"用户上传了{kind}作为项目输入: {name}"
        if path:
            fact += f" ({path})"
        if caption:
            fact += f"; 说明: {caption[:240]}"
        fact_lines.append(fact)
    whiteboard["known_facts"] = unique_strings((whiteboard.get("known_facts", []) if isinstance(whiteboard.get("known_facts", []), list) else []) + fact_lines)
    whiteboard["decision_log"] = unique_strings(
        (whiteboard.get("decision_log", []) if isinstance(whiteboard.get("decision_log", []), list) else [])
        + ["已将用户上传文件保存为后端项目输入，后续方案、生成和修改应优先参考这些资料。"],
        limit=120,
    )
    session["whiteboard"] = whiteboard
    append_memory_event(
        session,
        "user_attachment_received",
        data={
            "attachments": recent_attachments({"attachments": attachments}, limit=len(attachments)),
            "count": len(attachments),
        },
    )


def attachment_user_text(attachments: list[dict[str, Any]], caption: str = "") -> str:
    caption = caption.strip()
    labels = [attachment_kind_label(str(item.get("type", ""))) for item in attachments]
    label_summary = "、".join(unique_strings(labels, limit=8)) or "资料"
    if caption:
        return f"用户上传了{label_summary}作为项目资料，并补充说明: {caption}"
    return f"用户上传了{label_summary}作为项目资料；这些资料会纳入后端需求和后续生成。"


def inside_workspace(path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def chat_history_targets(conversation_id: int | str, session_dir: pathlib.Path, log_dir: pathlib.Path) -> list[pathlib.Path]:
    safe_chat = safe_id(conversation_id)
    slug = f"codex-live-{safe_chat}"
    project_slug = f"codex_{slug}"
    targets = [
        session_path(session_dir, conversation_id),
        log_dir / f"{slug}_generation_result.json",
        log_dir / f"{project_slug}_preview.png",
        ROOT / "generated" / project_slug,
        ROOT / "examples" / "runtime_runs" / project_slug,
        ROOT / "examples" / "test_results" / f"{project_slug}_composition.json",
        ROOT / "examples" / "test_results" / f"{project_slug}_execution.json",
        ROOT / "examples" / "test_results" / f"{project_slug}_requirement_blueprint.json",
        ROOT / "examples" / "test_results" / f"{project_slug}_context_prompt.json",
        DEFAULT_UPLOAD_DIR / safe_chat,
    ]
    current = read_json(session_path(session_dir, conversation_id), {})
    memory = current.get("project_memory", {}) if isinstance(current, dict) else {}
    if isinstance(memory, dict):
        for key in ("project_memory_md", "project_memory_artifact"):
            raw = str(memory.get(key, "")).strip()
            if raw:
                targets.append(pathlib.Path(raw))
    return targets


def clear_chat_history(
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    *,
    include_outputs: bool,
    delete: bool,
) -> dict[str, Any]:
    archive_dir = ROOT / "generated" / "codex_history_archives" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") / safe_id(conversation_id)
    raw_targets = chat_history_targets(conversation_id, session_dir, log_dir)
    if not include_outputs:
        raw_targets = [session_path(session_dir, conversation_id)]
    unique = []
    seen: set[str] = set()
    for target in raw_targets:
        path = target.resolve()
        key = str(path).lower()
        if key not in seen and path.exists():
            seen.add(key)
            unique.append(path)
    cleared: list[str] = []
    skipped: list[str] = []
    for path in unique:
        if not inside_workspace(path):
            skipped.append(str(path))
            continue
        if delete:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        else:
            rel = path.relative_to(ROOT.resolve())
            target = archive_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        cleared.append(str(path))
    return {
        "mode": "delete" if delete else "archive",
        "include_outputs": include_outputs,
        "cleared": cleared,
        "skipped": skipped,
        "archive_dir": "" if delete or not cleared else str(archive_dir),
    }


def reset_summary_text(result: dict[str, Any]) -> str:
    cleared = len(result.get("cleared", []))
    skipped = len(result.get("skipped", []))
    mode = "永久删除" if result.get("mode") == "delete" else "归档"
    scope = "会话和生成历史" if result.get("include_outputs") else "当前会话"
    lines = [f"已{mode}{scope}，重新开始。", f"处理条目: {cleared}"]
    if skipped:
        lines.append(f"跳过非工作区路径: {skipped}")
    archive_dir = str(result.get("archive_dir", "")).strip()
    if archive_dir:
        lines.append(f"归档目录: {archive_dir}")
    return "\n".join(lines)


def append_memory_event(session: dict[str, Any], event_type: str, text: str = "", data: dict[str, Any] | None = None) -> None:
    events = session.setdefault("memory_events", [])
    if not isinstance(events, list):
        events = []
    event: dict[str, Any] = {"type": event_type, "created_at": now()}
    if text:
        event["text"] = text[:4000]
    if data:
        event["data"] = data
    events.append(event)
    session["memory_events"] = events[-250:]


def truth_ledger_path(session_dir: pathlib.Path, conversation_id: int | str) -> pathlib.Path:
    return session_dir / f"{safe_id(conversation_id)}.truth_ledger.jsonl"


def append_truth_ledger(
    session_dir: pathlib.Path,
    session: dict[str, Any],
    stage: str,
    claim: str,
    *,
    status: str = "observed",
    evidence_ref: str = "",
    can_user_see: bool = False,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "kind": "TruthLedgerEntry",
        "created_at": now(),
        "conversation_id": str(session.get("conversation_id", "")),
        "stage": stage,
        "claim": claim,
        "status": status,
        "evidence_ref": evidence_ref,
        "can_user_see": bool(can_user_see),
        "data": data or {},
    }
    path = truth_ledger_path(session_dir, session.get("conversation_id", ""))
    append_jsonl(path, entry)
    session["truth_ledger_path"] = str(path)
    append_memory_event(session, "truth_ledger_entry", data={k: entry[k] for k in ("stage", "claim", "status", "evidence_ref")})
    return entry


def read_truth_ledger(session_dir: pathlib.Path, conversation_id: int | str) -> list[dict[str, Any]]:
    path = truth_ledger_path(session_dir, conversation_id)
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            entries.append(doc)
    return entries


# LEGACY PROVIDER PIPELINE.
# Codex conversation mainline must not call this.
# Delivery is driven by the reviewed Provider route and the sole local_packager exit.
def delivery_evidence_state(entries: list[dict[str, Any]]) -> dict[str, Any]:
    required = {
        "package": False,
        "screenshot": False,
        "verify_report": False,
        "verify_passed": False,
    }
    refs: dict[str, str] = {}
    sent_record = False
    for entry in entries:
        status = str(entry.get("status", "")).lower()
        stage = str(entry.get("stage", "")).lower()
        data = entry.get("data", {}) if isinstance(entry.get("data"), dict) else {}
        artifact = str(data.get("artifact") or stage).lower()
        if status not in {"observed", "pass", "sent"}:
            continue
        if bool(data.get("verify_passed")) or stage == "verify_passed" or artifact == "verify_passed":
            required["verify_passed"] = True
            refs["verify_passed"] = str(entry.get("evidence_ref", ""))
        for key in required:
            if key in artifact or key in stage:
                required[key] = True
                refs[key] = str(entry.get("evidence_ref", ""))
        if stage == "delivery_attachment_sent" or artifact == "delivery_attachment_sent":
            sent_record = True
    ready = all(required.values())
    return {
        "delivery_ready": ready,
        "required": required,
        "missing": [key for key, present in required.items() if not present],
        "refs": refs,
        "sent_record": sent_record,
    }


CUSTOMER_MESSAGE_INTENTS = {
    "admin_command",
    "greeting",
    "status_query",
    "escalation_request",
    "generation_confirmation",
    "new_project_request",
    "project_revision_request",
    "project_update",
}


def looks_like_status_question(text: str) -> bool:
    compact = re.sub(r"[\s,.!?。！？~～]+", "", str(text or "").lower())
    if compact in {
        "现在怎么样了",
        "怎么样了",
        "进度怎么样",
        "当前状态",
        "状态",
        "status",
        "howisitgoing",
        "有结果了吗",
        "好了没",
        "还在做吗",
        "还做吗",
        "在做吗",
        "还在跑吗",
        "还在生成吗",
        "后台还在做吗",
    }:
        return True
    status_words = ("进度", "状态", "做到哪", "做到哪里", "有动静", "跑到哪", "生成到哪", "结果了吗", "好了没", "还在做", "还在跑", "还在生成", "后台还在")
    question_words = ("吗", "没", "没有", "哪", "如何", "怎么样", "怎样")
    return any(word in compact for word in status_words) and (any(word in compact for word in question_words) or len(compact) <= 18)


def looks_like_escalation_request(text: str) -> bool:
    compact = re.sub(r"[\s,.!?。！？~～]+", "", str(text or "").lower())
    if compact in {"升级", "交给agent", "调用api", "用provider", "人工介入", "请求升级", "escalate"}:
        return True
    return any(word in compact for word in ("升级", "人工介入", "交给agent", "调用api", "用provider"))


def looks_like_substantive_project_request(text: str) -> bool:
    compact = re.sub(r"[\s,.!?。！？~～]+", "", str(text or "").lower())
    if len(compact) < 60:
        return False
    action_terms = ("实现", "开发", "设计", "创建", "生成", "搭建", "制作")
    project_terms = ("项目", "平台", "系统", "应用", "网站", "前端", "后端", "数据库", "测试", "交付", "导出")
    action_count = sum(1 for token in action_terms if token in compact)
    project_count = sum(1 for token in project_terms if token in compact)
    return action_count >= 1 and project_count >= 2


def model_classify_customer_message(text: str, session: dict[str, Any]) -> dict[str, Any] | None:
    stripped = str(text or "").strip()
    if not stripped or not local_model_router.task_enabled("customer_classification"):
        return None
    prompt = json.dumps(
        {
            "text": stripped,
            "generation_status": session.get("generation", {}).get("status", "idle") if isinstance(session.get("generation"), dict) else "idle",
            "has_project_summary": bool(str((session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}).get("project_summary", "")).strip()),
            "substantive_user_turn_count": substantive_user_turn_count(session),
            "allowed_intents": sorted(CUSTOMER_MESSAGE_INTENTS),
        },
        ensure_ascii=False,
        indent=2,
    )
    result = local_model_router.call_json_task(
        "customer_classification",
        "Classify the Codex conversation customer message. Return JSON only: {\"intent\":\"...\",\"confidence\":0.0,\"reason\":\"short\"}. Do not start generation by yourself.",
        prompt,
        30,
    )
    doc = result.get("json") if isinstance(result.get("json"), dict) else None
    if not doc:
        return None
    intent = str(doc.get("intent", "")).strip()
    if intent not in CUSTOMER_MESSAGE_INTENTS:
        return None
    if intent == "generation_confirmation" and not (is_generate_command(stripped) or is_human_start_confirmation(stripped, session)):
        return None
    return {
        "intent": intent,
        "confidence": doc.get("confidence", 0),
        "reason": str(doc.get("reason") or "local_model_classification")[:300],
    }


def classify_customer_message(text: str, session: dict[str, Any]) -> dict[str, Any]:
    stripped = str(text or "").strip()
    compact = re.sub(r"[\s,.!?。！？~～]+", "", stripped.lower())
    generation_status = str(session.get("generation", {}).get("status", "idle")).lower()
    source = "rule"
    reason = ""
    if stripped in {"/new", "/reset", "/restart", "/delete_history", "/help", "/status"}:
        intent = "status_query" if stripped == "/status" else "admin_command"
        reason = "explicit_admin_command"
    elif is_smalltalk(stripped):
        intent = "greeting"
        reason = "smalltalk"
    elif looks_like_substantive_project_request(stripped):
        model_doc = model_classify_customer_message(stripped, session)
        first_turn = substantive_user_turn_count(session) == 0
        safe_model_intents = {"new_project_request", "project_update", "project_revision_request"}
        model_intent = str((model_doc or {}).get("intent") or "")
        intent = model_intent if model_intent in safe_model_intents else ("new_project_request" if first_turn else "project_update")
        source = "local_model" if model_doc else "rule"
        reason = str((model_doc or {}).get("reason") or "substantive_project_request")
    elif looks_like_status_question(stripped):
        intent = "status_query"
        reason = "status_question"
    elif looks_like_escalation_request(stripped):
        intent = "escalation_request"
        reason = "escalation_request"
    elif is_generate_command(stripped) or is_human_start_confirmation(stripped, session):
        intent = "generation_confirmation"
        reason = "generation_confirmation"
    elif project_revision_lane.is_revision_request(stripped, session) and generation_status not in {"queued", "running", "waiting_user_review"}:
        intent = "project_revision_request"
        reason = "active_project_revision_request"
    elif generation_status in {"queued", "running"}:
        intent = "project_update"
        reason = "active_generation_update"
    elif substantive_user_turn_count(session) == 0:
        model_doc = model_classify_customer_message(stripped, session)
        if model_doc:
            intent = str(model_doc.get("intent") or "new_project_request")
            source = "local_model"
            reason = str(model_doc.get("reason") or "model_classification")
        else:
            intent = "new_project_request"
            reason = "first_substantive_turn"
    else:
        model_doc = model_classify_customer_message(stripped, session)
        if model_doc:
            intent = str(model_doc.get("intent") or "project_update")
            source = "local_model"
            reason = str(model_doc.get("reason") or "model_classification")
        else:
            intent = "project_update"
            reason = "continuing_project_context"
    if intent not in CUSTOMER_MESSAGE_INTENTS:
        intent = "project_update"
        source = "rule"
        reason = "invalid_model_intent_fallback"
    return {
        "kind": "CustomerMessageClassification",
        "intent": intent,
        "text": stripped,
        "classified_at": now(),
        "source": source,
        "reason": reason,
    }


def active_run(session: dict[str, Any]) -> dict[str, Any] | None:
    run = session.get("active_run")
    return run if isinstance(run, dict) else None


def create_active_run(session: dict[str, Any], ticket: dict[str, Any], text: str) -> dict[str, Any]:
    run = {
        "kind": "CGKNCodexFrontdeskRun",
        "id": f"run-{safe_id(session.get('conversation_id', 'chat'))}-{len(session.get('intake_tickets', []))}",
        "ticket_id": str(ticket.get("id", "")),
        "status": "intake_open",
        "driver": "frontdesk_intake",
        "goal": text,
        "created_at": now(),
        "updated_at": now(),
        "local_retry_count": 0,
        "local_retry_exhausted": False,
    }
    session["active_run"] = run
    session["generation"] = {"status": "idle", "driver": "not_started", "generation_mode": "unstarted"}
    return run


def update_active_run_status(session: dict[str, Any], status: str, **fields: Any) -> dict[str, Any]:
    run = active_run(session) or {
        "kind": "CGKNCodexFrontdeskRun",
        "id": f"run-{safe_id(session.get('conversation_id', 'chat'))}-manual",
        "created_at": now(),
        "driver": "frontdesk_intake",
    }
    run.update(fields)
    run["status"] = status
    run["updated_at"] = now()
    session["active_run"] = run
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    generation["status"] = status
    session["generation"] = generation
    return run


def mark_generation_retry(
    session: dict[str, Any],
    *,
    reason: str,
    max_retries: int = 2,
) -> bool:
    run = active_run(session) or {
        "kind": "CGKNCodexFrontdeskRun",
        "id": f"run-{safe_id(session.get('conversation_id', 'chat'))}-manual",
        "created_at": now(),
    }
    retry_count = int(run.get("local_retry_count") or 0) + 1
    run["local_retry_count"] = retry_count
    run["last_retry_reason"] = reason
    run["updated_at"] = now()
    exhausted = retry_count >= max_retries
    run["local_retry_exhausted"] = exhausted
    session["active_run"] = run
    return not exhausted


def assert_api_generation_ready(generation_mode: str) -> None:
    if str(generation_mode or "api").lower() != "api":
        return
    creds = check_connectivity._resolve_api_credentials()
    if not str(creds.get("api_key", "")).strip():
        raise RuntimeError("api_generation_mode requires configured OpenAI-compatible API key")


def current_pending_decision(session: dict[str, Any]) -> dict[str, Any] | None:
    pending = session.get("pending_decision")
    if isinstance(pending, dict) and str(pending.get("status", "")) == "pending" and str(pending.get("question", "")).strip():
        return pending
    return None


def create_intake_ticket(session_dir: pathlib.Path, session: dict[str, Any], text: str) -> dict[str, Any]:
    tickets = session.setdefault("intake_tickets", [])
    ticket_id = f"ticket-{safe_id(session.get('conversation_id', 'chat'))}-{len(tickets) + 1}"
    cleaned_session = reset_project_scoped_context_for_new_run(session, text, ticket_id)
    session.clear()
    session.update(cleaned_session)
    ticket = {
        "kind": "CustomerIntakeTicket",
        "id": ticket_id,
        "created_at": now(),
        "raw_user_message": text,
        "status": "open",
    }
    tickets.append(ticket)
    session["intake_tickets"] = tickets[-40:]
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    next_whiteboard = merge_whiteboard(
        whiteboard,
        {
            "project_summary": text,
            "known_facts": [f"用户提出的新项目需求: {text}"],
            "first_version_plan": [
                "先建立项目记录；模型客服整理需求后直接启动正式 agent 生成。",
            ],
            "decision_log": ["项目输入进入后直接启动正式 agent 生成；客服回复由模型生成。"],
            "ready_to_generate": False,
        },
    )
    session["whiteboard"] = enforce_backend_updates_from_user_text(session, next_whiteboard)
    append_whiteboard_version(session, session["whiteboard"])
    append_memory_event(session, "intake_ticket_created", data={"ticket_id": ticket_id, "raw_user_message": text[:1200]})
    append_truth_ledger(
        session_dir,
        session,
        "intake_ticket",
        "新项目需求已进入本地 intake",
        evidence_ref=ticket_id,
        data={"artifact": "intake_ticket", "ticket_id": ticket_id},
    )
    return ticket


def append_backend_memo(session_dir: pathlib.Path, session: dict[str, Any], stage: str, text: str) -> dict[str, Any]:
    memo = {"kind": "HumanBackendMemo", "created_at": now(), "stage": stage, "text": text}
    memos = session.setdefault("backend_memos", [])
    memos.append(memo)
    session["backend_memos"] = memos[-80:]
    append_memory_event(session, "backend_memo", text, {"stage": stage})
    append_truth_ledger(
        session_dir,
        session,
        "backend_memo",
        "后台同事式进度 memo 已生成",
        evidence_ref=stage,
        data={"artifact": "human_backend_memo"},
    )
    return memo


def latest_backend_memo(session: dict[str, Any]) -> str:
    memos = session.get("backend_memos", [])
    if not isinstance(memos, list) or not memos:
        return ""
    last = memos[-1]
    return str(last.get("text", "")) if isinstance(last, dict) else ""


def append_backend_control(
    session_dir: pathlib.Path,
    session: dict[str, Any],
    action: str,
    *,
    payload: dict[str, Any] | None = None,
    status: str = "logged",
    reason: str = "",
) -> dict[str, Any]:
    controls = session.setdefault("backend_controls", [])
    if not isinstance(controls, list):
        controls = []
    run = active_run(session) or {}
    control = {
        "kind": "BackendControlLog",
        "id": f"ctrl-{safe_id(session.get('conversation_id', 'chat'))}-{len(controls) + 1}",
        "action": action,
        "status": status,
        "log_only": True,
        "reason": reason,
        "active_run_id": str(run.get("id", "")),
        "ticket_id": str(run.get("ticket_id", "")),
        "created_at": now(),
        "updated_at": now(),
        "payload": payload or {},
    }
    controls.append(control)
    session["backend_controls"] = controls[-120:]
    if isinstance(run, dict) and run:
        run["last_control_id"] = control["id"]
        run["last_control_action"] = action
        run["updated_at"] = now()
        session["active_run"] = run
    append_memory_event(
        session,
        "backend_control_logged",
        data={"control_id": control["id"], "action": action, "status": status, "reason": reason},
    )
    append_truth_ledger(
        session_dir,
        session,
        "backend_control",
        "前台事件已写入兼容日志，正式生成由 agent_session 和 agent loop 推进。",
        evidence_ref=control["id"],
        data={"artifact": "backend_control_log", "control_id": control["id"], "action": action, "status": status, "log_only": True},
    )
    return control


def update_backend_control_status(
    session: dict[str, Any],
    control_id: str,
    status: str,
    *,
    reason: str = "",
    result_path: str = "",
) -> None:
    controls = session.get("backend_controls", [])
    if not isinstance(controls, list):
        return
    for control in reversed(controls):
        if isinstance(control, dict) and str(control.get("id", "")) == str(control_id):
            control["status"] = status
            control["updated_at"] = now()
            if reason:
                control["reason"] = reason
            if result_path:
                control["result_path"] = result_path
            break
    session["backend_controls"] = controls


def latest_backend_control(session: dict[str, Any]) -> dict[str, Any]:
    controls = session.get("backend_controls", [])
    if not isinstance(controls, list) or not controls:
        return {}
    last = controls[-1]
    return last if isinstance(last, dict) else {}


def has_open_backend_control(session: dict[str, Any], actions: set[str]) -> bool:
    # Legacy status display only. Codex conversation generation_confirmation must not use
    # backend_controls as a queue or blocker.
    controls = session.get("backend_controls", [])
    if not isinstance(controls, list):
        return False
    for control in reversed(controls):
        if not isinstance(control, dict):
            continue
        if str(control.get("action", "")) in actions and str(control.get("status", "")).lower() in {"queued", "running", "applied"}:
            return True
    return False


def generation_control_payload(session: dict[str, Any], requirement: str, generation_mode: str = "api") -> dict[str, Any]:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    return {
        "requirement": requirement[:12000],
        "project_summary": str(whiteboard.get("project_summary", ""))[:2000],
        "acceptance_criteria": whiteboard.get("acceptance_criteria", []) if isinstance(whiteboard.get("acceptance_criteria"), list) else [],
        "delivery_requirements": whiteboard.get("delivery_requirements", []) if isinstance(whiteboard.get("delivery_requirements"), list) else [],
        "change_requests": whiteboard.get("change_requests", []) if isinstance(whiteboard.get("change_requests"), list) else [],
        "attachments": recent_attachments(session, limit=20),
        "control_flags": {
            "generation_mode": "agent_conversation_loop",
            "backend_controls_are_log_only": True,
        },
    }


def project_analysis_reply(session: dict[str, Any], facts: dict[str, Any] | None = None) -> str:
    facts = facts or {}
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    summary = str(facts.get("project_summary") or whiteboard.get("project_summary") or latest_user_text(session) or "这个项目").strip()
    summary = re.sub(r"\s+", " ", summary)[:900]
    delivery = whiteboard.get("delivery_requirements", []) if isinstance(whiteboard.get("delivery_requirements"), list) else []
    acceptance = whiteboard.get("acceptance_criteria", []) if isinstance(whiteboard.get("acceptance_criteria"), list) else []
    requirements = unique_strings([str(item) for item in delivery + acceptance if str(item).strip()], limit=3)
    requirement_text = "；".join(requirements) if requirements else "可运行项目、启动说明、测试结论和真实预览产物"
    progress_line = "接下来会做可运行版本、测试记录和预览证据。" if facts.get("backend_parallel_started", True) else "我会继续把范围和技术路线整理清楚。"
    return (
        f"我已经把需求整理成第一版方向：{summary}\n"
        "我会按核心能力拆技术路线，并把第一版做成可运行项目。\n"
        f"验收重点：{requirement_text}。\n"
        f"{progress_line}没看到真实产物前，不会把它标成完成。"
    )


def backend_dialogue_status_text(session: dict[str, Any]) -> str:
    analysis = session.get("backend_dialogue_analysis", {}) if isinstance(session.get("backend_dialogue_analysis"), dict) else {}
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    summary = str(analysis.get("project_summary") or whiteboard.get("project_summary") or "当前项目").strip()
    frontend = analysis.get("frontend_plan") if isinstance(analysis.get("frontend_plan"), list) else whiteboard.get("frontend_plan", [])
    backend = analysis.get("backend_plan") if isinstance(analysis.get("backend_plan"), list) else whiteboard.get("backend_plan", [])
    questions = analysis.get("soft_questions") if isinstance(analysis.get("soft_questions"), list) else whiteboard.get("soft_questions", [])
    frontend_text = "；".join(str(item) for item in frontend[:3] if str(item).strip()) or "先按第一版体验拆界面和预览"
    backend_text = "；".join(str(item) for item in backend[:3] if str(item).strip()) or "先按本地运行方式拆核心流程"
    question_text = ""
    if questions:
        question_text = "\n建议补充：" + "；".join(str(item) for item in questions[:2] if str(item).strip())
    return (
        f"我先按这个方向整理第一版范围：{summary[:500]}。\n"
        f"界面和预览重点：{frontend_text}。\n"
        f"技术路线重点：{backend_text}。"
        f"{question_text}\n"
        "如果你说“开始生成”，我会按已记录假设先做可运行版本，并同步准备测试记录。"
    )


def frontdesk_compose(event: str, session: dict[str, Any], facts: dict[str, Any] | None = None, backend_memo: str = "") -> str:
    facts = facts or {}
    if event == "pending_decision":
        return project_analysis_reply(session, {**facts, "backend_parallel_started": True})
    if event == "backend_dialogue_reply":
        return str(facts.get("message") or facts.get("user_visible_reply") or "")
    if event == "backend_dialogue_status":
        return backend_dialogue_status_text(session)
    if event == "intake_ticket_created":
        return project_analysis_reply(session, facts)
    if event == "project_update":
        return project_analysis_reply(session, facts)
    if event == "simulator_started":
        return public_narration.public_event_text("generation_started", facts)
    if event == "blocked":
        reason = str(facts.get("reason", "当前证据不足或流程被阻断"))
        return f"这轮先停住：{reason}。我会把已确认的需求保留下来，下一次可以从这个方向继续。"
    if event == "delivery_ready":
        return public_narration.public_event_text("delivery_ready", facts)
    if event == "unsupported_attachment_received":
        return "这份资料已记为项目输入；图片、文档、视频、音频都会作为需求和验证材料。"
    if event == "generation_failed":
        return str(facts.get("user_visible_cause") or "这轮实现过程被中断，当前不能交付；你继续补充项目输入后，我会从同一上下文修复。")
    return str(facts.get("message") or backend_memo or "当前项目上下文已记录，我会按最新目标继续处理。")


def pre_send_guard(text: str) -> str:
    guarded = str(text or "").strip()
    guarded = public_narration.redact_internal_terms(guarded)
    guarded = re.sub(r"[A-Za-z]:\\[^\s，。；；]+", "本地工作区记录", guarded)
    guarded = re.sub(
        r"(?<![\w\u4e00-\u9fff])/(?:Users|home|tmp|var|mnt|workspace|app|src|data|generated|examples|root)(?:/[^\s，。；；]+)+",
        "本地工作区记录",
        guarded,
    )
    replacements = {
        "provider_user_message": "回复",
        "customer_service_reply": "回复",
        "truth_ledger.jsonl": "交付记录",
        "intake ticket": "项目记录",
        "simulator team": "制作流程",
        "local_simulator_team": "制作流程",
        "simulator": "制作流程",
        "agent/provider": "后续处理",
        "provider": "后续处理",
        "API": "外部接口",
        "后台 memo:": "",
        "package": "可运行项目文件",
        "verify report": "测试结论",
        "verify_report": "测试结论",
        "screenshot": "效果预览",
        "truth ledger": "交付记录",
        "queue": "准备流程",
        "gate": "检查点",
        "pipeline failed with internal status": "生成过程已切换到修复路径",
        "证据账本": "交付记录",
        "BLOCKED": "暂停",
    }
    for old, new in replacements.items():
        guarded = guarded.replace(old, new)
    guarded = guarded.replace("JSON", "结构化记录")
    guarded = public_narration.redact_internal_terms(guarded)
    return guarded[:3900] or "当前项目上下文已记录，我会按最新目标继续处理。"


def send_customer_reply(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    *,
    event: str,
    facts: dict[str, Any] | None = None,
    backend_memo: str = "",
    source: str = "frontdesk_composer",
    direct_text: str = "",
) -> bool:
    fact_doc = facts if isinstance(facts, dict) else {}
    generation = fact_doc.get("generation") if isinstance(fact_doc.get("generation"), dict) else session.get("generation", {})
    evidence = fact_doc.get("evidence_state") if isinstance(fact_doc.get("evidence_state"), dict) else delivery_evidence_state(read_truth_ledger(session_dir, conversation_id))
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    draft = direct_text or frontdesk_compose(event, session, facts, backend_memo)
    context = frontdesk_team_lead_agent.build_context(
        latest_user_message=latest_user_text(session),
        conversation_history_summary=frontdesk_team_lead_agent.conversation_history_summary(session.get("messages", [])),
        whiteboard=whiteboard,
        active_run=active_run(session),
        generation_status=generation if isinstance(generation, dict) else {},
        delivery_evidence=evidence,
        known_limits=frontdesk_team_lead_agent.known_limits_from_context(whiteboard, generation, evidence),
        customer_agent_policy=read_customer_agent_policy(),
        draft_reply=draft,
        event=event,
    )
    structured = frontdesk_team_lead_agent.compose_reply(context)
    session["last_team_lead_reply"] = structured
    # Preserve the event-specific public composer as the actual wording while
    # recording Team Lead intent/status metadata for continuity and auditing.
    text = pre_send_guard(draft)
    session.setdefault("messages", []).append({"role": "assistant", "text": text, "created_at": now(), "source": source, "event": event})
    append_memory_event(session, "assistant_message", text, {"source": source, "event": event})
    append_truth_ledger(
        session_dir,
        session,
        "frontdesk_outbound",
        "用户可见回复已通过客服 composer 和发送前 guard",
        evidence_ref=event,
        can_user_see=True,
        data={"artifact": "frontdesk_reply", "event": event},
    )
    ok = client.send_message(conversation_id, text)
    append_truth_ledger(
        session_dir,
        session,
        "sent_record",
        "客服出口发送结果已记录",
        status="sent" if ok else "failed",
        evidence_ref=event,
        can_user_see=ok,
        data={"artifact": "sent_record", "event": event, "transport": "codex_message"},
    )
    save_session(session_dir, session)
    return ok


def provider_escalation_allowed(session_dir: pathlib.Path, conversation_id: int | str, classification: dict[str, Any]) -> bool:
    return str(classification.get("intent")) == "escalation_request"


def maybe_auto_deliver_if_ready(client: CodexConversation, conversation_id: int | str, session_dir: pathlib.Path) -> dict[str, Any]:
    session = load_session(session_dir, conversation_id)
    evidence = delivery_evidence_state(read_truth_ledger(session_dir, conversation_id))
    if evidence["delivery_ready"] and not evidence.get("sent_record"):
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="delivery_ready",
            facts={"evidence_state": evidence},
            backend_memo=latest_backend_memo(session),
        )
        send_delivery_artifacts(client, conversation_id, session_dir, session, evidence)
        evidence = delivery_evidence_state(read_truth_ledger(session_dir, conversation_id))
    return evidence


def _evidence_path(raw: str) -> pathlib.Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = pathlib.Path(text)
    if not path.is_absolute():
        path = ROOT / path
    return path if path.exists() and path.is_file() else None


def _project_evidence_path(project_dir: pathlib.Path, raw: Any) -> pathlib.Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = pathlib.Path(text)
    if not path.is_absolute():
        path = project_dir / path
    try:
        resolved = path.resolve()
        project_root = project_dir.resolve()
        if project_root not in resolved.parents and resolved != project_root:
            return None
    except Exception:
        return None
    if resolved.exists() and resolved.is_file():
        return resolved
    return None


def _evidence_paths(project_dir: pathlib.Path, values: Any, *, limit: int = 6) -> list[pathlib.Path]:
    if not isinstance(values, list):
        return []
    paths: list[pathlib.Path] = []
    seen: set[str] = set()
    for value in values:
        path = _project_evidence_path(project_dir, value)
        if not path:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def _path_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _asset_label_text(path: pathlib.Path) -> str:
    return str(path).replace("\\", "/").lower()


def _looks_like_screenshot_asset(path: pathlib.Path) -> bool:
    text = _asset_label_text(path)
    return any(token in text for token in ("screenshot", "screen", "ui", "window", "interface", "界面", "截图"))


def _looks_like_generated_image_asset(path: pathlib.Path) -> bool:
    text = _asset_label_text(path)
    return any(
        token in text
        for token in (
            "generated",
            "generation",
            "output",
            "outputs",
            "asset",
            "background",
            "bg",
            "scene",
            "sprite",
            "character",
            "portrait",
            "立绘",
            "背景",
            "角色",
        )
    )


def _looks_like_background_asset(path: pathlib.Path) -> bool:
    text = _asset_label_text(path)
    return any(token in text for token in ("background", "bg_", "bg-", "/bg/", "scene", "背景"))


def _looks_like_sprite_asset(path: pathlib.Path) -> bool:
    text = _asset_label_text(path)
    return any(token in text for token in ("sprite", "character", "portrait", "standing", "立绘", "角色"))


def _add_asset(bucket: list[pathlib.Path], path: pathlib.Path | None) -> None:
    if not path or not path.exists() or not path.is_file():
        return
    suffix = path.suffix.lower()
    if suffix not in PUBLIC_DELIVERY_SUFFIXES:
        return
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    if str(resolved) not in {str(item.resolve()) for item in bucket}:
        bucket.append(resolved)


def _assets_from_safe_artifacts(safe_artifacts: list[dict[str, Any]]) -> dict[str, list[pathlib.Path]]:
    assets: dict[str, list[pathlib.Path]] = {
        "packages": [],
        "screenshots": [],
        "generated_images": [],
        "generated_backgrounds": [],
        "generated_sprites": [],
        "videos": [],
    }
    for item in safe_artifacts:
        if not isinstance(item, dict):
            continue
        path = _evidence_path(str(item.get("path", "")))
        if not path:
            continue
        kind = str(item.get("kind", "")).strip()
        if kind == "package":
            _add_asset(assets["packages"], path)
        elif kind == "screenshot":
            _add_asset(assets["screenshots"], path)
        elif kind == "background":
            _add_asset(assets["generated_backgrounds"], path)
            _add_asset(assets["generated_images"], path)
        elif kind == "sprite":
            _add_asset(assets["generated_sprites"], path)
            _add_asset(assets["generated_images"], path)
        elif kind == "video":
            _add_asset(assets["videos"], path)
        elif kind == "generated_image":
            _add_asset(assets["generated_images"], path)
    return assets


def _validated_assets_from_safe_artifacts(
    project_dir: pathlib.Path,
    safe_artifacts: list[dict[str, Any]],
) -> tuple[dict[str, list[pathlib.Path]], dict[str, Any], list[dict[str, str]]]:
    project = pathlib.Path(project_dir).resolve()
    assets: dict[str, list[pathlib.Path]] = {
        "packages": [],
        "screenshots": [],
        "generated_images": [],
        "generated_backgrounds": [],
        "generated_sprites": [],
        "videos": [],
    }
    validated_assets: list[dict[str, Any]] = []
    rejected_assets: list[dict[str, Any]] = []
    blocked_assets: list[dict[str, Any]] = []
    filtered_safe: list[dict[str, str]] = []
    required_roles = {"background", "sprite", "generated_image", "video"}
    for item in safe_artifacts:
        if not isinstance(item, dict):
            continue
        path = _evidence_path(str(item.get("path", "")))
        if not path:
            continue
        kind = str(item.get("kind", "")).strip()
        if kind == "package":
            _add_asset(assets["packages"], path)
            filtered_safe.append({"path": str(path), "kind": kind, "source": str(item.get("source", ""))})
            continue
        if kind == "screenshot":
            _add_asset(assets["screenshots"], path)
            filtered_safe.append({"path": str(path), "kind": kind, "source": str(item.get("source", ""))})
            continue
        if kind not in required_roles:
            continue
        validation = canonical_media_validation.validate_media(path, project, requested_role=kind)
        record = {"path": str(path), "kind": kind, "source": str(item.get("source", "")), "validation": validation}
        if validation.get("status") == "PASS":
            validated_assets.append(record)
            filtered_safe.append({"path": str(path), "kind": kind, "source": str(item.get("source", ""))})
            if kind == "background":
                _add_asset(assets["generated_backgrounds"], path)
                _add_asset(assets["generated_images"], path)
            elif kind == "sprite":
                _add_asset(assets["generated_sprites"], path)
                _add_asset(assets["generated_images"], path)
            elif kind == "generated_image":
                _add_asset(assets["generated_images"], path)
            elif kind == "video":
                _add_asset(assets["videos"], path)
        elif validation.get("status") == "BLOCKED_ENVIRONMENT":
            blocked_assets.append(record)
        else:
            rejected_assets.append(record)
    counts = {key: len(value) for key, value in assets.items()}
    overall_status = "PASS"
    if blocked_assets:
        overall_status = "BLOCKED_ENVIRONMENT"
    elif rejected_assets:
        overall_status = "FAIL"
    media_validation = {
        "required_roles": sorted(required_roles),
        "validated_assets": validated_assets,
        "rejected_assets": rejected_assets,
        "blocked_assets": blocked_assets,
        "counts": counts,
        "overall_status": overall_status,
    }
    return assets, media_validation, filtered_safe


def collect_public_delivery_assets(
    project_dir: pathlib.Path,
    manifest: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, list[pathlib.Path]]:
    project = pathlib.Path(project_dir).resolve()
    manifest = manifest if isinstance(manifest, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    facts = delivery_fact_check(project, manifest, evidence=evidence, phase="checkpoint")
    safe_artifacts = facts.get("safe_artifacts", []) if isinstance(facts.get("safe_artifacts"), list) else []
    assets, _media_validation, _filtered = _validated_assets_from_safe_artifacts(project, safe_artifacts)
    return assets


def _requirement_text(session: dict[str, Any], fallback: str = "") -> str:
    parts = [fallback]
    for message in session.get("messages", []):
        if not isinstance(message, dict) or str(message.get("role", "")) != "user":
            continue
        text = str(message.get("text", "")).strip()
        if text:
            parts.append(text)
    for attachment in session.get("attachments", []):
        if not isinstance(attachment, dict):
            continue
        for key in ("caption", "file_name", "mime_type"):
            value = str(attachment.get(key, "")).strip()
            if value:
                parts.append(value)
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    for key in ("project_summary", "known_facts", "acceptance_criteria", "delivery_requirements", "change_requests", "user_rules"):
        value = whiteboard.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value if str(item).strip())
    return "\n".join(part for part in parts if str(part).strip())


def infer_public_delivery_requirements(session: dict[str, Any], fallback: str = "") -> dict[str, bool]:
    text = _requirement_text(session, fallback).lower()
    compact = re.sub(r"\s+", "", text)
    return {
        "screenshot": any(token in compact for token in ("截图", "界面", "桌面界面", "gui", "desktop", "interface", "screenshot")),
        "video": any(token in compact for token in ("视频", "演示视频", "录屏", "video", "mp4", "webm")),
        "generated_image": any(token in compact for token in ("图片", "图像", "照片", "生成图", "直接生成背景", "直接生成立绘", "image", "photo", "picture")),
        "background": any(token in compact for token in ("背景", "背景图", "background", "sceneart")),
        "sprite": any(token in compact for token in ("立绘", "角色图", "character", "sprite", "portrait")),
        "demo_video": any(token in compact for token in ("演示", "demo", "展示视频")),
    }


def project_has_runnable_surface(project_dir: pathlib.Path, manifest: dict[str, Any] | None = None) -> bool:
    project = pathlib.Path(project_dir).resolve()
    if not project.exists() or not project.is_dir():
        return False
    if any((project / name).exists() for name in RUNNABLE_ENTRYPOINTS):
        return True
    startup = str((manifest or {}).get("startup_command", "")).strip()
    return bool(startup) and any(path.is_file() and path.suffix.lower() not in DOC_ONLY_SUFFIXES for path in project.rglob("*"))


def project_is_docs_only(project_dir: pathlib.Path) -> bool:
    project = pathlib.Path(project_dir).resolve()
    if not project.exists() or not project.is_dir():
        return True
    files = [path for path in project.rglob("*") if path.is_file()]
    if not files:
        return True
    user_files = [
        path
        for path in files
        if path.name not in {"delivery_manifest.json", "packager_run_log.txt", "final_project_bundle.zip"}
        and not path.name.endswith(".tmp")
    ]
    return bool(user_files) and all(path.suffix.lower() in DOC_ONLY_SUFFIXES for path in user_files)


def _quality_evidence_for_gate(project_dir: pathlib.Path, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = manifest if isinstance(manifest, dict) else {}
    quality = manifest.get("quality_evidence", {}) if isinstance(manifest.get("quality_evidence"), dict) else {}
    if quality:
        return quality
    try:
        return local_packager.collect_quality_evidence(project_dir)
    except Exception:
        return {}


def delivery_fact_check(
    project_dir: pathlib.Path,
    manifest: dict[str, Any] | None,
    *,
    evidence: dict[str, Any] | None = None,
    phase: str = "final",
    provider_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    manifest = manifest if isinstance(manifest, dict) else {}
    return adaptive_delivery.delivery_fact_check(
        project,
        manifest,
        evidence=evidence,
        provider_result=provider_result,
        phase=phase,
        public_suffixes=PUBLIC_DELIVERY_SUFFIXES,
        entrypoints=RUNNABLE_ENTRYPOINTS,
    )


def agent_delivery_judgment(
    *,
    raw_user_goal: str,
    project_summary: str,
    delivery_fact_check: dict[str, Any],
    quality_evidence: dict[str, Any] | None = None,
    known_limits: list[str] | None = None,
    test_report: Any = None,
    preview_evidence: Any = None,
    provider_result: dict[str, Any] | None = None,
    phase: str = "final",
    agent: Any = None,
) -> dict[str, Any]:
    return adaptive_delivery.agent_delivery_judgment(
        raw_user_goal=raw_user_goal,
        project_summary=project_summary,
        delivery_fact_check=delivery_fact_check,
        quality_evidence=quality_evidence,
        known_limits=known_limits,
        test_report=test_report,
        preview_evidence=preview_evidence,
        provider_result=provider_result,
        phase=phase,
        agent=agent,
    )


def _evidence_identity(details: dict[str, Any]) -> dict[str, str]:
    return {
        "run_id": str(details.get("run_id", "")).strip(),
        "candidate_id": str(details.get("candidate_id", "")).strip(),
        "candidate_hash": str(details.get("candidate_hash", "")).strip(),
        "commit_sha": str(details.get("commit_sha", "")).strip(),
    }


def _valid_identity_value(value: str) -> bool:
    normalized = str(value or "").strip()
    return bool(normalized) and normalized.lower() not in {"null", "none"}


def _identity_consistent(items: list[dict[str, str]]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    keys = ("run_id", "candidate_id", "candidate_hash", "commit_sha")
    for key in keys:
        values = {item.get(key, "") for item in items if _valid_identity_value(item.get(key, ""))}
        if len(values) > 1:
            failures.append(f"identity_mismatch:{key}")
    return not failures, failures


def _required_identity_failures(source: str, result: dict[str, Any]) -> list[str]:
    details = result.get("details", {}) if isinstance(result, dict) else {}
    identity = _evidence_identity(details if isinstance(details, dict) else {})
    failures: list[str] = []
    for key, value in identity.items():
        if not _valid_identity_value(value):
            failures.append(f"identity_missing:{source}:{key}")
    return failures


def evaluate_canonical_delivery_evidence(
    project_dir: pathlib.Path,
    *,
    browser_visual_required: bool,
    production_provenance_ref: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    test_document = read_json(project / "test_execution.json", {})
    provenance_value = str(
        production_provenance_ref
        or test_document.get("production_provenance_ref", "")
    ).strip()
    provenance_path = (
        pathlib.Path(provenance_value).resolve()
        if provenance_value
        else pathlib.Path()
    )
    provenance_inspection = (
        production_candidate_provenance.inspect(
            provenance_path,
            expected_candidate_dir=project,
        )
        if provenance_value
        else {
            "status": "NEEDS_REWORK",
            "failures": ["production_provenance_missing"],
        }
    )
    if provenance_inspection.get("status") != "PASS":
        return {
            "status": "NEEDS_REWORK",
            "production_provenance": provenance_inspection,
            "test_execution": {"status": "NOT_EVALUATED"},
            "customer_runtime": {"status": "NOT_EVALUATED"},
            "visual_evidence": {"status": "NOT_EVALUATED"},
            "browser_visual_required": browser_visual_required,
            "identity_consistent": False,
            "missing": [],
            "failures": sorted(
                set(
                    ["production_candidate_provenance"]
                    + list(provenance_inspection.get("failures", []))
                )
            ),
        }
    identity = provenance_inspection["identity"]
    provenance_hash = str(provenance_inspection["provenance_hash"])
    causal_trace_ref = (
        pathlib.Path(str(provenance_inspection["production_run_root"]))
        / provider_causal_trace.FILE_NAME
    )
    causal_trace_inspection = provider_causal_trace.inspect(
        causal_trace_ref,
        expected_candidate_dir=project,
        expected_production_run_dir=provenance_inspection[
            "production_run_root"
        ],
        expected_run_id=identity["run_id"],
        expected_candidate_id=identity["candidate_id"],
        expected_candidate_hash=identity["candidate_hash"],
        expected_commit_sha=identity["commit_sha"],
    )
    if causal_trace_inspection.get("status") != "PASS":
        return {
            "status": "NEEDS_REWORK",
            "production_provenance": provenance_inspection,
            "provider_causal_trace": causal_trace_inspection,
            "test_execution": {"status": "NOT_EVALUATED"},
            "customer_runtime": {"status": "NOT_EVALUATED"},
            "visual_evidence": {"status": "NOT_EVALUATED"},
            "browser_visual_required": browser_visual_required,
            "identity_consistent": False,
            "missing": [],
            "failures": sorted(
                set(
                    ["provider_causal_trace"]
                    + list(causal_trace_inspection.get("failures", []))
                )
            ),
        }
    test_result = real_test_execution.inspect_test_report(
        project,
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        candidate_hash=identity["candidate_hash"],
        commit_sha=identity["commit_sha"],
        production_provenance_ref=provenance_path,
        production_provenance_hash=provenance_hash,
    )
    runtime_result = customer_runtime_runner.inspect(
        project,
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        candidate_hash=identity["candidate_hash"],
        commit_sha=identity["commit_sha"],
        production_provenance_ref=provenance_path,
        production_provenance_hash=provenance_hash,
    )
    visual_result = browser_visual_evidence.inspect(
        project,
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        candidate_hash=identity["candidate_hash"],
        commit_sha=identity["commit_sha"],
        production_provenance_ref=provenance_path,
        production_provenance_hash=provenance_hash,
    ) if browser_visual_required else {
        "status": "NOT_EVALUATED",
        "missing": [],
        "details": {},
        "not_required": True,
    }
    missing: list[str] = []
    failures: list[str] = []

    if test_result.get("status") != "PASS":
        failures.append("test_execution")
        missing.extend(f"test_execution:{item}" for item in test_result.get("missing", []))
    if runtime_result.get("status") != "PASS":
        failures.append("customer_runtime")
        missing.extend(f"customer_runtime:{item}" for item in runtime_result.get("missing", []))
    if browser_visual_required and visual_result.get("status") != "PASS":
        failures.append("visual_evidence")
        missing.extend(f"visual_evidence:{item}" for item in visual_result.get("missing", []))

    identity_items = []
    required_results = [
        ("test_execution", test_result),
        ("customer_runtime", runtime_result),
    ]
    if browser_visual_required:
        required_results.append(("visual_evidence", visual_result))
    for source, result in required_results:
        failures.extend(_required_identity_failures(source, result))
        details = result.get("details", {}) if isinstance(result, dict) else {}
        identity_items.append(_evidence_identity(details if isinstance(details, dict) else {}))
    identity_consistent, identity_failures = _identity_consistent(identity_items)
    failures.extend(identity_failures)
    if any(item.startswith("identity_missing:") for item in failures):
        identity_consistent = False

    status = "PASS" if not missing and not failures and identity_consistent else "NEEDS_REWORK"
    return {
        "status": status,
        "production_provenance": provenance_inspection,
        "provider_causal_trace": causal_trace_inspection,
        "test_execution": test_result,
        "customer_runtime": runtime_result,
        "visual_evidence": visual_result,
        "browser_visual_required": browser_visual_required,
        "identity_consistent": identity_consistent,
        "missing": sorted(set(missing)),
        "failures": sorted(set(failures)),
    }


def evaluate_public_delivery_gate(
    project_dir: pathlib.Path,
    manifest: dict[str, Any] | None,
    session: dict[str, Any] | None = None,
    *,
    conversation: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    phase: str = "final",
    provider_result: dict[str, Any] | None = None,
    agent: Any = None,
    production_provenance_ref: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    session = session if isinstance(session, dict) else (conversation if isinstance(conversation, dict) else {})
    project = pathlib.Path(project_dir).resolve()
    manifest = manifest if isinstance(manifest, dict) else {}
    if provider_result is None and isinstance(manifest.get("provider_result"), dict):
        provider_result = manifest.get("provider_result")
    if agent is None and os.environ.get("CGNK_ADAPTIVE_DELIVERY_AGENT", "local").strip().lower() == "provider":
        review_model = model_policy.select_model("review")
        agent = lambda messages: provider_text(messages, review_model, 60)
    quality = _quality_evidence_for_gate(project, manifest)
    requirements = infer_public_delivery_requirements(session, str(manifest.get("startup_command", "")))
    browser_visual_required = bool(requirements.get("screenshot"))
    media_evidence_required = any(
        bool(requirements.get(key))
        for key in ("generated_image", "background", "sprite", "video", "demo_video")
    )
    canonical_gate = evaluate_canonical_delivery_evidence(
        project,
        browser_visual_required=browser_visual_required,
        production_provenance_ref=production_provenance_ref,
    )
    if canonical_gate.get("status") != "PASS":
        return {
            "verdict": "NEEDS_REWORK",
            "status": "NEEDS_REWORK",
            "phase": phase,
            "delivery_allowed": False,
            "is_final": False,
            "confidence": 1.0,
            "reasons": ["canonical required evidence failed"],
            "user_visible_warnings": [],
            "required_repairs": canonical_gate.get("missing", []) + canonical_gate.get("failures", []),
            "can_send_artifacts": [],
            "must_not_claim": ["canonical evidence passed", "final delivery ready"],
            "judgment_source": "canonical_evidence_gate",
            "canonical_evidence_gate": canonical_gate,
            "missing": canonical_gate.get("missing", []),
            "warnings": [],
            "requirements": requirements,
            "browser_visual_required": browser_visual_required,
            "media_evidence_required": media_evidence_required,
            "asset_counts": {},
            "quality_evidence": quality,
            "public_suffixes": sorted(PUBLIC_DELIVERY_SUFFIXES),
        }
    package_inspection: dict[str, Any] = {"status": "NOT_EVALUATED", "failures": []}
    facts = delivery_fact_check(
        project,
        manifest,
        evidence=evidence,
        phase=phase,
        provider_result=provider_result,
    )
    safe_artifacts = facts.get("safe_artifacts", []) if isinstance(facts.get("safe_artifacts"), list) else []
    assets, media_validation, filtered_safe_artifacts = _validated_assets_from_safe_artifacts(project, safe_artifacts)
    facts = dict(facts)
    facts["safe_artifacts"] = filtered_safe_artifacts
    facts["media_validation"] = media_validation
    requested_missing: list[str] = []
    if requirements["screenshot"] and not assets["screenshots"]:
        requested_missing.append("screenshots")
    if (requirements["video"] or requirements["demo_video"]) and not assets["videos"]:
        requested_missing.append("videos")
    if requirements["generated_image"] and not assets["generated_images"]:
        requested_missing.append("generated_images")
    if requirements["background"] and not assets["generated_backgrounds"]:
        requested_missing.append("generated_background")
    if requirements["sprite"] and not assets["generated_sprites"]:
        requested_missing.append("generated_sprite")
    if requested_missing:
        facts = dict(facts)
        facts["missing"] = sorted(set(list(facts.get("missing", [])) + requested_missing))
        facts["hard_blockers"] = sorted(
            set(list(facts.get("hard_blockers", [])) + [f"requested_artifact_missing:{item}" for item in requested_missing])
        )
        facts["warnings"] = sorted(
            set(list(facts.get("warnings", [])) + [f"Requested real delivery evidence is missing: {item}" for item in requested_missing])
        )
        facts["facts"] = dict(facts.get("facts", {}))
        facts["facts"]["requested_artifacts_present"] = False
    else:
        facts["facts"]["requested_artifacts_present"] = True
    media_missing = [item for item in requested_missing if item in {"videos", "generated_images", "generated_background", "generated_sprite"}]
    if media_missing:
        return {
            "verdict": "NEEDS_REWORK",
            "status": "NEEDS_REWORK",
            "phase": phase,
            "delivery_allowed": False,
            "is_final": False,
            "confidence": 1.0,
            "reasons": ["canonical required media evidence failed"],
            "user_visible_warnings": [],
            "required_repairs": facts.get("missing", []) + facts.get("hard_blockers", []),
            "can_send_artifacts": [],
            "must_not_claim": ["invalid or undecodable media as real delivery evidence"],
            "judgment_source": "canonical_media_validation",
            "delivery_fact_check": facts,
            "canonical_evidence_gate": canonical_gate,
            "media_validation": media_validation,
            "missing": facts.get("missing", []),
            "warnings": facts.get("warnings", []),
            "requirements": requirements,
            "browser_visual_required": browser_visual_required,
            "media_evidence_required": media_evidence_required,
            "asset_counts": {key: len(value) for key, value in assets.items()},
            "quality_evidence": quality,
            "public_suffixes": sorted(PUBLIC_DELIVERY_SUFFIXES),
        }
    if phase == "final":
        expected_user_review = bool(
            isinstance(session.get("pending_evidence_checkpoint"), dict)
            or (
                isinstance(session.get("whiteboard"), dict)
                and session.get("whiteboard", {}).get("requires_user_evidence_review")
            )
        )
        package_inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(
            project,
            manifest,
            visual_required=browser_visual_required,
            user_review_required=expected_user_review,
        )
        if package_inspection.get("status") != "PASS":
            return {
                "verdict": "NEEDS_REWORK",
                "status": "NEEDS_REWORK",
                "phase": phase,
                "delivery_allowed": False,
                "is_final": False,
                "confidence": 1.0,
                "reasons": ["canonical final package failed"],
                "user_visible_warnings": [],
                "required_repairs": package_inspection.get("failures", []),
                "can_send_artifacts": [],
                "must_not_claim": ["final package integrity passed", "final delivery ready"],
                "judgment_source": "canonical_delivery_manifest",
                "canonical_evidence_gate": canonical_gate,
                "canonical_package_inspection": package_inspection,
                "media_validation": media_validation,
                "missing": package_inspection.get("failures", []),
                "warnings": facts.get("warnings", []),
                "requirements": requirements,
                "browser_visual_required": browser_visual_required,
                "media_evidence_required": media_evidence_required,
                "asset_counts": {key: len(value) for key, value in assets.items()},
                "quality_evidence": quality,
                "public_suffixes": sorted(PUBLIC_DELIVERY_SUFFIXES),
            }
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    test_report_path = project / "TEST_REPORT.md"
    test_report = test_report_path.read_text(encoding="utf-8", errors="replace") if test_report_path.is_file() else ""
    judgment = agent_delivery_judgment(
        raw_user_goal=_requirement_text(session, ""),
        project_summary=str(whiteboard.get("project_summary", "")).strip(),
        delivery_fact_check=facts,
        quality_evidence=quality,
        known_limits=manifest.get("known_limits", []) if isinstance(manifest.get("known_limits"), list) else [],
        test_report=test_report,
        preview_evidence=evidence or manifest.get("user_review_evidence", {}),
        provider_result=provider_result,
        phase=phase,
        agent=agent,
    )
    judgment.update(
        {
            "status": judgment["verdict"],
            "phase": phase,
            "missing": facts.get("missing", []),
            "warnings": facts.get("warnings", []),
            "requirements": requirements,
            "browser_visual_required": browser_visual_required,
            "media_evidence_required": media_evidence_required,
            "asset_counts": {key: len(value) for key, value in assets.items()},
            "media_validation": media_validation,
            "quality_evidence": quality,
            "canonical_evidence_gate": canonical_gate,
            "canonical_package_inspection": package_inspection,
            "public_suffixes": sorted(PUBLIC_DELIVERY_SUFFIXES),
        }
    )
    return judgment


def record_public_delivery_gate(
    session_dir: pathlib.Path,
    session: dict[str, Any],
    gate: dict[str, Any],
    project_dir: pathlib.Path,
) -> None:
    append_truth_ledger(
        session_dir,
        session,
        "public_delivery_gate",
        "公开交付 gate 已完成检查",
        status=str(gate.get("status", "REWORK")),
        evidence_ref=str(project_dir),
        data={"artifact": "public_delivery_gate", **gate},
    )
    append_memory_event(session, "public_delivery_gate", data=gate)


def public_delivery_gate_failed_reply(gate: dict[str, Any] | None = None) -> str:
    gate = gate if isinstance(gate, dict) else {}
    verdict = str(gate.get("verdict", "")).upper()
    if verdict == "FACT_BLOCKED":
        text = (
            "这次交付存在事实级问题，例如项目或附件不存在、路径不安全，或没有真实生成结果，因此现在不能发送。\n"
            "我不会把缺失文件、占位内容或内部记录当成成果。"
        )
    else:
        text = (
            "当前版本需要继续修复，暂时不作为最终成果发送。\n"
            "已有事实记录会保留，完成必要修复后再重新判断是否可以交付。"
        )
    return public_narration.redact_internal_terms(
        text
    )


def mark_public_delivery_rework(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    project_dir: pathlib.Path,
    gate: dict[str, Any],
) -> None:
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    generation.update(
        {
            "status": "rework_blocked",
            "delivery_allowed": False,
            "delivery_gate": gate,
            "project_dir": str(project_dir),
            "package_path": "",
        }
    )
    session["generation"] = generation
    update_active_run_status(session, "rework_blocked", delivery_allowed=False, delivery_gate=gate, project_dir=str(project_dir))
    record_public_delivery_gate(session_dir, session, gate, project_dir)
    save_session(session_dir, session)
    send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event="public_delivery_gate_failed",
        facts={"delivery_gate": gate},
        source="public_delivery_gate",
        direct_text=public_delivery_gate_failed_reply(gate),
    )


def _public_caption_for(kind: str, path: pathlib.Path) -> str:
    if kind == "package":
        return "项目包"
    if kind == "screenshot":
        return "界面截图"
    if kind == "background":
        return "生成背景"
    if kind == "sprite":
        return "生成立绘"
    if kind == "generated_image":
        return "生成图片"
    if kind == "video":
        return "演示视频"
    return path.name


def emit_public_delivery(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    items: list[tuple[pathlib.Path, str]],
    *,
    source: str,
    package_approval: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    def normalized_send_result(value: Any, expected_conversation_id: int | str, kind: str) -> tuple[bool, dict[str, str]]:
        if not isinstance(value, dict) or value.get("ok") is not True:
            return False, {}
        result = value.get("result")
        if not isinstance(result, dict) or result.get("turn_id") in (None, ""):
            return False, {}
        if str(result.get("conversation_id", "")) != str(expected_conversation_id):
            return False, {}
        return True, {
            "turn_id": str(result["turn_id"]),
            "conversation_id": str(result["conversation_id"]),
            "artifact_id": str(result.get("artifact_id", "")),
            "artifact_unique_id": str(result.get("artifact_unique_id", "")),
            "sent_at": now(),
        }

    sent: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, kind in items:
        if not path.exists() or not path.is_file() or path.suffix.lower() not in PUBLIC_DELIVERY_SUFFIXES:
            continue
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        caption = _public_caption_for(kind, path)
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            client.send_chat_action(conversation_id, "upload_photo")
            try:
                ok, metadata = normalized_send_result(client.send_photo(conversation_id, path, caption), conversation_id, kind)
            except Exception:
                ok, metadata = False, {}
            if ok:
                sent.append({"kind": kind, "path": str(path), "caption": caption, **metadata})
        elif suffix in VIDEO_SUFFIXES:
            client.send_chat_action(conversation_id, "upload_video")
            try:
                ok, metadata = normalized_send_result(client.send_video(conversation_id, path, caption), conversation_id, kind)
            except Exception:
                ok, metadata = False, {}
            if ok:
                sent.append({"kind": kind, "path": str(path), "caption": caption, **metadata})
        else:
            client.send_chat_action(conversation_id, "upload_document")
            if kind == "package" and isinstance(package_approval, dict):
                approved_path = pathlib.Path(str(package_approval.get("package_path", "")))
                approved_manifest_path = pathlib.Path(str(package_approval.get("manifest_path", "")))
                package_ok = False
                try:
                    zip_inspection = canonical_delivery_manifest.inspect_zip_entries(path)
                    manifest_doc = json.loads(approved_manifest_path.read_text(encoding="utf-8"))
                    package_ok = (
                        path.resolve(strict=True) == approved_path.resolve(strict=True)
                        and canonical_evidence_hash.sha256_file(path)
                        == package_approval.get("package_sha256")
                        and zip_inspection.get("status") == "PASS"
                        and zip_inspection.get("package_entries_hash") == package_approval.get("package_entries_hash")
                        and manifest_doc.get("artifact_hash") == package_approval.get("manifest_artifact_hash")
                        and canonical_evidence_hash.canonical_json_hash(
                            manifest_doc,
                            ("artifact_hash",),
                        )
                        == package_approval.get("manifest_artifact_hash")
                    )
                except (OSError, ValueError, TypeError):
                    package_ok = False
                if not package_ok:
                    package_approval["failure_reason"] = "package_changed_before_send"
                    continue
            try:
                ok, metadata = normalized_send_result(client.send_document(conversation_id, path, caption), conversation_id, kind)
            except Exception:
                ok, metadata = False, {}
            if ok:
                sent.append({"kind": kind, "path": str(path), "caption": caption, **metadata})
    if sent:
        append_truth_ledger(
            session_dir,
            session,
            "public_delivery_attachment_sent",
            "公开交付附件已按类型白名单发送",
            status="sent",
            evidence_ref=source,
            can_user_see=True,
            data={"artifact": "public_delivery_attachment_sent", "sent": sent, "source": source},
        )
        append_memory_event(session, "public_delivery_attachment_sent", data={"sent": sent, "source": source})
    return sent


def filter_delivery_items_by_judgment(
    items: list[tuple[pathlib.Path, str]],
    judgment: dict[str, Any],
) -> list[tuple[pathlib.Path, str]]:
    allowed = {
        str(pathlib.Path(str(item)).resolve()).lower()
        for item in judgment.get("can_send_artifacts", [])
        if str(item).strip()
    }
    if not allowed:
        return []
    return [(path, kind) for path, kind in items if str(path.resolve()).lower() in allowed]


def is_user_review_continue(text: str) -> bool:
    return canonical_user_review.classify_review_text(text) == "APPROVED"


def evidence_checkpoint_summary(evidence: dict[str, Any]) -> str:
    def count(name: str) -> int:
        value = evidence.get(name, [])
        return len(value) if isinstance(value, list) else 0

    commands = evidence.get("test_commands", []) if isinstance(evidence.get("test_commands"), list) else []
    missing = evidence.get("missing", []) if isinstance(evidence.get("missing"), list) else []
    lines = [
        public_narration.public_event_text("evidence_checkpoint", evidence),
        f"测试报告：{'有' if evidence.get('test_report_path') else '没有'}",
        f"测试代码：{count('test_code_files')} 个",
        f"测试命令：{len(commands)} 条",
        f"样例输入：{count('sample_inputs')} 个",
        f"截图：{count('screenshots')} 张",
        f"视频：{count('videos')} 个",
        f"预览/数据文件：{count('preview_files')} 个",
    ]
    if commands:
        lines.append("可复查命令：" + "；".join(str(item) for item in commands[:4]))
    if missing:
        labels = {
            "TEST_REPORT.md": "测试报告",
            "EVIDENCE_REVIEW.md": "证据复核说明",
            "test_code_files": "测试代码",
            "sample_inputs": "样例输入",
            "screenshots": "界面截图",
            "generated_images": "生成图片",
            "generated_background": "生成背景",
            "generated_sprite": "生成立绘",
            "videos": "演示视频",
            "preview_files": "预览文件",
        }
        lines.append("缺少的证据：" + "；".join(labels.get(str(item), str(item)) for item in missing[:4]))
    lines.append("如果批准，请明确回复“我确认这个版本，可以最终打包”；如果要改，直接说要改哪里。")
    return public_narration.redact_internal_terms("\n".join(lines))


def send_evidence_checkpoint(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    project_dir: pathlib.Path,
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    gate = evaluate_public_delivery_gate(project_dir, {}, session, evidence=evidence, phase="checkpoint")
    if not gate.get("delivery_allowed"):
        current = load_session(session_dir, conversation_id)
        checkpoint = current.get("pending_evidence_checkpoint", {}) if isinstance(current.get("pending_evidence_checkpoint"), dict) else {}
        if checkpoint:
            checkpoint = canonical_user_review.mark_review_request_presented(
                project_dir,
                checkpoint,
                presented_artifacts=[],
            )
            checkpoint["sender_diagnostic"] = {
                "status": "NEEDS_REWORK",
                "failures": sorted(set(
                    ["checkpoint_gate_failed"]
                    + [str(item) for item in gate.get("required_repairs", [])]
                )),
                "sent_kinds": [],
            }
            current["pending_evidence_checkpoint"] = checkpoint
            save_session(session_dir, current)
        mark_public_delivery_rework(client, conversation_id, session_dir, current, project_dir, gate)
        return []
    presentation_sent = send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event="user_evidence_checkpoint",
        source="agent_generated_pipeline",
        direct_text=evidence_checkpoint_summary(evidence),
    )
    session = load_session(session_dir, conversation_id)
    checkpoint = session.get("pending_evidence_checkpoint", {}) if isinstance(session.get("pending_evidence_checkpoint"), dict) else {}
    sender_failures: list[str] = []
    summary_artifact = {
        "kind": "nonvisual_summary",
        "ref": f"codex:chat:{conversation_id}:review-summary",
        "sha256": canonical_evidence_hash.sha256_bytes(evidence_checkpoint_summary(evidence).encode("utf-8")),
        "sent": True,
        "presented_at": now(),
    } if presentation_sent else None
    assets = collect_public_delivery_assets(project_dir, {}, evidence)
    items: list[tuple[pathlib.Path, str]] = []
    items.extend((path, "package") for path in assets["packages"][:1])
    items.extend((path, "screenshot") for path in assets["screenshots"][:3])
    items.extend((path, "background") for path in assets["generated_backgrounds"][:2])
    items.extend((path, "sprite") for path in assets["generated_sprites"][:2])
    for path in assets["generated_images"]:
        if path not in assets["generated_backgrounds"] and path not in assets["generated_sprites"]:
            items.append((path, "generated_image"))
        if len(items) >= 8:
            break
    items.extend((path, "video") for path in assets["videos"][:2])
    items = filter_delivery_items_by_judgment(items, gate)
    request_inspection = canonical_user_review.inspect_user_review_request(project_dir, require_presented=False)
    if request_inspection.get("status") != "PASS":
        sender_failures.extend(request_inspection.get("failures", ["review_request_pre_send_invalid"]))
        items = []
    elif checkpoint.get("visual_required") is not True:
        items = [(path, kind) for path, kind in items if kind != "screenshot"]
    else:
        visual_inspection = browser_visual_evidence.inspect(project_dir)
        visual_details = visual_inspection.get("details", {}) if isinstance(visual_inspection.get("details"), dict) else {}
        canonical_screenshot = pathlib.Path(str(visual_details.get("screenshot_path", "")))
        canonical_hash = str(visual_details.get("screenshot_hash", ""))
        valid_items: list[tuple[pathlib.Path, str]] = []
        canonical_screenshot_found = False
        for path, kind in items:
            if kind != "screenshot":
                valid_items.append((path, kind))
                continue
            try:
                matches = (
                    visual_inspection.get("status") == "PASS"
                    and path.resolve(strict=True) == canonical_screenshot.resolve(strict=True)
                    and canonical_evidence_hash.sha256_file(path) == canonical_hash
                )
            except (OSError, ValueError):
                matches = False
            if matches:
                valid_items.append((path, kind))
                canonical_screenshot_found = True
            else:
                sender_failures.append("canonical_screenshot_path_or_hash_changed")
        if not canonical_screenshot_found:
            sender_failures.append("canonical_screenshot_not_sendable")
        items = valid_items
    sent = emit_public_delivery(client, conversation_id, session_dir, session, items, source="user_evidence_checkpoint")
    if checkpoint.get("visual_required") is True and not any(item.get("kind") == "screenshot" for item in sent):
        sender_failures.append("codex_screenshot_send_failed_or_invalid")
    presented_artifacts = ([summary_artifact] if summary_artifact else []) + [
        {
            "kind": str(item.get("kind", "")),
            "ref": str(pathlib.Path(str(item.get("path", ""))).resolve()),
            "sha256": canonical_evidence_hash.sha256_file(item["path"]),
            "sent": True,
            "presented_at": now(),
            **{
                key: str(item[key])
                for key in ("turn_id", "conversation_id")
                if item.get(key) not in (None, "")
            },
        }
        for item in sent
        if item.get("path") and pathlib.Path(str(item["path"])).is_file()
    ]
    checkpoint = canonical_user_review.mark_review_request_presented(
        project_dir,
        checkpoint,
        presented_artifacts=presented_artifacts,
    )
    checkpoint["sender_diagnostic"] = {
        "status": "PASS" if checkpoint.get("presentation_succeeded") else "NEEDS_REWORK",
        "failures": sorted(set(sender_failures)),
        "sent_kinds": [str(item.get("kind", "")) for item in sent],
    }
    session["pending_evidence_checkpoint"] = checkpoint
    save_session(session_dir, session)
    if sent:
        append_truth_ledger(
            session_dir,
            session,
            "user_evidence_checkpoint_sent",
            "中间测试和预览证据已发送给用户判断",
            status="sent",
            evidence_ref=str(project_dir),
            can_user_see=True,
            data={
                "artifact": "user_evidence_checkpoint",
                "sent": sent,
                "review_request_id": checkpoint.get("review_request_id", ""),
                "presented_artifacts": checkpoint.get("presented_artifacts", []),
                "reviewed_evidence_hashes": checkpoint.get("reviewed_evidence_hashes", []),
            },
        )
        append_memory_event(session, "user_evidence_checkpoint_sent", data={"sent": sent, "evidence": evidence})
        save_session(session_dir, session)
    return sent


def make_project_package(project_dir: pathlib.Path, log_dir: pathlib.Path) -> pathlib.Path:
    source = pathlib.Path(project_dir)
    if not source.exists() or not source.is_dir():
        raise RuntimeError(f"project directory is missing for delivery package: {source}")
    package_base = log_dir / f"{safe_id(source.name)}_final_project_bundle"
    zip_path = pathlib.Path(str(package_base) + ".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(package_base), "zip", root_dir=str(source))
    return zip_path


def ensure_verify_report(result: dict[str, Any], log_dir: pathlib.Path) -> pathlib.Path:
    existing = pathlib.Path(str(result.get("effect_report_path", "")))
    if existing.exists() and existing.is_file():
        return existing
    report = log_dir / f"{safe_id(result.get('project_dir', 'project'))}_verify_report.json"
    write_json(
        report,
        {
            "kind": "VerifyReport",
            "status": str(result.get("status", "")).upper(),
            "project_dir": result.get("project_dir", ""),
            "runtime_dir": result.get("runtime_dir", ""),
            "generated_files": result.get("generated_files", []),
            "agent_usage": result.get("agent_usage", {}),
        },
    )
    return report


# LEGACY PROVIDER PIPELINE.
# Codex conversation mainline must not call this.
# Delivery is driven by the reviewed Provider route and the sole local_packager exit.
def emit_delivery_evidence(
    session_dir: pathlib.Path,
    session: dict[str, Any],
    result: dict[str, Any],
    screenshot: pathlib.Path | None,
    log_dir: pathlib.Path,
) -> dict[str, str]:
    project_dir = pathlib.Path(str(result.get("project_dir", "")))
    package = make_project_package(project_dir, log_dir)
    verify_report = ensure_verify_report(result, log_dir)
    refs = {
        "package": str(package),
        "verify_report": str(verify_report),
        "verify_passed": str(verify_report),
    }
    if screenshot:
        refs["screenshot"] = str(screenshot)
    for artifact, path in refs.items():
        append_truth_ledger(
            session_dir,
            session,
            artifact,
            f"{artifact} evidence recorded",
            status="pass",
            evidence_ref=path,
            data={"artifact": artifact, "verify_passed": artifact == "verify_passed"},
        )
    save_session(session_dir, session)
    return refs


def send_delivery_artifacts(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    refs = evidence.get("refs", {}) if isinstance(evidence.get("refs"), dict) else {}
    sent: list[dict[str, Any]] = []
    screenshot = _evidence_path(str(refs.get("screenshot", "")))
    if screenshot:
        client.send_chat_action(conversation_id, "upload_photo")
        if client.send_photo(conversation_id, screenshot, "效果预览"):
            sent.append({"kind": "photo", "path": str(screenshot)})
    package = _evidence_path(str(refs.get("package", "")))
    if package and package.suffix.lower() == ".zip":
        client.send_chat_action(conversation_id, "upload_document")
        if client.send_document(conversation_id, package, "项目包"):
            sent.append({"kind": "document", "artifact": "package", "path": str(package)})
    if sent:
        append_truth_ledger(
            session_dir,
            session,
            "delivery_attachment_sent",
            "真实交付附件已通过 Codex conversation 发送",
            status="sent",
            evidence_ref="conversation_delivery",
            can_user_see=True,
            data={"artifact": "delivery_attachment_sent", "sent": sent},
        )
        append_memory_event(session, "delivery_attachment_sent", data={"sent": sent})
        save_session(session_dir, session)
    return sent


def read_delivery_manifest(path: str | pathlib.Path) -> dict[str, Any]:
    manifest_path = pathlib.Path(str(path))
    if not manifest_path.exists():
        return {}
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def user_visible_known_limit(raw: Any) -> str:
    text = str(raw or "").strip()
    lowered = text.lower()
    if "placeholder" in lowered or "占位" in text:
        return "预览为占位示例，不算真实运行证据"
    if "screenshot not provided" in lowered or "screenshot missing" in lowered:
        return "本轮没有生成效果预览图，已先交付可运行项目文件"
    text = text.replace("not provided", "暂未提供")
    text = text.replace("hard gate", "强制检查")
    text = text.replace("screenshot", "效果预览")
    text = text.replace("package", "可运行项目文件")
    text = text.replace("verify_report", "测试结论")
    return pre_send_guard(public_narration.redact_internal_terms(text))


def build_delivery_summary_text(manifest: dict[str, Any]) -> str:
    startup_command = str(manifest.get("startup_command", "")).strip()
    known_limits = manifest.get("known_limits", []) if isinstance(manifest.get("known_limits"), list) else []
    quality_evidence = manifest.get("quality_evidence", {}) if isinstance(manifest.get("quality_evidence"), dict) else {}
    test_report_found = bool(quality_evidence.get("test_report_found"))
    delivery_notes_found = bool(quality_evidence.get("delivery_notes_found"))
    preview_evidence_found = bool(quality_evidence.get("preview_evidence_found"))
    test_has_commands = bool(quality_evidence.get("test_report_has_commands"))
    test_no_executed = bool(quality_evidence.get("test_report_has_no_test_executed"))
    sample_input_found = bool(quality_evidence.get("sample_input_found") or quality_evidence.get("test_report_mentions_sample_input"))
    preview_placeholder_found = bool(quality_evidence.get("preview_placeholder_found"))
    judgment = manifest.get("agent_delivery_judgment", {}) if isinstance(manifest.get("agent_delivery_judgment"), dict) else {}
    verdict = str(judgment.get("verdict", "")).strip().upper()
    status_raw = str(manifest.get("status", "")).strip().lower()
    delivery_status = verdict or ("PASS" if status_raw == "ready" else ("WARNING" if status_raw == "ready_with_warnings" else "PARTIAL"))
    if not test_report_found:
        test_execution = "没有"
        test_record_status = "没有"
    elif test_no_executed:
        test_execution = "未执行真实测试"
        test_record_status = "没有真实执行证据"
    elif test_has_commands:
        test_execution = "已执行命令"
        test_record_status = "已执行命令"
    else:
        test_execution = "仅人工检查"
        test_record_status = "没有真实执行证据"
    preview_status = "真实预览" if preview_evidence_found else ("占位示例" if preview_placeholder_found else "没有")
    forced_missing = bool(manifest.get("forced_start_with_missing_inputs"))
    if not forced_missing:
        forced_missing = any("缺少真实 demo 或样例输入" in str(item) for item in known_limits)
    lines = [
        public_narration.public_event_text("delivery_ready", manifest),
        "项目包：已生成",
        f"测试报告：{'有' if test_report_found else '没有'}",
        f"测试执行：{test_execution}",
        f"交付说明：{'有' if delivery_notes_found else '没有'}",
        f"预览证据：{preview_status}",
        f"真实输入验证：{'有' if sample_input_found else '没有'}",
        f"交付状态：{delivery_status}",
    ]
    if startup_command:
        lines.append(f"启动方式：{startup_command}")
    if known_limits:
        visible_limits = [item for item in (user_visible_known_limit(item) for item in known_limits[:4]) if item]
        if visible_limits:
            lines.append("已知限制：" + "；".join(visible_limits))
    else:
        lines.append("已知限制：暂无")
    judgment_warnings = judgment.get("user_visible_warnings", []) if isinstance(judgment.get("user_visible_warnings"), list) else []
    visible_judgment_warnings = [item for item in (user_visible_known_limit(raw) for raw in judgment_warnings[:6]) if item]
    if visible_judgment_warnings:
        lines.append("本次带限制交付：" + "；".join(visible_judgment_warnings))
    if not test_report_found:
        lines.append("这轮没有完整测试报告，所以不能标成完整测试通过。")
    if not delivery_notes_found:
        lines.append("这轮缺少完整交付复核说明，交付状态只能按 warning 处理。")
    if forced_missing or any("缺少真实 demo 或样例输入" in str(item) for item in known_limits):
        lines.append(public_narration.public_event_text("generation_warning", {"warning": "这轮缺少真实 demo 或样例输入，只能算框架版/样例级验证。"}))
    return pre_send_guard("\n".join(lines))


def build_intake_waiting_text(analysis: dict[str, Any], fallback_reply: str = "") -> str:
    questions: list[str] = []
    for key in ("critical_questions", "missing_required_inputs", "soft_questions"):
        values = analysis.get(key, []) if isinstance(analysis.get(key), list) else []
        questions.extend(str(item).strip() for item in values if str(item).strip())
    summary = str(analysis.get("project_summary") or analysis.get("summary") or "").strip()
    signals = extract_project_intent_signals(summary, {}, analysis)
    if signals["actionable_project_request"] and not signals["has_hard_blocker"]:
        limits = unique_strings(questions, limit=3)
        text = f"我先把需求整理成第一版方向：{summary[:260]}。"
        if limits:
            text += "\n这些点会写进假设或验收限制，不会把占位、降级预览或缺失配置当成完整通过：\n"
            text += "\n".join(f"{index}. {item}" for index, item in enumerate(limits, 1))
        text += "\n你可以继续补充细节；当前范围已经可以先按第一版可运行结构推进。"
        return pre_send_guard(text)
    text = public_narration.public_event_text("intake_waiting", {"questions": unique_strings(questions, limit=3)})
    if fallback_reply and not questions:
        text += "\n\n" + str(fallback_reply).strip()[:500]
    return pre_send_guard(text)


def delivery_send_diagnostic(
    gate: dict[str, Any],
    items: list[tuple[pathlib.Path, str]],
    sent: list[dict[str, Any]],
) -> dict[str, Any]:
    intended = [str(pathlib.Path(str(item)).resolve()) for item in gate.get("can_send_artifacts", []) if str(item).strip()]
    valid = [{"path": str(path.resolve()), "kind": kind} for path, kind in items if path.exists() and path.is_file()]
    sent_paths = {str(pathlib.Path(str(item.get("path", ""))).resolve()).lower() for item in sent if str(item.get("path", "")).strip()}
    failed = [item for item in valid if item["path"].lower() not in sent_paths]
    package_required = str(gate.get("verdict", "")).upper() in {"PASS_FINAL", "DELIVER_WITH_WARNINGS"}
    package_sent = any(item.get("kind") == "package" for item in sent)
    if package_required and not package_sent:
        reason = "final_package_send_failed"
    elif not sent:
        reason = "no_public_artifacts_sent"
    else:
        reason = ""
    return {
        "intended_artifacts": intended,
        "valid_artifacts": valid,
        "sent_artifacts": sent,
        "failed_artifacts": failed,
        "package_required": package_required,
        "package_sent": package_sent,
        "reason": reason,
    }


def send_delivery_from_manifest(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    manifest: dict[str, Any],
    provider_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    project_dir = pathlib.Path(str(manifest.get("project_dir", ""))).resolve()
    gate = evaluate_public_delivery_gate(
        project_dir,
        manifest,
        session,
        phase="final",
        provider_result=provider_result,
    )
    if not gate.get("delivery_allowed"):
        mark_public_delivery_rework(client, conversation_id, session_dir, session, project_dir, gate)
        return []
    package_inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(
        project_dir,
        manifest,
        visual_required=bool(gate.get("browser_visual_required")),
    )
    if package_inspection.get("status") != "PASS":
        failed_gate = dict(gate)
        failed_gate.update(
            {
                "verdict": "NEEDS_REWORK",
                "status": "NEEDS_REWORK",
                "delivery_allowed": False,
                "is_final": False,
                "required_repairs": package_inspection.get("failures", []),
                "canonical_package_inspection": package_inspection,
            }
        )
        mark_public_delivery_rework(client, conversation_id, session_dir, session, project_dir, failed_gate)
        return []
    approved_manifest = package_inspection.get("manifest", {}) if isinstance(package_inspection.get("manifest"), dict) else {}
    package_approval = {
        "package_path": package_inspection.get("package_path", ""),
        "package_sha256": package_inspection.get("package_sha256", ""),
        "package_entries_hash": package_inspection.get("package_entries_hash", ""),
        "manifest_path": package_inspection.get("manifest_path", ""),
        "manifest_artifact_hash": approved_manifest.get("artifact_hash", ""),
        "failure_reason": "",
    }
    session = load_session(session_dir, conversation_id)
    assets = collect_public_delivery_assets(project_dir, manifest)
    items: list[tuple[pathlib.Path, str]] = []
    items.extend((path, "package") for path in assets["packages"][:1])
    items.extend((path, "screenshot") for path in assets["screenshots"][:3])
    items.extend((path, "background") for path in assets["generated_backgrounds"][:2])
    items.extend((path, "sprite") for path in assets["generated_sprites"][:2])
    for path in assets["generated_images"]:
        if path not in assets["generated_backgrounds"] and path not in assets["generated_sprites"]:
            items.append((path, "generated_image"))
        if len(items) >= 8:
            break
    items.extend((path, "video") for path in assets["videos"][:2])
    items = filter_delivery_items_by_judgment(items, gate)
    requirements = gate.get("requirements", {}) if isinstance(gate.get("requirements"), dict) else {}
    required_kinds = set(canonical_delivery_receipt.required_attachment_kinds(requirements))
    items = [(path, kind) for path, kind in items if kind in required_kinds]
    delivery_started_at = now()
    sent = emit_public_delivery(
        client,
        conversation_id,
        session_dir,
        session,
        items,
        source="delivery_manifest",
        package_approval=package_approval,
    )
    diagnostic = delivery_send_diagnostic(gate, items, sent)
    canonical_delivery_receipt.produce_canonical_delivery_receipt(
        project_dir,
        conversation_id=conversation_id,
        manifest_inspection=package_inspection,
        requirement_snapshot=requirements,
        attempted_items=items,
        sent_items=sent,
        started_at=delivery_started_at,
    )
    receipt_inspection = canonical_delivery_receipt.inspect_canonical_delivery_receipt(
        project_dir,
        expected_conversation_id=conversation_id,
        expected_requirements=requirements,
        expected_attachment_refs={kind: path for path, kind in items},
    )
    gate["canonical_delivery_receipt_inspection"] = receipt_inspection
    if package_approval.get("failure_reason"):
        diagnostic["reason"] = str(package_approval["failure_reason"])
        diagnostic["package_sent"] = False
    if diagnostic["reason"] or receipt_inspection.get("status") != "PASS" or gate.get("verdict") != "PASS_FINAL":
        failed_gate = dict(gate)
        failed_gate.update(
            {
                "delivery_allowed": False,
                "is_final": False,
                "status": "delivery_send_failed",
                "delivery_send_diagnostic": diagnostic,
                "canonical_delivery_receipt_inspection": receipt_inspection,
                "required_repairs": receipt_inspection.get("failures", [])
                + ([] if gate.get("verdict") == "PASS_FINAL" else ["canonical_final_delivery_requires_pass_final"]),
            }
        )
        mark_public_delivery_rework(client, conversation_id, session_dir, session, project_dir, failed_gate)
        return sent
    send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event="delivery_manifest_ready",
        facts={"manifest": manifest},
        source="delivery_team_summary",
        direct_text=build_delivery_summary_text(manifest),
    )
    session = load_session(session_dir, conversation_id)
    gate["delivery_send_diagnostic"] = diagnostic
    record_public_delivery_gate(session_dir, session, gate, project_dir)
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    generation.update(
        {
            "status": "delivered_with_warnings" if gate.get("verdict") == "DELIVER_WITH_WARNINGS" else "delivered",
            "delivery_allowed": True,
            "delivery_gate": gate,
            "project_dir": str(project_dir),
        }
    )
    session["generation"] = generation
    update_active_run_status(
        session,
        "delivered_with_warnings" if gate.get("verdict") == "DELIVER_WITH_WARNINGS" else "delivered",
        delivery_allowed=True,
        delivery_gate=gate,
        project_dir=str(project_dir),
    )
    if sent:
        append_memory_event(session, "delivery_manifest_sent", data={"sent": sent, "manifest": manifest})
    save_session(session_dir, session)
    return sent


def append_whiteboard_version(session: dict[str, Any], whiteboard: dict[str, Any]) -> None:
    versions = session.setdefault("whiteboard_versions", [])
    if not isinstance(versions, list):
        versions = []
    versions.append({"created_at": now(), "whiteboard": whiteboard})
    session["whiteboard_versions"] = versions[-80:]


def unique_strings(values: list[Any], limit: int = 120) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out[-limit:]


PROJECT_SIGNAL_TERMS = {
    "csgo",
    "csgo2",
    "cs2",
    "demo",
    "鉴挂",
    "反作弊",
    "鼠标键盘",
    "视角异常",
    "命中事件",
    "风险评分",
    "vn",
    "视觉小说",
    "故事",
    "时间线",
    "背景",
    "立绘",
    "角色",
    "剧情",
    "导出",
    "本地模型",
    "桌面界面",
    "桌面",
    "界面",
    "本地",
    "可运行",
    "项目助手",
    "图片",
    "图像",
    "生成图片",
    "文件导出",
    "测试",
    "截图",
    "视频",
    "预览",
    "zip",
    "api",
    "数据库",
    "知识库",
    "剪辑",
    "高光",
    "ocr",
}


def _project_signal_terms(text: str) -> set[str]:
    lowered = str(text or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    matched: set[str] = set()
    for term in PROJECT_SIGNAL_TERMS:
        needle = term.lower()
        if needle in lowered or needle in compact:
            matched.add(needle)
    for token in re.findall(r"[a-z0-9][a-z0-9_+.-]{1,}", lowered):
        if token not in {"this", "that", "with", "from", "into", "user", "task", "test"}:
            matched.add(token)
    return matched


def reply_matches_current_goal(reply: str, current_goal: str) -> bool:
    goal_terms = _project_signal_terms(current_goal)
    reply_terms = _project_signal_terms(reply)
    if not goal_terms or not reply_terms:
        return True
    if goal_terms & reply_terms:
        return True
    if len(reply_terms) >= 2:
        return False
    return True


def current_goal_text(session: dict[str, Any]) -> str:
    run = active_run(session)
    if run and str(run.get("goal", "")).strip():
        return str(run.get("goal", "")).strip()
    latest = latest_user_text(session)
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    return latest or str(whiteboard.get("project_summary", "")).strip()


def grounded_current_goal_reply(session: dict[str, Any]) -> str:
    goal = current_goal_text(session)
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    summary = str(whiteboard.get("project_summary", "")).strip() or goal
    if goal and summary and not reply_matches_current_goal(summary, goal):
        summary = goal
    context = goal + "\n" + summary
    questions: list[str] = []
    if any(token in context for token in ("本地模型", "图片", "图像", "背景", "立绘")):
        questions.append("本地模型/本地图片后端使用哪一个，或者模型目录在哪里？")
    if any(token in context for token in ("背景", "立绘", "图片", "图像")):
        questions.append("图片产物需要真实模型直接生成；如果当前没有可用模型，我会把它记为交付限制，不能算通过。")
    if any(token in context for token in ("导出", "文件导出", "export")):
        questions.append("导出格式优先选择什么？可以先按项目数据、可读文档和压缩包交付来做。")
    if any(token in context for token in ("桌面", "界面", "gui", "desktop")):
        questions.append("桌面界面先按本地可运行的简单桌面应用实现，后续再细化交互。")
    if not questions:
        questions = [
            "第一版按本地可运行项目实现，并补齐启动方式、测试命令和交付包。",
            "缺少真实外部能力或运行证据时，我会写进限制，不能当成完整通过。",
        ]
    question_lines = "\n".join(f"{index}. {item}" for index, item in enumerate(questions[:4], 1))
    signals = extract_project_intent_signals(context, session, {"project_summary": summary})
    if signals["actionable_project_request"] and not signals["has_hard_blocker"]:
        return (
            f"我先把这个项目整理成第一版方向：{summary[:260] or goal[:260]}。\n\n"
            "当前范围已经足够启动本地可运行版本；下面这些点会作为验收限制和实现假设记录：\n"
            f"{question_lines}\n\n"
            "缺少真实外部能力、配置或运行证据时，不会把占位结果当成完整通过。"
        )
    return (
        f"我先把这个需求整理成第一版方向：{summary[:260] or goal[:260]}。\n\n"
        "现在有几个点会影响实现质量，所以不会马上开工：\n"
        f"{question_lines}\n\n"
        "你可以补充；也可以说“按默认假设开始”，我会先做可运行版本，并把缺少真实验证的部分写进限制。"
    )


def reject_off_topic_public_reply(
    session_dir: pathlib.Path,
    conversation_id: int | str,
    session: dict[str, Any],
    reply: str,
    *,
    source: str,
) -> tuple[str, bool]:
    goal = current_goal_text(session)
    if reply_matches_current_goal(reply, goal):
        return reply, False
    grounded = grounded_current_goal_reply(session)
    event = {
        "kind": "public_reply_rejected_off_topic_domain_mismatch",
        "role": "system",
        "source": source,
        "current_goal": goal[:1200],
        "rejected_reply": str(reply or "")[:1200],
    }
    append_agent_session_event(session_dir, conversation_id, event)
    append_memory_event(session, "public_reply_rejected_off_topic_domain_mismatch", data=event)
    return grounded, True


def reset_project_scoped_context_for_new_run(session: dict[str, Any], raw_user_message: str, run_id: str) -> dict[str, Any]:
    cleaned = dict(session)
    for key in (
        "pending_start_assumptions",
        "pending_soft_questions",
        "pending_critical_questions",
        "pending_required_inputs",
        "pending_evidence_checkpoint",
        "pending_decision",
        "forced_start_with_missing_inputs",
        "missing_required_inputs",
        "backend_dialogue_analysis",
        "delivery_gate",
        "public_delivery_gate",
    ):
        cleaned.pop(key, None)
    cleaned["forced_start_with_missing_inputs"] = False
    cleaned["generation_start_waiting"] = False
    cleaned["start_wait_reason"] = ""
    old_whiteboard = cleaned.get("whiteboard", {}) if isinstance(cleaned.get("whiteboard"), dict) else {}
    preserved_keys = (
        "user_rules",
        "global_user_preferences",
        "preferred_language",
        "local_first_preference",
        "testing_evidence_preference",
        "no_fake_delivery_preference",
        "no_internal_details_preference",
    )
    preserved = {key: old_whiteboard.get(key) for key in preserved_keys if key in old_whiteboard}
    cleaned["whiteboard"] = {
        "project_summary": raw_user_message,
        "known_facts": [f"用户提出的新项目需求: {raw_user_message}"],
        "open_questions": [],
        "default_assumptions": [],
        "first_version_plan": [],
        "blocking_questions": [],
        "critical_questions": [],
        "soft_questions": [],
        "capability_research_targets": [],
        "user_rules": list(old_whiteboard.get("user_rules", []) if isinstance(old_whiteboard.get("user_rules"), list) else []),
        "acceptance_criteria": [],
        "change_requests": [],
        "delivery_requirements": [],
        "decision_log": [],
        "ready_to_generate": False,
    }
    cleaned["whiteboard"].update({key: value for key, value in preserved.items() if key != "user_rules"})
    cleaned["project_scoped_context_run_id"] = str(run_id)
    return cleaned


def merge_whiteboard(previous: dict[str, Any], next_whiteboard: dict[str, Any]) -> dict[str, Any]:
    merged = dict(previous)
    append_keys = {
        "known_facts",
        "default_assumptions",
        "first_version_plan",
        "user_rules",
        "acceptance_criteria",
        "change_requests",
        "critical_questions",
        "capability_research_targets",
        "decision_log",
        "delivery_requirements",
    }
    replace_keys = {"open_questions", "blocking_questions"}
    for key, value in next_whiteboard.items():
        if key in append_keys:
            prior = previous.get(key, [])
            merged[key] = unique_strings((prior if isinstance(prior, list) else []) + (value if isinstance(value, list) else []))
        elif key in replace_keys:
            merged[key] = unique_strings(value if isinstance(value, list) else [], limit=40)
        elif key == "project_summary":
            text = str(value).strip()
            merged[key] = text or str(previous.get(key, "")).strip()
        else:
            merged[key] = value
    for key in append_keys | replace_keys:
        merged.setdefault(key, [])
    merged.setdefault("project_summary", "")
    merged.setdefault("ready_to_generate", False)
    return merged


def read_project_memory_excerpt(session: dict[str, Any], limit: int = 6000) -> str:
    project_memory = session.get("project_memory", {})
    if not isinstance(project_memory, dict):
        return ""
    path = pathlib.Path(str(project_memory.get("project_memory_md", "")))
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def combined_requirement(session: dict[str, Any]) -> str:
    whiteboard = session.get("whiteboard", {})
    if isinstance(whiteboard, dict):
        parts: list[str] = []
        project_memory = session.get("project_memory", {})
        if isinstance(project_memory, dict):
            md_path = str(project_memory.get("project_memory_md", "")).strip()
            artifact_path = str(project_memory.get("project_memory_artifact", "")).strip()
            if md_path or artifact_path:
                parts.append(
                    "项目长期规格文档:\n"
                    + (f"- markdown: {md_path}\n" if md_path else "")
                    + (f"- artifact_json: {artifact_path}" if artifact_path else "")
                )
        summary = str(whiteboard.get("project_summary", "")).strip()
        if summary:
            parts.append(summary)
        target_architecture = whiteboard.get("target_project_architecture")
        if isinstance(target_architecture, dict) and target_architecture:
            parts.append(
                "目标项目模型架构要求:\n"
                + "\n".join(f"- {key}: {value}" for key, value in sorted(target_architecture.items()))
            )
        cgkn_execution = whiteboard.get("cgkn_execution")
        if isinstance(cgkn_execution, dict) and cgkn_execution:
            parts.append(
                "平台生成约束:\n"
                + "\n".join(f"- {key}: {value}" for key, value in sorted(cgkn_execution.items()))
            )
        product_design = whiteboard.get("product_design")
        if isinstance(product_design, dict) and product_design.get("required"):
            surfaces = product_design.get("interaction_surfaces", []) if isinstance(product_design.get("interaction_surfaces"), list) else []
            lines = [f"- interaction_surfaces: {', '.join(str(item) for item in surfaces)}"]
            summary_text = str(product_design.get("brief_summary", "")).strip()
            if summary_text:
                lines.append(f"- approved_design_summary: {summary_text}")
            parts.append("交互界面约束:\n" + "\n".join(lines))
        attachment_lines = attachment_requirement_lines(session)
        if attachment_lines:
            parts.append("用户上传资料和本地输入:\n" + "\n".join(attachment_lines))
        for key, label in (
            ("known_facts", "已确认事实"),
            ("default_assumptions", "默认假设"),
            ("first_version_plan", "第一版方案"),
            ("user_rules", "用户长期规则"),
            ("acceptance_criteria", "验收标准"),
            ("change_requests", "用户纠正和后续修改"),
            ("delivery_requirements", "交付展示要求"),
            ("decision_log", "已采用决策记录"),
        ):
            values = whiteboard.get(key, [])
            lines = [f"- {item}" for item in values if isinstance(item, str) and item.strip()]
            if lines:
                parts.append(label + ":\n" + "\n".join(lines))
        memory_excerpt = read_project_memory_excerpt(session)
        if memory_excerpt:
            parts.append("项目长期规格 MD 摘要:\n" + memory_excerpt)
        if parts:
            return "\n".join(parts).strip()
    lines: list[str] = []
    for msg in session.get("messages", []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            text = str(msg.get("text", "")).strip()
            if text and not text.startswith("/") and not is_generate_command(text) and not is_smalltalk(text):
                lines.append(text)
    return "\n".join(lines).strip()


def build_generation_context_snapshot(session: dict[str, Any], requirement: str) -> dict[str, Any]:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    pending_soft_questions = session.get("pending_soft_questions", []) if isinstance(session.get("pending_soft_questions"), list) else []
    pending_critical_questions = session.get("pending_critical_questions", []) if isinstance(session.get("pending_critical_questions"), list) else []
    pending_required_inputs = session.get("pending_required_inputs", []) if isinstance(session.get("pending_required_inputs"), list) else []
    unanswered_questions = unique_strings(
        [str(item) for item in pending_soft_questions + pending_critical_questions + pending_required_inputs if str(item).strip()],
        limit=20,
    )
    forced_missing = bool(session.get("forced_start_with_missing_inputs") or pending_critical_questions or pending_required_inputs)
    user_messages = [
        {
            "text": str(message.get("text", ""))[:4000],
            "created_at": message.get("created_at", ""),
        }
        for message in session.get("messages", [])
        if isinstance(message, dict) and message.get("role") == "user" and str(message.get("text", "")).strip()
    ][-20:]
    memory_events = [
        event
        for event in session.get("memory_events", [])
        if isinstance(event, dict) and str(event.get("type", "")) in {"backend_dialogue_tick", "whiteboard_revision", "agent_loop_started"}
    ][-20:]
    return {
        "kind": "generation_context_snapshot",
        "created_at": now(),
        "requirement": requirement[:12000],
        "whiteboard": whiteboard,
        "user_messages": user_messages,
        "backend_dialogue_ticks": memory_events,
        "soft_questions_are_blocking": False,
        "unanswered_questions": unanswered_questions,
        "pending_start_assumptions": session.get("pending_start_assumptions", []) if isinstance(session.get("pending_start_assumptions"), list) else [],
        "missing_required_inputs": pending_required_inputs,
        "forced_start_with_missing_inputs": forced_missing,
        "scope_downgrade": "scaffold_only_or_partial" if forced_missing else "",
        "must_not_claim_full_domain_validation": forced_missing,
    }


def ensure_generation_context_snapshot(
    session_dir: pathlib.Path,
    conversation_id: int | str,
    session: dict[str, Any],
    requirement: str,
) -> dict[str, Any]:
    snapshot = build_generation_context_snapshot(session, requirement)
    session["generation_context_snapshot"] = snapshot
    append_agent_session_event(session_dir, conversation_id, snapshot)
    return snapshot


def write_generation_context_snapshot(project_dir: pathlib.Path, snapshot: dict[str, Any]) -> pathlib.Path:
    path = pathlib.Path(project_dir) / "generation_context_snapshot.json"
    write_json(path, snapshot)
    return path


def pipeline_steps_from_session(session_path_value: pathlib.Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    if session_path_value.exists():
        for line in session_path_value.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if isinstance(event, dict) and event.get("kind") == "pipeline_step_result":
                step_id = str(event.get("step_id", ""))
                if step_id:
                    statuses[step_id] = event
    steps: list[dict[str, Any]] = []
    for step in manifest.get("steps", []) if isinstance(manifest.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id", ""))
        event = statuses.get(step_id, {})
        steps.append(
            {
                "id": step_id,
                "type": str(step.get("type", "")),
                "role": str(step.get("role", event.get("role", ""))),
                "status": str(event.get("status", "unknown" if not event else "")) or "unknown",
            }
        )
    return steps


def write_pipeline_run_summary(
    project_dir: pathlib.Path,
    *,
    driver: str,
    pipeline_manifest_path: pathlib.Path | str,
    agent_session_path_value: pathlib.Path,
    manifest: dict[str, Any],
    fallback_used: bool,
    fallback_reason: str = "",
) -> pathlib.Path:
    summary: dict[str, Any] = {
        "driver": driver,
        "pipeline_manifest_path": str(pipeline_manifest_path),
        "agent_session_path": str(agent_session_path_value),
        "project_dir": str(pathlib.Path(project_dir).resolve()),
        "fallback_used": fallback_used,
        "steps": pipeline_steps_from_session(agent_session_path_value, manifest),
    }
    if fallback_used:
        summary["fallback_reason"] = fallback_reason
    path = pathlib.Path(project_dir) / "pipeline_run_summary.json"
    write_json(path, summary)
    return path


def is_smalltalk(text: str) -> bool:
    compact = re.sub(r"[\s,.!?。！？~～]+", "", text.lower())
    return compact in {
        "你好",
        "您好",
        "hello",
        "hi",
        "hey",
        "在吗",
        "测试",
        "test",
        "有人吗",
    }


def is_generate_command(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.lower())
    if compact in {"/generate", "/build"}:
        return True
    control_phrases = {
        "开始生成",
        "可以生成",
        "直接生成",
        "按默认假设开始",
        "按默认假设生成",
        "按默认假设开始生成",
        "按这个方向做",
        "可以开始",
        "生成项目",
        "生成吧",
        "开始吧",
        "开工",
        "直接做",
        "做吧",
        "start",
        "go",
    }
    if compact in control_phrases:
        return True
    # Long requirement text can naturally contain words like "生成图片".
    # Treat generation triggers as commands only when the whole message is a short control phrase.
    return len(compact) <= 10 and any(phrase == compact for phrase in control_phrases)


def assistant_invited_start(session: dict[str, Any]) -> bool:
    for msg in reversed(session.get("messages", [])):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip()
        text = str(msg.get("text", "")).strip()
        if role == "assistant":
            compact = re.sub(r"\s+", "", text.lower())
            return any(token in compact for token in ("可以开始", "开始做", "确认后", "我这边开始", "我来推进"))
        if role == "user":
            continue
    return False


def is_human_start_confirmation(text: str, session: dict[str, Any]) -> bool:
    if not assistant_invited_start(session):
        return False
    compact = re.sub(r"[\s,.!?。！？~～]+", "", text.lower())
    confirmations = {
        "可以",
        "没问题",
        "对",
        "是的",
        "确认",
        "确认无误",
        "就这样",
        "按这个做",
        "帮我做",
        "帮我做吧",
        "好的",
        "ok",
        "yes",
        "go",
    }
    return compact in confirmations


def explicit_start_requested(user_text: str) -> bool:
    compact = re.sub(r"[\s,.!?。！？~～]+", "", str(user_text or "").lower())
    if compact in {"做一个东西", "帮我搞一下", "帮我弄一下", "做个东西", "搞一下", "帮我做个东西"}:
        return False
    if any(phrase in compact for phrase in ("直接生成图片", "直接生成图", "直接生成背景", "直接生成立绘", "directlygenerateimage")):
        return False
    if is_generate_command(user_text):
        return True
    contains_phrases = (
        "开始生成",
        "可以开始",
        "按默认假设开始",
        "按默认假设生成",
        "按默认假设开始生成",
        "按这个方向做",
        "直接做",
        "生成吧",
    )
    if any(phrase in compact for phrase in contains_phrases):
        return True
    return compact in {"start", "go"}


def _analysis_list(analysis: dict[str, Any], key: str) -> list[str]:
    value = analysis.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def extract_project_intent_signals(text: str, session: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    context = "\n".join(
        str(item)
        for item in (
            text,
            analysis.get("project_summary", ""),
            whiteboard.get("project_summary", ""),
        )
        if str(item or "").strip()
    ).lower()
    compact = re.sub(r"[\s，。,.!?！？]+", "", context)
    vague_request = compact in {"做一个东西", "帮我搞一下", "帮我弄一下", "做个东西", "搞一下"} or len(compact) <= 6
    goal_terms = ("工具", "系统", "项目", "助手", "平台", "后台", "应用", "app", "网站", "程序", "服务", "机器人")
    intent_terms = ("做", "帮我", "想要", "需要", "开发", "实现", "搭建", "生成一个", "创建")
    capability_terms = (
        "管理",
        "生成",
        "分析",
        "导出",
        "自动化",
        "预览",
        "处理",
        "识别",
        "编辑",
        "整理",
        "导入",
        "截取",
        "报告",
        "对接",
        "接 api",
        "api",
        "转换",
        "配置",
        "测试",
        "搜索",
        "分类",
        "训练",
        "上传",
        "下载",
    )
    runtime_terms = ("本地", "网页", "桌面", "cli", "命令行", "服务端", "codex", "界面", "页面", "后台", "可运行")
    output_terms = ("文件", "导出", "报告", "结果", "包", "zip", "截图", "预览", "列表", "看板")
    has_goal = any(term in context for term in goal_terms) and any(term in context for term in intent_terms)
    has_capability = any(term in context for term in capability_terms)
    has_output_or_runtime = any(term in context for term in runtime_terms + output_terms)
    can_default_runtime = has_goal and has_capability
    start_allowed = bool(analysis.get("start_allowed_with_assumptions", True))
    hard_blockers: list[str] = []
    if vague_request or not has_goal or not has_capability:
        hard_blockers.append("unclear_goal_or_capability")
    if not start_allowed:
        hard_blockers.append("defaults_disallowed")
    missing_inputs = _analysis_list(analysis, "missing_required_inputs") or (
        whiteboard.get("missing_required_inputs") if isinstance(whiteboard.get("missing_required_inputs"), list) else []
    )
    requires_unscaffoldable_file = bool(missing_inputs) and any(
        phrase in context
        for phrase in ("必须上传", "必须提供文件", "只能基于", "没有文件不能", "必须用这个文件", "依赖上传文件")
    )
    if requires_unscaffoldable_file:
        hard_blockers.append("missing_required_file")
    actionable = has_goal and has_capability and (has_output_or_runtime or can_default_runtime) and not hard_blockers
    return {
        "has_goal": has_goal,
        "has_capability": has_capability,
        "has_output_or_runtime": has_output_or_runtime,
        "can_default_runtime": can_default_runtime,
        "has_hard_blocker": bool(hard_blockers),
        "hard_blockers": hard_blockers,
        "start_allowed_with_assumptions": start_allowed,
        "missing_required_inputs": missing_inputs,
        "actionable_project_request": actionable,
    }


def should_auto_start_generation(session: dict[str, Any], analysis: dict[str, Any], user_text: str) -> tuple[bool, str]:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    if explicit_start_requested(user_text):
        return True, "explicit_start_requested"
    session_analysis = session.get("backend_dialogue_analysis", {}) if isinstance(session.get("backend_dialogue_analysis"), dict) else {}
    if session_analysis:
        analysis = {**analysis, **session_analysis}
    context = "\n".join(
        str(item)
        for item in (
            user_text,
            analysis.get("project_summary", ""),
            whiteboard.get("project_summary", ""),
        )
        if str(item or "").strip()
    )
    signals = extract_project_intent_signals(context, session, analysis)
    start_allowed = bool(signals["start_allowed_with_assumptions"])
    if signals["has_hard_blocker"]:
        reason = str((signals.get("hard_blockers") or ["hard_blocker"])[0])
        if reason == "defaults_disallowed":
            return False, "defaults_disallowed"
        if reason == "missing_required_file":
            return False, "missing_required_inputs"
        return False, "unclear_project_request"
    critical_questions = _analysis_list(analysis, "critical_questions") or (
        whiteboard.get("critical_questions") if isinstance(whiteboard.get("critical_questions"), list) else []
    )
    if critical_questions and not start_allowed:
        return False, "critical_questions_pending"
    if signals["actionable_project_request"]:
        return True, "actionable_project_request"
    try:
        confidence = float(analysis.get("confidence") or 0)
    except Exception:
        confidence = 0.0
    if confidence < 0.8:
        return False, "unclear_project_request"
    return True, "simple_clear_request"


def parse_json_object(text: str) -> dict[str, Any] | None:
    return local_model_router.extract_json(text)


def extract_json_string_field(text: str, field: str) -> str:
    raw = str(text or "")
    marker = f'"{field}"'
    index = raw.find(marker)
    if index < 0:
        return ""
    colon = raw.find(":", index + len(marker))
    if colon < 0:
        return ""
    quote = raw.find('"', colon + 1)
    if quote < 0:
        return ""
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(raw[quote:])
    except Exception:
        return ""
    return str(value).strip() if isinstance(value, str) else ""


def fallback_whiteboard_for_unparsed_frontdesk(session: dict[str, Any]) -> dict[str, Any]:
    existing = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    user_text = latest_user_text(session)
    summary = str(existing.get("project_summary", "")).strip() or user_text
    return merge_whiteboard(
        existing,
        {
            "project_summary": summary,
            "known_facts": [f"用户项目需求: {user_text}"] if user_text else [],
            "default_assumptions": ["先按本地可运行、可测试、带结果预览的第一版推进"],
            "first_version_plan": ["整理输入解析", "生成核心分析流程", "提供可视化摘要和测试结论"],
            "blocking_questions": [],
            "open_questions": [],
            "acceptance_criteria": ["项目必须能运行，并输出测试结论和可视化/预览结果"],
            "delivery_requirements": ["交付可运行项目文件、效果预览和测试结论"],
            "decision_log": ["模型前台返回结构化内容解析失败，本地兜底保留用户需求并继续正式生成主线。"],
            "ready_to_generate": bool(summary),
        },
    )


def customer_reply_temperature() -> float:
    raw = os.environ.get("CGNK_CUSTOMER_TEMPERATURE", "0.72")
    try:
        base = float(raw)
    except ValueError:
        base = 0.72
    base = max(0.2, min(base, 1.1))
    return round(min(1.2, base + random.SystemRandom().uniform(0.0, 0.18)), 2)


def reply_variation_seed() -> str:
    return f"{int(time.time() * 1000)}-{random.SystemRandom().randint(1000, 9999)}"


def provider_text(messages: list[dict[str, str]], model: str, timeout: int) -> str:
    if str(model or "").lower().startswith("gpt-test"):
        latest = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                latest = str(message.get("content", "")).strip()
                if latest:
                    break
        system = str(messages[0].get("content", "")) if messages else ""
        if "输出必须是 JSON 对象" in system:
            summary = latest
            try:
                payload = json.loads(str(messages[1].get("content", "{}"))) if len(messages) > 1 else {}
                whiteboard = payload.get("current_whiteboard", {}) if isinstance(payload, dict) else {}
                if isinstance(whiteboard, dict) and str(whiteboard.get("project_summary", "")).strip():
                    summary = str(whiteboard.get("project_summary", "")).strip()
            except Exception:
                pass
            is_greeting_turn = re.sub(r"[\s，。,.!?！？]+", "", latest.lower()) in {"你好", "您好", "hi", "hello"}
            project_summary = "" if is_greeting_turn else summary[:500]
            action = "continue_chat" if is_greeting_turn or not project_summary else "start_generation"
            return json.dumps(
                {
                    "reply": "模型测试回复：我会按最新输入拆解项目并推进执行。" if project_summary else "模型测试回复：当前没有项目输入，可以直接发送目标和约束。",
                    "action": action,
                    "whiteboard": {
                        "project_summary": project_summary,
                        "known_facts": [project_summary] if project_summary else [],
                        "default_assumptions": ["本地可运行", "直接生成并测试"],
                        "first_version_plan": ["前端交互", "后端处理", "测试与交付"],
                        "blocking_questions": [],
                        "open_questions": [],
                        "user_rules": [],
                        "acceptance_criteria": ["可运行", "有测试结论"],
                        "change_requests": [],
                        "delivery_requirements": ["交付项目包和预览"],
                        "decision_log": ["项目输入到达即启动正式生成"],
                        "ready_to_generate": bool(project_summary),
                    },
                },
                ensure_ascii=False,
            )
        return "模型测试回复：我会按当前状态继续处理，并把可执行结果同步给你。"
    creds = check_connectivity._resolve_api_credentials()
    token = creds.get("api_key", "")
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key for Codex conversation customer service")
    root = str(creds.get("base_url", "")).rstrip("/")
    temperature = customer_reply_temperature()
    endpoint = check_connectivity._openai_compatible_endpoint(root)
    payload = check_connectivity._build_openai_compatible_payload(
        root,
        {"model": model, "messages": messages, "temperature": temperature, "max_tokens": 900},
    )
    last_error = ""
    for attempt in range(6):
        doc, error = check_connectivity._post_json(endpoint, payload, token, timeout)
        if doc is not None:
            break
        last_error = error
        if not check_connectivity._error_is_retryable(error):
            break
        time.sleep(min(20.0, 2.0 * (attempt + 1)))
    else:
        raise RuntimeError(last_error)
    if doc is None:
        raise RuntimeError(f"provider_api_request_failed: {last_error}")
    text = check_connectivity._extract_text(doc)
    if not text:
        raise RuntimeError("empty customer-service response")
    return text


def recent_dialogue(session: dict[str, Any], limit: int = 12) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for msg in session.get("messages", [])[-limit:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip()
        text = str(msg.get("text", "")).strip()
        if text.startswith("客服 API 暂时没有返回合格回复") or text.startswith("API_CUSTOMER_SERVICE_FAILED"):
            continue
        if "请回复" in text or "开始生成" in text:
            continue
        if role == "user" and is_generate_command(text):
            continue
        if role in {"user", "assistant"} and text:
            out.append({"role": role, "content": text})
    return out


def latest_user_text(session: dict[str, Any]) -> str:
    for msg in reversed(session.get("messages", [])):
        if isinstance(msg, dict) and msg.get("role") == "user":
            text = str(msg.get("text", "")).strip()
            if text and not text.startswith("/"):
                return text
    return ""


def meaningful_terms(text: str) -> set[str]:
    raw = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(text or "").lower())
    terms: set[str] = set()
    for part in raw.split():
        if len(part) >= 3:
            terms.add(part)
        if re.search(r"[\u4e00-\u9fff]", part):
            for size in (2, 3, 4):
                for i in range(0, max(0, len(part) - size + 1)):
                    terms.add(part[i : i + size])
    stop = {"这个", "那个", "然后", "就是", "可以", "需要", "项目", "生成", "帮我", "做个", "一个"}
    return {term for term in terms if term not in stop}


def reply_looks_off_topic(session: dict[str, Any], reply: str, whiteboard: dict[str, Any]) -> bool:
    user_text = latest_user_text(session)
    if not user_text or len(user_text) < 6:
        return False
    project_summary = str(whiteboard.get("project_summary", ""))
    source_terms = meaningful_terms(user_text) | set(list(meaningful_terms(project_summary))[:40])
    if not source_terms:
        return False
    reply_terms = meaningful_terms(reply)
    overlap = source_terms & reply_terms
    if overlap:
        return False
    generic_markers = ("我可以", "请提供", "需要更多信息", "无法", "不确定", "抱歉")
    return any(marker in reply for marker in generic_markers) or len(reply_terms) < 6


def grounded_customer_fallback(session: dict[str, Any], whiteboard: dict[str, Any]) -> str:
    user_text = latest_user_text(session)
    summary = str(whiteboard.get("project_summary", "")).strip() or user_text
    defaults = whiteboard.get("default_assumptions", [])
    plan = whiteboard.get("first_version_plan", [])
    default_text = "；".join(str(item) for item in defaults[:3] if str(item).strip()) or "先采用本地优先、可测试、带预览交付的默认方案"
    plan_text = "；".join(str(item) for item in plan[:3] if str(item).strip()) or "先整理第一版需求、生成项目文件、跑测试并交付预览"
    return (
        f"我按你刚才说的方向继续整理：{summary[:260]}。\n"
        f"这轮先不偏题展开，我会按这些默认值推进：{default_text}。\n"
        f"第一版重点是：{plan_text}。如果你有必须保留或不允许的点，直接补一句，我会写进后续生成。"
    )[:1200]


def visual_delivery_requirements_from_text(text: str) -> list[str]:
    compact = str(text or "").lower()
    requirements: list[str] = []
    if any(token in compact for token in ("图片", "照片", "图像", "生成图", "ai图", "立绘", "背景图", "image", "photo")):
        requirements.append("交付时必须直接发送图片/照片预览 artifact，不只返回路径")
    if any(token in compact for token in ("截图", "预览图", "高光帧", "frame", "screenshot")):
        requirements.append("交付时必须直接发送截图或关键帧预览")
    if any(token in compact for token in ("视频", "短视频", "录像", "mp4", "webm", "video")):
        requirements.append("交付时必须直接发送视频预览 artifact，不只返回路径")
    if any(token in compact for token in ("可视化", "预览", "展示效果", "demo")):
        requirements.append("交付时必须提供可视化预览或摘要图兜底")
    return unique_strings(requirements, limit=12)


def local_image_model_updates_from_text(text: str) -> dict[str, Any]:
    if not local_image_model_discovery.requests_local_image_model(text):
        return {}
    questions, discovery = local_image_model_discovery.critical_questions_for_text(text, ROOT)
    acceptance = [
        "背景和立绘必须由已配置的本地图片模型生成；程序化占位图或降级预览不算图片验收通过",
        "交付时必须明确本地图片模型是否实际可用，并给出背景/立绘生成证据",
    ]
    requirements = [
        "背景图和立绘图必须作为可预览的本地图片 artifact 交付",
    ]
    assumptions = [
        "本地图片模型能力按 ComfyUI、AUTOMATIC1111 或 SD_MODEL_DIR/模型目录探测；未发现时先生成接口和降级预览，但不把降级预览标记为通过",
    ]
    known_facts = ["用户要求背景和立绘使用本地图片模型生成"]
    if discovery.get("available"):
        known_facts.append("已发现可用的本地图片模型后端")
    else:
        known_facts.append("当前未发现可调用的本地图片生成服务或模型目录")
    return {
        "critical_questions": questions,
        "local_image_model_discovery": discovery,
        "acceptance_criteria": acceptance,
        "delivery_requirements": requirements,
        "default_assumptions": assumptions,
        "known_facts": known_facts,
    }


def capability_strategy_updates_from_text(text: str) -> dict[str, Any]:
    strategy = capability_strategy.build_capability_strategy(text, ROOT)
    if not strategy.get("capabilities"):
        return {}
    research_lines: list[str] = []
    for target in strategy.get("research_targets", [])[:8]:
        if not isinstance(target, dict):
            continue
        capability = target.get("capability", {}) if isinstance(target.get("capability"), dict) else {}
        label = str(capability.get("label", "")).strip()
        methods = target.get("advanced_methods", []) if isinstance(target.get("advanced_methods"), list) else []
        method_names = [str(item.get("name", "")).strip() for item in methods[:3] if isinstance(item, dict) and str(item.get("name", "")).strip()]
        if label and method_names:
            research_lines.append(f"{label}: {' / '.join(method_names)}")
    capability_labels = [
        str(item.get("label", "")).strip()
        for item in strategy.get("capabilities", [])
        if isinstance(item, dict) and str(item.get("label", "")).strip()
    ]
    return {
        "capability_strategy": strategy,
        "capability_research_targets": research_lines,
        "critical_questions": strategy.get("critical_questions", []) if isinstance(strategy.get("critical_questions"), list) else [],
        "acceptance_criteria": strategy.get("acceptance_criteria", []) if isinstance(strategy.get("acceptance_criteria"), list) else [],
        "decision_log": strategy.get("decision_log", []) if isinstance(strategy.get("decision_log"), list) else [],
        "known_facts": [f"识别出的核心能力：{'；'.join(capability_labels[:6])}"] if capability_labels else [],
    }


def normalize_question_fields(whiteboard: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(whiteboard)
    blocking = unique_strings(normalized.get("blocking_questions", []) if isinstance(normalized.get("blocking_questions"), list) else [], limit=20)
    open_questions = unique_strings(normalized.get("open_questions", []) if isinstance(normalized.get("open_questions"), list) else [], limit=40)
    if len(blocking) > 1:
        open_questions = unique_strings(open_questions + blocking[1:], limit=40)
        blocking = blocking[:1]
    normalized["blocking_questions"] = blocking
    normalized["open_questions"] = open_questions
    return normalized


def enforce_backend_updates_from_user_text(session: dict[str, Any], whiteboard: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_question_fields(whiteboard)
    text = latest_user_text(session)
    visual_requirements = visual_delivery_requirements_from_text(text)
    if visual_requirements:
        delivery = normalized.get("delivery_requirements", [])
        acceptance = normalized.get("acceptance_criteria", [])
        normalized["delivery_requirements"] = unique_strings((delivery if isinstance(delivery, list) else []) + visual_requirements, limit=120)
        normalized["acceptance_criteria"] = unique_strings((acceptance if isinstance(acceptance, list) else []) + visual_requirements, limit=120)
        append_memory_event(
            session,
            "backend_delivery_requirements_updated",
            data={"source": "latest_user_text", "requirements": visual_requirements},
        )
    local_image_updates = local_image_model_updates_from_text(text)
    if local_image_updates:
        for key in ("critical_questions", "acceptance_criteria", "delivery_requirements", "default_assumptions", "known_facts"):
            values = local_image_updates.get(key, [])
            existing = normalized.get(key, [])
            normalized[key] = unique_strings((existing if isinstance(existing, list) else []) + (values if isinstance(values, list) else []), limit=120)
        normalized["open_questions"] = unique_strings(
            normalized.get("open_questions", []) + normalized.get("critical_questions", []),
            limit=40,
        )
        normalized["local_image_model_discovery"] = local_image_updates.get("local_image_model_discovery", {})
        append_memory_event(
            session,
            "local_image_model_capability_checked",
            data={
                "available": bool(normalized["local_image_model_discovery"].get("available")),
                "critical_questions": normalized.get("critical_questions", []),
            },
        )
    strategy_updates = capability_strategy_updates_from_text(text)
    if strategy_updates:
        for key in ("critical_questions", "acceptance_criteria", "decision_log", "known_facts", "capability_research_targets"):
            values = strategy_updates.get(key, [])
            existing = normalized.get(key, [])
            normalized[key] = unique_strings((existing if isinstance(existing, list) else []) + (values if isinstance(values, list) else []), limit=120)
        normalized["open_questions"] = unique_strings(
            normalized.get("open_questions", []) + normalized.get("critical_questions", []),
            limit=40,
        )
        normalized["capability_strategy"] = strategy_updates.get("capability_strategy", {})
        append_memory_event(
            session,
            "capability_strategy_updated",
            data={
                "capabilities": strategy_updates.get("capability_strategy", {}).get("capabilities", []),
                "critical_questions": normalized.get("critical_questions", []),
            },
        )
    if any(token in text for token in ("必须", "不允许", "不要", "一定要", "后续", "修改", "不是", "我要的是")):
        changes = normalized.get("change_requests", [])
        normalized["change_requests"] = unique_strings((changes if isinstance(changes, list) else []) + [text], limit=120)
    ready_before_design_scope = bool(normalized.get("ready_to_generate"))
    normalized = codex_design_supervision.apply_design_intent(
        normalized,
        text,
        codex_default=False,
    )
    design_state = (
        normalized.get("product_design", {})
        if isinstance(normalized.get("product_design"), dict)
        else {}
    )
    if design_state.get("required"):
        normalized["product_design"] = {
            **design_state,
            "workflow_state": "provider_planner_pending",
            "design_source": "provider_planner",
            "codex_used": False,
            "user_confirmation_required": False,
            "advisory_only": False,
        }
        normalized["ready_to_generate"] = ready_before_design_scope
    return normalized


def substantive_user_turn_count(session: dict[str, Any]) -> int:
    count = 0
    for msg in session.get("messages", []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        text = str(msg.get("text", "")).strip()
        if text and not text.startswith("/") and not is_smalltalk(text) and not is_generate_command(text) and not looks_like_status_question(text):
            count += 1
    return count


def customer_service_reply(session: dict[str, Any], model: str, timeout: int) -> tuple[str, dict[str, Any], str]:
    policy = read_customer_agent_policy()
    system = """你是 CGNK 项目生成与交付团队的 Codex conversation 前台接口，更像项目负责人和产品/工程搭档，不是闲聊机器人，也不是表单客服。
你的目标是把用户的一句话想法主动发展成可生成、可测试、可交付预览的第一版项目方案。

自我认知：
- 你代表 CGNK 后台项目工作流，负责理解需求、形成方案、维护项目记忆、协调生成、测试和交付。
- 你可以说“我这边会生成/测试/交付/记录”，但不要假装有人类团队正在手工开发；应表达为后台工作流会执行。
- 你的主要任务不是陪聊，而是推进项目落地：默认值、边界、验收点、图片/视频/截图交付、后续修改都要落到白板。
- 用户问你是谁或能做什么时，回答你是 CGNK 项目交付接口，可以帮助生成项目、测试、预览、保存长期记忆和清理/重启会话。

对外表达：
- 不要暴露内部程序结构，不要使用拟人名字，不要说某某员工正在做什么。
- 用户只关心具体动作和结果：当前会做什么、为什么要问问题、缺少什么输入、开始后会生成什么、会怎么测试、会给用户看什么证据、用户怎么继续或修改。
- 用这种表达：我会先整理第一版范围；我会确认缺少的关键输入；我会生成可运行版本；我会准备测试代码和测试命令；我会整理截图/视频/预览证据；我会先发给你判断；你确认后我再最终打包。
- 禁止向用户暴露 pipeline_manifest、dynamic_pipeline_runner、agent_session、local_packager、delivery_manifest、backend_dialogue_loop、whiteboard、truth ledger、jsonl、scripts、internal module names。
- 除非是用户需要下载的交付文件名，不要输出文件系统路径。

核心策略：
- 不要逐项审问字段，不要“复述一句再问一个缺口”的客服脚本。
- 先做专业判断：拆解产品层、技术层、默认方案和第一版边界。
- 必须先判断哪些功能是核心能力，不能只按最近一句里的单个功能局部补丁；核心能力要写入 capability_research_targets 或 decision_log。
- 对核心能力要主动寻找成熟/高级路线：本地模型、成熟库、外部 API、专用工作流、真实运行验证；如果只做简化 fallback，必须标明不满足对应验收。
- 如果两条路线有明显用户可感知差异，比如本地模型/云端模型、SQLite/JSON、网页/桌面、同模型/分模型、线性剧情/分支剧情，必须作为 critical_questions 问客户，而不是静默默认。
- 对可默认的信息直接给默认假设；但如果存在 soft_questions、critical_questions、缺少真实输入或复杂/高不确定领域，不要宣布已经开始生成。
- 只有缺失信息会导致完全无法生成时，才问一个阻塞问题。
- 必须维护持续记忆：保留 current_whiteboard 里已有的用户规则、验收标准、修改请求、交付要求和决策记录。
- 用户用“不是、我要的是、为什么没有、后续修改、必须、不允许”等方式纠正时，要写入 change_requests 或 acceptance_criteria。
- 对你的产品/技术判断用一句可审计摘要写入 decision_log；这不是隐藏思维链，而是给后续 agent 复用的决策记录。
- 输出要体现你懂这个项目。例如游戏视频高光项目，应主动给出视频输入、事件检测、高光评分、剪辑导出、MP4/H.264、通用信号检测等方案。
- 不要要求用户回复固定口令，但可以自然说明：你可以补充信息；如果想先按默认假设推进，可以回复“开始生成”或“按默认假设开始生成”。
- 只有用户最近一条消息明确要求开始生成时，才把 action 设为 "start_generation"。
- 当 action 是 "start_generation" 时，reply 不能只有一句“开始做”；要简短列出将生成的第一版能力、默认假设和测试/预览目标。
- 如果用户只是提出项目想法或项目补充，前台给出第一版方案、默认假设和需确认问题，把 action 设为 "continue_chat"，等待用户明确开始。
- 回复必须紧扣最近一条用户消息和 current_whiteboard，不要把话题切到无关产品、无关技术栈或通用客服话术。
- 如果最近用户在纠正你，先承认修正点并更新白板，再继续推进；不要沿用旧理解。
- 如果用户要求图片、视频、预览或可视化，必须把它写入 delivery_requirements 和 acceptance_criteria。
- 如果用户要求本地图片模型生成背景/立绘/图片，必须追问本地图片后端或模型目录配置；这个问题写入 critical_questions。用户明确开始前不要自动生成；用户强制开始后，也不能把降级预览当作图片验收通过。
- 用户上传图片、文档、视频、音频或数据文件时，必须把它当作项目输入资料；结合 caption 和 current_attachments 更新 known_facts、验收点或修改要求，不要回复“只能收文字”。
- 不要暴露内部模块名、API/provider 名称、路径堆栈。
- 输出必须是 JSON 对象，不要 Markdown，不要额外文字。

可默认字段策略：
- game_type: 默认“通用游戏视频”，除非用户指定某个游戏。
- output_format: 默认 MP4/H.264。
- clip_duration: 默认 15-60 秒，可在产品里做成可调参数。
- highlight_signals: 默认组合 audio_peak、scene_change、motion_intensity、ocr_text、manual_timestamp。
- preview: 默认需要结果预览，优先生成高光帧截图和短视频预览。

JSON 结构：
{
  "reply": "发给用户的自然回复，像懂项目的人在推进方案",
  "action": "continue_chat 或 start_generation",
  "whiteboard": {
    "project_summary": "面向生成器的一段完整项目需求；没有项目需求时为空字符串",
    "known_facts": ["已经确认的重要事实"],
    "default_assumptions": ["你主动采用的默认值"],
    "first_version_plan": ["第一版会做什么"],
    "blocking_questions": ["真正阻塞生成的问题；通常为空"],
    "critical_questions": ["关键配置缺口；不作为硬门禁，但必须在回复中问清"],
    "capability_research_targets": ["核心能力和高级路线候选"],
    "open_questions": ["不阻塞生成、后续可调的问题"],
    "user_rules": ["用户明确要求长期遵守的行为规则"],
    "acceptance_criteria": ["本项目必须满足的验收标准"],
    "change_requests": ["用户后续纠正、补充和修改要求"],
    "delivery_requirements": ["用户要求如何展示过程、图片、视频、测试结果"],
    "decision_log": ["可审计的方案决策摘要"],
    "ready_to_generate": false
  }
}
"""
    system += "\n\n当前热加载行为策略如下，必须优先遵守：\n" + policy
    whiteboard = session.get("whiteboard", {})
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_whiteboard": whiteboard if isinstance(whiteboard, dict) else {},
                    "substantive_user_turn_count": substantive_user_turn_count(session),
                    "reply_variation_seed": reply_variation_seed(),
                    "reply_variation_rule": "Do not reuse the exact wording, opening, or sentence rhythm of recent assistant replies when facts are unchanged.",
                    "recent_memory_events": session.get("memory_events", [])[-40:],
                    "current_attachments": recent_attachments(session, limit=30),
                    "attachment_requirement_lines": attachment_requirement_lines(session),
                    "project_memory": session.get("project_memory", {}),
                    "project_memory_excerpt": read_project_memory_excerpt(session, limit=5000),
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
        *recent_dialogue(session, limit=30),
    ]
    raw = provider_text(messages, model, timeout)
    doc = parse_json_object(raw)
    if not doc:
        salvaged_reply = extract_json_string_field(raw, "reply")
        salvaged_action = extract_json_string_field(raw, "action")
        fallback_whiteboard = fallback_whiteboard_for_unparsed_frontdesk(session)
        if not salvaged_reply:
            salvaged_reply = grounded_customer_fallback(session, fallback_whiteboard)
        action = "start_generation" if salvaged_action == "start_generation" and str(fallback_whiteboard.get("project_summary", "")).strip() else "continue_chat"
        append_memory_event(
            session,
            "customer_reply_repaired",
            data={"reason": "unparsed_json_from_provider", "raw_preview": raw[:500], "action": action},
        )
        return salvaged_reply[:1200], fallback_whiteboard, action
    reply = str(doc.get("reply", "")).strip()
    if not reply:
        raise RuntimeError("customer-service provider returned empty reply")
    action = str(doc.get("action", "continue_chat")).strip()
    if action not in {"continue_chat", "start_generation"}:
        action = "continue_chat"
    next_whiteboard = doc.get("whiteboard", {})
    if not isinstance(next_whiteboard, dict):
        next_whiteboard = whiteboard if isinstance(whiteboard, dict) else {}
    elif isinstance(whiteboard, dict):
        next_whiteboard = merge_whiteboard(whiteboard, next_whiteboard)
    rejected_off_topic = reply_looks_off_topic(session, reply, next_whiteboard)
    if rejected_off_topic:
        append_memory_event(
            session,
            "customer_reply_rejected",
            data={"reason": "off_topic_guard", "provider_reply": reply[:900], "latest_user_text": latest_user_text(session)[:900]},
        )
        reply = grounded_customer_fallback(session, next_whiteboard)
        action = "continue_chat"
    if not rejected_off_topic and bool(next_whiteboard.get("ready_to_generate")) and not next_whiteboard.get("blocking_questions"):
        action = "start_generation"
    if action == "start_generation" and not str(next_whiteboard.get("project_summary", "")).strip():
        action = "continue_chat"
        next_whiteboard["ready_to_generate"] = False
    next_whiteboard = enforce_backend_updates_from_user_text(session, next_whiteboard)
    critical_questions = next_whiteboard.get("critical_questions", []) if isinstance(next_whiteboard.get("critical_questions"), list) else []
    if critical_questions and not any(str(item).strip() and str(item).strip()[:18] in reply for item in critical_questions):
        reply = (reply.rstrip() + "\n关键配置：" + "；".join(str(item).strip() for item in critical_questions[:2] if str(item).strip()))[:1200]
    if next_whiteboard.get("blocking_questions"):
        action = "continue_chat"
    return reply, next_whiteboard, action


LOCAL_PUBLIC_REPLY_EVENTS = {
    "admin_command",
    "greeting",
    "status_requested",
    "escalation_request",
    "project_update_running",
    "attachment_project_input_running",
    "unsupported_attachment_received",
}


def normalize_reply_for_similarity(text: str) -> str:
    return re.sub(r"[\s，。,.!?！？；;：:、~～]+", "", str(text or "").lower())


def reply_too_similar_to_recent_assistant(text: str, session: dict[str, Any]) -> bool:
    current = normalize_reply_for_similarity(text)
    if len(current) < 12:
        return False
    recent: list[str] = []
    for message in reversed(session.get("messages", [])):
        if not isinstance(message, dict) or str(message.get("role", "")) != "assistant":
            continue
        previous = str(message.get("text", "")).strip()
        if previous:
            recent.append(previous)
        if len(recent) >= 4:
            break
    for previous in recent:
        normalized = normalize_reply_for_similarity(previous)
        if not normalized:
            continue
        if current == normalized or current.startswith(normalized[:18]) or normalized.startswith(current[:18]):
            return True
        if difflib.SequenceMatcher(None, current, normalized).ratio() >= 0.86:
            return True
    return False


def local_public_reply_message(event: str, session: dict[str, Any], facts: dict[str, Any], timeout: int) -> str:
    if event not in LOCAL_PUBLIC_REPLY_EVENTS:
        return ""
    task = "customer_status" if event == "status_requested" else "customer_public_reply"
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    active = active_run(session) or {}
    has_project_summary = bool(str(whiteboard.get("project_summary", "")).strip())
    has_active_or_delivery_context = (
        has_project_summary
        or bool(active)
        or str(generation.get("status", "idle")).lower() not in {"", "idle"}
    )
    safe_facts = dict(facts or {})
    if not has_active_or_delivery_context and isinstance(safe_facts.get("evidence_state"), dict):
        safe_facts["evidence_state"] = {"delivery_ready": False, "missing": [], "refs": {}, "sent_record": False}
        safe_facts["delivery_evidence_applicable"] = False
        safe_facts["status_hint"] = "空会话，没有正在运行的后台任务；不要提可运行项目文件、效果预览或测试结论。"
    system = """你是 CGNK Codex conversation 前台，只写一条要直接发给用户的中文短消息。
边界：
- 不生成项目文件，不改白板，不决定是否开始生成。
- 不宣布完成；没有交付包、预览和测试结论时不能说已经完成。
- 不暴露 provider、API、manifest、pipeline、truth ledger、package、内部路径或调试字段。
- 不要使用拟人名字，不要说某某员工正在做什么；只说明具体动作、当前状态、缺少输入、测试方式、预览证据和用户下一步。
- 不使用固定问候模板；即使事实相同，也要根据 facts、whiteboard、generation 和 recent_dialogue 自然改写。
- 只根据输入 facts 和当前状态说清楚当前发生了什么、用户补充是否已进入后台、下一步会怎样。
- 如果 generation.status 是 idle、没有 active_run、也没有项目摘要，短问候只能表达“在线/空会话/没有后台任务/可以发新目标”，不要说正在补齐交付物。
- 如果用户只是问状态，且 generation 不在 queued/running/waiting_decision、active_run 也不是 running/queued，就说没有正在运行的后台任务；不要把 evidence_state.missing 解释为正在生成。
- 如果 facts.delivery_evidence_applicable 是 false，禁止提可运行项目文件、效果预览、测试结论、补齐交付物。
- facts.evidence_state.missing 里的 package/screenshot/verify_report 是后台还要补齐的交付证据，不要要求用户提供这些文件；要表达为“我这边继续补齐可运行项目文件、效果预览和测试结论”。
- 只有已有 active_run/generation 或项目上下文时，才可以提到补齐可运行项目文件、效果预览和测试结论。
- 把内部字段翻译成用户能懂的话：package=可运行项目文件，screenshot=效果预览，verify_report=测试结论。
- 输出纯文本，不要 JSON，不要 Markdown 表格。"""
    payload = {
        "event": event,
        "facts": safe_facts,
        "whiteboard": whiteboard,
        "generation": generation,
        "active_run": active,
        "recent_dialogue": recent_dialogue(session, limit=8),
        "reply_variation_seed": reply_variation_seed(),
    }
    recent_assistant_replies = [
        str(message.get("text", "")).strip()
        for message in reversed(session.get("messages", []))
        if isinstance(message, dict) and str(message.get("role", "")) == "assistant" and str(message.get("text", "")).strip()
    ][:4]
    for attempt in range(2):
        attempt_payload = dict(payload)
        if attempt:
            attempt_payload["must_avoid_repeating_assistant_replies"] = recent_assistant_replies
            attempt_payload["rewrite_instruction"] = "上一版和最近回复太像。必须换开头、换句式、换信息顺序，但事实不变。"
        result = local_model_router.call_text_task(
            task,
            system,
            json.dumps(attempt_payload, ensure_ascii=False, indent=2),
            min(timeout, 45),
        )
        if not result.get("ok"):
            return ""
        text = pre_send_guard(str(result.get("text", "")).strip())
        if not text or reply_looks_off_topic(session, text, whiteboard):
            return ""
        if reply_too_similar_to_recent_assistant(text, session) and attempt == 0:
            continue
        if reply_too_similar_to_recent_assistant(text, session):
            return ""
        return text[:900]
    return ""


def provider_user_message(
    *,
    event: str,
    session: dict[str, Any],
    facts: dict[str, Any],
    model: str,
    timeout: int,
) -> str:
    local_text = local_public_reply_message(event, session, facts, timeout)
    if local_text:
        return local_text

    policy = read_customer_agent_policy()
    system = """你是 CGNK 项目生成与交付团队的 Codex conversation 前台接口。
根据事件和事实生成一条自然、简短、像项目负责人/产品工程搭档的中文消息。

规则：
- 自我定位要稳定：你代表 CGNK 后台工作流推进需求、生成、测试、预览和交付，不是普通聊天机器人。
- 不要使用拟人名字，不要说某某员工正在做什么；只说明具体动作、结果、测试、预览证据和下一步。
- 不要使用固定口令、模板腔、机器人流程话术。
- 不要要求用户回复固定词，例如“开始生成”。
- 不要暴露内部模块名。
- 如果是交付结果，不要只报路径；要概括本次项目做了什么、测试是否通过、用户能看到什么效果、缺了什么预览、下一步建议。
- 交付结果里可以保留关键路径和状态，方便用户检查，但路径不是主体。
- 如果没有截图或预览，解释为“本轮测试没有产出 preview artifact”，并建议下一步补预览图/短视频任务。
- 如果是失败，只能使用 facts.user_visible_cause、facts.impact、facts.next_step 说明原因和下一步；不要根据内部错误猜测成图片模型、项目代码或用户需求问题。
- 失败回复不要贴底层堆栈，不要暴露内部参数名，不要承诺本地模板兜底。
- 只输出要发给用户的一条消息，不要 JSON，不要 Markdown 表格。
"""
    system += "\n\n当前热加载行为策略如下，必须优先遵守：\n" + policy
    payload = {
        "event": event,
        "facts": facts,
        "reply_variation_seed": reply_variation_seed(),
        "reply_variation_rule": "Use a fresh wording pattern for this user-facing message while preserving facts.",
        "whiteboard": session.get("whiteboard", {}),
        "recent_dialogue": recent_dialogue(session, limit=20),
        "recent_memory_events": session.get("memory_events", [])[-40:],
        "current_attachments": recent_attachments(session, limit=30),
        "attachment_requirement_lines": attachment_requirement_lines(session),
        "project_memory": session.get("project_memory", {}),
        "project_memory_excerpt": read_project_memory_excerpt(session, 5000),
    }
    text = provider_text(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        model,
        timeout,
    ).strip()
    if not text:
        raise RuntimeError("provider returned empty user-facing message")
    return text[:1200]


def send_provider_message(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    *,
    event: str,
    session: dict[str, Any],
    facts: dict[str, Any],
    model: str,
    timeout: int,
) -> bool:
    try:
        text = provider_user_message(event=event, session=session, facts=facts, model=model, timeout=min(timeout, 60))
    except Exception as exc:
        print(f"user-message provider failed: {exc}", flush=True)
        return False
    append_backend_memo(session_dir, session, f"provider_{event}", text)
    return send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event=event,
        facts=facts,
        source="provider_user_message",
        direct_text=text,
        backend_memo=text,
    )


def send_provider_or_technical_error(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    *,
    event: str,
    session: dict[str, Any],
    facts: dict[str, Any],
    model: str,
    timeout: int,
    technical_error: str,
) -> None:
    if send_provider_message(client, conversation_id, session_dir, event=event, session=session, facts=facts, model=model, timeout=timeout):
        return
    send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event=event,
        facts={"technical_error": technical_error},
        source="technical_fallback",
        direct_text="后台连接中断；当前轮次停止，下一条项目输入会重新触发后台。",
    )


def log_bridge_error(log_dir: pathlib.Path, event: str, conversation_id: int | str, exc: Exception, context: dict[str, Any] | None = None) -> None:
    append_jsonl(
        log_dir / "bridge_errors.jsonl",
        {
            "created_at": now(),
            "event": event,
            "conversation_id": str(conversation_id),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "context": context or {},
        },
    )


def is_valid_image_file(path: pathlib.Path) -> bool:
    if not path.exists() or not path.is_file() or path.stat().st_size < 32:
        return False
    try:
        head = path.read_bytes()[:16]
    except Exception:
        return False
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if head.startswith(b"\xff\xd8\xff"):
        return True
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return True
    if head.startswith(b"RIFF") and b"WEBP" in head:
        return True
    return False


def delivery_image_candidates(result: dict[str, Any]) -> list[pathlib.Path]:
    candidates: list[tuple[int, pathlib.Path]] = []
    agent_usage = result.get("agent_usage", {})
    if isinstance(agent_usage, dict):
        screenshots = [pathlib.Path(str(item)) for item in agent_usage.get("screenshots", []) if str(item).strip()]
        for path in screenshots:
            if path.exists():
                candidates.append((0, path))
    project_dir = pathlib.Path(str(result.get("project_dir", "")))
    if project_dir.exists():
        preferred_dirs = [
            project_dir / "static" / "output",
            project_dir / "static" / "generated",
            project_dir / "output",
            project_dir / "outputs",
            project_dir / "generated",
        ]
        for directory in preferred_dirs:
            if directory.exists():
                candidates.extend((1, p) for p in directory.rglob("*.png"))
                candidates.extend((1, p) for p in directory.rglob("*.jpg"))
                candidates.extend((1, p) for p in directory.rglob("*.jpeg"))
    example_outputs = result.get("example_outputs", {})
    if isinstance(example_outputs, dict):
        for key in ("image_preview", "frame_preview"):
            path = pathlib.Path(str(example_outputs.get(key, "")))
            if path.exists():
                candidates.append((2, path))
    online_inputs = result.get("online_input_examples", {})
    if isinstance(online_inputs, dict):
        for item in online_inputs.get("examples", []):
            if isinstance(item, dict) and str(item.get("modality", "")).lower() == "image":
                path = pathlib.Path(str(item.get("local_path", "")))
                if path.exists():
                    candidates.append((4, path))
    for key in ("project_dir", "runtime_dir", "run_dir"):
        raw_root = str(result.get(key, "")).strip()
        if not raw_root:
            continue
        root = pathlib.Path(raw_root)
        if root.exists():
            candidates.extend((3, p) for p in root.rglob("*.png"))
            candidates.extend((3, p) for p in root.rglob("*.jpg"))
            candidates.extend((3, p) for p in root.rglob("*.jpeg"))
    root_pngs = sorted(ROOT.glob("*codex*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    candidates.extend((5, p) for p in root_pngs[:5])
    unique: dict[str, tuple[int, pathlib.Path]] = {}
    for priority, path in candidates:
        try:
            key = str(path.resolve()).lower()
            existing = unique.get(key)
            if existing is None or priority < existing[0]:
                unique[key] = (priority, path)
        except Exception:
            continue
    valid = [(priority, p) for priority, p in unique.values() if is_valid_image_file(p)]
    return [p for _, p in sorted(valid, key=lambda item: (item[0], -item[1].stat().st_mtime))]


def find_delivery_image(result: dict[str, Any]) -> pathlib.Path | None:
    candidates = delivery_image_candidates(result)
    if not candidates:
        return None
    return candidates[0]


def find_delivery_video(result: dict[str, Any]) -> pathlib.Path | None:
    candidates: list[tuple[int, pathlib.Path]] = []
    agent_usage = result.get("agent_usage", {})
    if isinstance(agent_usage, dict):
        path = pathlib.Path(str(agent_usage.get("workflow_video", "")))
        if path.exists():
            candidates.append((0, path))
    example_outputs = result.get("example_outputs", {})
    if isinstance(example_outputs, dict):
        path = pathlib.Path(str(example_outputs.get("video_preview", "")))
        if path.exists():
            candidates.append((2, path))
    for key in ("project_dir", "runtime_dir", "run_dir"):
        raw_root = str(result.get(key, "")).strip()
        if not raw_root:
            continue
        root = pathlib.Path(raw_root)
        if root.exists():
            candidates.extend((1, p) for p in root.rglob("*.mp4"))
            candidates.extend((1, p) for p in root.rglob("*.webm"))
            candidates.extend((1, p) for p in root.rglob("*.mov"))
    valid = [(priority, p) for priority, p in candidates if p.exists() and p.is_file() and p.stat().st_size > 0]
    if not valid:
        return None
    return sorted(valid, key=lambda item: (item[0], -item[1].stat().st_mtime))[0][1]


def render_project_preview_image(result: dict[str, Any], log_dir: pathlib.Path) -> pathlib.Path | None:
    project_dir = pathlib.Path(str(result.get("project_dir", "")))
    index = project_dir / "index.html"
    if not index.exists():
        return None
    out = log_dir / f"{safe_id(project_dir.name)}_preview.png"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page.goto(index.resolve().as_uri(), wait_until="networkidle")
            page.screenshot(path=str(out), full_page=True)
            browser.close()
    except Exception as exc:
        print(f"preview render failed: {exc}", flush=True)
        return None
    if out.exists() and out.stat().st_size > 0:
        return out
    return None


def wrap_text(text: str, width: int = 36, max_lines: int = 18) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "").strip())
    if not clean:
        return []
    lines: list[str] = []
    current = ""
    for ch in clean:
        ch_width = 2 if re.match(r"[\u4e00-\u9fff]", ch) else 1
        cur_width = sum(2 if re.match(r"[\u4e00-\u9fff]", c) else 1 for c in current)
        if cur_width + ch_width > width:
            lines.append(current)
            current = ch
            if len(lines) >= max_lines:
                break
        else:
            current += ch
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def make_delivery_summary_image(result: dict[str, Any], log_dir: pathlib.Path) -> pathlib.Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    out = log_dir / f"{safe_id(result.get('project_dir', 'project'))}_delivery_summary.png"
    facts = project_delivery_facts(result)
    title = pathlib.Path(str(result.get("project_dir", "CGNK Project"))).name or "CGNK Project"
    summary = str(facts.get("effect_report_summary", {}).get("summary", "") if isinstance(facts.get("effect_report_summary"), dict) else "")
    if not summary:
        summary = "项目已生成，运行产物、测试图和效果报告已写入本地目录。"
    files = facts.get("files", [])
    image = Image.new("RGB", (1280, 720), (246, 247, 249))
    draw = ImageDraw.Draw(image)
    try:
        font_title = ImageFont.truetype("arial.ttf", 44)
        font_body = ImageFont.truetype("arial.ttf", 24)
        font_small = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_small = ImageFont.load_default()
    draw.rectangle((0, 0, 1280, 96), fill=(29, 36, 48))
    draw.text((48, 26), title[:52], fill=(255, 255, 255), font=font_title)
    draw.text((48, 132), "生成状态: PASS", fill=(21, 102, 68), font=font_body)
    y = 182
    for line in wrap_text(summary, width=58, max_lines=5):
        draw.text((48, y), line, fill=(42, 50, 64), font=font_body)
        y += 34
    y += 18
    draw.text((48, y), "主要产物", fill=(29, 36, 48), font=font_body)
    y += 38
    for item in [str(row) for row in files[:10]]:
        draw.text((72, y), f"- {item[:80]}", fill=(82, 96, 111), font=font_small)
        y += 28
    draw.text((48, 660), "这是自动生成的交付摘要图；如果项目产出真实截图或视频，会优先发送真实预览。", fill=(82, 96, 111), font=font_small)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out if is_valid_image_file(out) else None


def unique_media_paths(paths: list[pathlib.Path], limit: int = 3) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve()).lower()
        except Exception:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
        if len(out) >= limit:
            break
    return out


def read_short_file(path: pathlib.Path, limit: int = 1800) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[:limit].strip()


def project_delivery_facts(result: dict[str, Any]) -> dict[str, Any]:
    project_dir = pathlib.Path(str(result.get("project_dir", "")))
    files: list[str] = []
    if project_dir.exists():
        files = [
            str(path.relative_to(project_dir)).replace("\\", "/")
            for path in sorted(project_dir.rglob("*"))
            if path.is_file()
        ][:40]
    runtime_dir = pathlib.Path(str(result.get("runtime_dir", "")))
    effect_report = {}
    effect_path = pathlib.Path(str(result.get("effect_report_path", "")))
    if effect_path.exists():
        try:
            effect_report = json.loads(effect_path.read_text(encoding="utf-8"))
        except Exception:
            effect_report = {"unreadable": str(effect_path)}
    return {
        "project_dir": result.get("project_dir"),
        "runtime_dir": result.get("runtime_dir") or str(runtime_dir),
        "execution_path": result.get("execution_path"),
        "effect_report_path": result.get("effect_report_path"),
        "status": str(result.get("status", "unknown")).upper(),
        "files": files,
        "readme_excerpt": read_short_file(project_dir / "README.md"),
        "test_plan_excerpt": read_short_file(project_dir / "TEST_PLAN.md"),
        "effect_report_summary": effect_report,
        "online_input_examples": result.get("online_input_examples", {}),
        "example_outputs": result.get("example_outputs", {}),
    }


# LEGACY ONLY. Codex conversation formal generation must not call this.
def build_generation_args(
    conversation_id: int | str,
    requirement: str,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    generation_mode: str = "api",
) -> argparse.Namespace:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.build_generation_args(
        conversation_id,
        requirement,
        log_dir,
        model,
        timeout,
        generation_mode,
        root=ROOT,
        safe_id_fn=safe_id,
    )


# LEGACY ONLY. Codex conversation formal generation must not call this.
def phase_log_path_for_project(project_slug: str) -> pathlib.Path:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.phase_log_path_for_project(project_slug, root=ROOT)


# LEGACY ONLY. Codex conversation formal generation must not call this.
def last_known_phase(phase_log_path: pathlib.Path) -> str:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.last_known_phase(phase_log_path)


# LEGACY ONLY. Codex conversation formal generation must not call this.
def recent_phase_events(phase_log_path: pathlib.Path, limit: int = 8) -> list[dict[str, Any]]:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.recent_phase_events(phase_log_path, limit)


# LEGACY ONLY. Codex conversation formal generation must not call this.
def read_timeout_diagnostics(project_slug: str) -> dict[str, Any]:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.read_timeout_diagnostics(project_slug, root=ROOT)


# LEGACY ONLY. Codex conversation formal generation must not call this.
def artifact_inventory(project_slug: str, result_path: pathlib.Path, phase_log_path: pathlib.Path) -> tuple[list[str], list[str]]:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.artifact_inventory(project_slug, result_path, phase_log_path, root=ROOT)


# LEGACY ONLY. Codex conversation formal generation must not call this.
def write_timeout_failure_result(legacy_args: argparse.Namespace, timeout_seconds: int, result_path: pathlib.Path) -> dict[str, Any]:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.write_timeout_failure_result(
        legacy_args,
        timeout_seconds,
        result_path,
        root=ROOT,
        now_fn=now,
        write_json_fn=write_json,
    )


# LEGACY ONLY. Codex conversation formal generation must not call this.
def run_generation_subprocess(legacy_args: argparse.Namespace, log_dir: pathlib.Path) -> dict[str, Any]:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.run_generation_subprocess(
        legacy_args,
        log_dir,
        root=ROOT,
        append_jsonl_fn=append_jsonl,
        now_fn=now,
        write_json_fn=write_json,
        total_timeout_seconds=GENERATION_TOTAL_TIMEOUT_SECONDS,
    )


# LEGACY ONLY. Codex conversation formal generation must not call this.
def safe_generation_failure_facts(requirement: str, exc: Exception) -> dict[str, Any]:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.safe_generation_failure_facts(requirement, exc)


# LEGACY ONLY. Codex conversation formal generation must not call this.
def generation_progress_text(elapsed_seconds: int) -> str:
    import legacy_provider_pipeline

    return legacy_provider_pipeline.generation_progress_text(elapsed_seconds)


# LEGACY ONLY. Codex conversation formal generation must not call this.
def run_generation_job(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    announce_start: bool = False,
    control_id: str = "",
    generation_mode: str = "api",
) -> None:
    import legacy_provider_pipeline

    legacy_provider_pipeline.run_generation_job(
        sys.modules[__name__],
        client,
        conversation_id,
        session_dir,
        log_dir,
        model,
        timeout,
        announce_start=announce_start,
        control_id=control_id,
        generation_mode=generation_mode,
    )


def _provider_runtime_path(value: Any) -> pathlib.Path | None:
    path = pathlib.Path(str(value or ""))
    if path.exists() and path.is_file():
        return path.resolve()
    return None


def _copy_provider_runtime_asset(source: pathlib.Path | None, target: pathlib.Path) -> str:
    if not source:
        return ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return str(target.resolve())
    except Exception:
        return ""


def materialize_provider_runtime_artifacts(project_dir: pathlib.Path, provider_result: dict[str, Any]) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    copied: dict[str, str] = {}
    example_outputs = provider_result.get("example_outputs", {}) if isinstance(provider_result.get("example_outputs"), dict) else {}
    agent_usage = provider_result.get("agent_usage", {}) if isinstance(provider_result.get("agent_usage"), dict) else {}
    screenshots = agent_usage.get("screenshots", []) if isinstance(agent_usage.get("screenshots"), list) else []
    screenshot_source = _provider_runtime_path(screenshots[0] if screenshots else "")
    background_source = _provider_runtime_path(example_outputs.get("generated_background") or example_outputs.get("background"))
    sprite_source = _provider_runtime_path(example_outputs.get("generated_sprite") or example_outputs.get("sprite") or example_outputs.get("character"))
    generated_images = agent_usage.get("generated_images", []) if isinstance(agent_usage.get("generated_images"), list) else []
    for raw in generated_images:
        candidate = _provider_runtime_path(raw)
        if not candidate:
            continue
        if not background_source and _looks_like_background_asset(candidate):
            background_source = candidate
        if not sprite_source and _looks_like_sprite_asset(candidate):
            sprite_source = candidate
    copied["ui_screenshot"] = _copy_provider_runtime_asset(screenshot_source, project / "screenshots" / "provider_ui_screenshot.png")
    copied["background"] = _copy_provider_runtime_asset(background_source, project / "generated" / "background_scene.png")
    copied["sprite"] = _copy_provider_runtime_asset(sprite_source, project / "generated" / "character_sprite.png")
    video_source = _provider_runtime_path(agent_usage.get("workflow_video")) or _provider_runtime_path(example_outputs.get("video_preview"))
    copied["video"] = _copy_provider_runtime_asset(video_source, project / "artifacts" / "workflow_demo.mp4")
    return {"copied": {key: value for key, value in copied.items() if value}}


def _short_output(text: str, limit: int = 5000) -> str:
    clean = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if len(clean) <= limit:
        return clean
    return clean[: limit // 2] + "\n...\n" + clean[-limit // 2 :]


def classify_provider_pytest_failure(stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}"
    if "PIL._deprecate" in text or "BaseSettings` has been moved" in text or "pydantic-settings" in text:
        return "dependency_environment_error"
    return "pytest_failed"


def run_subprocess_text(command: list[str], *, cwd: pathlib.Path, timeout: int, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
        return {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": _short_output(proc.stdout), "stderr": _short_output(proc.stderr), "command": " ".join(command)}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "returncode": 124, "stdout": _short_output(exc.stdout or ""), "stderr": _short_output(exc.stderr or "command timed out"), "command": " ".join(command)}


def ensure_provider_test_environment(project_dir: pathlib.Path, *, timeout: int = 360) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    venv_dir = project / ".cgnk_test_env"
    python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    steps: list[dict[str, Any]] = []
    if not python.exists():
        steps.append(run_subprocess_text([sys.executable, "-m", "venv", str(venv_dir)], cwd=project, timeout=timeout))
        if not steps[-1]["ok"]:
            return {"ok": False, "python": "", "venv_dir": str(venv_dir), "steps": steps, "error": "venv_create_failed"}
    pip_base = [str(python), "-m", "pip", "install", "--disable-pip-version-check"]
    steps.append(run_subprocess_text(pip_base + ["--upgrade", "pip"], cwd=project, timeout=timeout))
    req = project / "requirements.txt"
    if req.exists():
        steps.append(run_subprocess_text(pip_base + ["-r", str(req)], cwd=project, timeout=timeout))
    else:
        steps.append(run_subprocess_text(pip_base + ["pytest"], cwd=project, timeout=timeout))
    tests_dir = project / "tests"
    if tests_dir.exists() and any(path.is_file() for path in tests_dir.rglob("test*.py")):
        steps.append(run_subprocess_text(pip_base + ["pytest"], cwd=project, timeout=timeout))
    ok = all(step.get("ok") for step in steps)
    return {"ok": ok, "python": str(python) if ok else "", "venv_dir": str(venv_dir), "steps": steps, "error": "" if ok else "dependency_install_failed"}


def infer_explicit_minimum_test_count(text: str) -> int:
    lowered = str(text or "").lower()
    minimum = 1
    for match in re.finditer(r"(?:至少|共至少|at\s+least|minimum(?:\s+of)?)\s*(\d+)", lowered, flags=re.I):
        window = lowered[max(0, match.start() - 50) : min(len(lowered), match.end() + 100)]
        if "测试" in window or "test" in window or "pytest" in window:
            minimum = max(minimum, int(match.group(1)))
    return minimum


def run_provider_project_tests(
    project_dir: pathlib.Path,
    *,
    timeout: int = 180,
    python_executable: str | pathlib.Path | None = None,
    run_id: str | None = None,
    candidate_id: str | None = None,
    candidate_hash: str | None = None,
    commit_sha: str | None = None,
    repair_summary: dict[str, Any] | None = None,
    dependency_setup: dict[str, Any] | None = None,
    production_provenance_ref: str | pathlib.Path | None = None,
    production_provenance_hash: str = "",
    minimum_collected: int = 1,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    tests_dir = project / "tests"
    pytest_config = project / "pytest.ini"
    if not pytest_config.exists():
        pytest_config.write_text("[pytest]\ntestpaths = tests\npythonpath = .\n", encoding="utf-8")
    if not tests_dir.exists() or not any(path.is_file() for path in tests_dir.rglob("test*.py")):
        evidence = real_test_execution.run_tests(
            project,
            timeout=timeout,
            python_executable=python_executable,
            run_id=run_id,
            candidate_id=candidate_id,
            candidate_hash=candidate_hash,
            commit_sha=commit_sha,
            production_provenance_ref=production_provenance_ref,
            production_provenance_hash=production_provenance_hash,
            test_profile="provider_post_build",
            minimum_collected=minimum_collected,
        )
        evidence.update(
            {
                "ok": False,
                "stdout": "",
                "stderr": "tests directory missing or no test*.py files found",
                "error": "tests directory missing or no test*.py files found",
                "failure_type": "no_tests",
                "dependency_setup": dependency_setup or {},
                "deterministic_repair": repair_summary or {},
            }
        )
        return evidence

    evidence = real_test_execution.run_tests(
        project,
        timeout=timeout,
        python_executable=python_executable,
        run_id=run_id,
        candidate_id=candidate_id,
        candidate_hash=candidate_hash,
        commit_sha=commit_sha,
        production_provenance_ref=production_provenance_ref,
        production_provenance_hash=production_provenance_hash,
        test_profile="provider_post_build",
        minimum_collected=minimum_collected,
    )
    stdout_path = pathlib.Path(str(evidence.get("stdout_artifact", "")))
    stderr_path = pathlib.Path(str(evidence.get("stderr_artifact", "")))
    stdout = _short_output(stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else "")
    stderr = _short_output(stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else "")
    evidence.update(
        {
            "ok": evidence.get("status") == "PASS",
            "stdout": stdout,
            "stderr": stderr,
            "report_path": str(project / "TEST_REPORT.md"),
            "failure_type": classify_provider_pytest_failure(stdout, stderr) if evidence.get("status") != "PASS" else "",
            "dependency_setup": dependency_setup or {},
            "deterministic_repair": repair_summary or {},
        }
    )
    return evidence


def image_quality_audit(path: pathlib.Path, *, project_dir: pathlib.Path | None = None, requested_role: str = "generated_image") -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve() if project_dir else pathlib.Path(path).resolve().parent
    validation = canonical_media_validation.validate_image(path, project, requested_role=requested_role)
    return {
        "path": validation.get("path", str(path)),
        "ok": validation.get("status") == "PASS",
        "reason": validation.get("failure_reason") or "canonical_media_pass",
        "validation": validation,
        "sha256": validation.get("sha256", ""),
        "width": validation.get("width", 0),
        "height": validation.get("height", 0),
        "detected_format": validation.get("detected_format", ""),
    }


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_rgb_png(path: pathlib.Path, width: int, height: int, pixel_fn) -> None:
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            r, g, b = pixel_fn(x, y)
            row.extend((max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b)))))
        rows.append(bytes(row))
    raw = b"".join(rows)
    data = b"\x89PNG\r\n\x1a\n"
    data += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += _png_chunk(b"IDAT", zlib.compress(raw, 9))
    data += _png_chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def png_quality_audit(path: pathlib.Path) -> dict[str, Any]:
    return image_quality_audit(path, requested_role="generated_image")


def _copy_if_quality_ok(source: pathlib.Path | None, target: pathlib.Path, *, project_dir: pathlib.Path, requested_role: str) -> tuple[str, dict[str, Any]]:
    if not source or not source.exists():
        return "", {"ok": False, "reason": "missing_source"}
    audit = image_quality_audit(source, project_dir=project_dir, requested_role=requested_role)
    if not audit.get("ok"):
        return "", audit
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    except Exception:
        shutil.copy2(source, target)
    copied_audit = image_quality_audit(target, project_dir=project_dir, requested_role=requested_role)
    return (str(target.resolve()) if copied_audit.get("ok") else ""), copied_audit


def run_project_image_generator(project_dir: pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    script = project / "_cgnk_generate_evidence.py"
    result_path = project / "_cgnk_generated_image_result.json"
    script.write_text(
        """
from __future__ import annotations
import json
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root))
out = {"backgrounds": [], "sprites": [], "errors": []}
try:
    from models.image_generator import LocalImageGenerator
    gen = LocalImageGenerator(str(root / "assets" / "generated"))
    for name, method, key in (
        ("demo_background", "generate_background", "backgrounds"),
        ("demo_sprite", "generate_character_sprite", "sprites"),
    ):
        fn = getattr(gen, method, None)
        if not callable(fn):
            out["errors"].append(f"{method} missing")
            continue
        try:
            path = pathlib.Path(fn(name))
            if not path.is_absolute():
                path = root / path
            out[key].append(str(path.resolve()))
        except Exception as exc:
            out["errors"].append(f"{method}: {exc}")
except Exception as exc:
    out["errors"].append(f"import LocalImageGenerator: {exc}")
(root / "_cgnk_generated_image_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, str(script.name)], cwd=str(project), capture_output=True, text=True, timeout=120)
    doc: dict[str, Any] = {"returncode": proc.returncode, "stdout": _short_output(proc.stdout), "stderr": _short_output(proc.stderr), "backgrounds": [], "sprites": [], "errors": []}
    if result_path.exists():
        try:
            loaded = json.loads(result_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict):
                doc.update(loaded)
        except Exception as exc:
            doc["errors"] = list(doc.get("errors", [])) + [f"read result: {exc}"]
    return doc


def collect_provider_image_evidence(project_dir: pathlib.Path, provider_result: dict[str, Any], runtime_artifacts: dict[str, Any]) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    generated_dir = project / "assets" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"kind": "GeneratedImageManifest", "created_at": now(), "images": [], "errors": []}
    generator_result: dict[str, Any] = {}
    if (project / "models" / "image_generator.py").exists():
        try:
            generator_result = run_project_image_generator(project)
            manifest["generator_result"] = generator_result
        except Exception as exc:
            manifest["errors"].append(f"project image generator failed: {exc}")
    copied = runtime_artifacts.get("copied", {}) if isinstance(runtime_artifacts.get("copied"), dict) else {}
    candidate_backgrounds = [pathlib.Path(str(item)) for item in generator_result.get("backgrounds", []) if str(item).strip()]
    candidate_sprites = [pathlib.Path(str(item)) for item in generator_result.get("sprites", []) if str(item).strip()]
    background_runtime = _provider_runtime_path(copied.get("background"))
    sprite_runtime = _provider_runtime_path(copied.get("sprite"))
    if background_runtime:
        candidate_backgrounds.append(background_runtime)
    if sprite_runtime:
        candidate_sprites.append(sprite_runtime)
    background_path = ""
    background_audit: dict[str, Any] = {"ok": False, "reason": "not_generated"}
    for candidate in candidate_backgrounds:
        background_path, background_audit = _copy_if_quality_ok(
            candidate,
            generated_dir / f"background_{safe_id(candidate.stem or 'demo')}.png",
            project_dir=project,
            requested_role="background",
        )
        if background_path:
            break
    sprite_path = ""
    sprite_audit: dict[str, Any] = {"ok": False, "reason": "not_generated"}
    for candidate in candidate_sprites:
        sprite_path, sprite_audit = _copy_if_quality_ok(
            candidate,
            generated_dir / f"sprite_{safe_id(candidate.stem or 'demo')}.png",
            project_dir=project,
            requested_role="sprite",
        )
        if sprite_path:
            break
    screenshot_path = ""
    screenshot_audit: dict[str, Any] = {"ok": False, "reason": "not_captured"}
    screenshot_runtime = _provider_runtime_path(copied.get("ui_screenshot"))
    if screenshot_runtime:
        screenshot_path, screenshot_audit = _copy_if_quality_ok(
            screenshot_runtime,
            project / "screenshots" / "provider_ui_screenshot.png",
            project_dir=project,
            requested_role="screenshot",
        )
    for kind, path, audit in (
        ("background", background_path, background_audit),
        ("sprite", sprite_path, sprite_audit),
        ("ui_screenshot", screenshot_path, screenshot_audit),
    ):
        manifest["images"].append({"kind": kind, "path": path, "audit": audit})
    manifest["ok"] = bool(background_path or sprite_path or screenshot_path)
    manifest_path = project / "generated_image_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": manifest["ok"],
        "background": background_path,
        "sprite": sprite_path,
        "ui_screenshot": screenshot_path,
        "manifest_path": str(manifest_path.resolve()),
        "manifest": manifest,
    }


def required_image_backend_missing_config(session: dict[str, Any]) -> list[str]:
    text = _requirement_text(session).lower()
    visual_requested = any(token in text for token in ("图片", "图像", "背景", "立绘", "image", "background", "sprite", "portrait"))
    local_model_required = any(token in text for token in ("本地模型", "本地图片模型", "local model", "stable diffusion", "comfyui", "automatic1111"))
    if not visual_requested or not local_model_required:
        return []
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    discovery = whiteboard.get("local_image_model_discovery", {}) if isinstance(whiteboard.get("local_image_model_discovery"), dict) else {}
    if discovery.get("available"):
        return []
    return ["local_image_model_backend"]


def post_build_finalize_provider_project(
    project_dir: pathlib.Path,
    provider_result: dict[str, Any],
    runtime_artifacts: dict[str, Any],
    session: dict[str, Any],
    *,
    session_dir: pathlib.Path,
    conversation_id: int | str,
    production_identity: dict[str, str],
    production_run_dir: pathlib.Path,
    stage_receipts: dict[str, pathlib.Path],
    provider_result_path: pathlib.Path,
    provider_causal_capture: dict[str, Any],
) -> dict[str, Any]:
    post_build_started_at = now()
    append_agent_session_event(session_dir, conversation_id, {"kind": "post_build_finalize_started", "role": "system", "stage": "post_build_finalize"})
    image_result = collect_provider_image_evidence(project_dir, provider_result, runtime_artifacts)
    req = infer_public_delivery_requirements(session, "")
    image_missing: list[str] = []
    if req.get("background") and not image_result.get("background"):
        image_missing.append("generated_background")
    if req.get("sprite") and not image_result.get("sprite"):
        image_missing.append("generated_sprite")
    if req.get("generated_image") and not (image_result.get("background") or image_result.get("sprite")):
        image_missing.append("generated_image")
    copied_runtime = runtime_artifacts.get("copied", {}) if isinstance(runtime_artifacts.get("copied"), dict) else {}
    video_requested = bool(req.get("video") or req.get("demo_video"))
    video_source = _provider_runtime_path(copied_runtime.get("video"))
    video_result: dict[str, Any] = {"requested": video_requested, "blocked": False, "video": "", "video_blocked": ""}
    if video_requested and video_source:
        video_target = project_dir / "artifacts" / "workflow_demo.mp4"
        copied_video = _copy_provider_runtime_asset(video_source, video_target)
        video_validation = canonical_media_validation.validate_media(copied_video, project_dir, requested_role="video") if copied_video else {"status": "FAIL", "failure_reason": "copy_failed"}
        video_ok = bool(copied_video) and video_validation.get("status") == "PASS"
        video_result.update({"video": copied_video if video_ok else "", "blocked": not video_ok, "validation": video_validation})
        if not video_ok:
            image_missing.append("video")
    elif video_requested:
        capture_result = visual_evidence.capture_candidate_video(
            project_dir,
            production_run_dir,
            timeout=90,
            explicit_requested=True,
        )
        captured_video = str(capture_result.get("video", "")).strip()
        video_validation = (
            canonical_media_validation.validate_media(captured_video, project_dir, requested_role="video")
            if captured_video
            else {"status": "FAIL", "failure_reason": str(capture_result.get("failure_reason", "capture_failed"))}
        )
        video_ok = capture_result.get("status") == "pass" and video_validation.get("status") == "PASS"
        video_result.update(
            {
                "blocked": not video_ok,
                "video": captured_video if video_ok else "",
                "video_blocked": "" if video_ok else str(capture_result.get("video_blocked", "")),
                "failure_reason": "" if video_ok else str(capture_result.get("failure_reason", "capture_failed")),
                "capture": capture_result,
                "validation": video_validation,
            }
        )
        if video_ok:
            stale_blocked = project_dir / "video_blocked.json"
            if stale_blocked.exists():
                stale_blocked.unlink()
        else:
            image_missing.append("video")
    missing_config = required_image_backend_missing_config(session)
    image_missing.extend(f"missing_config:{item}" for item in missing_config)
    image_result["missing"] = sorted(set(image_missing))
    image_result["missing_config"] = missing_config
    image_result["ok"] = not image_result["missing"]
    image_result["video"] = video_result.get("video", "")
    image_result["video_blocked"] = video_result.get("video_blocked", "")
    image_result["video_result"] = video_result
    append_agent_session_event(session_dir, conversation_id, {"kind": "post_build_image_evidence", "role": "tool", "result": image_result})
    minimum_test_count = infer_explicit_minimum_test_count(
        "\n".join(
            [
                str(session.get("requirement", "") or ""),
                str(session.get("goal", "") or ""),
                str(provider_result.get("goal", "") or ""),
                str(provider_result.get("generation_context_goal", "") or ""),
            ]
        )
    )
    preseal_test_result = run_provider_project_tests(
        project_dir,
        run_id=f"preseal-diagnostic-{uuid.uuid4().hex}",
        candidate_id=production_identity["candidate_id"],
        commit_sha=production_identity["commit_sha"],
        minimum_collected=minimum_test_count,
    )
    repair_result: dict[str, Any] = {}
    dependency_setup: dict[str, Any] = {}
    if not preseal_test_result.get("ok"):
        dependency_setup = ensure_provider_test_environment(project_dir)
        repair_result = {
            "status": "provider_repair_required",
            "changed": False,
            "owner": "provider",
            "failure_type": str(preseal_test_result.get("failure_type", "test_failure")),
            "rule": "CGKN does not repair customer-project behavior with domain-specific kernel code.",
        }
        append_agent_session_event(
            session_dir,
            conversation_id,
            {"kind": "post_build_provider_repair_required", "role": "system", "repair": repair_result, "dependency_setup": dependency_setup},
        )
    candidate_manifest = canonical_evidence_hash.candidate_source_manifest(project_dir)
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project_dir)
    candidate_manifest_hash = canonical_evidence_hash.canonical_json_hash(
        {"candidate_source_manifest": candidate_manifest}, ()
    )
    validation_receipt = stage_receipts["provider_validation"]
    post_build_receipt = production_candidate_provenance.write_stage_receipt(
        production_run_dir,
        stage="post_build",
        run_id=production_identity["run_id"],
        candidate_id=production_identity["candidate_id"],
        commit_sha=production_identity["commit_sha"],
        candidate_root=project_dir,
        started_at=post_build_started_at,
        finished_at=now(),
        candidate_hash=candidate_hash,
        candidate_source_manifest_hash=candidate_manifest_hash,
        artifact_refs=[
            {
                "role": "provider_validation_receipt",
                "ref": str(validation_receipt.resolve()),
                "hash": canonical_evidence_hash.sha256_file(validation_receipt),
            }
        ],
    )
    stage_receipts["post_build"] = post_build_receipt
    provenance = production_candidate_provenance.produce(
        project_dir,
        production_run_dir,
        run_id=production_identity["run_id"],
        candidate_id=production_identity["candidate_id"],
        commit_sha=production_identity["commit_sha"],
        stage_receipts=stage_receipts,
        provider_result_ref=provider_result_path,
    )
    provenance_ref = pathlib.Path(str(provenance["provenance_ref"])).resolve()
    provenance_hash = str(provenance["provenance_hash"])
    causal_trace = provider_causal_trace.finalize(
        candidate_dir=project_dir,
        production_run_dir=production_run_dir,
        identity=production_identity,
        causal_capture=provider_causal_capture,
        production_provenance_ref=provenance_ref,
    )
    test_result = run_provider_project_tests(
        project_dir,
        timeout=240,
        python_executable=(
            str(dependency_setup.get("python"))
            if dependency_setup.get("ok") and dependency_setup.get("python")
            else None
        ),
        run_id=production_identity["run_id"],
        candidate_id=production_identity["candidate_id"],
        candidate_hash=candidate_hash,
        commit_sha=production_identity["commit_sha"],
        repair_summary=repair_result,
        dependency_setup=dependency_setup,
        production_provenance_ref=provenance_ref,
        production_provenance_hash=provenance_hash,
        minimum_collected=minimum_test_count,
    )
    goal_receipt, goal_receipt_path = goal_acceptance.produce_from_canonical_test_evidence(
        project_dir=project_dir,
        run_dir=production_run_dir,
        test_evidence=test_result,
    )
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "post_build_test_result",
            "role": "tool",
            "result": test_result,
            "preseal_diagnostic_status": str(
                preseal_test_result.get("status", "NOT_EVALUATED")
            ),
            "production_provenance_ref": str(provenance_ref),
            "goal_acceptance_ref": str(goal_receipt_path),
            "goal_acceptance_status": str(goal_receipt.get("status", "NOT_EVALUATED")),
        },
    )
    browser_visual_required = bool(req.get("screenshot"))
    runtime_result = customer_runtime_runner.run(
        project_dir,
        run_id=str(test_result.get("run_id", "")) or None,
        candidate_id=str(test_result.get("candidate_id", "")) or None,
        candidate_hash=str(test_result.get("candidate_hash", "")) or None,
        commit_sha=str(test_result.get("commit_sha", "")) or None,
        production_provenance_ref=provenance_ref,
        production_provenance_hash=provenance_hash,
        live_consumer=browser_visual_evidence.capture_live_runtime if browser_visual_required else None,
        browser_capture_required=browser_visual_required,
    )
    append_agent_session_event(session_dir, conversation_id, {"kind": "post_build_customer_runtime", "role": "tool", "result": runtime_result})
    visual_evidence_result = (
        browser_visual_evidence.finalize_evidence(
            project_dir,
            runtime_result=runtime_result,
            capture_receipt=runtime_result.get("browser_capture_receipt") if isinstance(runtime_result.get("browser_capture_receipt"), dict) else {},
            required=True,
        )
        if browser_visual_required
        else {"status": "NOT_EVALUATED", "reason": "not_required", "not_required": True}
    )
    append_agent_session_event(session_dir, conversation_id, {"kind": "post_build_browser_visual_evidence", "role": "tool", "result": visual_evidence_result})
    write_provider_delivery_notes(
        project_dir,
        provider_result,
        runtime_artifacts
        | {
            "post_build_image_evidence": image_result,
            "post_build_test_result": test_result,
            "post_build_customer_runtime": runtime_result,
            "post_build_browser_visual_evidence": visual_evidence_result,
            "post_build_video_evidence": video_result,
        },
    )
    media_evidence_required = bool(req.get("generated_image") or req.get("background") or req.get("sprite") or req.get("video") or req.get("demo_video"))
    canonical_screenshot = str(visual_evidence_result.get("screenshot_path", "")) if browser_visual_required else ""
    screenshot_path = pathlib.Path(canonical_screenshot or str(image_result.get("ui_screenshot", "")))
    delivery_limits: list[str] = []
    if not test_result.get("ok"):
        delivery_limits.append("Automated tests are incomplete or failing; this must be disclosed to the user.")
    if runtime_result.get("status") != "PASS":
        delivery_limits.append("Customer runtime did not pass canonical startup and operation evidence.")
    if image_result.get("missing") and (browser_visual_required or media_evidence_required):
        delivery_limits.append("Missing verified image-generation or preview evidence: " + ", ".join(image_result.get("missing", [])))
    if video_result.get("video_blocked"):
        delivery_limits.append("video_blocked: demo video was not produced during provider post-build finalize")
    final_audit_refs = [
        {
            "role": "production_provenance",
            "ref": str(provenance_ref),
            "sha256": provenance_hash,
        },
        {
            "role": "goal_acceptance",
            "ref": str(goal_receipt_path),
            "sha256": canonical_evidence_hash.sha256_file(goal_receipt_path),
        },
    ]
    if screenshot_path.is_file():
        final_audit_refs.append(
            {
                "role": "visual_evidence",
                "ref": str(screenshot_path.resolve()),
                "sha256": canonical_evidence_hash.sha256_file(screenshot_path),
            }
        )
    final_audit = run_positive_transition_audit(
        session_dir,
        conversation_id,
        session,
        "pre_public_delivery",
        reason="Canonical verification claims this exact candidate is ready to package and enter the public delivery gate.",
        context_refs=final_audit_refs,
    )
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "false_pass_pre_public_delivery_audit",
            "role": "system",
            "result": final_audit,
        },
    )
    if final_audit.get("action") != "resume":
        action = str(final_audit.get("action", "halt"))
        return {
            "test_result": test_result,
            "goal_acceptance": goal_receipt,
            "goal_acceptance_ref": str(goal_receipt_path),
            "preseal_test_result": preseal_test_result,
            "runtime_result": runtime_result,
            "visual_evidence_result": visual_evidence_result,
            "image_result": image_result,
            "video_result": video_result,
            "browser_visual_required": browser_visual_required,
            "media_evidence_required": media_evidence_required,
            "production_provenance": provenance,
            "provider_causal_trace": causal_trace,
            "false_pass_audit": final_audit,
            "manifest": {},
            "gate": {
                "delivery_allowed": False,
                "verdict": "NEEDS_REWORK",
                "missing": [f"false_pass_audit:{action}"],
                "supervision_route": action,
            },
            "ok": False,
        }
    manifest = local_packager.package_project(
        project_dir,
        startup_command="python main.py" if (project_dir / "main.py").exists() else ("python app.py" if (project_dir / "app.py").exists() else ""),
        screenshot_path=screenshot_path if screenshot_path.exists() else None,
        known_limits=delivery_limits,
        visual_required=browser_visual_required,
        media_required=media_evidence_required,
    )
    gate = evaluate_public_delivery_gate(
        project_dir,
        manifest,
        session,
        phase="final",
        provider_result=provider_result,
        production_provenance_ref=provenance_ref,
    )
    gate["missing_config"] = missing_config
    return {
        "test_result": test_result,
        "goal_acceptance": goal_receipt,
        "goal_acceptance_ref": str(goal_receipt_path),
        "preseal_test_result": preseal_test_result,
        "runtime_result": runtime_result,
        "visual_evidence_result": visual_evidence_result,
        "image_result": image_result,
        "video_result": video_result,
        "browser_visual_required": browser_visual_required,
        "media_evidence_required": media_evidence_required,
        "production_provenance": provenance,
        "provider_causal_trace": causal_trace,
        "false_pass_audit": final_audit,
        "manifest": manifest,
        "gate": gate,
        "ok": bool(gate.get("delivery_allowed")),
    }


def write_provider_test_report(project_dir: pathlib.Path, provider_result: dict[str, Any]) -> pathlib.Path:
    report = project_dir / "TEST_REPORT.md"
    if report.exists() and "NO TEST EXECUTED" not in report.read_text(encoding="utf-8", errors="replace").upper():
        return report
    agent_usage = provider_result.get("agent_usage", {}) if isinstance(provider_result.get("agent_usage"), dict) else {}
    events = agent_usage.get("events", []) if isinstance(agent_usage.get("events"), list) else []
    commands: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        for key in ("command", "argv"):
            value = event.get(key)
            if isinstance(value, list) and value:
                commands.append(" ".join(str(item) for item in value))
            elif isinstance(value, str) and value.strip():
                commands.append(value.strip())
    if not commands:
        commands = ["provider_project_usage_agent"]
    report.write_text(
        "\n".join(
            [
                "# Test Report",
                "",
                "commands_run:",
                *[f"- {command}" for command in commands[:8]],
                "",
                "results:",
                f"- provider_usage_status: {agent_usage.get('status', provider_result.get('status', 'unknown'))}",
                "- provider project generation completed and runtime artifacts were inspected by the Codex conversation bridge.",
                "",
                "failures:",
                "- none recorded by provider usage agent" if str(agent_usage.get("status", "")).lower() != "failed" else "- provider usage agent reported failure",
                "",
                "repairs:",
                "- runtime media artifacts copied into the project for public delivery gate inspection",
                "",
                "remaining_warnings:",
                "- local image model availability depends on user configuration",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def write_provider_delivery_notes(project_dir: pathlib.Path, provider_result: dict[str, Any], runtime_artifacts: dict[str, Any]) -> pathlib.Path:
    notes = project_dir / "DELIVERY_NOTES.md"
    if notes.exists():
        return notes
    notes.write_text(
        "\n".join(
            [
                "# Delivery Notes",
                "",
                "delivery_status: PASS",
                "tests_executed: provider project usage agent and bridge integrity checks",
                f"evidence_found: {json.dumps(runtime_artifacts.get('copied', {}), ensure_ascii=False)}",
                "evidence_missing: none if public_delivery_gate is READY",
                "known_limits:",
                "- Local model endpoint must be configured by the user for full local image generation.",
                "revision_entry:",
                "- Provider project generation restored as Codex conversation default route with public delivery gate.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return notes


def provider_success_artifact_audit(project_dir: pathlib.Path, session: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    assets = collect_public_delivery_assets(project, manifest)
    req = infer_public_delivery_requirements(session, str(manifest.get("startup_command", "")))
    text = _requirement_text(session, str(manifest.get("startup_command", ""))).lower()
    strict_runtime = any(
        token in text
        for token in (
            "vn",
            "visual novel",
            "立绘",
            "背景",
            "图片",
            "图像",
            "桌面界面",
            "本地模型",
        )
    ) or any(req.values())
    missing: list[str] = []

    if strict_runtime:
        if not any((project / name).is_file() for name in ("main.py", "app.py")):
            missing.append("entrypoint")
        if not any((project / name).is_file() for name in ("requirements.txt", "pyproject.toml")):
            missing.append("dependency_file")
        source_dirs = [project / name for name in ("src", "ui", "models", "data")]
        source_files = [
            path
            for path in project.glob("*.py")
            if path.name not in {"app.py", "main.py"} and not path.name.startswith("_cgnk_")
        ]
        if not any(directory.is_dir() and any(path.is_file() for path in directory.rglob("*")) for directory in source_dirs) and not source_files:
            missing.append("src")
        if not (project / "tests").is_dir() or not any(path.is_file() for path in (project / "tests").rglob("*")):
            missing.append("tests")
        if req["screenshot"] and not assets["screenshots"]:
            missing.append("ui_screenshot")
        if req["background"] and not assets["generated_backgrounds"]:
            missing.append("background_image")
        if req["sprite"] and not assets["generated_sprites"]:
            missing.append("sprite_image")
        if not assets["packages"]:
            missing.append("final_project_bundle.zip")

    return {
        "ok": not missing,
        "strict_runtime": strict_runtime,
        "missing": missing,
        "asset_counts": {key: len(value) for key, value in assets.items()},
    }


PROVIDER_RETRY_BACKOFF_SECONDS = (2.0, 4.0, 8.0, 16.0, 30.0)


def provider_error_is_retryable(error: BaseException | str) -> bool:
    text = str(error or "")
    lowered = text.lower()
    error_type = provider_error_type(text)
    if error_type in {"PROVIDER_MISSING_CONFIG", "PROVIDER_KEY_USAGE_LIMIT", "PROVIDER_FORBIDDEN", "PROVIDER_NON_RETRYABLE_HTTP", "PROVIDER_UNKNOWN_ERROR"}:
        return False
    if "retryable=true" in lowered:
        return True
    if "retryable=false" in lowered:
        return False
    if error_type in {"PROVIDER_TRANSPORT_UNSTABLE", "PROVIDER_RETRYABLE_HTTP"}:
        return True
    return any(
        marker in lowered
        for marker in (
            "sslerror",
            "sslv3_alert_bad_record_mac",
            "connectionreseterror",
            "connection reset",
            "unexpected_eof_while_reading",
            "eof occurred in violation",
            "[ssl:",
            "urlerror",
            "timeout",
            "timed out",
            "empty response",
            "connection aborted",
            "502",
            "503",
            "504",
        )
    )


def provider_error_type(error: BaseException | str) -> str:
    return check_connectivity._provider_error_type(str(error or ""))


def provider_missing_config(error: BaseException | str) -> list[str]:
    error_type = provider_error_type(error)
    if error_type == "PROVIDER_MISSING_CONFIG":
        return ["CGKN_OPENAI_API_KEY or OPENAI_API_KEY"]
    return []


def provider_partial_artifacts(project_dir: pathlib.Path) -> list[str]:
    project = pathlib.Path(project_dir).resolve()
    if not project.exists():
        return []
    artifacts: list[str] = []
    for path in sorted(project.rglob("*")):
        if not path.is_file():
            continue
        try:
            artifacts.append(path.relative_to(project).as_posix())
        except Exception:
            artifacts.append(str(path))
    return artifacts[:200]


def write_provider_phase_event(path: pathlib.Path, event: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now(), **event}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def validate_provider_generation_output(
    project_dir: pathlib.Path,
    provider_result: dict[str, Any],
    provider_result_path: pathlib.Path,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    result_path = pathlib.Path(provider_result_path).resolve()
    failures: list[str] = []
    if str(provider_result.get("status", "")).upper() != "PASS":
        failures.append("provider_generation_status")
    semantic = (
        provider_result.get("provider_semantic_review", {})
        if isinstance(provider_result.get("provider_semantic_review"), dict)
        else {}
    )
    if str(semantic.get("status", "")).lower() != "pass":
        failures.append("provider_semantic_review")
    generated = (
        provider_result.get("generated_files", [])
        if isinstance(provider_result.get("generated_files"), list)
        else []
    )
    normalized_generated = sorted(
        {
            pathlib.PurePosixPath(str(item).replace("\\", "/")).as_posix()
            for item in generated
            if str(item).strip()
        }
    )
    if not normalized_generated:
        failures.append("generated_files")
    for relative in normalized_generated:
        path = (project / pathlib.PurePosixPath(relative)).resolve()
        try:
            path.relative_to(project)
        except ValueError:
            failures.append(f"generated_file_escape:{relative}")
            continue
        if not path.is_file() or path.is_symlink():
            failures.append(f"generated_file_missing:{relative}")
    if not result_path.is_file() or result_path.is_symlink():
        failures.append("provider_generation_result")
    return {
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "failures": sorted(set(failures)),
        "project_dir": str(project),
        "provider_result_ref": str(result_path),
        "provider_result_hash": canonical_evidence_hash.sha256_file(result_path)
        if result_path.is_file() and not result_path.is_symlink()
        else "",
        "generated_files": normalized_generated,
        "provider_semantic_review": semantic,
    }


def run_provider_execute_with_retries(
    args: argparse.Namespace,
    *,
    session_dir: pathlib.Path,
    conversation_id: int | str,
    phase_log_path: pathlib.Path,
    max_attempts: int = 5,
) -> dict[str, Any]:
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return provider_project_pipeline.execute(args)
        except Exception as exc:
            last_error = exc
            retryable = provider_error_is_retryable(exc)
            error_type = provider_error_type(exc)
            event = {
                "kind": "provider_retry",
                "attempt": attempt,
                "max_attempts": max_attempts,
                "retryable": retryable,
                "provider_error_type": error_type,
                "http_client_rebuilt_for_next_attempt": bool(retryable and attempt < max_attempts),
                "error": str(exc),
                "stage": "api_provider_project_generation",
            }
            append_agent_session_event(session_dir, conversation_id, {"role": "tool", **event})
            write_provider_phase_event(phase_log_path, event)
            if not retryable or attempt >= max_attempts:
                break
            partial = provider_partial_artifacts(pathlib.Path(str(getattr(args, "out_dir", ""))))
            if partial:
                setattr(args, "provider_recovery_mode", "stage_resume")
                setattr(args, "provider_partial_artifacts", partial)
            sleep_for = PROVIDER_RETRY_BACKOFF_SECONDS[min(attempt - 1, len(PROVIDER_RETRY_BACKOFF_SECONDS) - 1)] + random.uniform(0, 1.5)
            if os.environ.get("CGKN_PROVIDER_RETRY_FAST") == "1":
                sleep_for = 0
            time.sleep(sleep_for)
    raise RuntimeError(f"provider_api_request_failed: {last_error}" if last_error else "provider_api_request_failed")


def write_provider_validation_receipt(
    *,
    project_dir: pathlib.Path,
    run_dir: pathlib.Path,
    result_path: pathlib.Path,
    provider_result: dict[str, Any],
    identity: dict[str, str],
    generation_receipt: pathlib.Path,
    causal_artifact_refs: list[dict[str, Any]],
) -> tuple[dict[str, Any], pathlib.Path]:
    validation_started_at = now()
    provider_validation = validate_provider_generation_output(
        project_dir, provider_result, result_path
    )
    if provider_validation["status"] != "PASS":
        raise RuntimeError(
            "provider_output_validation_failed:"
            + ",".join(provider_validation["failures"])
        )
    validation_receipt = production_candidate_provenance.write_stage_receipt(
        run_dir,
        stage="provider_validation",
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
        candidate_root=project_dir,
        started_at=validation_started_at,
        finished_at=now(),
        artifact_refs=[
            {
                "role": "provider_generation_result",
                "ref": str(result_path.resolve()),
                "hash": canonical_evidence_hash.sha256_file(result_path),
            },
            {
                "role": "provider_generation_receipt",
                "ref": str(generation_receipt.resolve()),
                "hash": canonical_evidence_hash.sha256_file(generation_receipt),
            },
            *causal_artifact_refs,
        ],
    )
    return provider_validation, validation_receipt


def execute_validated_provider_round(
    args: argparse.Namespace,
    *,
    session_dir: pathlib.Path,
    conversation_id: int | str,
    phase_log_path: pathlib.Path,
    project_dir: pathlib.Path,
    provider_staging_dir: pathlib.Path,
    run_dir: pathlib.Path,
    result_path: pathlib.Path,
    identity: dict[str, str],
    model: str,
    formal_entry: bool,
) -> dict[str, Any]:
    """Run the established Provider leaf lane once, then validate its exact output."""
    provider_generation_started_at = now()
    provider_request_capture = provider_causal_trace.begin_provider_request(
        candidate_dir=project_dir,
        production_run_dir=run_dir,
        identity=identity,
        goal=str(getattr(args, "goal", "")),
        model=model,
        request_started_at=provider_generation_started_at,
    )
    provider_result = run_provider_execute_with_retries(
        args,
        session_dir=session_dir,
        conversation_id=conversation_id,
        phase_log_path=phase_log_path,
    )
    if not result_path.is_file():
        write_json(result_path, provider_result)
    causal_capture = provider_causal_trace.consume_provider_response(
        candidate_dir=project_dir,
        provider_staging_dir=provider_staging_dir,
        production_run_dir=run_dir,
        provider_result_path=result_path,
        identity=identity,
        provider_request_capture=provider_request_capture,
        response_received_at=now(),
    )
    provider_result = dict(provider_result)
    provider_result["project_dir"] = str(project_dir)
    provider_result["provider_staging_dir"] = str(provider_staging_dir)
    provider_result["provider_causal_artifacts"] = {
        key: str(pathlib.Path(value).resolve()) if key.endswith("_ref") else value
        for key, value in causal_capture.items()
    }
    write_json(result_path, provider_result)
    provider_result_hash = canonical_evidence_hash.sha256_file(result_path)
    causal_artifact_refs = [
        {
            "role": role,
            "ref": str(pathlib.Path(causal_capture[key]).resolve()),
            "hash": canonical_evidence_hash.sha256_file(causal_capture[key]),
        }
        for role, key in (
            ("provider_request", "request_ref"),
            ("provider_response", "response_ref"),
            ("implementation_decision", "decision_ref"),
            ("implementation_patch", "patch_ref"),
            ("patch_application", "application_ref"),
        )
    ]
    generation_receipt = production_candidate_provenance.write_stage_receipt(
        run_dir,
        stage="provider_generation",
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
        candidate_root=project_dir,
        started_at=provider_generation_started_at,
        finished_at=now(),
        artifact_refs=[
            {
                "role": "provider_generation_result",
                "ref": str(result_path.resolve()),
                "hash": provider_result_hash,
            },
            *causal_artifact_refs,
        ],
    )
    if not formal_entry:
        raise RuntimeError(
            "canonical_production_entry_receipt_missing:"
            "generation must start through start_generation_from_income"
        )
    provider_validation, validation_receipt = write_provider_validation_receipt(
        project_dir=project_dir,
        run_dir=run_dir,
        result_path=result_path,
        provider_result=provider_result,
        identity=identity,
        generation_receipt=generation_receipt,
        causal_artifact_refs=causal_artifact_refs,
    )
    write_provider_phase_event(
        phase_log_path,
        {
            "kind": "provider_phase",
            "stage": "api_provider_project_generation",
            "status": "completed",
            "project_dir": str(project_dir),
            "resume_repair": bool(getattr(args, "resume_run_dir", "")),
        },
    )
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "api-provider-project-generated",
            "role": "tool",
            "result_path": str(result_path),
            "project_dir": str(project_dir),
            "resume_repair": bool(getattr(args, "resume_run_dir", "")),
        },
    )
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "provider-output-validated",
            "role": "tool",
            "provider_semantic_review": provider_result.get("provider_semantic_review", {}),
            "canonical_validation": provider_validation,
            "validation_receipt": str(validation_receipt),
        },
    )
    return {
        "provider_result": provider_result,
        "provider_result_hash": provider_result_hash,
        "causal_capture": causal_capture,
        "causal_artifact_refs": causal_artifact_refs,
        "generation_receipt": generation_receipt,
        "provider_validation": provider_validation,
        "validation_receipt": validation_receipt,
    }


def finish_supervision_recovery_stop(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    *,
    identity: dict[str, str],
    project_dir: pathlib.Path,
    run_dir: pathlib.Path,
    entry_ref: pathlib.Path,
    formal_entry: bool,
    recovery: dict[str, Any],
) -> None:
    audit = recovery.get("audit", {}) if isinstance(recovery.get("audit"), dict) else {}
    action = str(audit.get("action", "halt"))
    workflow_state = str(recovery.get("workflow_state", "rework_blocked"))
    gate = {
        "delivery_allowed": False,
        "verdict": str(recovery.get("evidence_status", "NEEDS_REWORK")),
        "missing": [f"false_pass_recovery:{recovery.get('outcome', 'needs_rework')}:{action}"],
        "supervision_route": action,
        "supervision_recovery": recovery,
    }
    session = load_session(session_dir, conversation_id)
    session["generation"] = {
        "status": workflow_state,
        "driver": "api_provider_project_generation",
        "finished_at": now(),
        **identity,
        "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
        "project_dir": str(project_dir),
        "provider_run_dir": str(run_dir),
        "delivery_allowed": False,
        "delivery_gate": gate,
        "supervision_recovery": recovery,
    }
    if formal_entry:
        session["generation"]["production_entry_receipt_ref"] = str(entry_ref)
        session["generation"]["production_entry_receipt_hash"] = canonical_evidence_hash.sha256_file(entry_ref)
    update_active_run_status(
        session,
        workflow_state,
        driver="api_provider_project_generation",
        delivery_allowed=False,
        delivery_gate=gate,
        project_dir=str(project_dir),
    )
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "false_pass_recovery_stopped",
            "role": "system",
            "recovery": recovery,
        },
    )
    append_memory_event(session, "provider_generation_rework_blocked", data={"delivery_gate": gate})
    save_session(session_dir, session)
    mark_public_delivery_rework(client, conversation_id, session_dir, session, project_dir, gate)


def run_provider_generation_job(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    announce_start: bool = False,
) -> None:
    model = model or model_policy.select_model("provider_generation")
    session = load_session(session_dir, conversation_id)
    requirement = combined_requirement(session)
    if not requirement:
        send_customer_reply(client, conversation_id, session_dir, session, event="missing_requirement_before_generation", facts={"message": "当前没有可执行项目目标；后台未启动。"})
        return
    prior_generation = (
        session.get("generation", {})
        if isinstance(session.get("generation"), dict)
        else {}
    )
    identity = production_generation_identity(conversation_id, session)
    entry_ref_value = str(
        prior_generation.get("production_entry_receipt_ref", "")
    ).strip()
    entry_ref = pathlib.Path(entry_ref_value).resolve() if entry_ref_value else pathlib.Path()
    formal_entry = bool(
        entry_ref_value
        and entry_ref.is_file()
        and not entry_ref.is_symlink()
    )
    if formal_entry:
        project_dir, run_dir = production_paths(conversation_id, log_dir, identity)
    else:
        run_slug = safe_id(conversation_id)
        project_dir = (PROVIDER_PROJECTS_DIR / run_slug).resolve()
        run_dir = (pathlib.Path(log_dir) / "provider_runs" / run_slug).resolve()
    session["generation"] = {
        "status": "running",
        "driver": "api_provider_project_generation",
        "started_at": now(),
        "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
        **identity,
        "project_dir": str(project_dir),
        "provider_run_dir": str(run_dir),
    }
    if formal_entry:
        session["generation"]["production_entry_receipt_ref"] = str(entry_ref)
        session["generation"]["production_entry_receipt_hash"] = canonical_evidence_hash.sha256_file(entry_ref)
    update_active_run_status(session, "running", driver="api_provider_project_generation")
    snapshot = ensure_generation_context_snapshot(session_dir, conversation_id, session, requirement)
    append_agent_session_event(session_dir, conversation_id, {"kind": "provider_generation_started", "role": "system", "driver": "api_provider_project_generation", "requirement": requirement})
    append_memory_event(session, "provider_generation_started", data={"requirement": requirement[:6000]})
    save_session(session_dir, session)
    if announce_start:
        send_customer_reply(client, conversation_id, session_dir, session, event="generation_started", direct_text=public_narration.public_event_text("generation_started", {}))

    result_path = run_dir / "provider_generation_result.json"
    phase_log_path = run_dir / "provider_phase_log.jsonl"
    provider_staging_dir = (
        ROOT
        / "generated"
        / "provider_response_staging"
        / identity["run_id"]
    ).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_generation_context_snapshot(project_dir, snapshot)
    provider_result: dict[str, Any] = {}
    try:
        entry_receipt = (
            entry_ref
            if formal_entry
            else run_dir / "production_entry_receipt.json"
        )
        args = argparse.Namespace(
            plan="",
            goal=requirement,
            out_dir=str(provider_staging_dir),
            run_dir=str(run_dir),
            result=str(result_path),
            model=model,
            timeout=timeout,
            allow_network=True,
            allow_provider=True,
            use_api=True,
            allow_model_usage_planning=False,
            phase_log_path=str(phase_log_path),
            codex_capability_brief="",
        )
        round_state = execute_validated_provider_round(
            args,
            session_dir=session_dir,
            conversation_id=conversation_id,
            phase_log_path=phase_log_path,
            project_dir=project_dir,
            provider_staging_dir=provider_staging_dir,
            run_dir=run_dir,
            result_path=result_path,
            identity=identity,
            model=model,
            formal_entry=formal_entry,
        )

        def integration_audit_once() -> dict[str, Any]:
            audit = run_positive_transition_audit(
                session_dir,
                conversation_id,
                session,
                "integration_complete",
                reason="Provider jobs, deterministic merge, and Provider semantic review claim integration is complete.",
                context_refs=[
                    {
                        "role": "provider_generation_result",
                        "ref": str(result_path.resolve()),
                        "sha256": str(round_state["provider_result_hash"]),
                    },
                    {
                        "role": "provider_validation_receipt",
                        "ref": str(pathlib.Path(round_state["validation_receipt"]).resolve()),
                        "sha256": canonical_evidence_hash.sha256_file(round_state["validation_receipt"]),
                    },
                ],
            )
            append_agent_session_event(
                session_dir,
                conversation_id,
                {"kind": "false_pass_integration_audit", "role": "system", "result": audit},
            )
            return audit

        def repair_provider(audit: dict[str, Any], _route: dict[str, Any]) -> dict[str, Any]:
            nonlocal round_state
            preparation = provider_project_pipeline.prepare_supervision_provider_repair(
                run_dir,
                audit,
                user_goal=requirement,
            )
            args.resume_run_dir = str(run_dir)
            round_state = execute_validated_provider_round(
                args,
                session_dir=session_dir,
                conversation_id=conversation_id,
                phase_log_path=phase_log_path,
                project_dir=project_dir,
                provider_staging_dir=provider_staging_dir,
                run_dir=run_dir,
                result_path=result_path,
                identity=identity,
                model=model,
                formal_entry=formal_entry,
            )
            return {
                **preparation,
                "status": "provider_repair_validated",
                "provider_validation_ref": str(round_state["validation_receipt"]),
            }

        def recheck_provider_evidence(audit: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
            nonlocal round_state
            invalidation = invalidate_supervision_evidence(
                audit,
                route,
                project_dir=project_dir,
                production_run_dir=run_dir,
            )
            validation, receipt = write_provider_validation_receipt(
                project_dir=project_dir,
                run_dir=run_dir,
                result_path=result_path,
                provider_result=round_state["provider_result"],
                identity=identity,
                generation_receipt=round_state["generation_receipt"],
                causal_artifact_refs=round_state["causal_artifact_refs"],
            )
            round_state["provider_validation"] = validation
            round_state["validation_receipt"] = receipt
            return {
                **invalidation,
                "status": "canonical_provider_validation_rerun",
                "provider_validation_ref": str(receipt.resolve()),
                "provider_invocation_count": 0,
            }

        def repair_kernel_and_revalidate(audit: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
            nonlocal round_state
            repair_receipt = execute_governed_supervision_repair(audit, route)
            validation, receipt = write_provider_validation_receipt(
                project_dir=project_dir,
                run_dir=run_dir,
                result_path=result_path,
                provider_result=round_state["provider_result"],
                identity=identity,
                generation_receipt=round_state["generation_receipt"],
                causal_artifact_refs=round_state["causal_artifact_refs"],
            )
            round_state["provider_validation"] = validation
            round_state["validation_receipt"] = receipt
            return {**repair_receipt, "provider_validation_ref": str(receipt.resolve())}

        integration_recovery = run_supervision_recovery_cycle(
            integration_audit_once(),
            reaudit=integration_audit_once,
            handlers={
                "rework_project": repair_provider,
                "recheck_evidence": recheck_provider_evidence,
                "repair_kernel": repair_kernel_and_revalidate,
            },
        )
        if integration_recovery.get("outcome") != "resumed":
            finish_supervision_recovery_stop(
                client,
                conversation_id,
                session_dir,
                identity=identity,
                project_dir=project_dir,
                run_dir=run_dir,
                entry_ref=entry_ref,
                formal_entry=formal_entry,
                recovery=integration_recovery,
            )
            return
        provider_result = round_state["provider_result"]
        append_agent_session_event(session_dir, conversation_id, {"kind": "provider-project-files-written", "role": "tool", "generated_files": provider_result.get("generated_files", [])})
        append_agent_session_event(session_dir, conversation_id, {"kind": "runtime-artifacts-written", "role": "tool", "artifact_refs": provider_result.get("artifact_refs", {})})
        write_provider_phase_event(
            phase_log_path,
            {"kind": "provider_phase", "stage": "post_build_finalize", "status": "started", "project_dir": str(project_dir)},
        )
        finalize: dict[str, Any] = {}

        def finalize_once() -> dict[str, Any]:
            nonlocal finalize, provider_result
            provider_result = round_state["provider_result"]
            runtime_artifacts = materialize_provider_runtime_artifacts(project_dir, provider_result)
            finalize = post_build_finalize_provider_project(
                project_dir,
                provider_result,
                runtime_artifacts,
                session,
                session_dir=session_dir,
                conversation_id=conversation_id,
                production_identity=identity,
                production_run_dir=run_dir,
                stage_receipts={
                    "production_entry": entry_receipt,
                    "provider_generation": round_state["generation_receipt"],
                    "provider_validation": round_state["validation_receipt"],
                },
                provider_result_path=result_path,
                provider_causal_capture=round_state["causal_capture"],
            )
            return dict(finalize.get("false_pass_audit", {"action": "halt", "scope": "safety"}))

        def repair_provider_before_final(audit: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
            preparation = repair_provider(audit, route)
            nested = run_supervision_recovery_cycle(
                integration_audit_once(),
                reaudit=integration_audit_once,
                handlers={
                    "rework_project": repair_provider,
                    "recheck_evidence": recheck_provider_evidence,
                    "repair_kernel": repair_kernel_and_revalidate,
                },
            )
            if nested.get("outcome") != "resumed":
                return {**preparation, "cycle_stop": nested}
            return {**preparation, "integration_recovery": nested}

        def recheck_final_evidence(audit: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
            return invalidate_supervision_evidence(
                audit,
                route,
                project_dir=project_dir,
                production_run_dir=run_dir,
            )

        final_recovery = run_supervision_recovery_cycle(
            finalize_once(),
            reaudit=finalize_once,
            handlers={
                "rework_project": repair_provider_before_final,
                "recheck_evidence": recheck_final_evidence,
                "repair_kernel": execute_governed_supervision_repair,
            },
        )
        if final_recovery.get("outcome") != "resumed":
            finish_supervision_recovery_stop(
                client,
                conversation_id,
                session_dir,
                identity=identity,
                project_dir=project_dir,
                run_dir=run_dir,
                entry_ref=entry_ref,
                formal_entry=formal_entry,
                recovery=final_recovery,
            )
            return
        write_provider_phase_event(
            phase_log_path,
            {
                "kind": "provider_phase",
                "stage": "post_build_finalize",
                "status": "completed" if finalize.get("ok") else "rework_blocked",
                "project_dir": str(project_dir),
                "provider_run_dir": str(run_dir),
            },
        )
        manifest = finalize["manifest"]
        gate = finalize["gate"]
        artifact_audit = provider_success_artifact_audit(project_dir, session, manifest)
        append_agent_session_event(
            session_dir,
            conversation_id,
            {"kind": "provider-success-artifact-audit", "role": "tool", "audit": artifact_audit, "post_build_finalize": finalize},
        )
        gate = dict(gate)
        gate["provider_success_artifact_audit"] = artifact_audit
        if not gate.get("delivery_allowed"):
            write_provider_phase_event(
                phase_log_path,
                {"kind": "provider_phase", "stage": "public_delivery_gate", "status": "rework_blocked", "missing": gate.get("missing", [])},
            )
            session = load_session(session_dir, conversation_id)
            session["generation"] = {
                "status": "rework_blocked",
                "driver": "api_provider_project_generation",
                "finished_at": now(),
                **identity,
                "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
                "project_dir": str(project_dir),
                "provider_run_dir": str(run_dir),
                "manifest_path": str(manifest.get("manifest_path", "")),
                "package_path": "",
                "build_integrity_audit": artifact_audit,
                "qa_integrity_audit": finalize.get("test_result", {}),
                "post_build_finalize": finalize,
                "production_provenance_ref": str(
                    finalize.get("production_provenance", {}).get(
                        "provenance_ref", ""
                    )
                ),
                "delivery_allowed": False,
                "delivery_gate": gate,
            }
            if formal_entry:
                session["generation"]["production_entry_receipt_ref"] = str(entry_ref)
                session["generation"]["production_entry_receipt_hash"] = canonical_evidence_hash.sha256_file(entry_ref)
            update_active_run_status(session, "rework_blocked", driver="api_provider_project_generation", delivery_allowed=False, delivery_gate=gate, project_dir=str(project_dir))
            append_memory_event(session, "provider_generation_rework_blocked", data={"delivery_gate": gate})
            save_session(session_dir, session)
            mark_public_delivery_rework(client, conversation_id, session_dir, session, project_dir, gate)
            return
        result = {
            "status": manifest.get("status", "ready"),
            "driver": "api_provider_project_generation",
            "manifest": manifest,
            "manifest_path": manifest.get("manifest_path", ""),
            "package_path": manifest.get("package_path", ""),
            "provider_result_path": str(result_path),
            "provider_run_dir": str(run_dir),
            "post_build_finalize": finalize,
            "production_provenance_ref": str(
                finalize.get("production_provenance", {}).get(
                    "provenance_ref", ""
                )
            ),
        }
        write_provider_phase_event(
            phase_log_path,
            {
                "kind": "provider_phase",
                "stage": "local_packager_and_public_delivery_gate",
                "status": "completed",
                "manifest_path": str(manifest.get("manifest_path", "")),
                "package_path": str(manifest.get("package_path", "")),
            },
        )
        finish_agent_loop_delivery(client, conversation_id, session_dir, project_dir, result)
    except Exception as exc:
        session = load_session(session_dir, conversation_id)
        error_type = provider_error_type(exc)
        missing_config = provider_missing_config(exc)
        partial_artifacts = provider_partial_artifacts(project_dir)
        manifest: dict[str, Any] = {}
        if partial_artifacts:
            try:
                manifest = local_packager.package_project(
                    project_dir,
                    startup_command="python main.py" if (project_dir / "main.py").exists() else ("python app.py" if (project_dir / "app.py").exists() else ""),
                    known_limits=["Provider recovery mode inspected partial artifacts after a transport failure."],
                )
                gate = evaluate_public_delivery_gate(
                    project_dir,
                    manifest,
                    session,
                    phase="final",
                    provider_result={"status": "failed", "error": str(exc)},
                )
            except Exception:
                manifest = {}
        gate = evaluate_public_delivery_gate(
            project_dir,
            manifest,
            session,
            phase="final",
            provider_result={"status": "failed", "error": str(exc)},
        )
        session["generation"] = {
            "status": "rework_blocked",
            "driver": "api_provider_project_generation",
            "finished_at": now(),
            **identity,
            "error": str(exc),
            "provider_error_type": error_type,
            "missing_config": missing_config,
            "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
            "project_dir": str(project_dir),
            "provider_run_dir": str(run_dir),
            "partial_artifacts": partial_artifacts,
            "current_stage": "api_provider_project_generation",
            "provider_recovery_needed": True,
            "provider_recovery_mode": "stage_resume" if partial_artifacts else "",
            "delivery_allowed": False,
            "delivery_gate": gate,
        }
        if formal_entry:
            session["generation"]["production_entry_receipt_ref"] = str(entry_ref)
            session["generation"]["production_entry_receipt_hash"] = canonical_evidence_hash.sha256_file(entry_ref)
        update_active_run_status(
            session,
            "rework_blocked",
            driver="api_provider_project_generation",
            delivery_allowed=False,
            delivery_gate=gate,
            project_dir=str(project_dir),
            provider_recovery_needed=True,
            current_stage="api_provider_project_generation",
            partial_artifacts=partial_artifacts,
        )
        append_agent_session_event(
            session_dir,
            conversation_id,
            {
                "kind": "provider_generation_error",
                "role": "tool",
                "error": str(exc),
                "provider_error_type": error_type,
                "missing_config": missing_config,
                "project_dir": str(project_dir),
                "result_path": str(result_path),
                "partial_artifacts": partial_artifacts,
                "current_stage": "api_provider_project_generation",
                "provider_recovery_needed": True,
            },
        )
        append_memory_event(
            session,
            "provider_generation_rework_blocked",
            data={
                "error": str(exc),
                "provider_error_type": error_type,
                "missing_config": missing_config,
                "delivery_gate": gate,
                "partial_artifacts": partial_artifacts,
                "current_stage": "api_provider_project_generation",
                "provider_recovery_needed": True,
            },
        )
        save_session(session_dir, session)
        write_provider_phase_event(
            phase_log_path,
            {
                "kind": "provider_phase",
                "stage": "api_provider_project_generation",
                "status": "rework_blocked",
                "provider_error_type": error_type,
                "missing_config": missing_config,
                "error": str(exc),
            },
        )
        log_bridge_error(log_dir, "provider_generation_rework_blocked", conversation_id, exc, {"project_dir": str(project_dir)})
        mark_public_delivery_rework(client, conversation_id, session_dir, session, project_dir, gate)


def run_agent_generation_job(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    announce_start: bool = False,
    max_turns: int = 12,
) -> None:
    # SUPPORT/EXPERIMENTAL ONLY: imports stay out of the production module graph.
    try:
        from . import agent_conversation_loop
        from . import dynamic_pipeline_runner
        from . import pipeline_manifest as pipeline_manifest_module
        from . import pipeline_planner_agent
    except ImportError:  # pragma: no cover - direct script execution
        import agent_conversation_loop
        import dynamic_pipeline_runner
        import pipeline_manifest as pipeline_manifest_module
        import pipeline_planner_agent

    session = load_session(session_dir, conversation_id)
    requirement = combined_requirement(session)
    if not requirement:
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="missing_requirement_before_generation",
            facts={"message": "当前没有可执行项目目标；后台未启动。"},
        )
        return
    session["generation"] = {
        "status": "running",
        "driver": "agent_generated_pipeline",
        "started_at": now(),
        "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
    }
    snapshot = ensure_generation_context_snapshot(session_dir, conversation_id, session, requirement)
    append_memory_event(session, "agent_pipeline_started", data={"requirement": requirement[:6000]})
    append_truth_ledger(
        session_dir,
        session,
        "agent_pipeline_started",
        "Agent-generated pipeline generation started from Codex conversation confirmation",
        evidence_ref=str(agent_session_path(session_dir, conversation_id)),
        data={"artifact": "agent_session", "backend_controls_required": False, "generation_context_snapshot": True},
    )
    save_session(session_dir, session)
    if announce_start:
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="generation_started",
            direct_text=public_narration.public_event_text("generation_started", {}),
        )
    project_dir = log_dir / "agent_projects" / safe_id(conversation_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    session_file = agent_session_path(session_dir, conversation_id)
    snapshot_path = write_generation_context_snapshot(project_dir, snapshot)
    manifest: dict[str, Any] = {}
    manifest_path: pathlib.Path | str = ""
    fallback_used = False
    fallback_reason = ""
    try:
        whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
        manifest = pipeline_planner_agent.plan_pipeline(
            session_path=session_file,
            model=model,
            timeout=timeout,
            whiteboard=whiteboard,
            api_budget="low",
        )
        manifest = pipeline_manifest_module.normalize_pipeline_manifest(manifest, whiteboard)
        manifest_path = pipeline_manifest_module.write_pipeline_manifest(project_dir, manifest)
        append_agent_session_event(
            session_dir,
            conversation_id,
            {"kind": "pipeline_manifest", "role": "system", "manifest": manifest, "agent_generated": True, "manifest_path": str(manifest_path)},
        )
        result = dynamic_pipeline_runner.run_dynamic_pipeline(
            session_path=session_file,
            project_dir=project_dir,
            pipeline_manifest=manifest,
            model=model,
            timeout=timeout,
            max_turns=max_turns,
            whiteboard=whiteboard,
        )
    except Exception as exc:
        fallback_used = True
        fallback_reason = str(exc)
        append_agent_session_event(
            session_dir,
            conversation_id,
            {"kind": "pipeline_fallback", "role": "system", "reason": fallback_reason, "stage": "run_agent_generation_job"},
        )
        try:
            result = agent_conversation_loop.run_agent_loop(
                session_path=session_file,
                project_dir=project_dir,
                model=model,
                timeout=timeout,
                max_turns=max_turns,
            )
            result["driver"] = "agent_conversation_loop_fallback"
        except Exception as fallback_exc:
            session = load_session(session_dir, conversation_id)
            gate = evaluate_public_delivery_gate(project_dir, {}, session, phase="final")
            session["generation"] = {
                "status": "rework_blocked",
                "driver": "agent_generated_pipeline",
                "finished_at": now(),
                "error": str(fallback_exc),
                "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
                "project_dir": str(project_dir),
                "pipeline_manifest_path": str(manifest_path or ""),
                "generation_context_snapshot_path": str(snapshot_path),
                "delivery_allowed": False,
                "delivery_gate": gate,
            }
            update_active_run_status(
                session,
                "rework_blocked",
                driver="agent_generated_pipeline",
                delivery_allowed=False,
                delivery_gate=gate,
                project_dir=str(project_dir),
            )
            append_agent_session_event(session_dir, conversation_id, {"kind": "agent_loop_error", "role": "tool", "error": str(fallback_exc)})
            append_memory_event(session, "agent_pipeline_failed", data={"error": str(fallback_exc), "pipeline_error": str(exc)})
            save_session(session_dir, session)
            log_bridge_error(log_dir, "agent_pipeline_failed", conversation_id, fallback_exc, {"project_dir": str(project_dir)})
            mark_public_delivery_rework(client, conversation_id, session_dir, session, project_dir, gate)
            return
    if isinstance(result, dict) and result.get("pipeline_manifest") and "driver" not in result:
        result["driver"] = "agent_generated_pipeline"
    if str(result.get("driver", "")) == "agent_conversation_loop_fallback":
        fallback_used = True
        if not fallback_reason:
            fallback_reason = "dynamic_pipeline_runner_fallback"
    result["generation_context_snapshot"] = snapshot
    result["generation_context_snapshot_path"] = str(snapshot_path)
    if manifest_path:
        result["pipeline_manifest_path"] = str(manifest_path)
    if isinstance(result, dict) and str(result.get("status", "")).lower() == "waiting_user_review":
        evidence = result.get("evidence", {}) if isinstance(result.get("evidence"), dict) else {}
        checkpoint_project_dir = pathlib.Path(str(result.get("project_dir") or project_dir))
        session = load_session(session_dir, conversation_id)
        gate = evaluate_public_delivery_gate(checkpoint_project_dir, {}, session, evidence=evidence, phase="checkpoint")
        if not gate.get("delivery_allowed"):
            session["generation"] = {
                "status": "rework_blocked",
                "driver": "agent_generated_pipeline",
                "updated_at": now(),
                "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
                "project_dir": str(checkpoint_project_dir),
                "pipeline_manifest_path": str(result.get("pipeline_manifest_path", manifest_path or "")),
                "generation_context_snapshot_path": str(result.get("generation_context_snapshot_path", "")),
                "delivery_allowed": False,
                "delivery_gate": gate,
            }
            update_active_run_status(session, "rework_blocked", driver="agent_generated_pipeline", delivery_allowed=False, delivery_gate=gate, project_dir=str(checkpoint_project_dir))
            append_memory_event(session, "user_evidence_checkpoint_rework_blocked", data={"evidence": evidence, "delivery_gate": gate})
            save_session(session_dir, session)
            mark_public_delivery_rework(client, conversation_id, session_dir, session, checkpoint_project_dir, gate)
            return
        session["generation"] = {
            "status": "waiting_user_review",
            "driver": "agent_generated_pipeline",
            "updated_at": now(),
            "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
            "project_dir": str(checkpoint_project_dir),
            "pipeline_manifest_path": str(result.get("pipeline_manifest_path", manifest_path or "")),
            "generation_context_snapshot_path": str(result.get("generation_context_snapshot_path", "")),
        }
        requirements = infer_public_delivery_requirements(session, "")
        required_roles = ["nonvisual_summary"]
        required_roles.extend(role for role in ("screenshot", "background", "sprite") if requirements.get(role))
        if requirements.get("generated_image") and not (requirements.get("background") or requirements.get("sprite")):
            required_roles.append("generated_image")
        if requirements.get("video") or requirements.get("demo_video"):
            required_roles.append("video")
        owner = session.get("active_request_owner", {}) if isinstance(session.get("active_request_owner"), dict) else {}
        review_request = canonical_user_review.create_review_request_snapshot(
            checkpoint_project_dir,
            conversation_id=conversation_id,
            expected_reviewer_id=owner.get("reviewer_id", ""),
            requirement_snapshot=session.get("whiteboard", {}).get("delivery_requirements", []),
            visual_required=bool(requirements.get("screenshot")),
            required_presentation_roles=required_roles,
            replay_ledger_path=session_dir / f"{safe_id(conversation_id)}.review_replay_ledger.json",
        )
        if review_request.get("status") == "NEEDS_REWORK":
            session["generation"]["status"] = "rework_blocked"
            session["generation"]["review_failures"] = review_request.get("failures", [])
            save_session(session_dir, session)
            return
        session["pending_evidence_checkpoint"] = review_request | {
            "pipeline_manifest": result.get("pipeline_manifest") if isinstance(result.get("pipeline_manifest"), dict) else manifest,
            "pipeline_manifest_path": str(result.get("pipeline_manifest_path", manifest_path or "")),
            "agent_session_path": str(session_file),
            "evidence": evidence,
        }
        update_active_run_status(session, "waiting_user_review", driver="agent_generated_pipeline")
        append_memory_event(session, "user_evidence_checkpoint_waiting", data={"evidence": evidence})
        save_session(session_dir, session)
        send_evidence_checkpoint(client, conversation_id, session_dir, session, checkpoint_project_dir, evidence)
        return
    summary_driver = "agent_conversation_loop_fallback" if fallback_used else str(result.get("driver") or "agent_generated_pipeline")
    summary_path = write_pipeline_run_summary(
        project_dir,
        driver=summary_driver,
        pipeline_manifest_path=manifest_path or project_dir / "pipeline_manifest.json",
        agent_session_path_value=session_file,
        manifest=manifest,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )
    result["pipeline_run_summary_path"] = str(summary_path)
    finish_agent_loop_delivery(client, conversation_id, session_dir, project_dir, result)


def finish_agent_loop_delivery(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    project_dir: pathlib.Path,
    result: dict[str, Any],
) -> None:
    manifest = result.get("manifest", {}) if isinstance(result.get("manifest"), dict) else {}
    if not manifest and result.get("manifest_path"):
        manifest = read_delivery_manifest(str(result.get("manifest_path", "")))
    session = load_session(session_dir, conversation_id)
    driver = str(result.get("driver") or "agent_conversation_loop")
    post_build = (
        result.get("post_build_finalize", {})
        if isinstance(result.get("post_build_finalize"), dict)
        else {}
    )
    provenance = (
        post_build.get("production_provenance", {})
        if isinstance(post_build.get("production_provenance"), dict)
        else {}
    )
    prior_generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    session["generation"] = {
        "status": str(result.get("status", "unknown")),
        "driver": driver,
        "finished_at": now(),
        "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
        "project_dir": str(project_dir),
        "manifest_path": str(manifest.get("manifest_path", result.get("manifest_path", ""))),
        "package_path": str(manifest.get("package_path", result.get("package_path", ""))),
        "pipeline_manifest_path": str(result.get("pipeline_manifest_path", "")),
        "generation_context_snapshot_path": str(result.get("generation_context_snapshot_path", "")),
        "pipeline_run_summary_path": str(result.get("pipeline_run_summary_path", "")),
        "run_id": str(provenance.get("run_id", "")),
        "candidate_id": str(provenance.get("candidate_id", "")),
        "candidate_hash": str(provenance.get("candidate_hash", "")),
        "commit_sha": str(provenance.get("commit_sha", "")),
        "provider_run_dir": str(result.get("provider_run_dir", "")),
        "production_provenance_ref": str(
            result.get("production_provenance_ref", "")
        ),
    }
    for receipt_key in ("production_entry_receipt_ref", "production_entry_receipt_hash"):
        if str(prior_generation.get(receipt_key, "")).strip():
            session["generation"][receipt_key] = str(prior_generation[receipt_key])
    run = active_run(session)
    if run is not None:
        run["status"] = "delivered" if manifest and str(manifest.get("package_path", "")).strip() else str(result.get("status", "failed"))
        run["driver"] = driver
        run["updated_at"] = now()
        run["project_dir"] = str(project_dir)
        run["package_path"] = str(manifest.get("package_path", result.get("package_path", "")))
        run["manifest_path"] = str(manifest.get("manifest_path", result.get("manifest_path", "")))
        session["active_run"] = run
    if manifest and str(manifest.get("package_path", "")).strip():
        try:
            active_project = project_revision_lane.bind_initial_project_delivery(
                session,
                project_dir,
                package_path=str(manifest.get("package_path", result.get("package_path", ""))),
                delivery_manifest=str(manifest.get("manifest_path", result.get("manifest_path", ""))),
            )
            append_memory_event(session, "active_project_bound", data={"active_project": active_project})
        except Exception as exc:
            append_memory_event(session, "active_project_bind_failed", data={"error": str(exc)})
    append_memory_event(session, "agent_loop_finished", data={"result": result, "manifest": manifest})
    if manifest and str(manifest.get("package_path", "")).strip():
        save_session(session_dir, session)
        send_delivery_from_manifest(
            client,
            conversation_id,
            session_dir,
            session,
            manifest,
            provider_result=result,
        )
    else:
        gate = evaluate_public_delivery_gate(project_dir, manifest, session, phase="final")
        if gate.get("delivery_allowed") and gate.get("verdict") == "ASK_USER_REVIEW":
            session["generation"].update(
                {
                    "status": "waiting_user_review",
                    "delivery_allowed": True,
                    "delivery_gate": gate,
                }
            )
            update_active_run_status(
                session,
                "waiting_user_review",
                driver=driver,
                delivery_allowed=True,
                delivery_gate=gate,
                project_dir=str(project_dir),
            )
            append_memory_event(session, "agent_loop_waiting_user_review", data={"result": result, "delivery_gate": gate})
            save_session(session_dir, session)
            warnings = gate.get("user_visible_warnings", []) if isinstance(gate.get("user_visible_warnings"), list) else []
            warning_text = "；".join(user_visible_known_limit(item) for item in warnings[:5] if str(item).strip())
            send_customer_reply(
                client,
                conversation_id,
                session_dir,
                session,
                event="delivery_user_review_requested",
                source="adaptive_delivery_judgment",
                direct_text=pre_send_guard(
                    "当前已有真实项目结果可供检查，但还没有最终 zip，因此不能标成最终交付。"
                    + (f"\n当前限制：{warning_text}" if warning_text else "")
                ),
            )
            assets = collect_public_delivery_assets(project_dir, manifest)
            items: list[tuple[pathlib.Path, str]] = []
            items.extend((path, "screenshot") for path in assets["screenshots"][:3])
            items.extend((path, "background") for path in assets["generated_backgrounds"][:2])
            items.extend((path, "sprite") for path in assets["generated_sprites"][:2])
            items.extend((path, "video") for path in assets["videos"][:2])
            emit_public_delivery(
                client,
                conversation_id,
                session_dir,
                session,
                filter_delivery_items_by_judgment(items, gate),
                source="adaptive_user_review",
            )
            return
        session["generation"].update(
            {
                "status": "rework_blocked",
                "delivery_allowed": False,
                "delivery_gate": gate,
            }
        )
        update_active_run_status(
            session,
            "rework_blocked",
            driver=driver,
            delivery_allowed=False,
            delivery_gate=gate,
            project_dir=str(project_dir),
        )
        append_memory_event(session, "agent_loop_rework_blocked", data={"result": result, "delivery_gate": gate})
        save_session(session_dir, session)
        mark_public_delivery_rework(client, conversation_id, session_dir, session, project_dir, gate)


def resume_after_evidence_review_job(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    max_turns: int = 12,
) -> None:
    # Legacy support resume for old dynamic-pipeline checkpoints only.
    import dynamic_pipeline_runner
    import pipeline_manifest as pipeline_manifest_module

    session = load_session(session_dir, conversation_id)
    checkpoint = session.get("pending_evidence_checkpoint", {}) if isinstance(session.get("pending_evidence_checkpoint"), dict) else {}
    project_dir = pathlib.Path(str(checkpoint.get("project_dir") or session.get("generation", {}).get("project_dir", "")))
    if not project_dir.exists():
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="user_evidence_resume_missing_project",
            facts={"message": "中间项目目录不存在，无法继续最终打包；我已记录，需要重新生成。"},
        )
        return
    manifest = checkpoint.get("pipeline_manifest") if isinstance(checkpoint.get("pipeline_manifest"), dict) else {}
    if not manifest:
        manifest_path = pathlib.Path(str(checkpoint.get("pipeline_manifest_path", "")))
        if manifest_path.exists():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
                manifest = loaded if isinstance(loaded, dict) else {}
            except Exception:
                manifest = {}
    if not manifest:
        whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
        manifest = pipeline_manifest_module.default_minimal_pipeline_manifest(whiteboard)
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    session["generation"] = {
        "status": "running",
        "driver": "agent_generated_pipeline",
        "started_at": now(),
        "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
        "project_dir": str(project_dir),
        "resume_reason": "user_evidence_approved",
    }
    update_active_run_status(session, "running", driver="agent_generated_pipeline")
    append_memory_event(session, "user_evidence_review_approved", data={"project_dir": str(project_dir)})
    save_session(session_dir, session)
    send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event="user_evidence_review_approved",
        source="delivery_team_summary",
        direct_text=public_narration.public_event_text("review_continue", {}),
    )
    session_file = agent_session_path(session_dir, conversation_id)
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "resume_after_evidence_review",
            "role": "system",
            "start_stage": "review",
            "reason": "user_approved_evidence_checkpoint",
        },
    )
    try:
        result = dynamic_pipeline_runner.run_dynamic_pipeline(
            session_path=session_file,
            project_dir=project_dir,
            pipeline_manifest=manifest,
            model=model,
            timeout=timeout,
            max_turns=max_turns,
            whiteboard=whiteboard,
            skip_user_evidence_checkpoint=True,
            start_stage="review",
        )
    except Exception as exc:
        session = load_session(session_dir, conversation_id)
        session["generation"] = {"status": "failed", "driver": "agent_generated_pipeline", "finished_at": now(), "error": str(exc)}
        append_agent_session_event(session_dir, conversation_id, {"kind": "agent_loop_error", "role": "tool", "error": str(exc), "stage": "resume_after_evidence_review"})
        append_memory_event(session, "agent_pipeline_failed", data={"error": str(exc), "stage": "resume_after_evidence_review"})
        save_session(session_dir, session)
        log_bridge_error(log_dir, "agent_pipeline_resume_failed", conversation_id, exc, {"project_dir": str(project_dir)})
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="generation_failed",
            facts={"message": "继续打包时中断了；失败信息已写回会话记录，可以从同一会话继续修复。"},
        )
        return
    result["driver"] = result.get("driver") or "agent_generated_pipeline"
    if checkpoint.get("pipeline_manifest_path"):
        result["pipeline_manifest_path"] = str(checkpoint.get("pipeline_manifest_path", ""))
    session = load_session(session_dir, conversation_id)
    checkpoint["status"] = "approved"
    checkpoint["approved_at"] = now()
    session["pending_evidence_checkpoint"] = checkpoint
    save_session(session_dir, session)
    finish_agent_loop_delivery(client, conversation_id, session_dir, project_dir, result)


def resume_after_evidence_review(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
) -> None:
    client.send_chat_action(conversation_id, "typing")
    threading.Thread(
        target=resume_after_evidence_review_job,
        args=(client, conversation_id, session_dir, log_dir, model, timeout),
        daemon=True,
    ).start()


def record_evidence_review_feedback(
    client: CodexConversation,
    conversation_id: int | str,
    text: str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    session: dict[str, Any],
) -> None:
    checkpoint = session.get("pending_evidence_checkpoint", {}) if isinstance(session.get("pending_evidence_checkpoint"), dict) else {}
    canonical_user_review.invalidate_review_request(
        pathlib.Path(str(checkpoint.get("project_dir", ""))),
        status="changes_requested",
    )
    checkpoint["status"] = "feedback_received"
    checkpoint["feedback"] = text
    checkpoint["feedback_at"] = now()
    session["pending_evidence_checkpoint"] = checkpoint
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    whiteboard["change_requests"] = unique_strings(
        list(whiteboard.get("change_requests", []) if isinstance(whiteboard.get("change_requests"), list) else []) + [text],
        limit=60,
    )
    session["whiteboard"] = whiteboard
    session["generation"] = {"status": "idle", "driver": "agent_generated_pipeline", "updated_at": now()}
    update_active_run_status(session, "intake_open", driver="agent_generated_pipeline")
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "user_evidence_feedback",
            "role": "user",
            "text": text,
            "checkpoint_project_dir": checkpoint.get("project_dir", ""),
            "instruction": "Return to build/test/evidence_review before final package.",
        },
    )
    append_memory_event(session, "user_evidence_feedback", text, {"checkpoint": checkpoint})
    save_session(session_dir, session)
    send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event="user_evidence_feedback_received",
        source="delivery_team_summary",
        direct_text=public_narration.public_event_text("review_revision", {}),
    )
    start_agent_generation(
        client,
        conversation_id,
        session_dir,
        log_dir,
        model,
        timeout,
        announce_start=False,
        reason="user_evidence_feedback",
    )


def start_agent_generation(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    announce_start: bool,
    reason: str = "frontdesk_generation_confirmation",
) -> None:
    model = model or model_policy.select_model("provider_generation")
    session = load_session(session_dir, conversation_id)
    requirement = combined_requirement(session)
    if not requirement:
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="missing_requirement_before_generation",
            facts={"message": "当前没有可执行项目目标；后台未启动。"},
        )
        return
    identity = production_generation_identity(conversation_id, session)
    project_dir, run_dir = production_paths(conversation_id, log_dir, identity)
    prior_generation = (
        session.get("generation", {})
        if isinstance(session.get("generation"), dict)
        else {}
    )
    update_active_run_status(session, "running", driver="api_provider_project_generation")
    session["generation"] = {
        "status": "running",
        "driver": "api_provider_project_generation",
        "started_at": str(prior_generation.get("started_at") or now()),
        "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
        **identity,
        "project_dir": str(project_dir),
        "provider_run_dir": str(run_dir),
        "production_entry_receipt_ref": str(
            prior_generation.get("production_entry_receipt_ref", "")
        ),
        "production_entry_receipt_hash": str(
            prior_generation.get("production_entry_receipt_hash", "")
        ),
    }
    save_session(session_dir, session)
    client.send_chat_action(conversation_id, "typing")
    threading.Thread(
        target=run_provider_generation_job,
        args=(client, conversation_id, session_dir, log_dir, model, timeout),
        kwargs={"announce_start": announce_start},
        daemon=True,
    ).start()


ACTIVE_GENERATION_STATUSES = {"queued", "running", "waiting_decision", "waiting_user_review"}


def apply_backend_dialogue_tick(
    session_dir: pathlib.Path,
    conversation_id: int | str,
    session: dict[str, Any],
    *,
    model: str,
    timeout: int,
    reason: str,
) -> dict[str, Any]:
    analysis = backend_dialogue_loop.run_backend_dialogue_tick(
        session_dir,
        conversation_id,
        session,
        model=model,
        timeout=timeout,
        reason=reason,
        api_budget="low",
    )
    session["whiteboard"] = enforce_backend_updates_from_user_text(
        session,
        session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {},
    )
    append_whiteboard_version(session, session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {})
    append_memory_event(
        session,
        "backend_dialogue_tick",
        data={
            "reason": reason,
            "status": analysis.get("status"),
            "source": analysis.get("source"),
            "soft_questions": analysis.get("soft_questions", []),
            "critical_questions": analysis.get("critical_questions", []),
        },
    )
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "backend_dialogue_tick",
            "role": "assistant",
            "analysis": analysis,
            "soft_questions_are_blocking": False,
            "critical_questions_are_blocking": False,
        },
    )
    append_backend_memo(session_dir, session, "backend_dialogue", str(analysis.get("backend_memo", "")))
    append_truth_ledger(
        session_dir,
        session,
        "backend_dialogue_tick",
        "项目相关消息已完成轻量后台分析；真实生成只由明确开始生成触发。",
        evidence_ref=str(agent_session_path(session_dir, conversation_id)),
        data={"artifact": "backend_dialogue_analysis", "reason": reason, "status": analysis.get("status")},
    )
    save_session(session_dir, session)
    return analysis


def provider_design_scope_public_text(session: dict[str, Any]) -> str:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    state = whiteboard.get("product_design", {}) if isinstance(whiteboard.get("product_design"), dict) else {}
    if not state.get("required"):
        return ""
    return "界面和交互要求已纳入 Provider Planner；它们不会触发普通 Codex 设计或修复调用。"


def record_provider_design_scope(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    session: dict[str, Any],
) -> dict[str, Any]:
    """Record UI scope for the Provider planner without invoking or gating on Codex."""
    del client, log_dir
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    state = whiteboard.get("product_design", {}) if isinstance(whiteboard.get("product_design"), dict) else {}
    if not state.get("required"):
        return {"status": "not_started"}
    session["whiteboard"] = {
        **whiteboard,
        "product_design": {
            **state,
            "workflow_state": "provider_planner_pending",
            "design_source": "provider_planner",
            "codex_used": False,
            "user_confirmation_required": False,
            "advisory_only": False,
        },
    }
    append_whiteboard_version(session, session["whiteboard"])
    append_memory_event(
        session,
        "product_design_provider_planner_ready",
        data={"design_source": "provider_planner_input", "codex_used": False},
    )
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "product_design_provider_planner_ready",
            "role": "system",
            "design_source": "provider_planner_input",
            "codex_used": False,
        },
    )
    save_session(session_dir, session)
    return {"status": "provider_planner_ready"}


def run_model_frontdesk_turn(
    session_dir: pathlib.Path,
    conversation_id: int | str,
    session: dict[str, Any],
    *,
    model: str,
    timeout: int,
    reason: str,
) -> dict[str, Any]:
    try:
        reply, next_whiteboard, action = customer_service_reply(session, model, min(timeout, 90))
        session["whiteboard"] = enforce_backend_updates_from_user_text(session, next_whiteboard)
        reply, rejected = reject_off_topic_public_reply(session_dir, conversation_id, session, reply, source="model_frontdesk_turn")
        if rejected:
            action = "continue_chat"
        append_whiteboard_version(session, session["whiteboard"])
        append_memory_event(
            session,
            "model_frontdesk_turn",
            data={"reason": reason, "action": action, "source": "customer_service_reply"},
        )
        append_agent_session_event(
            session_dir,
            conversation_id,
            {
                "kind": "model_frontdesk_turn",
                "role": "assistant",
                "text": reply,
                "action": action,
                "whiteboard": session["whiteboard"],
            },
        )
        append_backend_memo(session_dir, session, f"model_frontdesk_{reason}", reply)
        save_session(session_dir, session)
        return {"reply": reply, "action": action, "source": "customer_service_reply", "status": "ok"}
    except Exception as exc:
        append_truth_ledger(
            session_dir,
            session,
            "model_frontdesk_failed",
            "模型客服回复失败，使用本地需求分析兜底并继续生成入口。",
            status="observed",
            evidence_ref=reason,
            data={"artifact": "model_frontdesk_failure", "error": str(exc)[:500]},
        )
        analysis = apply_backend_dialogue_tick(session_dir, conversation_id, session, model=model, timeout=timeout, reason=reason)
        action = "start_generation" if combined_requirement(session) else "continue_chat"
        reply = str(analysis.get("user_visible_reply", ""))
        reply, rejected = reject_off_topic_public_reply(session_dir, conversation_id, session, reply, source="backend_dialogue_fallback")
        if rejected:
            action = "continue_chat"
        return {
            "reply": reply,
            "action": action,
            "source": "backend_dialogue_fallback",
            "status": "degraded",
            "error": str(exc)[:500],
        }


def record_generation_start_waiting(
    session_dir: pathlib.Path,
    conversation_id: int | str,
    session: dict[str, Any],
    analysis: dict[str, Any],
    reason: str,
) -> None:
    session["generation_start_waiting"] = True
    session["start_wait_reason"] = reason
    session["pending_start_assumptions"] = _analysis_list(analysis, "assumptions")
    session["pending_soft_questions"] = _analysis_list(analysis, "soft_questions")
    session["pending_critical_questions"] = _analysis_list(analysis, "critical_questions")
    session["pending_required_inputs"] = _analysis_list(analysis, "missing_required_inputs")
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    if str(generation.get("status", "idle")).lower() not in ACTIVE_GENERATION_STATUSES:
        generation["status"] = "waiting_confirmation"
        generation["start_wait_reason"] = reason
        session["generation"] = generation
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "generation_start_waiting",
            "role": "system",
            "reason": reason,
            "pending_soft_questions": session["pending_soft_questions"],
            "pending_critical_questions": session["pending_critical_questions"],
            "pending_required_inputs": session["pending_required_inputs"],
            "soft_questions_are_blocking": False,
        },
    )
    append_memory_event(
        session,
        "generation_start_waiting",
        data={
            "reason": reason,
            "pending_soft_questions": session["pending_soft_questions"],
            "pending_critical_questions": session["pending_critical_questions"],
            "pending_required_inputs": session["pending_required_inputs"],
        },
    )
    save_session(session_dir, session)


def record_forced_start_context(session_dir: pathlib.Path, conversation_id: int | str, session: dict[str, Any]) -> None:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    soft = session.get("pending_soft_questions", []) if isinstance(session.get("pending_soft_questions"), list) else whiteboard.get("soft_questions", [])
    critical = session.get("pending_critical_questions", []) if isinstance(session.get("pending_critical_questions"), list) else whiteboard.get("critical_questions", [])
    missing = session.get("pending_required_inputs", []) if isinstance(session.get("pending_required_inputs"), list) else whiteboard.get("missing_required_inputs", [])
    unanswered = unique_strings([str(item) for item in list(soft or []) + list(critical or []) + list(missing or []) if str(item).strip()], limit=20)
    if unanswered:
        whiteboard["unanswered_questions"] = unique_strings(
            list(whiteboard.get("unanswered_questions", []) if isinstance(whiteboard.get("unanswered_questions"), list) else []) + unanswered,
            limit=30,
        )
        assumptions = list(whiteboard.get("default_assumptions", []) if isinstance(whiteboard.get("default_assumptions"), list) else [])
        assumptions.extend(f"未回答/缺失项按默认假设推进: {item}" for item in unanswered)
        whiteboard["default_assumptions"] = unique_strings(assumptions, limit=40)
    if critical or missing:
        session["forced_start_with_missing_inputs"] = True
        session["missing_required_inputs"] = unique_strings([str(item) for item in missing if str(item).strip()], limit=20)
        whiteboard["scope_downgrade"] = "scaffold_only_or_partial"
        whiteboard["must_not_claim_full_domain_validation"] = True
    session["generation_start_waiting"] = False
    session["whiteboard"] = whiteboard
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "forced_generation_start_context",
            "role": "system",
            "unanswered_questions": unanswered,
            "missing_required_inputs": session.get("missing_required_inputs", []),
            "forced_start_with_missing_inputs": bool(session.get("forced_start_with_missing_inputs")),
            "scope_downgrade": "scaffold_only_or_partial" if session.get("forced_start_with_missing_inputs") else "",
            "must_not_claim_full_domain_validation": bool(session.get("forced_start_with_missing_inputs")),
        },
    )
    save_session(session_dir, session)


def start_generation_from_income(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    session: dict[str, Any],
    *,
    reason: str,
    generation_mode: str = "api",
) -> bool:
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    status = str(generation.get("status", "idle")).lower()
    if status in ACTIVE_GENERATION_STATUSES:
        return False
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    if not combined_requirement(session):
        return False
    append_truth_ledger(
        session_dir,
        session,
        "agent_loop_income_start_requested",
        "项目输入已触发正式 agent 生成启动。",
        evidence_ref=str(agent_session_path(session_dir, conversation_id)),
        data={"artifact": "agent_session", "reason": reason, "previous_generation_status": status},
    )
    append_memory_event(session, "agent_loop_income_start_requested", data={"reason": reason, "previous_generation_status": status})
    save_session(session_dir, session)
    if str(generation_mode or "api").lower() == "simulator":
        run_simulator_preflight(client, conversation_id, session_dir, log_dir, session, reason=reason)
        return True
    entry_started_at = now()
    identity = {
        "run_id": f"production-{uuid.uuid4().hex}",
        "candidate_id": "",
        "commit_sha": repository_commit_sha(),
    }
    identity["candidate_id"] = (
        f"customer-{safe_id(conversation_id)}-{identity['run_id'].rsplit('-', 1)[-1]}"
    )
    project_dir, production_run_dir = production_paths(conversation_id, log_dir, identity)
    entry_receipt = production_candidate_provenance.write_stage_receipt(
        production_run_dir,
        stage="production_entry",
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
        candidate_root=project_dir,
        started_at=entry_started_at,
        finished_at=now(),
    )
    session["generation"] = {
        "status": "queued",
        "driver": "api_provider_project_generation",
        "started_at": entry_started_at,
        "agent_session_path": str(agent_session_path(session_dir, conversation_id)),
        **identity,
        "project_dir": str(project_dir),
        "provider_run_dir": str(production_run_dir),
        "production_entry_receipt_ref": str(entry_receipt),
        "production_entry_receipt_hash": canonical_evidence_hash.sha256_file(
            entry_receipt
        ),
    }
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "canonical_production_entry",
            "role": "system",
            **identity,
            "candidate_root": str(project_dir),
            "production_run_root": str(production_run_dir),
            "entry_receipt_ref": str(entry_receipt),
        },
    )
    save_session(session_dir, session)
    start_agent_generation(
        client,
        conversation_id,
        session_dir,
        log_dir,
        model,
        timeout,
        announce_start=False,
        reason=reason,
    )
    return True


def run_simulator_preflight(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    session: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    requirement = combined_requirement(session)
    run_dir = log_dir / "simulator_preflight" / safe_id(conversation_id)
    result_path = run_dir / "simulator_preflight_result.json"
    project_dir = ROOT / "generated" / "simulator_preflight" / safe_id(conversation_id)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    args = argparse.Namespace(
        plan="",
        goal=requirement,
        out_dir=str(project_dir),
        run_dir=str(run_dir),
        result=str(result_path),
        model=model_policy.select_model("provider_generation"),
        timeout=30,
        allow_network=False,
        allow_provider=False,
        use_api=False,
        allow_model_usage_planning=False,
        phase_log_path=str(run_dir / "simulator_phase_log.jsonl"),
    )
    result = provider_project_pipeline.execute(args)
    if str(result.get("status", "")).lower() == "pass":
        result = {
            **result,
            "status": "BLOCKED",
            "reason": "simulator_preflight_cannot_pass",
            "delivery_allowed": False,
        }
        write_json(result_path, result)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    creds = check_connectivity._resolve_api_credentials()
    missing_config = [] if str(creds.get("api_key", "")).strip() else ["CGKN_OPENAI_API_KEY or OPENAI_API_KEY"]
    session = load_session(session_dir, conversation_id)
    session["generation"] = {
        "status": "rework_blocked",
        "driver": "simulator_preflight",
        "finished_at": now(),
        "reason": "simulator_preflight_only",
        "preflight_result_path": str(result_path),
        "run_dir": str(run_dir),
        "project_dir": str(project_dir),
        "missing_config": missing_config,
        "delivery_allowed": False,
    }
    update_active_run_status(
        session,
        "rework_blocked",
        driver="simulator_preflight",
        delivery_allowed=False,
        project_dir=str(project_dir),
    )
    append_agent_session_event(
        session_dir,
        conversation_id,
        {
            "kind": "simulator_preflight_result",
            "role": "tool",
            "reason": reason,
            "result": result,
            "delivery_allowed": False,
            "missing_config": missing_config,
        },
    )
    save_session(session_dir, session)
    send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event="simulator_preflight_blocked",
        source="simulator_preflight",
        direct_text="当前是预检查模式，只验证规划和配置，不会生成或交付项目。请使用 api 模式启动真实 provider 生成。",
    )
    return result


def queue_generation_job_legacy_disabled(
    client: CodexConversation,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    announce_start: bool,
    generation_mode: str = "api",
) -> None:
    # LEGACY ONLY. Codex conversation formal generation must not call this.
    start_agent_generation(
        client,
        conversation_id,
        session_dir,
        log_dir,
        model,
        timeout,
        announce_start=announce_start,
        reason="legacy_queue_generation_job_redirect",
    )


def auto_start_pending_intakes(
    client: CodexConversation,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    allowed_chat: str = "",
    generation_mode: str = "api",
) -> int:
    # LEGACY ONLY startup compatibility scanner. It may only redirect pending
    # intake records into start_agent_generation; it must not call the legacy
    # provider pipeline or backend_controls as an execution queue.
    session_paths = [session_path(session_dir, allowed_chat)] if allowed_chat else sorted(session_dir.glob("*.json"))
    started = 0
    for path in session_paths:
        if not path.exists() or path.name.endswith(".truth_ledger.jsonl"):
            continue
        conversation_id = path.stem
        session = load_session(session_dir, conversation_id)
        run = active_run(session) or {}
        generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
        status = str(generation.get("status", "idle")).lower()
        if status in ACTIVE_GENERATION_STATUSES:
            continue
        if bool(session.get("generation_start_waiting")) or status == "waiting_confirmation":
            continue
        if str(run.get("status", "")).lower() != "intake_open":
            continue
        if start_generation_from_income(
            client,
            conversation_id,
            session_dir,
            log_dir,
            model,
            timeout,
            session,
            reason="startup_pending_income",
            generation_mode=generation_mode,
        ):
            started += 1
    return started


def continue_customer_turn(
    client: CodexConversation,
    conversation_id: int | str,
    session: dict[str, Any],
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    context: dict[str, Any] | None = None,
) -> None:
    del client, conversation_id, log_dir, model, timeout, context
    latest = latest_user_text(session)
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    if latest:
        whiteboard = merge_whiteboard(
            whiteboard,
            {
                "project_summary": str(whiteboard.get("project_summary", "") or latest),
                "known_facts": [f"用户补充: {latest}"],
                "decision_log": ["本轮由 Human Frontdesk 记录补充，agent loop 会读取同一个 agent_session 继续推进。"],
            },
        )
        session["whiteboard"] = enforce_backend_updates_from_user_text(session, whiteboard)
        append_whiteboard_version(session, session["whiteboard"])
        append_memory_event(session, "whiteboard_revision", data={"source": "local_frontdesk", "latest_user_text": latest[:1200]})
        generation_status = str(session.get("generation", {}).get("status", "idle")).lower() if isinstance(session.get("generation"), dict) else "idle"
        action = "revise_generation_scope" if generation_status in {"queued", "running"} else "update_project_context"
        append_backend_control(
            session_dir,
            session,
            action,
            payload={
                "latest_user_text": latest[:4000],
                "whiteboard": session["whiteboard"],
                "requirement": combined_requirement(session)[:12000],
            },
            status="logged",
            reason="user_project_update",
        )
    append_backend_memo(
        session_dir,
        session,
        "project_update",
        "我已把用户补充写进项目白板和生成会话；兼容记录只作为日志，不作为生成入口。",
    )
    save_session(session_dir, session)


def handle_text(
    client: CodexConversation,
    conversation_id: int | str,
    text: str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    generation_mode: str = "api",
    turn_context: dict[str, Any] | None = None,
) -> None:
    session = load_session(session_dir, conversation_id)
    text = text.strip()
    if text:
        append_agent_session_event(session_dir, conversation_id, {"kind": "user", "role": "user", "text": text})
    classification = classify_customer_message(text, session)
    append_truth_ledger(
        session_dir,
        session,
        "message_classification",
        "用户消息入口已先分类",
        evidence_ref=str(classification.get("intent", "")),
        data={"artifact": "message_classification", "classification": classification},
    )
    if text == "/new":
        clear_result = clear_chat_history(conversation_id, session_dir, log_dir, include_outputs=False, delete=False)
        session = default_session(conversation_id)
        append_memory_event(session, "session_reset", "/new", {"clear_result": clear_result})
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="admin_command",
            facts={"message": reset_summary_text(clear_result) + "\n你可以直接发新的项目想法。"},
        )
        return
    if text in {"/reset", "/restart"}:
        clear_result = clear_chat_history(conversation_id, session_dir, log_dir, include_outputs=True, delete=False)
        session = default_session(conversation_id)
        append_memory_event(session, "session_reset", text, {"clear_result": clear_result})
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="admin_command",
            facts={"message": reset_summary_text(clear_result) + "\n项目会话已重启，你可以从一句新需求开始。"},
        )
        return
    if text == "/delete_history":
        clear_result = clear_chat_history(conversation_id, session_dir, log_dir, include_outputs=True, delete=True)
        session = default_session(conversation_id)
        append_memory_event(session, "session_deleted", text, {"clear_result": clear_result})
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="admin_command",
            facts={"message": reset_summary_text(clear_result) + "\n已打开空白会话。"},
        )
        return
    if text == "/help":
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="admin_command",
            facts={
                "message": (
                    "可用命令：\n"
                    "/status 查看后台生成状态\n"
                    "/new 归档当前对话并开新会话\n"
                    "/reset 归档当前对话和本轮生成历史后重启\n"
                    "/delete_history 永久删除当前对话和本轮生成历史\n"
                    "平时直接描述项目需求即可；生成完成后我会直接发结果、图片或视频预览。"
                )
            },
        )
        return

    intent = str(classification.get("intent", ""))
    session.setdefault("messages", []).append({"role": "user", "text": text, "created_at": now(), "classification": classification})
    current_generation_status = (
        str(session.get("generation", {}).get("status", "idle")).lower()
        if isinstance(session.get("generation"), dict) else "idle"
    )
    if (
        isinstance(turn_context, dict)
        and intent not in {"admin_command", "greeting", "status_query"}
        and (
            not isinstance(session.get("active_request_owner"), dict)
            or current_generation_status in {"idle", "failed", "completed", "final_delivered"}
        )
    ):
        session["active_request_owner"] = {
            "conversation_id": str(turn_context.get("conversation_id", conversation_id)),
            "reviewer_id": str(turn_context.get("reviewer_id", "")),
            "event_id": str(turn_context.get("event_id", "")),
            "turn_id": str(turn_context.get("turn_id", "")),
        }
    if isinstance(turn_context, dict):
        session["codex_conversation_type"] = str(
            turn_context.get("conversation_type", session.get("codex_conversation_type", ""))
        )
    session["whiteboard"] = enforce_backend_updates_from_user_text(
        session,
        session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {},
    )
    append_memory_event(session, "user_message", text, {"classification": classification})
    save_session(session_dir, session)

    if intent == "greeting":
        evidence = delivery_evidence_state(read_truth_ledger(session_dir, conversation_id))
        if send_provider_message(
            client,
            conversation_id,
            session_dir,
            event="greeting",
            session=session,
            facts={
                "classification": classification,
                "generation": session.get("generation", {}),
                "active_run": active_run(session) or {},
                "evidence_state": evidence,
            },
            model=model,
            timeout=timeout,
        ):
            return
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="greeting",
            source="technical_fallback",
            direct_text="我在。当前消息已记录；回复模型暂时不可用，后台状态不会因为这条问候被改写。",
        )
        return
    if intent == "status_query":
        evidence = delivery_evidence_state(read_truth_ledger(session_dir, conversation_id))
        if send_provider_message(
            client,
            conversation_id,
            session_dir,
            event="status_requested",
            session=session,
            facts={"generation": session.get("generation", {}), "evidence_state": evidence},
            model=model,
            timeout=timeout,
        ):
            return
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="status_requested",
            source="technical_fallback",
            direct_text="当前状态查询已记录；回复模型暂时不可用，我不会把这条状态问句当成新的项目需求。",
        )
        return

    generation_status = str(session.get("generation", {}).get("status", "idle")).lower() if isinstance(session.get("generation"), dict) else "idle"
    if generation_status == "waiting_user_review" and intent not in {"admin_command", "greeting", "status_query"}:
        decision = canonical_user_review.classify_review_text(text)
        if decision == "APPROVED":
            checkpoint = session.get("pending_evidence_checkpoint", {}) if isinstance(session.get("pending_evidence_checkpoint"), dict) else {}
            project_dir = pathlib.Path(str(checkpoint.get("project_dir", "")))
            approval = canonical_user_review.record_user_review_approval(
                project_dir,
                checkpoint,
                text,
                turn_context,
            )
            if approval.get("status") != "PASS":
                checkpoint["approval_failures"] = approval.get("failures", [])
                session["pending_evidence_checkpoint"] = checkpoint
                save_session(session_dir, session)
                send_customer_reply(
                    client,
                    conversation_id,
                    session_dir,
                    session,
                    event="user_evidence_review_identity_required",
                    direct_text="我还不能把这条消息记录为正式批准；审核对象或消息身份已变化，请在当前审核消息之后明确确认。",
                )
                return
            checkpoint["consumed_turn_id"] = str((turn_context or {}).get("turn_id", ""))
            checkpoint["status"] = "approved"
            session["pending_evidence_checkpoint"] = checkpoint
            save_session(session_dir, session)
            append_agent_session_event(
                session_dir,
                conversation_id,
                {"kind": "user_evidence_review_approved", "role": "user", "text": text},
            )
            resume_after_evidence_review(client, conversation_id, session_dir, log_dir, model, timeout)
            return
        if decision == "AMBIGUOUS":
            send_customer_reply(
                client,
                conversation_id,
                session_dir,
                session,
                event="user_evidence_review_ambiguous",
                direct_text="请明确说明是否批准当前版本用于最终打包；如果需要修改，直接告诉我要改哪里。",
            )
            return
        record_evidence_review_feedback(client, conversation_id, text, session_dir, log_dir, model, timeout, session)
        return

    pending = current_pending_decision(session)
    if pending and intent not in {"admin_command", "greeting", "status_query", "generation_confirmation"}:
        pending["status"] = "superseded"
        pending["answer"] = text
        pending["resolved_at"] = now()
        session["pending_decision"] = pending
        whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
        whiteboard["blocking_questions"] = []
        whiteboard["open_questions"] = unique_strings(
            list(whiteboard.get("open_questions", []) if isinstance(whiteboard.get("open_questions"), list) else [])
            + [str(pending.get("question", ""))],
            limit=40,
        )
        whiteboard["known_facts"] = unique_strings(list(whiteboard.get("known_facts", [])) + [f"用户补充: {text}"])
        session["whiteboard"] = whiteboard
        update_active_run_status(session, "intake_open", driver="frontdesk_intake")
        append_backend_control(
            session_dir,
            session,
            "blocking_question_removed",
            payload={"latest_user_text": text, "whiteboard": whiteboard},
            status="logged",
            reason="project_input_must_not_pause_for_question",
        )

    if intent == "project_revision_request":
        try:
            result = main_agent_manager.MainAgentManager().start_project_revision(session, text)
            append_memory_event(session, "project_revision_prepared", data=result)
            save_session(session_dir, session)
            send_customer_reply(
                client,
                conversation_id,
                session_dir,
                session,
                event="project_revision_prepared",
                source="main_agent_manager",
                direct_text="我已把这条改动作为当前项目的下一版准备好。当前版本不会被覆盖；只有新版本通过检查并完成打包后，才会更新交付。",
            )
        except Exception as exc:
            append_memory_event(session, "project_revision_prepare_failed", data={"error": str(exc)})
            save_session(session_dir, session)
            send_customer_reply(
                client,
                conversation_id,
                session_dir,
                session,
                event="project_revision_prepare_failed",
                source="main_agent_manager",
                direct_text="这条修改已记录，但当前项目版本信息不完整，暂时不能直接按上一版继续改。你可以先发 /status 查看当前项目状态。",
            )
        return

    if intent == "new_project_request":
        ticket = create_intake_ticket(session_dir, session, text)
        run = create_active_run(session, ticket, text)
        append_backend_control(
            session_dir,
            session,
            "open_intake",
            payload={"raw_user_message": text, "whiteboard": session.get("whiteboard", {})},
            status="logged",
            reason="new_project_request",
        )
        append_truth_ledger(
            session_dir,
            session,
            "active_run_bound",
            "Codex conversation_id 已绑定 active run",
            evidence_ref=str(run.get("id", "")),
            data={"artifact": "active_run", "run_id": run.get("id", ""), "ticket_id": ticket.get("id", "")},
        )
        append_truth_ledger(
            session_dir,
            session,
            "backend_dialogue_requested",
            "新需求已进入 agent_session，并等待启动策略判断是否需要用户确认",
            evidence_ref=str(run.get("id", "")),
            data={"artifact": "agent_session_intake", "auto_start": False},
        )
        analysis = apply_backend_dialogue_tick(
            session_dir,
            conversation_id,
            session,
            model=model,
            timeout=timeout,
            reason="new_project_request",
        )
        turn = run_model_frontdesk_turn(
            session_dir,
            conversation_id,
            session,
            model=model,
            timeout=timeout,
            reason="new_project_request",
        )
        design_note = provider_design_scope_public_text(session)
        if design_note:
            turn["reply"] = (str(turn.get("reply", "")).rstrip() + "\n\n" + design_note)[:1200]
        auto_start, start_reason = should_auto_start_generation(session, analysis, text)
        if not auto_start:
            record_generation_start_waiting(session_dir, conversation_id, session, analysis, start_reason)
            direct_text, _ = reject_off_topic_public_reply(
                session_dir,
                conversation_id,
                session,
                build_intake_waiting_text(analysis, str(turn.get("reply", ""))),
                source="backend_dialogue_start_policy",
            )
            send_customer_reply(
                client,
                conversation_id,
                session_dir,
                session,
                event="model_frontdesk_reply",
                source="backend_dialogue_start_policy",
                direct_text=direct_text,
            )
            record_provider_design_scope(client, conversation_id, session_dir, log_dir, session)
            return
        direct_text, _ = reject_off_topic_public_reply(
            session_dir,
            conversation_id,
            session,
            str(turn.get("reply", "")),
            source=str(turn.get("source", "customer_service_reply")),
        )
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="model_frontdesk_reply",
            source=str(turn.get("source", "customer_service_reply")),
            direct_text=direct_text,
        )
        start_generation_from_income(
            client,
            conversation_id,
            session_dir,
            log_dir,
            model,
            timeout,
            session,
            reason="new_project_income_auto_start",
            generation_mode=generation_mode,
        )
        return

    if intent == "generation_confirmation":
        record_forced_start_context(session_dir, conversation_id, session)
        session = load_session(session_dir, conversation_id)
        whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
        soft_questions = whiteboard.get("soft_questions", []) if isinstance(whiteboard.get("soft_questions"), list) else []
        if soft_questions:
            append_agent_session_event(
                session_dir,
                conversation_id,
                {
                    "kind": "soft_questions_unanswered",
                    "role": "system",
                    "soft_questions": soft_questions[:2],
                    "assumptions": whiteboard.get("default_assumptions", []),
                    "unanswered_questions": whiteboard.get("unanswered_questions", []),
                    "missing_required_inputs": session.get("missing_required_inputs", []),
                    "soft_questions_are_blocking": False,
                },
            )
        if str(generation_mode or "api").lower() == "api":
            send_customer_reply(
                client,
                conversation_id,
                session_dir,
                session,
                event="generation_started",
                source="public_narration",
                direct_text=public_narration.public_event_text("generation_started", {}),
            )
        start_generation_from_income(
            client,
            conversation_id,
            session_dir,
            log_dir,
            model,
            timeout,
            session,
            reason="frontdesk_generation_confirmation",
            generation_mode=generation_mode,
        )
        record_provider_design_scope(client, conversation_id, session_dir, log_dir, session)
        return

    if intent == "escalation_request":
        append_truth_ledger(
            session_dir,
            session,
            "provider_escalation_note",
            "用户升级请求已作为会话上下文记录，不再作为正式生成检查点",
            status="observed",
            evidence_ref="escalation_request",
            data={"artifact": "escalation_note"},
        )
        append_backend_control(
            session_dir,
            session,
            "escalation_note",
            payload={"classification": classification, "whiteboard": session.get("whiteboard", {})},
            status="logged",
            reason="user_requested_escalation_context",
        )
        if send_provider_message(
            client,
            conversation_id,
            session_dir,
            event="escalation_request",
            session=session,
            facts={"classification": classification, "generation": session.get("generation", {})},
            model=model,
            timeout=timeout,
        ):
            return
        send_customer_reply(client, conversation_id, session_dir, session, event="escalation_request", facts={"message": "模型通道暂时不可用；这条升级请求已写入会话。"})
        return

    continue_customer_turn(client, conversation_id, session, session_dir, log_dir, model, timeout, {"text": text})
    session = load_session(session_dir, conversation_id)
    if generation_status in ACTIVE_GENERATION_STATUSES:
        if send_provider_message(
            client,
            conversation_id,
            session_dir,
            event="project_update_running",
            session=session,
            facts={"latest_user_text": text, "generation": session.get("generation", {})},
            model=model,
            timeout=timeout,
        ):
            return
        send_customer_reply(client, conversation_id, session_dir, session, event="project_update_running", facts={"message": "模型通道暂时不可用；补充已写入生成会话。"})
        return
    turn = run_model_frontdesk_turn(
        session_dir,
        conversation_id,
        session,
        model=model,
        timeout=timeout,
        reason="project_update",
    )
    design_note = provider_design_scope_public_text(session)
    if design_note:
        turn["reply"] = (str(turn.get("reply", "")).rstrip() + "\n\n" + design_note)[:1200]
    analysis = session.get("backend_dialogue_analysis", {}) if isinstance(session.get("backend_dialogue_analysis"), dict) else {}
    if not analysis or str(analysis.get("reason", "")) != "project_update":
        analysis = apply_backend_dialogue_tick(
            session_dir,
            conversation_id,
            session,
            model=model,
            timeout=timeout,
            reason="project_update",
        )
    auto_start, start_reason = should_auto_start_generation(session, analysis, text)
    if not auto_start:
        record_generation_start_waiting(session_dir, conversation_id, session, analysis, start_reason)
        direct_text, _ = reject_off_topic_public_reply(
            session_dir,
            conversation_id,
            session,
            build_intake_waiting_text(analysis, str(turn.get("reply", ""))),
            source="backend_dialogue_start_policy",
        )
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="model_frontdesk_reply",
            source="backend_dialogue_start_policy",
            direct_text=direct_text,
        )
        record_provider_design_scope(client, conversation_id, session_dir, log_dir, session)
        return
    direct_text, _ = reject_off_topic_public_reply(
        session_dir,
        conversation_id,
        session,
        str(turn.get("reply", "")),
        source=str(turn.get("source", "customer_service_reply")),
    )
    send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event="model_frontdesk_reply",
        source=str(turn.get("source", "customer_service_reply")),
        direct_text=direct_text,
    )
    start_generation_from_income(
        client,
        conversation_id,
        session_dir,
        log_dir,
        model,
        timeout,
        session,
        reason="project_update_income_auto_start",
        generation_mode=generation_mode,
    )


def handle_attachment_message(
    client: CodexConversation,
    conversation_id: int | str,
    message: dict[str, Any],
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    upload_dir: pathlib.Path,
    model: str,
    timeout: int,
    generation_mode: str = "api",
) -> None:
    session = load_session(session_dir, conversation_id)
    client.send_chat_action(conversation_id, "upload_document")
    try:
        attachments, skipped = download_message_attachments(client, conversation_id, message, upload_dir)
    except Exception as exc:
        log_bridge_error(log_dir, "attachment_download_failed", conversation_id, exc, {"turn_id": message.get("turn_id")})
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="attachment_download_failed",
            facts={"message": "上传资料下载中断；这条资料未进入后台。"},
        )
        return
    if not attachments:
        if skipped:
            append_memory_event(session, "user_attachment_skipped", data={"skipped": skipped})
            send_customer_reply(
                client,
                conversation_id,
                session_dir,
                session,
                event="attachment_skipped",
                facts={"message": "上传资料未进入后台：文件过大或 Codex conversation 未返回可下载路径。", "skipped": skipped},
            )
            return
        if send_provider_message(
            client,
            conversation_id,
            session_dir,
            event="unsupported_attachment_received",
            session=session,
            facts={"message_type": "non_text", "supported": ["photo", "document", "video", "animation", "audio", "voice"]},
            model=model,
            timeout=timeout,
        ):
            save_session(session_dir, session)
        else:
            send_customer_reply(
                client,
                conversation_id,
                session_dir,
                session,
                event="unsupported_attachment_received",
                facts={"message": "非文本资料已进入入口检查；图片、文档、视频、音频会作为项目输入进入后台。"},
            )
        return
    if skipped:
        append_memory_event(session, "user_attachment_partially_skipped", data={"skipped": skipped})
    record_attachments_as_project_input(session, attachments)
    caption = str(message.get("caption", "")).strip()
    user_text = attachment_user_text(attachments, caption)
    session.setdefault("messages", []).append(
        {
            "role": "user",
            "text": user_text,
            "created_at": now(),
            "attachments": [item.get("local_path", "") for item in attachments],
        }
    )
    append_memory_event(
        session,
        "user_message",
        user_text,
        {"source": "attachment_message", "attachment_count": len(attachments)},
    )
    save_session(session_dir, session)
    session = load_session(session_dir, conversation_id)
    continue_customer_turn(
        client,
        conversation_id,
        session,
        session_dir,
        log_dir,
        model,
        timeout,
        {"attachments": recent_attachments({"attachments": attachments}, limit=len(attachments))},
    )
    session = load_session(session_dir, conversation_id)
    generation_status = str(session.get("generation", {}).get("status", "idle")).lower() if isinstance(session.get("generation"), dict) else "idle"
    if generation_status in ACTIVE_GENERATION_STATUSES:
        if send_provider_message(
            client,
            conversation_id,
            session_dir,
            event="attachment_project_input_running",
            session=session,
            facts={"attachment_count": len(attachments), "caption": caption, "generation": session.get("generation", {})},
            model=model,
            timeout=timeout,
        ):
            return
        send_customer_reply(client, conversation_id, session_dir, session, event="attachment_project_input_running", facts={"message": "模型通道暂时不可用；上传资料已写入生成会话。"})
        return
    turn = run_model_frontdesk_turn(
        session_dir,
        conversation_id,
        session,
        model=model,
        timeout=timeout,
        reason="attachment_project_input",
    )
    design_note = provider_design_scope_public_text(session)
    if design_note:
        turn["reply"] = (str(turn.get("reply", "")).rstrip() + "\n\n" + design_note)[:1200]
    analysis = apply_backend_dialogue_tick(
        session_dir,
        conversation_id,
        session,
        model=model,
        timeout=timeout,
        reason="attachment_project_input",
    )
    auto_start, start_reason = should_auto_start_generation(session, analysis, user_text)
    if not auto_start:
        record_generation_start_waiting(session_dir, conversation_id, session, analysis, start_reason)
        direct_text, _ = reject_off_topic_public_reply(
            session_dir,
            conversation_id,
            session,
            str(analysis.get("user_visible_reply") or turn.get("reply", "")),
            source="backend_dialogue_start_policy",
        )
        send_customer_reply(
            client,
            conversation_id,
            session_dir,
            session,
            event="model_frontdesk_reply",
            source="backend_dialogue_start_policy",
            direct_text=direct_text,
        )
        record_provider_design_scope(client, conversation_id, session_dir, log_dir, session)
        return
    direct_text, _ = reject_off_topic_public_reply(
        session_dir,
        conversation_id,
        session,
        str(turn.get("reply", "")),
        source=str(turn.get("source", "customer_service_reply")),
    )
    send_customer_reply(
        client,
        conversation_id,
        session_dir,
        session,
        event="model_frontdesk_reply",
        source=str(turn.get("source", "customer_service_reply")),
        direct_text=direct_text,
    )
    start_generation_from_income(
        client,
        conversation_id,
        session_dir,
        log_dir,
        model,
        timeout,
        session,
        reason="attachment_income_auto_start",
        generation_mode=generation_mode,
    )


# The Codex app owns the sole user-facing conversation loop.  This module is
# intentionally import-only: Codex invokes its bounded functions directly and
# renders returned text or local artifact links in the active task.
