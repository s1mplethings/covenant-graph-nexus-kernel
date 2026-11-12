"""ACFV release-candidate capability catalog and Host wiring (P1).

This module is Host integration, not ACFV business logic. It exposes the existing
ACFV CLI/tests and deterministic acceptance checks as Host capabilities. The
Planner still chooses the tree; execution, state, recovery and acceptance remain
``DAGRunner`` / ``FileRunStore`` / ``GoalAcceptance``.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from cgkn.agent.catalog_composer import CatalogAgentComposer
from cgkn.agent.project_loop import ProjectSession
from cgkn.application.promotion.video_contracts import PreflightRejected, PreflightedDAGRunner
from cgkn.execution import (BlockExecutionRequest, BlockExecutionResult, BlockStatus,
                            ExecutionError, ExecutionErrorCode)
from cgkn.execution.contracts import utc_now
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.executors import ExecutorRegistry, LLMExecutor
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.providers import CGKNModelRouting, CompletionClient, ModelRoleConfig
from cgkn.state import FileRunStore
from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
from cgkn.state.acceptance import identity

RELEASE_CONDITION = (
    "The ACFV release candidate passes independent deterministic checks: the package "
    "imports from documented sources; release source contains no private absolute "
    "machine paths; the existing clip pipeline runs on the formal real input and "
    "produces at least one real clip plus an export manifest; every delivered clip "
    "decodes, has audio, has a sane duration and is traceable to the frozen source "
    "hash. Perceptual quality remains pending human review."
)
PERCEPTUAL_OBLIGATIONS = (
    "acfv.clip_content_quality",
    "acfv.clip_cut_quality",
    "acfv.subtitle_quality_if_present",
    "acfv.user_perceived_usability",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _result(request: BlockExecutionRequest, outputs: Mapping[str, Any], *,
            status: BlockStatus = BlockStatus.SUCCEEDED,
            error: ExecutionError | None = None, started: str = "",
            clock: float | None = None) -> BlockExecutionResult:
    return BlockExecutionResult(
        project_id=request.project_id, run_id=request.run_id,
        attempt_id=request.attempt_id, node_id=request.node_id,
        executor_ref=request.executor_ref, status=status, outputs=dict(outputs),
        error=error, started_at=started or utc_now(), ended_at=utc_now(),
        duration_ms=max(0, int((time.perf_counter() - (clock or time.perf_counter())) * 1000)),
    )


class _BoundedExecutor:
    def __init__(self, capability: str, function, *, executor_ref: str | None = None,
                 timeout: float = 900.0, kind: str = "acfv_release"):
        self.capability = capability
        self.function = function
        ref = executor_ref or capability
        self.descriptor = ExecutorDescriptor(
            ref, kind, (capability,), ("filesystem.read", "filesystem.write", "process.execute"),
            default_timeout_seconds=timeout,
        )

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        return self.function(request)


def _contract(node_id: str, goal: str, kind: str, scope: list[str], acceptance: list[str],
              checker: str, executor: str, dependencies: list[str], **details) -> dict:
    return build_leaf_contract(
        goal=goal, kind=kind, scope=scope, acceptance=acceptance, checker=checker,
        output_identity=node_id, effect_domains=["filesystem"], executor=executor,
        dependencies=dependencies, **details,
    )


def _entry(executor_ref: str, contract: dict, workdir: Path, **extra: Any) -> dict:
    return {"executor_ref": executor_ref,
            "config": {"executor_ref": executor_ref, "workdir": str(workdir),
                       "leaf_contract": contract, **extra}}


def prepare_workspace(workdir: Path, harness_dir: Path) -> dict[str, Any]:
    workdir = Path(workdir)
    harness_dir = Path(harness_dir)
    (workdir / "docs" / "p1").mkdir(parents=True, exist_ok=True)
    (workdir / "evidence" / "p1").mkdir(parents=True, exist_ok=True)
    (workdir / "runs" / "p1-release").mkdir(parents=True, exist_ok=True)
    copied = {}
    for name, target in (("P1_GOAL.md", workdir / "docs" / "p1" / "P1_GOAL.md"),
                         ("ACFV_CAPABILITY_BASELINE.json",
                          workdir / "docs" / "p1" / "ACFV_CAPABILITY_BASELINE.json")):
        source = harness_dir / name
        if not source.is_file():
            raise FileNotFoundError(str(source))
        target.write_bytes(source.read_bytes())
        copied[str(target.relative_to(workdir)).replace("\\", "/")] = _sha(target)
    return copied


PATH_TARGETS = ("src/acfv/cli/creator_profile.py",
                "src/acfv/processing/selected_video.txt")
PATH_OLD_BLOCK = '''    project = Path.cwd().resolve()
    # User-authorized bounded root for this recovered model. Never expand this
    # command into a drive/home scan.
    roots = [Path("G:/Cliper")]
    report = discover_avatar_models(project, search_roots=roots, label_mapping=label_mapping)
'''
PATH_NEW_BLOCK = '''    project = Path.cwd().resolve()
    # The model search root is operator-supplied. No private machine path is
    # baked into the release source.
    configured_root = os.environ.get("ACFV_AVATAR_SEARCH_ROOT", "").strip()
    roots = [Path(configured_root).expanduser()] if configured_root else []
    report = discover_avatar_models(project, search_roots=roots, label_mapping=label_mapping)
'''


def deterministic_paths_contract(dependencies: list[str]) -> dict:
    return build_leaf_contract(
        goal="remove private absolute machine path dependence from the two known release files",
        kind="REPAIR", scope=list(PATH_TARGETS), acceptance=["acfv.private_paths"],
        checker="acfv.check.paths@1", output_identity="acfv.release.paths",
        effect_domains=["filesystem"], executor="acfv.paths.normalize@1",
        dependencies=list(dependencies),
        expected_delta="no drive-letter absolute path remains in the release source")


def exec_paths_normalize(request: BlockExecutionRequest) -> BlockExecutionResult:
    """Deterministic path repair. No provider call; full before/after evidence."""
    import difflib
    import re
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    workdir = Path(cfg["workdir"])
    before = {name: _sha(workdir / name) if (workdir / name).is_file() else None
              for name in PATH_TARGETS}
    try:
        source_path = workdir / PATH_TARGETS[0]
        text = source_path.read_text(encoding="utf-8")
        if PATH_OLD_BLOCK not in text:
            return _result(request, {"before": before}, status=BlockStatus.FAILED,
                           error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,
                                                "deterministic path block not found; refusing a blind replacement"),
                           started=started, clock=clock)
        updated = text.replace(PATH_OLD_BLOCK, PATH_NEW_BLOCK, 1)
        if "import os" not in updated.split("from pathlib import Path", 1)[0]:
            updated = updated.replace("import json\n", "import json\nimport os\n", 1)
        source_path.write_text(updated, encoding="utf-8")
        state_path = workdir / PATH_TARGETS[1]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("", encoding="utf-8")
        after = {name: _sha(workdir / name) for name in PATH_TARGETS}
        pattern = re.compile(r"""(?<![A-Za-z0-9_])[A-Za-z]:[\\/](?![ntr'"\\/])""")
        remaining = []
        for name in PATH_TARGETS:
            for lineno, line in enumerate((workdir / name).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if pattern.search(line):
                    remaining.append({"file": name, "line": lineno, "text": line.strip()[:160]})
        env = {**os.environ, "PYTHONPATH": str(workdir / "src")}
        import_check = subprocess.run([sys.executable, "-c", "import acfv; print('ACFV_IMPORT_OK')"],
                                      cwd=workdir, env=env, capture_output=True, text=True,
                                      timeout=180, check=False)
        cli_check = subprocess.run([sys.executable, "-m", "acfv.cli", "--help"],
                                   cwd=workdir, env=env, capture_output=True, text=True,
                                   timeout=180, check=False)
        profile_check = subprocess.run([sys.executable, "-m", "acfv.cli", "creator-profile", "--help"],
                                       cwd=workdir, env=env, capture_output=True, text=True,
                                       timeout=180, check=False)
        diff = "".join(difflib.unified_diff(
            text.splitlines(keepends=True), updated.splitlines(keepends=True),
            fromfile=PATH_TARGETS[0], tofile=PATH_TARGETS[0]))
        report = {
            "kind": "P1DeterministicPathRepair",
            "before": before, "after": after,
            "diff": diff,
            "remaining_private_paths": remaining,
            "consumer_checks": {
                "import": import_check.returncode == 0 and "ACFV_IMPORT_OK" in import_check.stdout,
                "cli_help": cli_check.returncode == 0,
                "creator_profile_help": profile_check.returncode == 0,
            },
            "semantics": "creator-profile search root is now ACFV_AVATAR_SEARCH_ROOT (empty means project-only); selected_video.txt is runtime state and is emptied",
        }
        _write_json(workdir / "evidence" / "p1" / "paths_repair.json", report)
        passed = not remaining and all(report["consumer_checks"].values())
        if not passed:
            return _result(request, {"paths": report}, status=BlockStatus.FAILED,
                           error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,
                                                "deterministic path repair failed its consumer checks"),
                           started=started, clock=clock)
        return _result(request, {"paths": report}, started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _result(request, {"before": before}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)),
                       started=started, clock=clock)


def build_acfv_catalog(workdir: Path, *, input_path: Path, input_sha: str,
                       acceptance_script: Path, pipeline_config: Path,
                       harness_dir: Path) -> dict[str, Any]:
    workdir = Path(workdir)
    goal_path = workdir / "docs" / "p1" / "P1_GOAL.md"
    read_goal = {str(goal_path.relative_to(workdir)).replace("\\", "/"): _sha(goal_path)}
    catalog: dict[str, Any] = {}

    catalog["acfv.release.env@1"] = _entry(
        "acfv.release.env@1",
        _contract("acfv.release.env", "verify the documented import and CLI entry point",
                  "INSPECTION", ["evidence/p1/env.json"], ["acfv.env"],
                  "acfv.check.env@1", "acfv.release.env@1", [],
                  subject="docs/p1/P1_GOAL.md",
                  expected_observation="package imports and CLI lists commands",
                  pass_fail_rule="import exit 0 and CLI help exit 0"),
        workdir,
    )

    catalog["acfv.release.gap@1"] = _entry(
        "acfv.release.gap@1",
        _contract("acfv.release.gap",
                  "read the frozen capability baseline and current workspace to identify release gaps",
                  "READ_ONLY_ANALYSIS", ["evidence/p1/release_gap.json"], ["acfv.gaps"],
                  "acfv.check.gaps@1", "acfv.release.gap@1", [],
                  source_refs=["docs/p1/ACFV_CAPABILITY_BASELINE.json", "docs/p1/P1_GOAL.md"],
                  completion_criterion="a gap report with existing capabilities, findings and release blockers"),
        workdir,
    )

    catalog["acfv.release.paths@1"] = _entry(
        "llm.cheap@1",
        _contract("acfv.release.paths",
                  "remove private absolute machine path dependence from the two known release files",
                  "REPAIR",
                  ["src/acfv/cli/creator_profile.py", "src/acfv/processing/selected_video.txt"],
                  ["acfv.private_paths"], "acfv.check.paths@1", "llm.cheap@1", [],
                  expected_delta="no drive-letter absolute path remains in the release source",
                  read_subjects=read_goal, read_scope=sorted(read_goal)),
        workdir,
        action_version=2,
        repair_contract={"strategy_semantics": {"full_file_write": True}},
    )

    catalog["acfv.release.docs@1"] = _entry(
        "llm.cheap@1",
        _contract("acfv.release.docs",
                  "make the release documentation accurate for a first-time local user",
                  "IMPLEMENTATION", ["README.md", "docs/RELEASE_CANDIDATE.md"],
                  ["acfv.docs"], "acfv.check.docs@1", "llm.cheap@1", [],
                  expected_delta="README and a release-candidate guide cover install/start/input/output/limits",
                  read_subjects=read_goal, read_scope=sorted(read_goal)),
        workdir,
        action_version=2,
        repair_contract={"strategy_semantics": {"full_file_write": True}},
    )

    catalog["acfv.release.tests@1"] = _entry(
        "acfv.release.tests@1",
        _contract("acfv.release.tests", "run the existing test suite to catch regressions",
                  "TEST", ["evidence/p1/tests.json"], ["acfv.tests"],
                  "acfv.check.tests@1", "acfv.release.tests@1", [],
                  subject="src/acfv", expected_observation="pytest summary",
                  pass_fail_rule="pytest exit code 0 with collected tests > 0"),
        workdir,
    )

    catalog["acfv.release.e2e@1"] = _entry(
        "acfv.release.e2e@1",
        _contract("acfv.release.e2e",
                  "run the existing clip pipeline on the formal real input and export real clips",
                  "IMPLEMENTATION", ["evidence/p1/e2e_result.json"], ["acfv.e2e"],
                  "acfv.check.e2e@1", "acfv.release.e2e@1", [],
                  expected_delta="one real run directory with a clips manifest and rendered clips",
                  command=[sys.executable, "-m", "acfv.cli", "pipe", "clip",
                           "--url", str(input_path), "--out-dir", "runs/p1-release",
                           "--cfg", str(pipeline_config)],
                  environment={"PYTHONPATH": str(workdir / "src")},
                  out_root="runs/p1-release"),
        workdir,
        timeout_seconds=3000,
    )

    catalog["acfv.release.accept@1"] = _entry(
        "acfv.release.accept@1",
        _contract("acfv.release.accept",
                  "independently check the produced release artifacts and traceability",
                  "TEST", ["evidence/p1/independent_acceptance.json"], ["acfv.release_candidate"],
                  "acfv.check.release@1", "acfv.release.accept@1", [],
                  subject="runs/p1-release", expected_observation="independent acceptance report",
                  pass_fail_rule="all deterministic release checks PASS",
                  condition=RELEASE_CONDITION, goal_id="acfv.release_candidate"),
        workdir,
        acceptance_script=str(acceptance_script),
        input_path=str(input_path),
        input_sha256=input_sha,
        out_root=str(workdir / "runs" / "p1-release"),
    )
    return catalog


# ---------------------------------------------------------------------------
# Deterministic executors
# ---------------------------------------------------------------------------

def exec_env(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    workdir = Path(cfg["workdir"])
    env = {**os.environ, "PYTHONPATH": str(workdir / "src")}
    import_check = subprocess.run([sys.executable, "-c", "import acfv;print('ACFV_IMPORT_OK')"],
                                  cwd=workdir, env=env, capture_output=True, text=True,
                                  timeout=180, check=False)
    cli_check = subprocess.run([sys.executable, "-m", "acfv.cli", "--help"],
                               cwd=workdir, env=env, capture_output=True, text=True,
                               timeout=180, check=False)
    report = {
        "kind": "P1EnvironmentCheck",
        "import_returncode": import_check.returncode,
        "import_ok": "ACFV_IMPORT_OK" in import_check.stdout,
        "cli_returncode": cli_check.returncode,
        "cli_help_present": "Commands" in cli_check.stdout or "Usage" in cli_check.stdout,
        "python": sys.version,
        "python_executable": sys.executable,
    }
    report["status"] = "PASS" if report["import_ok"] and cli_check.returncode == 0 else "FAIL"
    _write_json(workdir / "evidence" / "p1" / "env.json", report)
    if report["status"] != "PASS":
        return _result(request, {"env": report}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,
                                            "documented import/CLI check failed"),
                       started=started, clock=clock)
    return _result(request, {"env": report}, started=started, clock=clock)


def exec_gap(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    workdir = Path(cfg["workdir"])
    baseline = _read_json(workdir / "docs" / "p1" / "ACFV_CAPABILITY_BASELINE.json")
    private = baseline.get("hardcoded_private_paths", {})
    readme = workdir / "README.md"
    release_doc = workdir / "docs" / "RELEASE_CANDIDATE.md"
    doc_text = ""
    for path in (readme, release_doc):
        if path.is_file():
            doc_text += "\n" + path.read_text(encoding="utf-8", errors="replace").lower()
    topics = {
        "install": any(word in doc_text for word in ("install", "安装")),
        "start": any(word in doc_text for word in ("start", "启动", "run the", "运行")),
        "input": any(word in doc_text for word in ("input", "输入")),
        "output": any(word in doc_text for word in ("output", "输出")),
        "limits": any(word in doc_text for word in ("limit", "known", "限制", "已知")),
    }
    caps = baseline.get("capabilities", {})
    report = {
        "kind": "P1ReleaseGapReport",
        "existing_verified": sorted(k for k, v in caps.items() if v.get("status") == "VERIFIED_EXISTING"),
        "existing_unverified": sorted(k for k, v in caps.items() if v.get("status") == "EXISTING_UNVERIFIED"),
        "partial": sorted(k for k, v in caps.items() if v.get("status") == "PARTIAL"),
        "known_private_paths": private.get("examples", []),
        "known_private_path_count": private.get("count", 0),
        "docs_topics": topics,
        "release_doc_present": release_doc.is_file(),
        "declared_product_verdict": baseline.get("declared_product_verdict"),
        "gaps": [
            "private absolute paths remain in release source" if private.get("count") else None,
            "release documentation does not cover all required topics" if not all(topics.values()) else None,
        ],
    }
    report["gaps"] = [g for g in report["gaps"] if g]
    _write_json(workdir / "evidence" / "p1" / "release_gap.json", report)
    return _result(request, {"gap_report": report}, started=started, clock=clock)


def exec_tests(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    workdir = Path(cfg["workdir"])
    env = {**os.environ, "PYTHONPATH": str(workdir / "src"),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=workdir, env=env,
                          capture_output=True, text=True, timeout=900, check=False)
    tail = (proc.stdout + "\n" + proc.stderr)[-8000:]
    summary = None
    for line in reversed(proc.stdout.splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            summary = line.strip()
            break
    report = {"kind": "P1TestRun", "returncode": proc.returncode,
              "summary": summary, "tail": tail}
    _write_json(workdir / "evidence" / "p1" / "tests.json", report)
    if proc.returncode != 0:
        return _result(request, {"tests": report}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,
                                            "test suite failed", {"failure_domain": "BUSINESS"}),
                       started=started, clock=clock)
    return _result(request, {"tests": report}, started=started, clock=clock)


def exec_e2e(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    workdir = Path(cfg["workdir"])
    command = list(cfg["command"])
    env = {**os.environ, **dict(cfg.get("environment", {}))}
    out_root = workdir / str(cfg.get("out_root", "runs/p1-release"))
    proc = subprocess.run(command, cwd=workdir, env=env, capture_output=True, text=True,
                          timeout=float(cfg.get("timeout_seconds", 3000)), check=False)
    runs = sorted([p for p in out_root.iterdir() if p.is_dir() and p.name.startswith("run_")],
                  key=lambda p: p.stat().st_mtime) if out_root.is_dir() else []
    run_dir = str(runs[-1]) if runs else None
    manifest = None
    if runs:
        for candidate in (runs[-1] / "work" / "clips_manifest.json",
                          runs[-1] / "work" / "clip_manifest.json"):
            if candidate.is_file():
                manifest = candidate
                break
    report = {
        "kind": "P1PipelineRun",
        "returncode": proc.returncode,
        "command": command,
        "out_root": str(out_root),
        "run_dir": run_dir,
        "manifest": str(manifest) if manifest else None,
        "manifest_sha256": _sha(manifest) if manifest else None,
        "stdout_tail": proc.stdout[-6000:],
        "stderr_tail": proc.stderr[-6000:],
    }
    _write_json(workdir / "evidence" / "p1" / "e2e_result.json", report)
    if proc.returncode != 0 or manifest is None:
        return _result(request, {"e2e": report}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,
                                            "pipeline failed or produced no clip manifest",
                                            {"failure_domain": "BUSINESS"}),
                       started=started, clock=clock)
    return _result(request, {"e2e": report}, started=started, clock=clock)


def _load_acceptance_module(path: Path):
    spec = importlib.util.spec_from_file_location("p1_acceptance", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load acceptance script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exec_accept(request: BlockExecutionRequest, acceptance: GoalAcceptance | None = None) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    workdir = Path(cfg["workdir"])
    report_path = workdir / "evidence" / "p1" / "independent_acceptance.json"
    try:
        module = _load_acceptance_module(Path(cfg["acceptance_script"]))
        report = module.evaluate(workdir, workdir / "runs" / "p1-release",
                                 str(cfg["input_path"]), str(cfg["input_sha256"]))
        report["goal_condition"] = RELEASE_CONDITION
        _write_json(report_path, report)
        subject_rel = "evidence/p1/independent_acceptance.json"
        subjects = {subject_rel: _sha(report_path)}
        if acceptance is not None:
            acceptance.bind_subjects(subjects)
        passed = report.get("status") == "PASS"
        goal_check = {
            "goal_id": cfg.get("goal_id", "acfv.release_candidate"),
            "condition_hash": identity(cfg.get("condition", RELEASE_CONDITION)),
            "subjects": subjects,
            "execution": "VALID",
            "verdict": "VERIFIED" if passed else "FAILED",
            "observed": {
                "status": report.get("status"),
                "failed_checks": [k for k, v in report.get("checks", {}).items() if not v],
                "clip_count": report.get("artifacts", {}).get("manifest", {}).get("clip_count"),
            },
            "evidence_refs": ["evidence/p1/independent_acceptance.json",
                              "evidence/p1/e2e_result.json",
                              "evidence/p1/env.json",
                              "evidence/p1/tests.json"],
            "checker_version": "1",
        }
        return _result(request, {"goal_check": goal_check, "acceptance": report},
                       started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _result(request, {}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,
                                            "acceptance error: " + str(exc)),
                       started=started, clock=clock)


# ---------------------------------------------------------------------------
# Independent deliverable checkers
# ---------------------------------------------------------------------------

def _read_report(path: Path) -> dict:
    return _read_json(path) if path.is_file() else {}


def _check_env(root: Path, contract: Mapping[str, Any]) -> dict:
    report = _read_report(root / "evidence" / "p1" / "env.json")
    passed = report.get("status") == "PASS"
    return {"passed": passed, "observed": report, "artifacts": ["evidence/p1/env.json"]}


def _check_gaps(root: Path, contract: Mapping[str, Any]) -> dict:
    report = _read_report(root / "evidence" / "p1" / "release_gap.json")
    passed = bool(report.get("existing_verified")) and isinstance(report.get("gaps"), list)
    return {"passed": passed, "observed": report, "artifacts": ["evidence/p1/release_gap.json"]}


def _drive_path_hits(root: Path, scope: list[str]) -> list[dict]:
    import re
    pattern = re.compile(r"""(?<![A-Za-z0-9_])[A-Za-z]:[\\/](?![ntr'"\\/])""")
    hits = []
    for rel in scope:
        path = root / rel
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line):
                hits.append({"file": rel, "line": lineno, "text": line.strip()[:160]})
    return hits


def _check_paths(root: Path, contract: Mapping[str, Any]) -> dict:
    hits = _drive_path_hits(root, list(contract["target_scope"]))
    return {"passed": not hits, "observed": {"hits": hits}, "artifacts": list(contract["target_scope"])}


def _check_docs(root: Path, contract: Mapping[str, Any]) -> dict:
    text = ""
    for rel in ("README.md", "docs/RELEASE_CANDIDATE.md"):
        path = root / rel
        if path.is_file():
            text += "\n" + path.read_text(encoding="utf-8", errors="replace").lower()
    topics = {
        "install": any(w in text for w in ("install", "安装")),
        "start": any(w in text for w in ("start", "启动", "run the", "运行")),
        "input": any(w in text for w in ("input", "输入")),
        "output": any(w in text for w in ("output", "输出")),
        "limits": any(w in text for w in ("limit", "known", "限制", "已知")),
    }
    return {"passed": all(topics.values()), "observed": {"topics": topics},
            "artifacts": ["README.md", "docs/RELEASE_CANDIDATE.md"]}


def _check_tests(root: Path, contract: Mapping[str, Any]) -> dict:
    report = _read_report(root / "evidence" / "p1" / "tests.json")
    passed = report.get("returncode") == 0 and bool(report.get("summary"))
    return {"passed": passed, "observed": report, "artifacts": ["evidence/p1/tests.json"]}


def _check_e2e(root: Path, contract: Mapping[str, Any]) -> dict:
    report = _read_report(root / "evidence" / "p1" / "e2e_result.json")
    passed = (report.get("returncode") == 0 and bool(report.get("manifest"))
              and bool(report.get("manifest_sha256")))
    return {"passed": passed, "observed": report, "artifacts": ["evidence/p1/e2e_result.json"]}


def _check_release(root: Path, contract: Mapping[str, Any]) -> dict:
    report = _read_report(root / "evidence" / "p1" / "independent_acceptance.json")
    passed = report.get("status") == "PASS"
    return {"passed": passed, "observed": report,
            "artifacts": ["evidence/p1/independent_acceptance.json"]}


def install_acfv_acceptance(store: FileRunStore, project_id: str, run_id: str) -> GoalAcceptance:
    acceptance = GoalAcceptance(
        store, project_id, run_id,
        {"R-release": {"must": True}, "R-perceptual": {"must": False}},
        {"release_check": "acfv.release.accept@1"}, execution_mode='LEGACY',
    )
    acceptance.bind_subjects({"evidence/p1/independent_acceptance.json": "UNMATERIALIZED"})
    plan = {
        "phases": [{"id": "release", "depends_on": []}],
        "goals": [{
            "id": "acfv.release_candidate", "phase_id": "release",
            "requirement_refs": ["R-release"], "acceptance": RELEASE_CONDITION,
            "subject_refs": ["evidence/p1/independent_acceptance.json"],
            "checker": "release_check", "checker_version": "1", "task_refs": [],
        }],
    }
    acceptance.propose(plan, CapabilityTree("ACFV release candidate", ()))
    acceptance.commit(plan)
    return acceptance


def register_acfv_executors(registry: ExecutorRegistry, workdir: Path,
                            client: CompletionClient, worker_config: ModelRoleConfig,
                            acceptance: GoalAcceptance,
                            catalog: Mapping[str, Any]) -> dict[str, str]:
    workdir = Path(workdir)
    deterministic = {
        "acfv.release.env@1": exec_env,
        "acfv.release.gap@1": exec_gap,
        "acfv.paths.normalize@1": exec_paths_normalize,
        "acfv.release.tests@1": exec_tests,
        "acfv.release.e2e@1": exec_e2e,
        "acfv.release.accept@1": lambda request: exec_accept(request, acceptance),
    }
    for cap, entry in catalog.items():
        ref = entry["executor_ref"]
        function = deterministic.get(ref)
        if function is None:
            continue
        timeout = float(entry["config"].get("timeout_seconds", 900))
        registry.register(_BoundedExecutor(cap, function, executor_ref=ref, timeout=timeout))
    registry.register(LLMExecutor(workdir, client, worker_config, max_rounds=2))
    checks = {
        "acfv.env": _check_env,
        "acfv.gaps": _check_gaps,
        "acfv.private_paths": _check_paths,
        "acfv.docs": _check_docs,
        "acfv.tests": _check_tests,
        "acfv.e2e": _check_e2e,
        "acfv.release_candidate": _check_release,
    }
    registry.register(FileDeliverableChecker(workdir, checks))
    return {entry["config"]["leaf_contract"]["checker_ref"]: "deliverable.files@1"
            for entry in catalog.values()}


def run_acfv_release(*, workdir: Path, project_id: str, run_id: str,
                     client: CompletionClient, routing: CGKNModelRouting,
                     input_path: Path, input_sha: str, acceptance_script: Path,
                     pipeline_config: Path, harness_dir: Path,
                     store_root: Path | None = None,
                     max_decisions: int = 6,
                     resume: bool = False,
                     continuation_feedback: dict[str, Any] | None = None) -> dict[str, Any]:
    workdir = Path(workdir)
    prepare_workspace(workdir, harness_dir)
    catalog = build_acfv_catalog(workdir, input_path=input_path, input_sha=input_sha,
                                 acceptance_script=acceptance_script,
                                 pipeline_config=pipeline_config,
                                 harness_dir=harness_dir)
    store = FileRunStore(store_root or (workdir / "state"))
    acceptance = install_acfv_acceptance(store, project_id, run_id)
    registry = ExecutorRegistry()
    deliverable = register_acfv_executors(registry, workdir, client, routing.worker,
                                          acceptance, catalog)
    runner = PreflightedDAGRunner(registry, store, max_parallel=1,
                                  execution_mode='LEGACY',
                                  deliverable_checkers=deliverable,
                                  catalog=catalog, workdir=workdir)
    composer = CatalogAgentComposer(client, routing.agent, allow_goal_plan=False,
                                    root_config={"acceptance_goal_id": "acfv.release_candidate"})
    composer.additional_instructions = (
        (composer.additional_instructions or "")
        + "\nUse the catalog output identity as the node_id exactly as given "
          "(for example acfv.release.env, acfv.release.gap, acfv.release.paths, "
          "acfv.release.docs, acfv.release.tests, acfv.release.e2e, acfv.release.accept). "
          "Do not invent prefixes. Every provenance value must be a JSON object. "
          "update_config requires a non-empty node_id that already exists in the current tree; "
          "to rerun a failed node use retry_node with that exact node_id and a concrete reason. "
          "When a worker is asked to repair files, it must return write_file or patch_file actions; "
          "reading alone is not a repair."
    )
    goal = (
        "Turn this ACFV worktree into a local release candidate that another local user can "
        "actually try. The formal input is the frozen 26.7-minute 1920x1080 video named in "
        "docs/p1/P1_GOAL.md; never modify it and never substitute a short fixture for the "
        "formal end-to-end run. Reuse the existing pipeline and tests. Decide the tree "
        "yourself from the registered capability catalog and the gap report. Completion "
        "means: the documented import/entry check passes; release source no longer needs "
        "the author's private absolute paths; the existing clip pipeline really runs on the "
        "formal input and exports real clips; the existing test suite passes; release "
        "documentation covers install, start, input, output and known limits; and the "
        "independent acceptance checker verifies decode, audio, duration, source hash and "
        "artifact traceability. Finish only after that independent acceptance is VERIFIED. "
        "Perceptual quality stays pending human review. If a deterministic check fails, "
        "repair the smallest responsible capability first; do not rebuild the whole project."
    )
    session = ProjectSession(
        composer, runner, store, known_capabilities=set(catalog),
        worker_model=routing.worker.model, capability_catalog=catalog,
        max_decisions=max_decisions, acceptance=acceptance, continuous=True, execution_mode='LEGACY',
    )
    try:
        result = session.run(project_id=project_id, run_id=run_id, goal=goal,
                             constraints=("Reuse existing ACFV capabilities before growing",
                                          "Do not modify the frozen input or acceptance checker",
                                          "Do not rewrite the project because one check fails",
                                          "No external publishing",
                                          "Perceptual review remains pending"),
                             resume=resume,
                             continuation_feedback=continuation_feedback)
    except PreflightRejected as exc:
        payload = {"kind": "ACFVReleaseResult", "project_id": project_id, "run_id": run_id,
                   "status": "PRECHECK_FAIL", "preflight": exc.report,
                   "workspace": str(workdir), "agent_calls": 0, "worker_calls": 0}
        _write_json(workdir / "evidence" / "p1" / "release_result.json", payload)
        return payload
    payload = {
        "kind": "ACFVReleaseResult", "project_id": project_id, "run_id": run_id,
        "status": result.status, "decision_count": result.decision_count,
        "agent_calls": result.agent_calls, "worker_calls": result.worker_calls,
        "escalation_reason": result.escalation_reason,
        "run_summary": result.run_summary.as_dict() if result.run_summary else None,
        "tree": result.tree.as_dict(),
        "goal_acceptance": acceptance.view(),
        "workspace": str(workdir),
    }
    _write_json(workdir / "evidence" / "p1" / "release_result.json", payload)
    return payload
