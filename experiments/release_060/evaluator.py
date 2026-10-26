"""Deterministic public/private evaluator for generated ITER-060 projects."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import json
import os
import pathlib
import py_compile
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

from .contracts import ProjectFamilySpec, canonical_hash


FORBIDDEN_IMPORT_ROOTS = {"ftplib", "http", "requests", "socket", "subprocess", "urllib"}


@dataclass(frozen=True)
class EvaluationResult:
    status: str
    phase: str
    passed_checks: int
    total_checks: int
    duration_ms: int
    failure_class: str = ""
    public_failure: Mapping[str, Any] | None = None
    private_failure_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_sources(workspace: pathlib.Path) -> tuple[pathlib.Path, ...]:
    return tuple(sorted(path for path in workspace.rglob("*.py") if path.is_file() and not path.is_symlink()))


def _static_gate(workspace: pathlib.Path) -> str:
    for path in _safe_sources(workspace):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            py_compile.compile(str(path), doraise=True)
        except (SyntaxError, UnicodeDecodeError, py_compile.PyCompileError) as exc:
            return f"syntax:{path.relative_to(workspace).as_posix()}:{type(exc).__name__}"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {name.name.split(".", 1)[0] for name in node.names}
                if roots & FORBIDDEN_IMPORT_ROOTS:
                    return f"forbidden_import:{path.relative_to(workspace).as_posix()}"
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
                return f"forbidden_import:{path.relative_to(workspace).as_posix()}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and (node.func.value.id, node.func.attr) in {("os", "system"), ("os", "popen")}:
                    return f"forbidden_shell:{path.relative_to(workspace).as_posix()}"
    return ""


def _run_case(workspace: pathlib.Path, package: str, case: Mapping[str, Any], case_root: pathlib.Path) -> tuple[bool, dict[str, Any]]:
    shutil.copytree(workspace, case_root, dirs_exist_ok=False)
    for relative, content in dict(case.get("files") or {}).items():
        destination = case_root / str(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(str(content), encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(case_root),
        "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
        "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "",
    }
    for step_index, step in enumerate(case.get("steps") or (), start=1):
        command = [sys.executable, "-m", package, *map(str, step.get("argv") or ())]
        try:
            completed = subprocess.run(command, cwd=case_root, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=12)
        except subprocess.TimeoutExpired:
            return False, {"failure_class": "TIMEOUT", "step": step_index}
        expected_code = int(step.get("code", 0))
        if completed.returncode != expected_code:
            return False, {"failure_class": "EXIT_CODE", "step": step_index, "expected": expected_code, "observed": completed.returncode, "stderr": completed.stderr[-1200:]}
        file_json = step.get("file_json")
        if file_json:
            output = case_root / str(file_json["path"])
            if not output.is_file():
                return False, {"failure_class": "MISSING_OUTPUT", "step": step_index, "path": str(file_json["path"])}
            try:
                observed = json.loads(output.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return False, {"failure_class": "INVALID_OUTPUT", "step": step_index, "error": type(exc).__name__}
            if observed != file_json["value"]:
                return False, {"failure_class": "WRONG_OUTPUT", "step": step_index, "expected": file_json["value"], "observed": observed}
    return True, {}


def _invalid_input_gate(workspace: pathlib.Path, package: str, operation: str, case_root: pathlib.Path) -> tuple[bool, dict[str, Any]]:
    shutil.copytree(workspace, case_root, dirs_exist_ok=False)
    (case_root / "invalid.json").write_text("{not-json", encoding="utf-8")
    (case_root / "protected.json").write_text('"sentinel"', encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(case_root), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": ""}
    try:
        completed = subprocess.run(
            [sys.executable, "-m", package, operation, "invalid.json", "protected.json"],
            cwd=case_root, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=12,
        )
    except subprocess.TimeoutExpired:
        return False, {"failure_class": "INVALID_INPUT_TIMEOUT"}
    if completed.returncode != 2:
        return False, {"failure_class": "INVALID_INPUT_EXIT", "expected": 2, "observed": completed.returncode}
    if (case_root / "protected.json").read_text(encoding="utf-8") != '"sentinel"':
        return False, {"failure_class": "INVALID_INPUT_OVERWRITE"}
    return True, {}


def evaluate_family(
    workspace: pathlib.Path,
    family: ProjectFamilySpec,
    *,
    private: bool,
    evaluation_root: pathlib.Path | None = None,
    through_episode: int | None = None,
) -> EvaluationResult:
    started = time.perf_counter()
    episodes = family.episodes[:through_episode] if through_episode is not None else family.episodes
    if not episodes:
        raise ValueError("at least one episode must be evaluated")
    expected = {path for episode in episodes for path in episode.required_paths}
    missing = sorted(path for path in expected if not (workspace / path).is_file())
    checks = 1 + sum(len(episode.private_cases if private else episode.public_cases) + 1 for episode in episodes)
    if missing:
        detail = {"failure_class": "MISSING_FILES", "paths": missing}
        return _failure("PRIVATE" if private else "PUBLIC", 0, checks, started, detail, private)
    static_failure = _static_gate(workspace)
    if static_failure:
        return _failure("PRIVATE" if private else "PUBLIC", 0, checks, started, {"failure_class": "STATIC_GATE", "detail": static_failure}, private)
    passed = 1
    parent = evaluation_root or pathlib.Path(tempfile.mkdtemp(prefix="cgnk-060-eval-"))
    owned_parent = evaluation_root is None
    parent.mkdir(parents=True, exist_ok=True)
    try:
        ordinal = 0
        for episode in episodes:
            cases: Sequence[Mapping[str, Any]] = episode.private_cases if private else episode.public_cases
            for case in cases:
                ordinal += 1
                ok, detail = _run_case(workspace, family.package_name, case, parent / f"case-{ordinal:03d}")
                if not ok:
                    return _failure("PRIVATE" if private else "PUBLIC", passed, checks, started, detail | {"episode_id": episode.episode_id}, private)
                passed += 1
            operation = str(episode.public_cases[0]["steps"][0]["argv"][0])
            ordinal += 1
            ok, detail = _invalid_input_gate(workspace, family.package_name, operation, parent / f"invalid-{ordinal:03d}")
            if not ok:
                return _failure("PRIVATE" if private else "PUBLIC", passed, checks, started, detail | {"episode_id": episode.episode_id}, private)
            passed += 1
    finally:
        if owned_parent:
            shutil.rmtree(parent, ignore_errors=True)
    return EvaluationResult("PASS", "PRIVATE" if private else "PUBLIC", passed, checks, int((time.perf_counter() - started) * 1000))


def _failure(phase: str, passed: int, total: int, started: float, detail: Mapping[str, Any], private: bool) -> EvaluationResult:
    failure_hash = canonical_hash(detail)
    return EvaluationResult(
        "FAIL", phase, passed, total, int((time.perf_counter() - started) * 1000),
        failure_class=str(detail.get("failure_class") or "EVALUATION_FAILURE"),
        public_failure=None if private else dict(detail),
        private_failure_hash=failure_hash if private else "",
    )
