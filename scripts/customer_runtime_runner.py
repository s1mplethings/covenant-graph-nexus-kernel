from __future__ import annotations

import json
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from contracts.customer_runtime import KIND, PRODUCER, SCHEMA_VERSION
from contracts.status import EvidenceStatus
from scripts import canonical_evidence_hash


@dataclass(frozen=True)
class LiveRuntimeHandle:
    run_id: str
    candidate_id: str
    candidate_hash: str
    commit_sha: str
    source_project_root: pathlib.Path
    execution_root: pathlib.Path
    pid: int
    port: int
    url: str
    process: subprocess.Popen[str]
    startup_argv: list[str]
    started_at: str
    source_candidate_hash: str
    copied_candidate_hash: str
    copied_manifest_hash: str

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def execution_root_exists(self) -> bool:
        return self.execution_root.exists()

    def candidate_hash_verified(self) -> bool:
        return self.source_candidate_hash == self.copied_candidate_hash == self.candidate_hash

    def is_isolated(self) -> bool:
        return self.execution_root.resolve() != self.source_project_root.resolve() and not _is_relative_to(
            self.execution_root, self.source_project_root
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return canonical_evidence_hash.sha256_bytes(text.encode("utf-8"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tree_hash(project: pathlib.Path) -> str:
    return canonical_evidence_hash.candidate_source_hash(project)


def _manifest_hash(manifest: dict[str, str]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return canonical_evidence_hash.sha256_bytes(payload)


def _is_relative_to(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _external_symlink_failures(project: pathlib.Path) -> list[str]:
    failures: list[str] = []
    for path in sorted(project.rglob("*")):
        if not path.is_symlink():
            continue
        try:
            target = path.resolve(strict=True)
        except OSError as exc:
            failures.append(f"{path.relative_to(project).as_posix()}:unresolved:{exc}")
            continue
        if not _is_relative_to(target, project):
            failures.append(f"{path.relative_to(project).as_posix()} -> {target}")
    return failures


def _copy_candidate_source(
    source_project: pathlib.Path,
    execution_root: pathlib.Path,
    source_manifest: dict[str, str],
) -> dict[str, Any]:
    failures: list[str] = []
    external_symlinks = _external_symlink_failures(source_project)
    if external_symlinks:
        return {
            "ok": False,
            "failures": [f"external_symlink:{item}" for item in external_symlinks],
            "copied_file_count": 0,
            "copied_manifest": {},
            "copied_manifest_hash": "",
            "copied_candidate_hash": "",
        }
    for relative, expected_hash in source_manifest.items():
        source = source_project / pathlib.Path(*relative.split("/"))
        destination = execution_root / pathlib.Path(*relative.split("/"))
        try:
            if source.is_symlink() and not _is_relative_to(source.resolve(strict=True), source_project):
                failures.append(f"external_symlink:{relative}")
                continue
            if not source.is_file():
                failures.append(f"missing_source:{relative}")
                continue
            if canonical_evidence_hash.sha256_file(source) != expected_hash:
                failures.append(f"source_hash_changed:{relative}")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination, follow_symlinks=True)
            if canonical_evidence_hash.sha256_file(destination) != expected_hash:
                failures.append(f"copied_hash_mismatch:{relative}")
        except Exception as exc:
            failures.append(f"copy_failed:{relative}:{exc}")
    copied_manifest = canonical_evidence_hash.candidate_source_manifest(execution_root)
    copied_candidate_hash = canonical_evidence_hash.candidate_source_hash(execution_root)
    if copied_manifest != source_manifest:
        failures.append("copied_manifest_mismatch")
    return {
        "ok": not failures,
        "failures": failures,
        "copied_file_count": len(copied_manifest),
        "copied_manifest": copied_manifest,
        "copied_manifest_hash": _manifest_hash(copied_manifest),
        "copied_candidate_hash": copied_candidate_hash,
    }


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
    if (project / "index.html").exists() or (project / "frontend" / "index.html").exists():
        return [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
    return []


def _start_process(argv: list[str], cwd: pathlib.Path) -> subprocess.Popen[str]:
    return subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def run(
    project_dir: str | pathlib.Path,
    *,
    run_id: str | None = None,
    candidate_id: str | None = None,
    candidate_hash: str | None = None,
    commit_sha: str | None = None,
    production_provenance_ref: str | pathlib.Path | None = None,
    production_provenance_hash: str = "",
    customer_path: str = "/",
    live_consumer: Callable[[LiveRuntimeHandle], dict[str, Any]] | None = None,
    browser_capture_required: bool = False,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    started = _now()
    run_id = run_id or f"runtime-run-{uuid.uuid4().hex}"
    candidate_id = candidate_id or project.name or "candidate"
    source_manifest = canonical_evidence_hash.candidate_source_manifest(project)
    source_manifest_hash = _manifest_hash(source_manifest)
    current_candidate_hash = _tree_hash(project)
    expected_candidate_hash = candidate_hash
    candidate_hash = candidate_hash or current_candidate_hash
    commit_sha = commit_sha or _commit_sha(project)
    execution_root = pathlib.Path("")
    port = _free_port()
    url = f"http://127.0.0.1:{port}{customer_path}"
    argv: list[str] = []
    proc: subprocess.Popen[str] | None = None
    observed = ""
    health_code = 0
    health_body = ""
    shutdown_result: dict[str, Any] = {"stopped": False}
    cleanup_result: dict[str, Any] = {"removed": False}
    browser_capture_receipt: dict[str, Any] = {
        "capture_status": EvidenceStatus.NOT_EVALUATED.value,
        "error": "not_required" if not browser_capture_required else "not_started",
    }
    browser_capture_hash = canonical_evidence_hash.canonical_json_hash(browser_capture_receipt, ())
    copy_result: dict[str, Any] = {
        "ok": False,
        "failures": [],
        "copied_file_count": 0,
        "copied_manifest_hash": "",
        "copied_candidate_hash": "",
    }
    status = EvidenceStatus.FAIL.value
    try:
        with tempfile.TemporaryDirectory(prefix="cgkn_customer_runtime_") as temp_dir:
            execution_root = pathlib.Path(temp_dir).resolve()
            copy_result = _copy_candidate_source(project, execution_root, source_manifest)
            copied_candidate_hash = str(copy_result.get("copied_candidate_hash") or "")
            argv = _startup_for(execution_root, port)
            try:
                if not copy_result.get("ok"):
                    observed = "\n".join(str(item) for item in copy_result.get("failures", [])) or "candidate copy failed"
                elif current_candidate_hash != copied_candidate_hash:
                    observed = "candidate copy hash mismatch"
                elif expected_candidate_hash is not None and current_candidate_hash != expected_candidate_hash:
                    observed = "candidate source hash changed before runtime"
                elif not argv:
                    observed = "no supported startup command"
                else:
                    proc = _start_process(argv, execution_root)
                    health_code, health_body = _wait_for_health(f"http://127.0.0.1:{port}/")
                    if health_code:
                        _code, observed = _get(url)
                        status = EvidenceStatus.PASS.value if observed.strip() else EvidenceStatus.FAIL.value
                        if live_consumer is not None:
                            handle = LiveRuntimeHandle(
                                run_id=run_id,
                                candidate_id=candidate_id,
                                candidate_hash=candidate_hash,
                                commit_sha=commit_sha,
                                source_project_root=project,
                                execution_root=execution_root,
                                pid=int(proc.pid),
                                port=port,
                                url=url,
                                process=proc,
                                startup_argv=argv,
                                started_at=started,
                                source_candidate_hash=current_candidate_hash,
                                copied_candidate_hash=copied_candidate_hash,
                                copied_manifest_hash=str(copy_result.get("copied_manifest_hash") or ""),
                            )
                            try:
                                browser_capture_receipt = live_consumer(handle)
                            except Exception as exc:
                                browser_capture_receipt = {
                                    "capture_status": EvidenceStatus.FAIL.value,
                                    "error": f"{type(exc).__name__}: {exc}",
                                    "runtime_pid": int(proc.pid),
                                    "runtime_url": url,
                                    "runtime_port": port,
                                    "runtime_execution_root": str(execution_root),
                                    "runtime_alive_before_capture": proc.poll() is None,
                                    "runtime_alive_after_capture": proc.poll() is None,
                                }
                            browser_capture_hash = canonical_evidence_hash.canonical_json_hash(browser_capture_receipt, ())
                            if browser_capture_required and browser_capture_receipt.get("capture_status") != EvidenceStatus.PASS.value:
                                status = EvidenceStatus.FAIL.value
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
        cleanup_result = {"removed": bool(str(execution_root) and not execution_root.exists())}
    except Exception as exc:
        observed = (observed + "\n" if observed else "") + f"{type(exc).__name__}: {exc}"
        status = EvidenceStatus.FAIL.value
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
            shutdown_result = {"stopped": proc.poll() is not None, "returncode": proc.returncode, "forced": True}
    if not cleanup_result.get("removed"):
        status = EvidenceStatus.FAIL.value
    if browser_capture_required and browser_capture_receipt.get("capture_status") != EvidenceStatus.PASS.value:
        status = EvidenceStatus.FAIL.value
    finished = _now()
    health_body_hash = _sha256_text(health_body)
    copied_candidate_hash = str(copy_result.get("copied_candidate_hash") or "")
    observed_result = observed[:4000]
    evidence: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "source_project_root": str(project),
        "execution_root": str(execution_root),
        "execution_root_isolated": bool(str(execution_root) and execution_root.resolve() != project),
        "source_candidate_hash": current_candidate_hash,
        "copied_candidate_hash": copied_candidate_hash,
        "copied_file_count": int(copy_result.get("copied_file_count") or 0),
        "source_manifest_hash": source_manifest_hash,
        "copied_manifest_hash": str(copy_result.get("copied_manifest_hash") or ""),
        "candidate_hash_observed": current_candidate_hash,
        "candidate_hash_verified": current_candidate_hash == candidate_hash == copied_candidate_hash,
        "commit_sha": commit_sha,
        "production_provenance_ref": str(
            pathlib.Path(production_provenance_ref).resolve()
        )
        if production_provenance_ref
        else "",
        "production_provenance_hash": production_provenance_hash,
        "producer": PRODUCER,
        "created_at": finished,
        "status": status,
        "artifact_hash": "",
        "startup_argv": argv,
        "cwd": str(execution_root),
        "clean_environment_root": str(execution_root),
        "dependency_setup": {"status": "not_required_for_static_http"},
        "pid": int(proc.pid) if proc is not None else 0,
        "port": port,
        "url": url,
        "health_probe": {"status_code": health_code, "response_hash": health_body_hash},
        "customer_action": f"GET {customer_path}",
        "expected_result": "non-empty HTTP response body",
        "observed_result": observed_result,
        "observed_result_hash": _sha256_text(observed_result),
        "shutdown_result": shutdown_result,
        "cleanup_result": cleanup_result,
        "browser_capture_required": bool(browser_capture_required),
        "browser_capture_status": str(browser_capture_receipt.get("capture_status") or EvidenceStatus.NOT_EVALUATED.value),
        "browser_capture_id": str(browser_capture_receipt.get("capture_id") or ""),
        "browser_capture_hash": browser_capture_hash,
        "browser_runtime_pid": int(browser_capture_receipt.get("runtime_pid") or 0),
        "browser_runtime_url": str(browser_capture_receipt.get("runtime_url") or ""),
        "browser_runtime_port": int(browser_capture_receipt.get("runtime_port") or 0),
        "browser_runtime_execution_root": str(browser_capture_receipt.get("runtime_execution_root") or ""),
        "runtime_alive_before_browser": bool(browser_capture_receipt.get("runtime_alive_before_capture") or False),
        "runtime_alive_after_browser": bool(browser_capture_receipt.get("runtime_alive_after_capture") or False),
        "browser_capture_receipt": browser_capture_receipt,
        "started_at": started,
        "finished_at": finished,
    }
    evidence["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(evidence, ("artifact_hash",))
    path = project / "customer_runtime.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["result_file"] = str(path)
    return evidence


def inspect(
    path: str | pathlib.Path,
    *,
    run_id: str | None = None,
    candidate_id: str | None = None,
    candidate_hash: str | None = None,
    commit_sha: str | None = None,
    production_provenance_ref: str | pathlib.Path | None = None,
    production_provenance_hash: str | None = None,
) -> dict[str, Any]:
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
    expected_hash = canonical_evidence_hash.canonical_json_hash(doc, ("artifact_hash",))
    if not doc.get("artifact_hash") or doc.get("artifact_hash") != expected_hash:
        missing.append("artifact_hash_mismatch")
    if doc.get("status") != EvidenceStatus.PASS.value:
        missing.append("status")
    if int(doc.get("pid", 0) or 0) <= 0:
        missing.append("pid")
    if int(doc.get("health_probe", {}).get("status_code", 0) or 0) < 200:
        missing.append("health_probe")
    if not doc.get("observed_result_hash") or _sha256_text(str(doc.get("observed_result", ""))) != doc.get("observed_result_hash"):
        missing.append("observed_result_hash")
    project = evidence_path.parent.resolve()
    source_root_value = str(doc.get("source_project_root", "") or "")
    execution_root_value = str(doc.get("execution_root", "") or "")
    cwd_value = str(doc.get("cwd", "") or "")
    clean_root_value = str(doc.get("clean_environment_root", "") or "")
    source_root = pathlib.Path(source_root_value).resolve() if source_root_value else pathlib.Path("")
    execution_root = pathlib.Path(execution_root_value).resolve() if execution_root_value else pathlib.Path("")
    cwd = pathlib.Path(cwd_value).resolve() if cwd_value else pathlib.Path("")
    if not source_root_value:
        missing.append("source_project_root")
    elif source_root != project:
        missing.append("source_project_root")
    if not execution_root_value:
        missing.append("execution_root")
    if doc.get("execution_root_isolated") is not True:
        missing.append("execution_root_isolated")
    if source_root_value and execution_root_value and source_root == execution_root:
        missing.append("execution_root")
    if source_root_value and execution_root_value and _is_relative_to(execution_root, source_root):
        missing.append("execution_root_isolated")
    if not cwd_value or (execution_root_value and cwd != execution_root):
        missing.append("cwd")
    if clean_root_value and execution_root_value and pathlib.Path(clean_root_value).resolve() != execution_root:
        missing.append("clean_environment_root")
    if int(doc.get("copied_file_count", 0) or 0) <= 0:
        missing.append("copied_file_count")
    if not doc.get("copied_manifest_hash"):
        missing.append("copied_manifest_hash")
    if doc.get("cleanup_result", {}).get("removed") is not True:
        missing.append("cleanup_result")
    if execution_root_value and execution_root.exists():
        missing.append("execution_root_cleanup")
    current_candidate_hash = _tree_hash(project)
    source_candidate_hash = doc.get("source_candidate_hash")
    copied_candidate_hash = doc.get("copied_candidate_hash")
    if doc.get("candidate_hash") != current_candidate_hash:
        missing.append("candidate_hash_current")
    if source_candidate_hash != doc.get("candidate_hash"):
        missing.append("source_candidate_hash")
    if copied_candidate_hash != doc.get("candidate_hash"):
        missing.append("copied_candidate_hash")
    if doc.get("candidate_hash_observed") and doc.get("candidate_hash_observed") != doc.get("candidate_hash"):
        missing.append("candidate_hash_observed")
    if doc.get("candidate_hash_verified") is not True:
        missing.append("candidate_hash_verified")
    if not doc.get("shutdown_result", {}).get("stopped"):
        missing.append("shutdown_result")
    if doc.get("browser_capture_required") is True:
        receipt = doc.get("browser_capture_receipt", {})
        if not isinstance(receipt, dict):
            receipt = {}
            missing.append("browser_capture_receipt")
        expected_capture_hash = canonical_evidence_hash.canonical_json_hash(receipt, ())
        if not doc.get("browser_capture_hash") or doc.get("browser_capture_hash") != expected_capture_hash:
            missing.append("browser_capture_hash")
        if doc.get("browser_capture_status") != EvidenceStatus.PASS.value or receipt.get("capture_status") != EvidenceStatus.PASS.value:
            missing.append("browser_capture_status")
        if not doc.get("browser_capture_id") or doc.get("browser_capture_id") != receipt.get("capture_id"):
            missing.append("browser_capture_id")
        if int(doc.get("browser_runtime_pid", 0) or 0) != int(doc.get("pid", 0) or 0):
            missing.append("browser_runtime_pid")
        if doc.get("browser_runtime_url") != doc.get("url"):
            missing.append("browser_runtime_url")
        if int(doc.get("browser_runtime_port", 0) or 0) != int(doc.get("port", 0) or 0):
            missing.append("browser_runtime_port")
        if str(doc.get("browser_runtime_execution_root") or "") != str(doc.get("execution_root") or ""):
            missing.append("browser_runtime_execution_root")
        if doc.get("runtime_alive_before_browser") is not True or receipt.get("runtime_alive_before_capture") is not True:
            missing.append("runtime_alive_before_browser")
        if doc.get("runtime_alive_after_browser") is not True or receipt.get("runtime_alive_after_capture") is not True:
            missing.append("runtime_alive_after_browser")
    if candidate_hash is not None and doc.get("candidate_hash") != candidate_hash:
        missing.append("candidate_hash")
    if run_id is not None and doc.get("run_id") != run_id:
        missing.append("run_id")
    if candidate_id is not None and doc.get("candidate_id") != candidate_id:
        missing.append("candidate_id")
    if commit_sha is not None and doc.get("commit_sha") != commit_sha:
        missing.append("commit_sha")
    if production_provenance_ref is not None:
        expected_provenance = pathlib.Path(production_provenance_ref).resolve()
        actual_ref_value = str(doc.get("production_provenance_ref", "")).strip()
        actual_ref = pathlib.Path(actual_ref_value).resolve() if actual_ref_value else pathlib.Path()
        if actual_ref != expected_provenance:
            missing.append("production_provenance_ref")
        expected_file_hash = (
            canonical_evidence_hash.sha256_file(expected_provenance)
            if expected_provenance.is_file() and not expected_provenance.is_symlink()
            else ""
        )
        if (
            not expected_file_hash
            or doc.get("production_provenance_hash") != expected_file_hash
            or (
                production_provenance_hash is not None
                and doc.get("production_provenance_hash")
                != production_provenance_hash
            )
        ):
            missing.append("production_provenance_hash")
    return {"status": "PASS" if not missing else "FAIL", "missing": missing, "details": doc}
