from __future__ import annotations

import hashlib
import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from contracts.customer_runtime import KIND, PRODUCER, SCHEMA_VERSION
from contracts.status import EvidenceStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tree_hash(project: pathlib.Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in project.rglob("*") if item.is_file()):
        rel = path.relative_to(project).as_posix()
        if rel == "customer_runtime.json" or ".pytest_cache/" in rel:
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _commit_sha(project: pathlib.Path) -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, text=True, capture_output=True, timeout=10)
    except Exception:
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "unknown"


def _get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - localhost runtime probe
        return int(response.status), response.read().decode("utf-8", errors="replace")


def _wait_for_health(url: str, seconds: float = 5.0) -> tuple[int, str]:
    deadline = time.time() + seconds
    last_body = ""
    while time.time() < deadline:
        try:
            return _get(url)
        except Exception as exc:
            last_body = str(exc)
            time.sleep(0.1)
    return 0, last_body


def _startup_for(project: pathlib.Path, port: int) -> list[str]:
    if (project / "index.html").exists():
        return [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
    return []


def run(
    project_dir: str | pathlib.Path,
    *,
    run_id: str | None = None,
    candidate_id: str | None = None,
    candidate_hash: str | None = None,
    commit_sha: str | None = None,
    customer_path: str = "/",
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    started = _now()
    run_id = run_id or f"runtime-run-{uuid.uuid4().hex}"
    candidate_id = candidate_id or project.name or "candidate"
    candidate_hash = candidate_hash or _tree_hash(project)
    commit_sha = commit_sha or _commit_sha(project)
    clean_root = pathlib.Path(tempfile.mkdtemp(prefix="cgkn_customer_runtime_"))
    port = _free_port()
    argv = _startup_for(project, port)
    url = f"http://127.0.0.1:{port}{customer_path}"
    proc: subprocess.Popen[str] | None = None
    observed = ""
    health_code = 0
    shutdown_result: dict[str, Any] = {"stopped": False}
    status = EvidenceStatus.FAIL.value
    try:
        if not argv:
            observed = "no supported startup command"
        else:
            proc = subprocess.Popen(argv, cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            health_code, health_body = _wait_for_health(f"http://127.0.0.1:{port}/")
            if health_code:
                _code, observed = _get(url)
                status = EvidenceStatus.PASS.value if observed.strip() else EvidenceStatus.FAIL.value
            else:
                observed = health_body
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            shutdown_result = {"stopped": proc.poll() is not None, "returncode": proc.returncode}
    finished = _now()
    health_body_hash = _sha256_text(observed if health_code else "")
    evidence: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "commit_sha": commit_sha,
        "producer": PRODUCER,
        "created_at": finished,
        "status": status,
        "artifact_hash": "",
        "startup_argv": argv,
        "cwd": str(project),
        "clean_environment_root": str(clean_root),
        "dependency_setup": {"status": "not_required_for_static_http"},
        "pid": int(proc.pid) if proc is not None else 0,
        "port": port,
        "url": url,
        "health_probe": {"status_code": health_code, "response_hash": health_body_hash},
        "customer_action": f"GET {customer_path}",
        "expected_result": "non-empty HTTP response body",
        "observed_result": observed[:4000],
        "observed_result_hash": _sha256_text(observed),
        "shutdown_result": shutdown_result,
        "started_at": started,
        "finished_at": finished,
    }
    evidence["artifact_hash"] = _sha256_text(json.dumps({**evidence, "artifact_hash": ""}, sort_keys=True, ensure_ascii=False))
    path = project / "customer_runtime.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["result_file"] = str(path)
    return evidence


def inspect(path: str | pathlib.Path, *, candidate_hash: str | None = None, commit_sha: str | None = None) -> dict[str, Any]:
    evidence_path = pathlib.Path(path)
    if evidence_path.is_dir():
        evidence_path = evidence_path / "customer_runtime.json"
    if not evidence_path.exists():
        return {"status": "FAIL", "missing": ["customer_runtime.json"]}
    try:
        doc = json.loads(evidence_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"status": "FAIL", "missing": ["valid_json"], "error": str(exc)}
    missing: list[str] = []
    if doc.get("kind") != KIND:
        missing.append("kind")
    if doc.get("schema_version") != SCHEMA_VERSION:
        missing.append("schema_version")
    if doc.get("status") != EvidenceStatus.PASS.value:
        missing.append("status")
    if int(doc.get("pid", 0) or 0) <= 0:
        missing.append("pid")
    if int(doc.get("health_probe", {}).get("status_code", 0) or 0) < 200:
        missing.append("health_probe")
    if not doc.get("observed_result_hash") or _sha256_text(str(doc.get("observed_result", ""))) != doc.get("observed_result_hash"):
        missing.append("observed_result_hash")
    if not doc.get("shutdown_result", {}).get("stopped"):
        missing.append("shutdown_result")
    if candidate_hash is not None and doc.get("candidate_hash") != candidate_hash:
        missing.append("candidate_hash")
    if commit_sha is not None and doc.get("commit_sha") != commit_sha:
        missing.append("commit_sha")
    return {"status": "PASS" if not missing else "FAIL", "missing": missing, "details": doc}
