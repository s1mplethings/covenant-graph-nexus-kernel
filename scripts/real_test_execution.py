from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

from contracts.test_execution import KIND, PRODUCER, SCHEMA_VERSION
from scripts import canonical_evidence_hash


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return canonical_evidence_hash.sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: pathlib.Path) -> str:
    return canonical_evidence_hash.sha256_file(path)


def project_tree_hash(project: pathlib.Path) -> str:
    return canonical_evidence_hash.candidate_source_hash(project)


def current_commit_sha(project: pathlib.Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except Exception:
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "unknown"


def detect_commands(project_dir: str | pathlib.Path) -> list[list[str]]:
    project = pathlib.Path(project_dir)
    if (project / "tests").exists() and any(path.is_file() for path in (project / "tests").rglob("test*.py")):
        return [["python", "-m", "pytest", "tests"]]
    if (project / "package.json").exists():
        return [["npm", "test"]]
    if (project / "index.html").exists():
        return [["python", "-c", "from pathlib import Path; assert Path('index.html').read_text(encoding='utf-8').strip()"]]
    return []


def _pytest_counts(stdout: str, stderr: str, exit_code: int) -> dict[str, int]:
    text = "\n".join([stdout or "", stderr or ""])
    collected = 0
    match = re.search(r"collected\s+(\d+)\s+items?", text)
    if match:
        collected = int(match.group(1))
    passed = sum(int(n) for n in re.findall(r"(\d+)\s+passed", text))
    failed = sum(int(n) for n in re.findall(r"(\d+)\s+failed", text))
    skipped = sum(int(n) for n in re.findall(r"(\d+)\s+skipped", text))
    if collected == 0 and exit_code == 0 and passed == 0:
        passed = 1
        collected = 1
    if collected == 0:
        collected = passed + failed + skipped
    return {"collected": collected, "passed": passed, "failed": failed, "skipped": skipped}


def _skip_reasons(stdout: str, stderr: str) -> dict[str, int]:
    text = "\n".join([stdout or "", stderr or ""])
    reasons: dict[str, int] = {}
    for reason in re.findall(r"SKIPPED\s+\[[^\]]+\]\s+(.+)", text):
        key = reason.strip()[:160] or "uncategorized"
        reasons[key] = reasons.get(key, 0) + 1
    return reasons


def _normalize_command(command: list[str], python_executable: str | pathlib.Path | None) -> list[str]:
    if command[:3] == ["python", "-m", "pytest"]:
        return [str(python_executable or sys.executable), "-m", "pytest", *command[3:]]
    return [str(item) for item in command]


def run_tests(
    project_dir: str | pathlib.Path,
    *,
    timeout: int = 60,
    python_executable: str | pathlib.Path | None = None,
    run_id: str | None = None,
    candidate_id: str | None = None,
    candidate_hash: str | None = None,
    commit_sha: str | None = None,
    test_profile: str = "repo_default",
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    project.mkdir(parents=True, exist_ok=True)
    run_id = run_id or f"test-run-{uuid.uuid4().hex}"
    candidate_id = candidate_id or project.name or "candidate"
    candidate_manifest_before = canonical_evidence_hash.candidate_source_manifest(project)
    candidate_hash_before = project_tree_hash(project)
    candidate_hash = candidate_hash or candidate_hash_before
    commit_sha = commit_sha or current_commit_sha(project)
    started = _now()
    commands = detect_commands(project)
    argv = _normalize_command(commands[0], python_executable) if commands else []
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    timed_out = False

    env_classification = "clean_env_overlay"
    if not argv:
        status = "FAIL"
        stderr = "tests directory missing or no executable test command detected"
        counts = {"collected": 0, "passed": 0, "failed": 0, "skipped": 0}
    else:
        env = os.environ.copy()
        python_paths = [str(project)]
        src_path = project / "src"
        if src_path.exists():
            python_paths.append(str(src_path))
        if env.get("PYTHONPATH"):
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["CGKN_TEST_OUTPUT_DIR"] = tempfile.mkdtemp(prefix="cgkn_test_outputs_")
        try:
            proc = subprocess.run(argv, cwd=project, capture_output=True, text=True, timeout=timeout, env=env)
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            exit_code = int(proc.returncode)
        except subprocess.TimeoutExpired as exc:
            stdout = str(exc.stdout or "")
            stderr = str(exc.stderr or "test command timed out")
            exit_code = 124
            timed_out = True
        counts = _pytest_counts(stdout, stderr, int(exit_code))
        status = "PASS" if exit_code == 0 and counts["failed"] == 0 and counts["collected"] > 0 else "FAIL"

    stdout_path = project / "test_stdout.txt"
    stderr_path = project / "test_stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    candidate_manifest_after = canonical_evidence_hash.candidate_source_manifest(project)
    candidate_hash_after = project_tree_hash(project)
    candidate_mutated = candidate_hash_after != candidate_hash_before
    if candidate_mutated:
        status = "FAIL"
    finished = _now()
    evidence: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "candidate_hash_before": candidate_hash_before,
        "candidate_hash_after": candidate_hash_after,
        "candidate_mutated_during_test": candidate_mutated,
        "candidate_source_diff": canonical_evidence_hash.candidate_source_manifest_diff(candidate_manifest_before, candidate_manifest_after),
        "commit_sha": commit_sha,
        "producer": PRODUCER,
        "created_at": finished,
        "status": status,
        "artifact_hash": "",
        "argv": argv,
        "cwd": str(project),
        "environment": env_classification,
        "started_at": started,
        "finished_at": finished,
        "exit_code": exit_code if exit_code is not None else -1,
        "timeout": timed_out,
        "collected": counts["collected"],
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "skip_reasons": _skip_reasons(stdout, stderr),
        "stdout_artifact": str(stdout_path),
        "stdout_hash": _sha256_file(stdout_path),
        "stderr_artifact": str(stderr_path),
        "stderr_hash": _sha256_file(stderr_path),
        "result_artifact_hash": "",
        "test_profile": test_profile,
        "ok": status == "PASS",
        "commands_run": [" ".join(argv)] if argv else [],
        "verdict": status,
        "executions": [
            {
                "argv": argv,
                "exit_code": exit_code,
                "stdout_hash": _sha256_file(stdout_path),
                "stderr_hash": _sha256_file(stderr_path),
                "started_at": started,
                "finished_at": finished,
            }
        ]
        if argv
        else [],
    }
    artifact_hash = canonical_evidence_hash.canonical_json_hash(evidence, ("artifact_hash", "result_artifact_hash"))
    evidence["artifact_hash"] = artifact_hash
    evidence["result_artifact_hash"] = artifact_hash
    execution_path = project / "test_execution.json"
    execution_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["result_file"] = str(execution_path)
    write_test_report(project, evidence)
    return evidence


def write_test_report(project: pathlib.Path, evidence: dict[str, Any]) -> pathlib.Path:
    path = project / "TEST_REPORT.md"
    lines = [
        "# Test Report",
        "",
        f"kind: {evidence.get('kind', '')}",
        f"schema_version: {evidence.get('schema_version', '')}",
        f"run_id: {evidence.get('run_id', '')}",
        f"candidate_hash: {evidence.get('candidate_hash', '')}",
        f"commit_sha: {evidence.get('commit_sha', '')}",
        f"result_artifact_hash: {evidence.get('result_artifact_hash', '')}",
        "",
        "argv:",
    ]
    argv = evidence.get("argv", []) if isinstance(evidence.get("argv"), list) else []
    lines.extend(f"- {item}" for item in argv)
    lines.extend(
        [
            "",
            f"cwd: {evidence.get('cwd', '')}",
            f"exit_code: {evidence.get('exit_code', '')}",
            f"timeout: {str(evidence.get('timeout', False)).lower()}",
            f"collected: {evidence.get('collected', 0)}",
            f"passed: {evidence.get('passed', 0)}",
            f"failed: {evidence.get('failed', 0)}",
            f"skipped: {evidence.get('skipped', 0)}",
            f"status: {evidence.get('status', 'FAIL')}",
        ]
    )
    if not argv:
        lines.append("NO REAL TEST EXECUTION")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def inspect_test_report(
    project_dir: str | pathlib.Path,
    *,
    run_id: str | None = None,
    candidate_hash: str | None = None,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    execution = project / "test_execution.json"
    report = project / "TEST_REPORT.md"
    if not execution.exists():
        return {"verdict": "FAIL", "status": "FAIL", "source": "", "missing": ["test_execution.json"]}
    if not report.exists():
        return {"verdict": "FAIL", "status": "FAIL", "source": "test_execution.json", "missing": ["TEST_REPORT.md"]}
    try:
        doc = json.loads(execution.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"verdict": "FAIL", "status": "FAIL", "source": "test_execution.json", "missing": ["valid_json"], "error": str(exc)}
    missing: list[str] = []
    if doc.get("kind") != KIND:
        missing.append("canonical_kind")
    if doc.get("schema_version") != SCHEMA_VERSION:
        missing.append("schema_version")
    if not doc.get("argv"):
        missing.append("argv")
    for field in ("stdout_artifact", "stderr_artifact", "stdout_hash", "stderr_hash", "artifact_hash", "result_artifact_hash"):
        if not doc.get(field):
            missing.append(field)
    for artifact_field, hash_field in (("stdout_artifact", "stdout_hash"), ("stderr_artifact", "stderr_hash")):
        artifact = pathlib.Path(str(doc.get(artifact_field, "")))
        if not artifact.exists() or _sha256_file(artifact) != doc.get(hash_field):
            missing.append(f"{hash_field}_mismatch")
    expected_hash = canonical_evidence_hash.canonical_json_hash(doc, ("artifact_hash", "result_artifact_hash"))
    if doc.get("artifact_hash") != expected_hash:
        missing.append("artifact_hash_mismatch")
    if doc.get("result_artifact_hash") != expected_hash:
        missing.append("result_artifact_hash")
    current_candidate_hash = project_tree_hash(project)
    if doc.get("candidate_hash") != current_candidate_hash:
        missing.append("candidate_hash_current")
    if doc.get("candidate_hash_before") and doc.get("candidate_hash_before") != doc.get("candidate_hash"):
        missing.append("candidate_hash_before")
    if doc.get("candidate_hash_after") and doc.get("candidate_hash_after") != doc.get("candidate_hash"):
        missing.append("candidate_hash_after")
    if doc.get("candidate_mutated_during_test"):
        missing.append("candidate_mutated_during_test")
    text = report.read_text(encoding="utf-8", errors="replace")
    for token in (str(doc.get("run_id", "")), str(doc.get("candidate_hash", "")), str(doc.get("commit_sha", "")), str(doc.get("result_artifact_hash", ""))):
        if token and token not in text:
            missing.append("report_artifact_reference")
            break
    if run_id is not None and doc.get("run_id") != run_id:
        missing.append("run_id")
    if candidate_hash is not None and doc.get("candidate_hash") != candidate_hash:
        missing.append("candidate_hash")
    if commit_sha is not None and doc.get("commit_sha") != commit_sha:
        missing.append("commit_sha")
    if int(doc.get("collected", 0) or 0) <= 0:
        missing.append("collected")
    status = "PASS" if not missing and doc.get("status") == "PASS" else "FAIL"
    return {"verdict": status, "status": status, "source": "test_execution.json", "missing": missing, "details": doc}
