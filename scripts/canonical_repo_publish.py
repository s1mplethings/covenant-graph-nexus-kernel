#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Sequence


ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLISH_DIR = pathlib.Path(".cgkn/publish")
COMMIT_CLASSES = {"SOURCE", "TEST", "CONTRACT", "SCHEMA", "CURRENT_GOVERNANCE", "CURRENT_DOC"}
REVIEW_CLASSES = {"MIGRATION", "DURABLE_EVIDENCE"}
EXCLUDE_CLASSES = {"RUNTIME", "GENERATED", "CACHE", "LOG", "TEMP", "SCREENSHOT_TEMP", "LOCAL_STATE"}
FORBIDDEN_FORCE_OPTIONS = {"-f", "--force", "--force-with-lease"}
TRANSIENT_PUSH_ERRORS = ("ssl_error_syscall", "timed out", "connection reset", "could not resolve host")
CONVENTIONAL_MESSAGE = re.compile(r"^(feat|fix|refactor|test|docs|chore)(\([^)]+\))?:\s+\S")
SECRET_NAMES = re.compile(r"(^|/)(\.env(?:\..*)?|id_rsa.*|private_key.*|credentials.*)(/|$)", re.I)
SECRET_SUFFIXES = {".pem", ".key"}
SECRET_CONTENT = re.compile(
    r"(?i)(?:api[_-]?key|bearer|provider[_-]?secret|access[_-]?token)\s*[:=]\s*['\"]?"
    r"(?!placeholder|example|dummy|test|changeme|env\.|process\.|this\.|config\.|options?\.)"
    r"[A-Za-z0-9_\-/.]{16,}"
)

GitRunner = Callable[[pathlib.Path, Sequence[str]], dict[str, Any]]


class PublishBlocked(RuntimeError):
    def __init__(self, classification: str, detail: Any = None):
        self.classification = classification
        self.detail = detail
        super().__init__(classification)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_hash(document: dict[str, Any], excluded: tuple[str, ...] = ()) -> str:
    payload = {key: value for key, value in document.items() if key not in excluded}
    return sha256_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def run_git(root: pathlib.Path, args: Sequence[str]) -> dict[str, Any]:
    command = ["git", *args]
    try:
        completed = subprocess.run(command, cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    except Exception as exc:
        return {"ok": False, "command": command, "returncode": None, "stdout": "", "stderr": str(exc), "classification": "GIT_COMMAND_FAILED"}
    return {
        "ok": completed.returncode == 0,
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "classification": "PASS" if completed.returncode == 0 else "GIT_COMMAND_FAILED",
    }


def require_git(root: pathlib.Path, args: Sequence[str], runner: GitRunner = run_git) -> dict[str, Any]:
    result = runner(root, args)
    if not result.get("ok"):
        raise PublishBlocked("BLOCKED_GIT_STATE", result)
    return result


def _lines(result: dict[str, Any]) -> list[str]:
    return [line for line in str(result.get("stdout", "")).splitlines() if line.strip()]


def parse_status(lines: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in lines:
        if len(line) < 3:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rows.append({"git_status": code, "path": path.replace("\\", "/")})
    return rows


def _read_source_identity(root: pathlib.Path) -> dict[str, Any]:
    scripts = root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import source_identity

    try:
        return source_identity.capture(root)
    except Exception as exc:
        raise PublishBlocked("BLOCKED_GIT_STATE", str(exc)) from exc


def repository_state(root: pathlib.Path, runner: GitRunner = run_git) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    branch = require_git(root, ["branch", "--show-current"], runner)["stdout"].strip()
    head = require_git(root, ["rev-parse", "HEAD"], runner)["stdout"].strip()
    status_rows = parse_status(_lines(require_git(root, ["status", "--porcelain=v1", "--untracked-files=all"], runner)))
    tracking_result = runner(root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    tracking = tracking_result.get("stdout", "").strip() if tracking_result.get("ok") else ""
    remote_ref = tracking or (f"origin/{branch}" if branch else "")
    remote_result = runner(root, ["rev-parse", remote_ref]) if remote_ref else {"ok": False}
    remote_head = remote_result.get("stdout", "").strip() if remote_result.get("ok") else ""
    ahead = behind = 0
    if remote_head:
        counts = require_git(root, ["rev-list", "--left-right", "--count", f"{remote_ref}...HEAD"], runner)["stdout"].split()
        behind, ahead = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
    staged = [row["path"] for row in status_rows if row["git_status"][0] not in {" ", "?"}]
    unstaged = [row["path"] for row in status_rows if row["git_status"][1] not in {" ", "?"}]
    untracked = [row["path"] for row in status_rows if row["git_status"] == "??"]
    identity = _read_source_identity(root)
    return {
        "kind": "CGKNRepositoryState", "schema_version": "1.0", "branch": branch,
        "local_head": head, "remote": remote_ref.split("/", 1)[0] if "/" in remote_ref else "origin",
        "tracking_ref": tracking, "remote_ref": remote_ref, "remote_head": remote_head,
        "ahead": ahead, "behind": behind, "diverged": bool(ahead and behind),
        "working_tree_clean": not status_rows, "staged": sorted(set(staged)),
        "unstaged": sorted(set(unstaged)), "untracked": sorted(set(untracked)),
        "status_rows": status_rows, "source_identity_hash": identity["source_identity_hash"],
    }


def _secret_content(path: pathlib.Path) -> bool:
    if not path.is_file() or path.stat().st_size > 1_000_000:
        return False
    try:
        return bool(SECRET_CONTENT.search(path.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


def classify_path(path: str, root: pathlib.Path | None = None) -> tuple[str, str]:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    pure = pathlib.PurePosixPath(normalized)
    lower = normalized.lower()
    if SECRET_NAMES.search(normalized) or pure.suffix.lower() in SECRET_SUFFIXES or (root and _secret_content(pathlib.Path(root) / normalized)):
        return "SECRET", "secret-like name, suffix, or non-placeholder credential content"
    if lower.startswith(".cgkn/"):
        return "LOCAL_STATE", "project-local CGKN state"
    if lower.startswith(".cgnk/governance/"):
        return "CURRENT_GOVERNANCE", "consumer current governance state"
    if any(part in {"__pycache__", ".pytest_cache", ".cache", "node_modules"} for part in pure.parts):
        return "CACHE", "cache path"
    if pure.suffix.lower() == ".log" or lower.startswith("raw_logs/"):
        return "LOG", "log output"
    if pure.suffix.lower() in {".tmp", ".temp"}:
        return "TEMP", "temporary output"
    if lower.startswith("raw_screenshots/") or ("screenshot" in lower and lower.startswith(("artifacts/", "runs/"))):
        return "SCREENSHOT_TEMP", "runtime screenshot"
    if lower.startswith(("artifacts/", "runs/", "provider_outputs/", "coverage/", "examples/runtime_runs/")):
        return "RUNTIME", "runtime artifact"
    if lower.startswith(("generated/", "workspaces/", "examples/generated_projects/")) or pure.suffix.lower() == ".zip":
        return "GENERATED", "generated project or package"
    if lower.startswith("tests/") or pure.name.startswith("test_"):
        return "TEST", "test source"
    if lower.startswith("contracts/"):
        return "CONTRACT", "formal contract"
    if lower.startswith("specs/") or lower.startswith("schemas/"):
        return "SCHEMA", "formal schema/specification"
    if lower.startswith("governance/migrations/"):
        return "MIGRATION", "bounded migration record requires review"
    if lower.startswith("drizzle/") and pure.suffix.lower() == ".sql":
        return "MIGRATION", "database migration requires explicit review"
    if lower.startswith("governance/") or lower.startswith("project_management/current/"):
        return "CURRENT_GOVERNANCE", "current governance state"
    if lower.startswith("evidence/"):
        return "DURABLE_EVIDENCE", "bounded durable evidence requires review"
    if lower.startswith("docs/") or lower in {"readme.md", "agents.md", "version", "edition.md", "product_goal.md"} or lower.startswith("project_management/summaries/"):
        return "CURRENT_DOC", "current documentation or version truth"
    if lower.startswith(("scripts/", "cgkn/", "plugins/", "tools/", "src/", ".github/workflows/")) or pure.suffix.lower() in {".py", ".ps1"}:
        return "SOURCE", "production or repository source"
    return "UNKNOWN", "no deterministic repository role"


def build_change_manifest(root: pathlib.Path, state: dict[str, Any] | None = None, *, reviewed_paths: Sequence[str] = ()) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    state = state or repository_state(root)
    reviewed = {path.replace("\\", "/") for path in reviewed_paths}
    files: list[dict[str, str]] = []
    for row in state.get("status_rows", []):
        path = row["path"]
        classification, reason = classify_path(path, root)
        if classification in COMMIT_CLASSES or classification in REVIEW_CLASSES and path in reviewed:
            action = "COMMIT"
        elif classification in REVIEW_CLASSES:
            action = "REVIEW"
        elif classification in EXCLUDE_CLASSES:
            action = "EXCLUDE"
        else:
            action = "BLOCK"
        files.append({**row, "classification": classification, "action": action, "reason": reason})
    document = {
        "kind": "CGKNChangeManifest", "schema_version": "1.0",
        "baseline_sha": state["local_head"], "branch": state["branch"],
        "source_identity_hash": state["source_identity_hash"], "files": files,
        "commit_files": sorted(row["path"] for row in files if row["action"] == "COMMIT"),
        "excluded_files": sorted(row["path"] for row in files if row["action"] == "EXCLUDE"),
        "review_required_files": sorted(row["path"] for row in files if row["action"] == "REVIEW"),
        "blocked_files": sorted(row["path"] for row in files if row["action"] == "BLOCK"),
    }
    document["change_manifest_hash"] = canonical_hash(document, ("change_manifest_hash",))
    return document


def run_tests_and_write_receipt(root: pathlib.Path, manifest: dict[str, Any], commands: Sequence[str], output: pathlib.Path) -> dict[str, Any]:
    identity = _read_source_identity(root)
    results: list[dict[str, Any]] = []
    for command in commands:
        started = time.monotonic()
        completed = subprocess.run(command, cwd=root, shell=True, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
        results.append({"command": command, "status": "PASS" if completed.returncode == 0 else "FAIL", "returncode": completed.returncode, "duration_seconds": round(time.monotonic() - started, 3), "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:]})
    document = {
        "kind": "CGKNTestReceipt", "schema_version": "1.0",
        "source_identity_hash": identity["source_identity_hash"],
        "changed_paths": list(manifest["commit_files"]), "tests": results,
        "scoped_verdict": "PASS" if commands and all(row["status"] == "PASS" for row in results) else "NEEDS_REWORK",
        "created_at": now(),
    }
    document["test_receipt_hash"] = canonical_hash(document, ("test_receipt_hash", "created_at"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def load_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublishBlocked("INVALID_SUPPORT_ARTIFACT", str(path))
    return value


def verify_test_binding(root: pathlib.Path, manifest: dict[str, Any], receipt: dict[str, Any]) -> None:
    identity = _read_source_identity(root)
    if receipt.get("scoped_verdict") != "PASS" or receipt.get("source_identity_hash") != identity.get("source_identity_hash"):
        raise PublishBlocked("TEST_EVIDENCE_STALE")
    if set(receipt.get("changed_paths", [])) != set(manifest.get("commit_files", [])):
        raise PublishBlocked("TEST_CHANGED_PATH_SET_MISMATCH")


def validate_staged_set(root: pathlib.Path, expected: Sequence[str], runner: GitRunner = run_git) -> str:
    actual = sorted(_lines(require_git(root, ["diff", "--cached", "--name-only"], runner)))
    if actual != sorted(expected):
        raise PublishBlocked("STAGING_SET_MISMATCH", {"expected": sorted(expected), "actual": actual})
    for path in actual:
        classification, _ = classify_path(path, root)
        if classification in EXCLUDE_CLASSES | {"SECRET", "UNKNOWN"}:
            raise PublishBlocked("STAGED_FILE_FORBIDDEN", {"path": path, "classification": classification})
        if (root / path).is_file() and (root / path).stat().st_size > 10_000_000:
            raise PublishBlocked("STAGED_FILE_TOO_LARGE", path)
    require_git(root, ["diff", "--cached", "--name-status"], runner)
    require_git(root, ["diff", "--cached", "--stat"], runner)
    numstat = _lines(require_git(root, ["diff", "--cached", "--numstat"], runner))
    binary_paths = [line.split("\t")[-1] for line in numstat if line.startswith("-\t-\t")]
    if binary_paths:
        raise PublishBlocked("STAGED_BINARY_FORBIDDEN", binary_paths)
    return require_git(root, ["write-tree"], runner)["stdout"].strip()


def reject_force_options(options: Sequence[str]) -> None:
    if FORBIDDEN_FORCE_OPTIONS.intersection(options):
        raise PublishBlocked("BLOCKED_FORCE_PUSH")


def run_version_gate(root: pathlib.Path, command: str | None = None) -> dict[str, Any]:
    invocation: str | list[str] = command if command else [sys.executable, "scripts/canonical_version_gate.py"]
    completed = subprocess.run(invocation, cwd=root, shell=bool(command), text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode != 0:
        raise PublishBlocked("VERSION_GATE_FAILED", completed.stdout[-2000:] + completed.stderr[-2000:])
    return {"status": "PASS", "command": command or "python scripts/canonical_version_gate.py"}


def verify_remote_sha(root: pathlib.Path, branch: str, commit_sha: str, runner: GitRunner = run_git) -> str:
    require_git(root, ["fetch", "origin", branch], runner)
    remote_sha = require_git(root, ["rev-parse", f"origin/{branch}"], runner)["stdout"].strip()
    if remote_sha != commit_sha:
        raise PublishBlocked("PUSH_UNVERIFIED", {"local": commit_sha, "remote": remote_sha})
    return remote_sha


def verify_remote_baseline(root: pathlib.Path, branch: str, expected_remote: str, runner: GitRunner = run_git) -> str:
    fetch = runner(root, ["fetch", "origin", branch])
    if not fetch.get("ok"):
        if expected_remote:
            raise PublishBlocked("BLOCKED_GIT_STATE", fetch)
        return ""
    current_remote = require_git(root, ["rev-parse", f"origin/{branch}"], runner)["stdout"].strip()
    if expected_remote and current_remote != expected_remote:
        raise PublishBlocked("REMOTE_HEAD_CHANGED", {"expected": expected_remote, "actual": current_remote})
    return current_remote


def normal_push_with_retry(
    root: pathlib.Path, branch: str, expected_remote: str, push_args: Sequence[str],
    runner: GitRunner = run_git, attempts: int = 3,
) -> None:
    reject_force_options(push_args)
    failures: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        verify_remote_baseline(root, branch, expected_remote, runner)
        result = runner(root, push_args)
        if result.get("ok"):
            return
        failures.append({**result, "attempt": attempt})
        diagnostic = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".lower()
        if not any(marker in diagnostic for marker in TRANSIENT_PUSH_ERRORS):
            raise PublishBlocked("BLOCKED_GIT_STATE", result)
    raise PublishBlocked("BLOCKED_GIT_STATE", {"reason": "TRANSIENT_PUSH_RETRIES_EXHAUSTED", "failures": failures})


def publish(
    root: pathlib.Path, *, message: str, test_receipt_path: pathlib.Path,
    reviewed_paths: Sequence[str] = (), post_commit_commands: Sequence[str] = (),
    push_options: Sequence[str] = (), runner: GitRunner = run_git,
    target_branch: str | None = None, version_gate_command: str | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    reject_force_options(push_options)
    if not CONVENTIONAL_MESSAGE.match(message) or message.split(":", 1)[-1].strip().lower() in {"update", "changes", "misc", "stuff"}:
        raise PublishBlocked("COMMIT_MESSAGE_INVALID")
    initial = repository_state(root, runner)
    if initial["behind"] or initial["diverged"]:
        raise PublishBlocked("REMOTE_BASELINE_CHANGED", initial)
    if initial["staged"]:
        raise PublishBlocked("BLOCKED_PREEXISTING_STAGED_CHANGES", initial["staged"])
    manifest = build_change_manifest(root, initial, reviewed_paths=reviewed_paths)
    secret_paths = [row["path"] for row in manifest["files"] if row["classification"] == "SECRET"]
    if secret_paths:
        raise PublishBlocked("BLOCKED_SECRET_FILE", secret_paths)
    if manifest["blocked_files"] or manifest["review_required_files"] or not manifest["commit_files"]:
        classification = "REVIEW_REQUIRED" if manifest["blocked_files"] or manifest["review_required_files"] else "CHANGE_MANIFEST_BLOCKED"
        raise PublishBlocked(classification, {"blocked": manifest["blocked_files"], "review": manifest["review_required_files"]})
    receipt = load_json(test_receipt_path)
    verify_test_binding(root, manifest, receipt)
    version_gate = run_version_gate(root, version_gate_command) if version_gate_command else run_version_gate(root)
    require_git(root, ["add", "--", *manifest["commit_files"]], runner)
    staged_tree_hash = validate_staged_set(root, manifest["commit_files"], runner)
    require_git(root, ["commit", "-m", message], runner)
    commit_sha = require_git(root, ["rev-parse", "HEAD"], runner)["stdout"].strip()
    committed_tree = require_git(root, ["rev-parse", "HEAD^{tree}"], runner)["stdout"].strip()
    if committed_tree != staged_tree_hash:
        raise PublishBlocked("COMMITTED_TREE_MISMATCH")
    post_status = _lines(require_git(root, ["status", "--porcelain=v1", "--untracked-files=all"], runner))
    if post_status:
        raise PublishBlocked("POST_COMMIT_DIRTY", post_status)
    critical: list[dict[str, Any]] = []
    for command in post_commit_commands:
        completed = subprocess.run(command, cwd=root, shell=True, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
        critical.append({"command": command, "status": "PASS" if completed.returncode == 0 else "FAIL", "returncode": completed.returncode})
        if completed.returncode != 0:
            raise PublishBlocked("POST_COMMIT_VERIFICATION_FAILED", critical[-1])
    post_test_status = _lines(require_git(root, ["status", "--porcelain=v1", "--untracked-files=all"], runner))
    if post_test_status:
        raise PublishBlocked("POST_COMMIT_DIRTY", post_test_status)
    branch = target_branch or initial["branch"]
    if not branch:
        raise PublishBlocked("TARGET_BRANCH_REQUIRED")
    if target_branch:
        require_git(root, ["fetch", "origin", branch], runner)
        expected_remote = require_git(root, ["rev-parse", f"origin/{branch}"], runner)["stdout"].strip()
        if expected_remote != initial["local_head"]:
            raise PublishBlocked("REMOTE_BASELINE_CHANGED", {"local": initial["local_head"], "remote": expected_remote})
    else:
        expected_remote = initial["remote_head"]
    push_args = ["push", *push_options]
    if target_branch:
        push_args.extend(["origin", f"HEAD:refs/heads/{branch}"])
    elif initial["tracking_ref"]:
        push_args.extend(["origin", branch])
    else:
        push_args.extend(["-u", "origin", branch])
    normal_push_with_retry(root, branch, expected_remote, push_args, runner)
    remote_sha = verify_remote_sha(root, branch, commit_sha, runner)
    document = {
        "kind": "CGKNRepositoryPublishReceipt", "schema_version": "1.0",
        "authority": "repository_publish_support_only", "formal_evidence_status": "NOT_EVALUATED",
        "baseline_sha": initial["local_head"], "source_identity_hash": manifest["source_identity_hash"],
        "change_manifest_hash": manifest["change_manifest_hash"], "test_receipt_hash": receipt["test_receipt_hash"],
        "staged_tree_hash": staged_tree_hash, "commit_sha": commit_sha,
        "post_commit_verification": "PASS", "critical_tests": critical,
        "remote_before_sha": expected_remote, "remote_after_sha": remote_sha,
        "push_verified": remote_sha == commit_sha, "force_push": False,
        "version_gate_status": version_gate["status"], "pr": "NOT_REQUESTED", "ci": "NOT_AVAILABLE",
        "created_at": now(),
    }
    document["publish_receipt_hash"] = canonical_hash(document, ("publish_receipt_hash", "created_at"))
    output = root / PUBLISH_DIR / "publish_receipt.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def _write_runtime(root: pathlib.Path, name: str, document: dict[str, Any]) -> pathlib.Path:
    path = root / PUBLISH_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Canonical fail-closed CGKN repository publish gate.")
    parser.add_argument("--repository-root", default=str(ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect")
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--test-command", action="append", default=[])
    prepare_parser.add_argument("--review-path", action="append", default=[])
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--test-receipt", default=str(PUBLISH_DIR / "test_receipt.json"))
    verify_parser.add_argument("--review-path", action="append", default=[])
    verify_parser.add_argument("--version-gate-command")
    publish_parser = sub.add_parser("publish")
    publish_parser.add_argument("--message", required=True)
    publish_parser.add_argument("--test-receipt", default=str(PUBLISH_DIR / "test_receipt.json"))
    publish_parser.add_argument("--review-path", action="append", default=[])
    publish_parser.add_argument("--post-commit-command", action="append", default=[])
    publish_parser.add_argument("--target-branch")
    publish_parser.add_argument("--version-gate-command")
    args = parser.parse_args()
    repository_root = pathlib.Path(args.repository_root).resolve()
    try:
        state = repository_state(repository_root)
        manifest = build_change_manifest(repository_root, state, reviewed_paths=getattr(args, "review_path", []))
        if args.command == "inspect":
            result: dict[str, Any] = {"status": "PASS", "repository_state": state, "change_manifest": manifest}
        elif args.command == "prepare":
            manifest_path = _write_runtime(repository_root, "change_manifest.json", manifest)
            receipt = run_tests_and_write_receipt(repository_root, manifest, args.test_command, repository_root / PUBLISH_DIR / "test_receipt.json")
            result = {"status": receipt["scoped_verdict"], "manifest": str(manifest_path), "test_receipt": receipt}
        elif args.command == "verify":
            if manifest["blocked_files"] or manifest["review_required_files"]:
                raise PublishBlocked("CHANGE_MANIFEST_BLOCKED")
            receipt = load_json(repository_root / args.test_receipt)
            verify_test_binding(repository_root, manifest, receipt)
            run_version_gate(repository_root, args.version_gate_command) if args.version_gate_command else run_version_gate(repository_root)
            result = {"status": "PASS", "change_manifest_hash": manifest["change_manifest_hash"], "test_receipt_hash": receipt["test_receipt_hash"]}
        else:
            result = publish(repository_root, message=args.message, test_receipt_path=repository_root / args.test_receipt, reviewed_paths=args.review_path, post_commit_commands=args.post_commit_command, target_branch=args.target_branch, version_gate_command=args.version_gate_command)
            result = {"status": "PASS", "publish_receipt": result}
    except PublishBlocked as exc:
        result = {"status": "BLOCKED", "classification": exc.classification, "detail": exc.detail}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
