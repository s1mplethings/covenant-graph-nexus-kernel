from __future__ import annotations

import difflib
import hashlib
import json
import pathlib
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

try:
    import product_candidate_manager
except Exception:  # pragma: no cover
    from scripts import product_candidate_manager  # type: ignore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inside(base: pathlib.Path, target: pathlib.Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _read_text(path: pathlib.Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)


def _file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _artifact_path(root: pathlib.Path, raw: str) -> pathlib.Path:
    path = pathlib.Path(str(raw))
    return path if path.is_absolute() else root / path


def validate_nearest_test_result(test_result: dict[str, Any], *, artifact_root: str | pathlib.Path) -> dict[str, Any]:
    command = str(test_result.get("command") or "").strip()
    status = str(test_result.get("status") or "NOT_EVALUATED").strip()
    exit_code = test_result.get("exit_code", test_result.get("returncode"))
    artifact_refs = [str(item) for item in test_result.get("artifact_refs", []) if str(item).strip()] if isinstance(test_result.get("artifact_refs"), list) else []
    hashes = test_result.get("hashes") if isinstance(test_result.get("hashes"), dict) else {}
    if not command:
        return {"status": "REJECTED_NO_TEST", "reason": "nearest_test.command is empty"}
    if status != "PASS":
        return {"status": "REJECTED_TEST_FAILED", "reason": f"nearest_test.status is {status}"}
    try:
        code = int(exit_code)
    except (TypeError, ValueError):
        return {"status": "REJECTED_TEST_FAILED", "reason": "nearest_test.exit_code missing"}
    if code != 0:
        return {"status": "REJECTED_TEST_FAILED", "reason": f"nearest_test.exit_code is {code}"}
    provenance = str(test_result.get("provenance_status") or "observed")
    if provenance not in {"observed", "verified"}:
        return {"status": "REJECTED_EVIDENCE", "reason": f"nearest_test provenance is {provenance}"}
    if not artifact_refs:
        return {"status": "REJECTED_EVIDENCE", "reason": "nearest_test artifact_refs missing"}
    root = pathlib.Path(artifact_root).resolve()
    missing: list[str] = []
    mismatch: list[str] = []
    for ref in artifact_refs:
        path = _artifact_path(root, ref)
        if not path.exists() or not path.is_file():
            missing.append(ref)
            continue
        expected = str(hashes.get(ref) or hashes.get(path.name) or hashes.get("sha256") or "")
        if expected and _file_hash(path) != expected:
            mismatch.append(ref)
    if missing:
        return {"status": "REJECTED_EVIDENCE", "reason": "nearest_test artifact missing", "missing": missing}
    if mismatch:
        return {"status": "REJECTED_EVIDENCE", "reason": "nearest_test artifact hash mismatch", "hash_mismatch": mismatch}
    return {"status": "MERGED", "reason": "nearest_test evidence accepted"}


def changed_files_between(base_dir: str | pathlib.Path, workspace_dir: str | pathlib.Path) -> list[str]:
    base = pathlib.Path(base_dir).resolve()
    workspace = pathlib.Path(workspace_dir).resolve()
    files: set[str] = set()
    for root in (base, workspace):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(".git/") or rel.startswith(".cgkn_execution/") or "__pycache__/" in rel:
                continue
            files.add(rel)
    changed: list[str] = []
    for rel in sorted(files):
        b = base / rel
        w = workspace / rel
        if b.exists() != w.exists():
            changed.append(rel)
        elif b.exists() and w.exists() and _file_hash(b) != _file_hash(w):
            changed.append(rel)
    return changed


def make_patch(base_dir: str | pathlib.Path, workspace_dir: str | pathlib.Path, changed_files: list[str]) -> str:
    base = pathlib.Path(base_dir).resolve()
    workspace = pathlib.Path(workspace_dir).resolve()
    chunks: list[str] = []
    for rel in changed_files:
        old = _read_text(base / rel)
        new = _read_text(workspace / rel)
        chunks.extend(
            difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                lineterm="",
            )
        )
        if chunks and not chunks[-1].endswith("\n"):
            chunks[-1] += "\n"
    return "".join(line if line.endswith("\n") else line + "\n" for line in chunks)


def command_relevant_to_changed_files(command: str, changed_files: list[str]) -> bool:
    lowered = str(command or "").replace("\\", "/").lower()
    if not lowered.strip() or not changed_files:
        return False
    if "pytest" in lowered or "unittest" in lowered or "playwright" in lowered:
        return True
    explicit_paths = [token.strip("'\"") for token in lowered.split() if any(token.strip("'\"").endswith(ext) for ext in (".py", ".js", ".ts", ".html", ".css", ".json", ".md"))]
    if not explicit_paths:
        return True
    changed = [path.replace("\\", "/").lower() for path in changed_files]
    for token in explicit_paths:
        token_name = pathlib.PurePosixPath(token).name
        for rel in changed:
            if token == rel or token_name == pathlib.PurePosixPath(rel).name or token.startswith(rel):
                return True
    return False


class PatchMergeManager:
    def __init__(self, events_path: str | pathlib.Path) -> None:
        self.events_path = pathlib.Path(events_path)

    def build_leaf_result(
        self,
        *,
        base_candidate_dir: str | pathlib.Path,
        leaf_workspace_dir: str | pathlib.Path,
        leaf_dir: str | pathlib.Path,
        allowed_files: list[str],
        interface_impact: dict[str, Any] | None = None,
        nearest_test_result: dict[str, Any] | None = None,
        peer_dependencies: list[str] | None = None,
        unresolved_findings: list[str] | None = None,
    ) -> dict[str, Any]:
        base = pathlib.Path(base_candidate_dir).resolve()
        workspace = pathlib.Path(leaf_workspace_dir).resolve()
        leaf = pathlib.Path(leaf_dir).resolve()
        changed = changed_files_between(base, workspace)
        allowed = set(path.replace("\\", "/") for path in allowed_files)
        disallowed = [path for path in changed if path not in allowed]
        patch_text = make_patch(base, workspace, changed)
        patch_path = leaf / "patch.diff"
        patch_path.write_text(patch_text, encoding="utf-8")
        patch_hash = hashlib.sha256(patch_text.encode("utf-8")).hexdigest()
        test_gate = validate_nearest_test_result(nearest_test_result or {"status": "NOT_EVALUATED"}, artifact_root=leaf)
        result = {
            "base_candidate_hash": product_candidate_manager.tree_hash(base),
            "patch_diff": str(patch_path),
            "patch_hash": patch_hash,
            "changed_files": changed,
            "allowed_files_check": {"status": "PASS" if not disallowed else "NEEDS_REWORK", "disallowed": disallowed},
            "interface_impact": interface_impact or {},
            "nearest_test_result": nearest_test_result or {"status": "NOT_EVALUATED"},
            "nearest_test_gate": test_gate,
            "unresolved_findings": list(unresolved_findings or []),
            "peer_dependencies": list(peer_dependencies or []),
            "result_classification": "PASS" if changed and not disallowed and not unresolved_findings and test_gate["status"] == "MERGED" else "NEEDS_REWORK",
            "created_at": utc_now(),
        }
        (leaf / "result_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    def merge_leaf_result(
        self,
        *,
        candidate_dir: str | pathlib.Path,
        leaf_workspace_dir: str | pathlib.Path,
        result_manifest: dict[str, Any],
        nearest_test_command: str = "",
    ) -> dict[str, Any]:
        candidate = pathlib.Path(candidate_dir).resolve()
        workspace = pathlib.Path(leaf_workspace_dir).resolve()
        current_hash = product_candidate_manager.tree_hash(candidate)
        changed_files = [str(item) for item in result_manifest.get("changed_files", []) if str(item).strip()]
        if not changed_files:
            event = self._event("merge_rejected", candidate, result_manifest, reason="patch_has_no_changes", merge_status="REJECTED_CONFLICT")
            return {"status": "NEEDS_REWORK", "merge_status": "REJECTED_CONFLICT", "reason": "patch_has_no_changes", "event": event}
        if current_hash != result_manifest.get("base_candidate_hash"):
            event = self._event("merge_rejected", candidate, result_manifest, reason="base_candidate_hash_changed", merge_status="REJECTED_STALE_BASE")
            return {"status": "NEEDS_REWORK", "merge_status": "REJECTED_STALE_BASE", "reason": "base_candidate_hash_changed", "event": event}
        if result_manifest.get("allowed_files_check", {}).get("status") != "PASS":
            event = self._event("merge_rejected", candidate, result_manifest, reason="allowed_files_violation", merge_status="REJECTED_SCOPE")
            return {"status": "NEEDS_REWORK", "merge_status": "REJECTED_SCOPE", "reason": "allowed_files_violation", "event": event}
        test_gate = validate_nearest_test_result(
            result_manifest.get("nearest_test_result", {}) if isinstance(result_manifest.get("nearest_test_result"), dict) else {},
            artifact_root=pathlib.Path(str(result_manifest.get("patch_diff", ""))).parent if result_manifest.get("patch_diff") else workspace,
        )
        if test_gate["status"] != "MERGED":
            merge_status = str(test_gate["status"])
            event = self._event("merge_rejected", candidate, result_manifest, reason=test_gate.get("reason", "nearest_test_rejected"), merge_status=merge_status, test_gate=test_gate)
            return {"status": "NEEDS_REWORK", "merge_status": merge_status, "reason": test_gate.get("reason", "nearest_test_rejected"), "event": event, "test_gate": test_gate}
        merge_tmp = candidate.parent / f".merge_candidate_{hashlib.sha256(current_hash.encode()).hexdigest()[:8]}"
        if merge_tmp.exists():
            shutil.rmtree(merge_tmp)
        shutil.copytree(candidate, merge_tmp, dirs_exist_ok=True)
        for rel in result_manifest.get("changed_files", []):
            src = (workspace / rel).resolve()
            dst = (merge_tmp / rel).resolve()
            if not _inside(workspace, src) or not _inside(merge_tmp, dst):
                shutil.rmtree(merge_tmp, ignore_errors=True)
                event = self._event("merge_rejected", candidate, result_manifest, reason="path_escape")
                return {"status": "NEEDS_REWORK", "reason": "path_escape", "event": event}
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            elif dst.exists():
                dst.unlink()
        command = str(nearest_test_command or result_manifest.get("nearest_test_result", {}).get("command") or "").strip()
        if not command:
            shutil.rmtree(merge_tmp, ignore_errors=True)
            event = self._event("merge_rejected", candidate, result_manifest, reason="nearest_test.command is empty", merge_status="REJECTED_NO_TEST")
            return {"status": "NEEDS_REWORK", "merge_status": "REJECTED_NO_TEST", "reason": "nearest_test.command is empty", "event": event}
        if not command_relevant_to_changed_files(command, changed_files):
            shutil.rmtree(merge_tmp, ignore_errors=True)
            event = self._event("merge_rejected", candidate, result_manifest, reason="nearest_test.command unrelated to changed files", merge_status="REJECTED_UNRELATED_TEST")
            return {"status": "NEEDS_REWORK", "merge_status": "REJECTED_UNRELATED_TEST", "reason": "nearest_test.command unrelated to changed files", "event": event}
        proc = subprocess.run(command, cwd=str(merge_tmp), shell=True, text=True, capture_output=True, timeout=120)
        test_result = {
            "status": "PASS" if proc.returncode == 0 else "NEEDS_REWORK",
            "command": command,
            "returncode": proc.returncode,
            "exit_code": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
        if test_result["status"] != "PASS":
            shutil.rmtree(merge_tmp, ignore_errors=True)
            event = self._event("merge_rejected", candidate, result_manifest, reason="nearest_test_failed", merge_status="REJECTED_TEST_FAILED", test_result=test_result)
            return {"status": "NEEDS_REWORK", "merge_status": "REJECTED_TEST_FAILED", "reason": "nearest_test_failed", "test_result": test_result, "event": event}
        for rel in result_manifest.get("changed_files", []):
            src = merge_tmp / rel
            dst = candidate / rel
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            elif dst.exists():
                dst.unlink()
        shutil.rmtree(merge_tmp, ignore_errors=True)
        event = self._event("merge_accepted", candidate, result_manifest, reason="merged", merge_status="MERGED", test_result=test_result)
        return {"status": "PASS", "merge_status": "MERGED", "test_result": test_result, "event": event, "new_candidate_hash": product_candidate_manager.tree_hash(candidate)}

    def _event(self, kind: str, candidate: pathlib.Path, result_manifest: dict[str, Any], **extra: Any) -> dict[str, Any]:
        event = {
            "kind": kind,
            "created_at": utc_now(),
            "candidate_dir": str(candidate),
            "candidate_hash": product_candidate_manager.tree_hash(candidate),
            "patch_hash": result_manifest.get("patch_hash", ""),
            "changed_files": result_manifest.get("changed_files", []),
            **extra,
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event
