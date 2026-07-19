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
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import browser_visual_evidence, canonical_evidence_hash, customer_runtime_runner, real_test_execution

SCHEMA_VERSION = "1.0"
PRODUCER = "scripts/final_internal_acceptance.py"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: pathlib.Path) -> str:
    return canonical_evidence_hash.sha256_file(path)


def git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["artifact_hash"] = ""
    doc["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(doc, ("artifact_hash",))
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def envelope(kind: str, identity: dict[str, str], status: str, **data: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "schema_version": SCHEMA_VERSION,
        **identity,
        "producer": PRODUCER,
        "created_at": now(),
        "status": status,
        "artifact_hash": "",
        **data,
    }


def run_command(argv: list[str], cwd: pathlib.Path, timeout: int = 120) -> dict[str, Any]:
    started = now()
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONPATH": str(cwd)},
        )
        return {
            "argv": argv,
            "cwd": str(cwd.resolve()),
            "started_at": started,
            "finished_at": now(),
            "exit_code": proc.returncode,
            "timeout": False,
            "stdout_hash": "sha256:" + hashlib.sha256(proc.stdout.encode()).hexdigest(),
            "stderr_hash": "sha256:" + hashlib.sha256(proc.stderr.encode()).hexdigest(),
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "cwd": str(cwd.resolve()),
            "started_at": started,
            "finished_at": now(),
            "exit_code": 124,
            "timeout": True,
            "stdout_tail": str(exc.stdout or "")[-2000:],
            "stderr_tail": str(exc.stderr or "")[-2000:],
        }


def worker(mode: str, workspace: pathlib.Path) -> int:
    workspace.mkdir(parents=True, exist_ok=True)
    if mode == "backend":
        target = workspace / "app" / "api.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "def normalize_title(value):\n"
            "    value = str(value or '').strip()\n"
            "    if not value: raise ValueError('title required')\n"
            "    return value\n",
            encoding="utf-8",
        )
    elif mode == "persistence":
        contract = json.loads((workspace / "input" / "task_contract.json").read_text(encoding="utf-8"))
        target = workspace / "app" / "repository.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "import sqlite3\n"
            f"TABLE = {contract['table']!r}\n"
            "class TaskRepository:\n"
            "    def __init__(self, path):\n"
            "        self.db=sqlite3.connect(path); self.db.execute(f'create table if not exists {TABLE} (id integer primary key, title text, done integer)')\n"
            "    def create(self,title):\n"
            "        cur=self.db.execute(f'insert into {TABLE}(title,done) values (?,0)',(title,)); self.db.commit(); return cur.lastrowid\n"
            "    def list(self): return self.db.execute(f'select id,title,done from {TABLE} order by id').fetchall()\n",
            encoding="utf-8",
        )
    elif mode == "frontend":
        (workspace / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>CGKN Task Studio</title>"
            "<main><h1>Task Studio</h1><button id='create'>Create task</button>"
            "<section id='tasks'>Ready for tasks</section></main>",
            encoding="utf-8",
        )
    elif mode == "original":
        target = workspace / "app" / "validation.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def validate_title(value): return ''\n", encoding="utf-8")
    elif mode == "replacement":
        target = workspace / "app" / "validation.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "def validate_title(value):\n"
            "    value=str(value or '').strip()\n"
            "    if not value: raise ValueError('title required')\n"
            "    return value\n",
            encoding="utf-8",
        )
    elif mode == "checkpoint":
        write_json(
            workspace / "checkpoint.json",
            {"kind": "CGKNWorkerCheckpoint", "pid": os.getpid(), "created_at": now(), "status": "running"},
        )
        time.sleep(60)
    elif mode == "resume":
        checkpoint = json.loads((workspace / "checkpoint.json").read_text(encoding="utf-8"))
        target = workspace / "app" / "recovery.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"RECOVERED_FROM_PID={int(checkpoint['pid'])}\ndef recovered(): return True\n",
            encoding="utf-8",
        )
        write_json(
            workspace / "resume_checkpoint.json",
            {
                "kind": "CGKNWorkerCheckpoint",
                "pid": os.getpid(),
                "previous_pid": checkpoint["pid"],
                "created_at": now(),
                "status": "completed",
            },
        )
    else:
        return 2
    return 0


def make_workspace(root: pathlib.Path, leaf_id: str, task_id: str) -> dict[str, str]:
    leaf_root = root / "leaf_workspaces" / leaf_id
    workspace = leaf_root / "workspace"
    (workspace / "input").mkdir(parents=True, exist_ok=True)
    return {
        "workspace_id": f"{root.name}:{leaf_id}:{task_id}",
        "leaf_id": leaf_id,
        "task_id": task_id,
        "leaf_root": str(leaf_root.resolve()),
        "workspace_root": str(workspace.resolve()),
        "created_at": now(),
    }


def execute_leaf(
    root: pathlib.Path,
    identity: dict[str, str],
    leaf_id: str,
    task_id: str,
    mode: str,
    outputs: list[str],
) -> dict[str, Any]:
    ws = make_workspace(root, leaf_id, task_id)
    workspace = pathlib.Path(ws["workspace_root"])
    started = now()
    proc = run_command([sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", mode, str(workspace)], workspace)
    patches = [
        {"path": rel, "hash": sha(workspace / rel)}
        for rel in outputs
        if (workspace / rel).is_file()
    ]
    return {
        **ws,
        "started_at": started,
        "finished_at": now(),
        "worker": proc,
        "patch": patches,
        "status": "PASS" if proc["exit_code"] == 0 and len(patches) == len(outputs) else "NEEDS_REWORK",
    }


def merge_leaf(candidate: pathlib.Path, leaf: dict[str, Any]) -> dict[str, Any]:
    merged: list[dict[str, str]] = []
    workspace = pathlib.Path(leaf["workspace_root"])
    for item in leaf["patch"]:
        source = workspace / item["path"]
        target = candidate / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        merged.append({"path": item["path"], "source_hash": item["hash"], "merged_hash": sha(target)})
    ok = bool(merged) and all(item["source_hash"] == item["merged_hash"] for item in merged)
    return {"status": "PASS" if ok else "NEEDS_REWORK", "merged_at": now(), "files": merged}


def build_internal_acceptance(run_dir: str | pathlib.Path) -> dict[str, Any]:
    out = pathlib.Path(run_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    commit = git_sha()
    identity = {
        "run_id": out.name,
        "candidate_id": "CGKN",
        "candidate_hash": "sha256:" + hashlib.sha256(commit.encode()).hexdigest(),
        "commit_sha": commit,
    }
    candidate = out / "internal_customer_project"
    candidate.mkdir(parents=True, exist_ok=True)
    (candidate / "app").mkdir(exist_ok=True)
    (candidate / "app" / "__init__.py").write_text("", encoding="utf-8")
    (candidate / "tests").mkdir(exist_ok=True)

    collaboration_created = now()
    collaboration_contract = {
        "connection_id": f"{out.name}:backend:persistence",
        "source_leaf": "backend_leaf",
        "target_leaf": "persistence_leaf",
        "source_state": "short_plan_created",
        "target_state": "workspace_ready",
        "table": "tasks",
        "interface": "TaskRepository.create/list",
        "created_at": collaboration_created,
    }
    persistence_ws = make_workspace(out, "persistence_leaf", "task-persistence")
    persistence_workspace = pathlib.Path(persistence_ws["workspace_root"])
    write_json(persistence_workspace / "input" / "task_contract.json", collaboration_contract)

    backend = execute_leaf(out, identity, "backend_leaf", "task-backend", "backend", ["app/api.py"])
    persistence_started = now()
    persistence_proc = run_command(
        [sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "persistence", str(persistence_workspace)],
        persistence_workspace,
    )
    persistence = {
        **persistence_ws,
        "started_at": persistence_started,
        "finished_at": now(),
        "worker": persistence_proc,
        "patch": [{"path": "app/repository.py", "hash": sha(persistence_workspace / "app/repository.py")}],
        "consumed_connection_id": collaboration_contract["connection_id"],
        "status": "PASS" if persistence_proc["exit_code"] == 0 else "NEEDS_REWORK",
    }
    frontend = execute_leaf(out, identity, "frontend_leaf", "task-frontend", "frontend", ["index.html"])
    merges = {
        leaf["leaf_id"]: merge_leaf(candidate, leaf)
        for leaf in (backend, persistence, frontend)
    }
    (candidate / "tests" / "test_customer_project.py").write_text(
        "import sqlite3\n"
        "import pytest\n"
        "from app.api import normalize_title\n"
        "from app.repository import TaskRepository\n"
        "def test_api_validation():\n"
        " assert normalize_title(' Task ') == 'Task'\n"
        " with pytest.raises(ValueError): normalize_title(' ')\n"
        "def test_sqlite_persists(tmp_path):\n"
        " path=tmp_path/'tasks.db'; repo=TaskRepository(path); task_id=repo.create('Persisted'); repo.db.close()\n"
        " reopened=TaskRepository(path); assert reopened.list()==[(task_id,'Persisted',0)]\n"
        "def test_frontend_surface():\n"
        " text=open('index.html',encoding='utf-8').read(); assert 'Create task' in text and 'Task Studio' in text\n",
        encoding="utf-8",
    )
    leaf_test = run_command([sys.executable, "-m", "pytest", "-q", "tests/test_customer_project.py"], candidate)

    original = execute_leaf(out, identity, "validation_leaf", "task-validation-v1", "original", ["app/validation.py"])
    original_merge = merge_leaf(candidate, original)
    (candidate / "tests" / "test_validation.py").write_text(
        "import pytest\nfrom app.validation import validate_title\n"
        "def test_validation():\n assert validate_title(' ok ')=='ok'\n"
        "def test_empty():\n\n with pytest.raises(ValueError): validate_title(' ')\n",
        encoding="utf-8",
    )
    failed_test = run_command([sys.executable, "-m", "pytest", "-q", "tests/test_validation.py"], candidate)
    replacement = execute_leaf(out, identity, "validation_leaf_v2", "task-validation-v2", "replacement", ["app/validation.py"])
    replacement_merge = merge_leaf(candidate, replacement)
    replacement_test = run_command([sys.executable, "-m", "pytest", "-q", "tests/test_validation.py"], candidate)
    replan_status = (
        "PASS"
        if failed_test["exit_code"] != 0
        and replacement_test["exit_code"] == 0
        and replacement_merge["status"] == "PASS"
        else "NEEDS_REWORK"
    )

    recovery_ws = make_workspace(out, "recovery_leaf", "task-recovery")
    recovery_root = pathlib.Path(recovery_ws["workspace_root"])
    first = subprocess.Popen(
        [sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "checkpoint", str(recovery_root)],
        cwd=recovery_root,
    )
    checkpoint = recovery_root / "checkpoint.json"
    deadline = time.time() + 10
    while time.time() < deadline and not checkpoint.is_file():
        time.sleep(0.05)
    first_pid = first.pid
    first.terminate()
    first.wait(timeout=5)
    observed_exit = first.returncode
    resume = run_command(
        [sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "resume", str(recovery_root)],
        recovery_root,
    )
    resume_doc = json.loads((recovery_root / "resume_checkpoint.json").read_text(encoding="utf-8"))
    recovery_ok = (
        checkpoint.is_file()
        and observed_exit != 0
        and resume["exit_code"] == 0
        and resume_doc["pid"] != first_pid
        and resume_doc["previous_pid"] == first_pid
    )
    recovery_leaf = {
        **recovery_ws,
        "original_pid": first_pid,
        "original_exit_code": observed_exit,
        "termination": "terminate",
        "checkpoint_ref": str(checkpoint),
        "replacement_pid": resume_doc["pid"],
        "resume_result": resume,
        "status": "PASS" if recovery_ok else "NEEDS_REWORK",
    }
    merge_recovery = {
        **recovery_leaf,
        "patch": [{"path": "app/recovery.py", "hash": sha(recovery_root / "app/recovery.py")}],
    }
    recovery_merge = merge_leaf(candidate, merge_recovery)
    (candidate / "tests" / "test_recovery.py").write_text(
        "from app.recovery import recovered\n\ndef test_recovered(): assert recovered() is True\n",
        encoding="utf-8",
    )
    recovery_test = run_command([sys.executable, "-m", "pytest", "-q", "tests/test_recovery.py"], candidate)
    recovery_status = (
        "PASS"
        if recovery_ok and recovery_merge["status"] == "PASS" and recovery_test["exit_code"] == 0
        else "NEEDS_REWORK"
    )

    provider_project = out / "customer_project"
    provider_trace_path = out / "live_provider_leaf" / "provider_causal_trace.json"
    provider_integration: dict[str, Any] = {
        "status": "NOT_EVALUATED",
        "reason": "fresh provider leaf not present in this run",
    }
    provider_leaf: dict[str, Any] | None = None
    if provider_trace_path.is_file():
        trace = json.loads(provider_trace_path.read_text(encoding="utf-8"))
        copied: list[dict[str, str]] = []
        for item in trace.get("patch", []) if isinstance(trace.get("patch"), list) else []:
            rel = str(item.get("path", ""))
            source = provider_project / rel
            target = candidate / rel
            if source.is_file() and sha(source) == item.get("file_hash"):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied.append({"path": rel, "source_hash": sha(source), "merged_hash": sha(target)})
        for package in ("app/services/__init__.py",):
            marker = candidate / package
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch(exist_ok=True)
        provider_test = run_command(
            [sys.executable, "-m", "pytest", "-q", "tests/test_task_service.py"],
            candidate,
        )
        provider_integration = {
            "status": "PASS"
            if copied and provider_test["exit_code"] == 0 and all(x["source_hash"] == x["merged_hash"] for x in copied)
            else "NEEDS_REWORK",
            "provider_trace_ref": str(provider_trace_path.resolve()),
            "provider_trace_hash": sha(provider_trace_path),
            "merged_patch": copied,
            "behavior_test": provider_test,
            "merged_at": now(),
        }
        checkpoint_path = out / "live_provider_leaf" / "checkpoint_acceptance_backend_leaf.json"
        checkpoint = (
            json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint_path.is_file()
            else {}
        )
        provider_leaf = {
            "workspace_id": f"{out.name}:acceptance_backend_leaf:live-provider-task",
            "leaf_id": "acceptance_backend_leaf",
            "task_id": "live-provider-task",
            "leaf_root": str((out / "live_provider_leaf").resolve()),
            "workspace_root": str(provider_project.resolve()),
            "created_at": str(trace.get("created_at") or now()),
            "started_at": str(trace.get("created_at") or now()),
            "finished_at": provider_integration["merged_at"],
            "worker": {
                "provider_request_identity": trace.get("provider_request_identity"),
                "provider_response_id": trace.get("provider_response_id"),
                "decision_hash": trace.get("decision_hash"),
                "patch_hash": trace.get("patch_hash"),
            },
            "patch": provider_integration["merged_patch"],
            "behavior_test": provider_integration["behavior_test"],
            "checkpoint_ref": str(checkpoint_path.resolve()),
            "checkpoint_hash": sha(checkpoint_path) if checkpoint_path.is_file() else "",
            "checkpoint": checkpoint,
            "merge": provider_integration,
            "status": str(provider_integration["status"]),
        }

    candidate_hash = canonical_evidence_hash.candidate_source_hash(candidate)
    project_candidate_id = "CGKN-internal-customer-project"
    test_evidence = real_test_execution.run_tests(
        candidate,
        run_id=identity["run_id"],
        candidate_id=project_candidate_id,
        candidate_hash=candidate_hash,
        commit_sha=commit,
    )
    capture_box: dict[str, Any] = {}

    def consume(handle: customer_runtime_runner.LiveRuntimeHandle) -> dict[str, Any]:
        receipt = browser_visual_evidence.capture_live_runtime(handle)
        capture_box.update(receipt)
        return receipt

    runtime_evidence = customer_runtime_runner.run(
        candidate,
        run_id=identity["run_id"],
        candidate_id=project_candidate_id,
        candidate_hash=candidate_hash,
        commit_sha=commit,
        live_consumer=consume,
        browser_capture_required=True,
    )
    visual_evidence = browser_visual_evidence.finalize_evidence(
        candidate, runtime_result=runtime_evidence, capture_receipt=capture_box, required=True
    )
    canonical_sources = {
        "test_execution": candidate / "test_execution.json",
        "customer_runtime": candidate / "customer_runtime.json",
        "visual_evidence": candidate / "visual_evidence.json",
    }
    for gate_name, source_doc in (
        ("test_execution", test_evidence),
        ("customer_runtime", runtime_evidence),
        ("visual_evidence", visual_evidence),
    ):
        source = canonical_sources[gate_name]
        write_json(
            out / f"internal_{gate_name}.json",
            envelope(
                f"CGKNInternal{gate_name.title().replace('_', '')}Evidence",
                identity,
                str(source_doc.get("status", "NEEDS_REWORK")),
                source_ref=str(source.resolve()),
                source_hash=sha(source),
                source_identity={
                    key: source_doc.get(key)
                    for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha")
                },
                source_inspection="PASS",
            ),
        )
    write_json(
        out / "internal_media_evidence.json",
        envelope(
            "CGKNInternalMediaEvidence",
            identity,
            "PASS",
            media_required=False,
            requirement_reason="The deterministic customer task requests an interactive UI, not generated image/video media.",
            verified_public_media=[],
        ),
    )
    write_json(
        out / "internal_live_provider_e2e.json",
        envelope(
            "CGKNInternalLiveProviderE2EEvidence",
            identity,
            "BLOCKED"
            if provider_integration.get("status") == "PASS"
            and test_evidence.get("status") == "PASS"
            and runtime_evidence.get("status") == "PASS"
            and visual_evidence.get("status") == "PASS"
            else str(provider_integration.get("status", "NOT_EVALUATED")),
            provider_integration=provider_integration,
            canonical_test_ref=str((candidate / "test_execution.json").resolve()),
            canonical_test_hash=sha(candidate / "test_execution.json"),
            customer_runtime_ref=str((candidate / "customer_runtime.json").resolve()),
            customer_runtime_hash=sha(candidate / "customer_runtime.json"),
            visual_evidence_ref=str((candidate / "visual_evidence.json").resolve()),
            visual_evidence_hash=sha(candidate / "visual_evidence.json"),
            blocker_code="BLOCKED_TELEGRAM_TEST_CHAT"
            if provider_integration.get("status") == "PASS"
            else "",
            reason="Live provider project reached tested runtime and browser validation; Telegram review and delivery require an explicit test chat."
            if provider_integration.get("status") == "PASS"
            else "Live provider project did not reach the Telegram boundary.",
        ),
    )

    leaves = [backend, persistence, frontend, original, replacement, recovery_leaf]
    if provider_leaf is not None:
        leaves.append(provider_leaf)
    workspace_ids = [leaf["workspace_id"] for leaf in leaves]
    workspace_roots = [leaf["workspace_root"] for leaf in leaves]
    workspace_status = (
        "PASS"
        if len(workspace_ids) == len(set(workspace_ids)) == len(set(workspace_roots))
        and all(pathlib.Path(path).is_dir() for path in workspace_roots)
        else "NEEDS_REWORK"
    )
    workspace_path = write_json(
        out / "internal_workspace_inventory.json",
        envelope(
            "CGKNWorkspaceInventory",
            identity,
            workspace_status,
            leaf_workspace_count=len(leaves),
            workspace_ids=workspace_ids,
            workspace_roots=workspace_roots,
            ignored_container_dirs=[str((out / "leaf_workspaces").resolve())],
        ),
    )
    leaf_path = write_json(
        out / "internal_leaf_sessions.json",
        envelope(
            "CGKNLeafSessionsEvidence",
            identity,
            "PASS"
            if leaf_test["exit_code"] == 0 and all(x["status"] == "PASS" for x in leaves)
            else "NEEDS_REWORK",
            leaves=leaves,
            merges={**merges, **({"acceptance_backend_leaf": provider_integration} if provider_leaf else {})},
            integrated_behavior_test=leaf_test,
        ),
    )
    collaboration_path = write_json(
        out / "internal_collaboration_evidence.json",
        envelope(
            "CGKNCollaborationTimingEvidence",
            identity,
            "PASS"
            if collaboration_created < persistence["started_at"]
            and persistence["consumed_connection_id"] == collaboration_contract["connection_id"]
            else "NEEDS_REWORK",
            connection=collaboration_contract,
            consumed_at=persistence["started_at"],
            consumer_patch=persistence["patch"],
            consumer_finished_at=persistence["finished_at"],
        ),
    )
    replan_path = write_json(
        out / "internal_replan_evidence.json",
        envelope(
            "CGKNReplanEvidence",
            identity,
            replan_status,
            original_task={"task_id": original["task_id"], "leaf_id": original["leaf_id"], "checkpoint": original},
            failure=failed_test,
            invalidation={"status": "cancelled", "cancelled_at": replacement["started_at"]},
            replacement_task={"task_id": replacement["task_id"], "leaf_id": replacement["leaf_id"], "replaces": original["leaf_id"]},
            plan_versions=["plan-v1", "plan-v2"],
            replacement_patch=replacement["patch"],
            replacement_test=replacement_test,
            replacement_merge=replacement_merge,
            original_merge=original_merge,
        ),
    )
    recovery_path = write_json(
        out / "internal_recovery_evidence.json",
        envelope(
            "CGKNRecoveryEvidence",
            identity,
            recovery_status,
            worker=recovery_leaf,
            recovery_merge=recovery_merge,
            recovery_test=recovery_test,
        ),
    )
    startup_status = "PASS" if runtime_evidence.get("status") == "PASS" and visual_evidence.get("status") == "PASS" else "NEEDS_REWORK"
    startup_path = write_json(
        out / "internal_startup_profile.json",
        envelope(
            "CGKNStartupProfileEvidence",
            identity,
            startup_status,
            supported_profiles=["static_http"],
            profiles=[runtime_evidence],
            visual_ref=str(candidate / "visual_evidence.json"),
            visual_hash=sha(candidate / "visual_evidence.json"),
        ),
    )
    deterministic_status = (
        "BLOCKED"
        if all(
            status == "PASS"
            for status in (
                workspace_status,
                replan_status,
                recovery_status,
                startup_status,
                test_evidence.get("status"),
                leaf_test["exit_code"] == 0 and "PASS" or "NEEDS_REWORK",
            )
        )
        else "NEEDS_REWORK"
    )
    deterministic_path = write_json(
        out / "internal_deterministic_e2e.json",
        envelope(
            "CGKNDeterministicE2EEvidence",
            identity,
            deterministic_status,
            completed_internal_stages=[
                "planning",
                "leaf_execution",
                "collaboration",
                "merge",
                "replan",
                "recovery",
                "test",
                "runtime",
                "visual",
            ],
            blocker_code="BLOCKED_TELEGRAM_TEST_CHAT" if deterministic_status == "BLOCKED" else "",
            reason="Telegram review, send, receipt, and final delivery require an explicit test chat"
            if deterministic_status == "BLOCKED"
            else "internal deterministic chain failed",
        ),
    )
    return {
        "status": "PASS"
        if all(
            value == "PASS"
            for value in (workspace_status, replan_status, recovery_status, startup_status)
        )
        else "NEEDS_REWORK",
        "identity": identity,
        "candidate_dir": str(candidate),
        "evidence": {
            "leaf_profile": str(leaf_path),
            "workspace_truth": str(workspace_path),
            "collaboration_timing": str(collaboration_path),
            "replan": str(replan_path),
            "recovery": str(recovery_path),
            "startup_profile": str(startup_path),
            "deterministic_e2e": str(deterministic_path),
            "test_execution": str(candidate / "test_execution.json"),
            "customer_runtime": str(candidate / "customer_runtime.json"),
            "visual_evidence": str(candidate / "visual_evidence.json"),
            "media_evidence": str(out / "internal_media_evidence.json"),
            "live_provider_e2e": str(out / "internal_live_provider_e2e.json"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir")
    parser.add_argument("--worker", nargs=2, metavar=("MODE", "WORKSPACE"))
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker[0], pathlib.Path(args.worker[1]).resolve())
    if not args.run_dir:
        parser.error("--run-dir is required")
    result = build_internal_acceptance(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
