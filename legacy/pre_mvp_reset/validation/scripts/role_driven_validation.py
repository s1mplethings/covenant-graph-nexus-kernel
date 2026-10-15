#!/usr/bin/env python3
"""Model-independent role-driven black-box validation support lane.

This module does not produce formal CGKN evidence and does not participate in
generation, packaging, or delivery.  It exercises an existing project from an
isolated source worktree and keeps the evaluator's acceptance predicates out
of the public role/scenario plan.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterator


SUPPORT_STATUS = "NOT_EVALUATED"
REPORT_KIND = "CGKNRoleDrivenValidationSupportReport"
SCHEMA_VERSION = "1.0"
DEFAULT_SCENARIO_BUDGET = 4
DEFAULT_ACTION_BUDGET = 12


class ValidationError(RuntimeError):
    """A bounded validation setup or execution error."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: pathlib.Path, value: Any) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_json_output(step: dict[str, Any]) -> dict[str, Any]:
    stdout = str(step.get("stdout") or "")
    try:
        value = json.loads(stdout)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def run_process(
    argv: list[str],
    *,
    cwd: pathlib.Path,
    env: dict[str, str],
    timeout: int = 30,
) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = now()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = str(exc.stdout or "")
        stderr = str(exc.stderr or "")
        timed_out = True
    return {
        "argv": argv,
        "cwd": str(cwd),
        "started_at": started_at,
        "finished_at": now(),
        "duration_seconds": round(time.perf_counter() - started, 6),
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
    }


def git(project: pathlib.Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and completed.returncode != 0:
        raise ValidationError(completed.stderr.strip() or completed.stdout.strip() or f"git {' '.join(args)} failed")
    return completed


def public_project_files(project: pathlib.Path) -> list[pathlib.Path]:
    allowed_names = {"README.md", "PROJECT_VISION.md", "USAGE.md", "pyproject.toml", "package.json"}
    result: list[pathlib.Path] = []
    for path in sorted(project.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(project)
        if any(part.lower() in {"tests", "test", ".git", ".venv", "venv", "node_modules", "__pycache__"} for part in relative.parts):
            continue
        if path.name in allowed_names or path.suffix.lower() in {".py", ".md"}:
            result.append(path)
    return result[:200]


def project_tree_hash(project: pathlib.Path) -> str:
    rows = []
    for path in public_project_files(project):
        rows.append({"path": path.relative_to(project).as_posix(), "sha256": file_hash(path)})
    return canonical_hash(rows)


def inspect_project(project: pathlib.Path) -> dict[str, Any]:
    project = project.resolve()
    evidence: list[dict[str, str]] = []
    text_fragments: list[str] = []
    for name in ("README.md", "PROJECT_VISION.md", "USAGE.md", "pyproject.toml"):
        path = project / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            evidence.append({"path": name, "sha256": file_hash(path)})
            text_fragments.append(text[:16000])
    combined = "\n".join(text_fragments).lower()
    interfaces = []
    if "[project.scripts]" in combined or "argparse" in combined or "python -m " in combined:
        interfaces.append("cli")
    if any((project / candidate).is_dir() for candidate in ("src", "orbit360", "app")):
        interfaces.append("python_api")
    if any(project.rglob("*.html")) or "playwright" in combined or "browser" in combined:
        interfaces.append("gui")
    capabilities = []
    for label, markers in (
        ("planning", ("plan", "规划")),
        ("execution", ("run", "执行")),
        ("resume", ("resume", "续跑")),
        ("repair", ("repair", "修复")),
        ("status", ("status", "状态")),
        ("persistence", ("checkpoint", "sqlite", "持久")),
    ):
        if any(marker in combined for marker in markers):
            capabilities.append(label)
    goal_lines = []
    for text in text_fragments:
        for line in text.splitlines():
            stripped = line.strip(" #-\t")
            if stripped and len(stripped) <= 240 and ("愿景" in line or "goal" in line.lower() or "workbench" in line.lower()):
                goal_lines.append(stripped)
            if len(goal_lines) >= 5:
                break
    return {
        "project_root": str(project),
        "project_name": project.name,
        "goal_evidence": goal_lines[:5],
        "capabilities": capabilities,
        "interfaces": sorted(set(interfaces)),
        "public_evidence": evidence,
        "excluded_from_understanding": ["tests/**", "test/**", "hidden acceptance", "prior defect answers"],
        "public_tree_sha256": project_tree_hash(project),
    }


@dataclasses.dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    role_id: str
    channel: str
    task: str
    evidence_refs: tuple[str, ...]
    executor: str
    acceptance_id: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "role_id": self.role_id,
            "channel": self.channel,
            "task": self.task,
            "evidence_refs": list(self.evidence_refs),
        }


ORBIT_ROLES = [
    {
        "role_id": "local_operator",
        "name": "Local workflow operator",
        "goal": "Create, execute, and inspect a bounded workspace through documented commands.",
        "evidence_refs": ["README.md", "USAGE.md"],
    },
    {
        "role_id": "recovery_maintainer",
        "name": "Resume and recovery maintainer",
        "goal": "Confirm verified work is reused after a fresh invocation.",
        "evidence_refs": ["PROJECT_VISION.md", "USAGE.md"],
    },
    {
        "role_id": "automation_integrator",
        "name": "Python automation integrator",
        "goal": "Use the public Python API and inspect its persisted state independently.",
        "evidence_refs": ["pyproject.toml", "orbit360/runner.py"],
    },
    {
        "role_id": "boundary_operator",
        "name": "Boundary-condition operator",
        "goal": "Apply an allowed extreme repair request and verify the reported change matches reality.",
        "evidence_refs": ["USAGE.md", "orbit360/repair.py"],
    },
]


BASELINE_SCENARIOS = [
    Scenario("A-01", "Discover CLI", "generic_agent", "cli", "Open the command help and confirm the program is reachable.", ("README.md",), "help", "help_ok"),
    Scenario("A-02", "Create workspace", "generic_agent", "cli", "Create a small documented workspace.", ("USAGE.md",), "plan", "plan_ok"),
    Scenario("A-03", "Run and resume", "generic_agent", "cli", "Run a small workspace twice and inspect status.", ("USAGE.md",), "resume", "resume_ok"),
    Scenario("A-04", "Typical repair", "generic_agent", "cli", "Apply the documented +1 repair and rerun.", ("USAGE.md",), "repair_normal", "repair_normal_ok"),
]


ROLE_SCENARIOS = [
    Scenario("B-01", "Operator primary path", "local_operator", "cli", "Plan, run, and inspect a 12-unit workspace.", ("README.md", "USAGE.md"), "operator", "operator_ok"),
    Scenario("B-02", "Verified resume", "recovery_maintainer", "cli", "Run the same workspace from a fresh process and verify all valid results are reused.", ("PROJECT_VISION.md", "USAGE.md"), "resume", "resume_ok"),
    Scenario("B-03", "API integration", "automation_integrator", "python_api", "Create and execute a workspace through the public Python API.", ("pyproject.toml", "orbit360/runner.py"), "api", "api_ok"),
    Scenario("B-04", "Extreme decrement", "boundary_operator", "cli", "Request the documented minimum repair delta and compare the report with the actual descriptor change.", ("USAGE.md", "orbit360/repair.py"), "repair_extreme", "repair_extreme_truthful"),
]


def generate_roles(understanding: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    """Derive bounded roles from observed interfaces and capabilities, without model calls."""
    interfaces = set(understanding.get("interfaces", []))
    capabilities = set(understanding.get("capabilities", []))
    selected = []
    for role in ORBIT_ROLES:
        role_id = str(role["role_id"])
        eligible = (
            (role_id == "local_operator" and "cli" in interfaces)
            or (role_id == "recovery_maintainer" and "resume" in capabilities)
            or (role_id == "automation_integrator" and "python_api" in interfaces)
            or (role_id == "boundary_operator" and "repair" in capabilities)
        )
        if eligible:
            selected.append(role)
    if len(selected) < 3:
        raise ValidationError("Project evidence did not justify at least three distinct validation roles")
    return selected[:limit]


def generate_scenarios(roles: list[dict[str, Any]]) -> list[Scenario]:
    role_ids = {str(role["role_id"]) for role in roles}
    selected = [scenario for scenario in ROLE_SCENARIOS if scenario.role_id in role_ids]
    if len(selected) != len(roles):
        raise ValidationError("Every generated role must have one distinct executable scenario")
    return selected


def channel_selection(understanding: dict[str, Any], scenarios: list[Scenario]) -> dict[str, Any]:
    available = set(str(item) for item in understanding.get("interfaces", []))
    selected = sorted({scenario.channel for scenario in scenarios})
    unavailable = []
    for channel in ("cli", "python_api", "gui"):
        if channel not in available:
            unavailable.append({"channel": channel, "reason": "No public project evidence supports this channel."})
    return {
        "preference_order": ["cli", "python_api", "gui"],
        "available": sorted(available),
        "selected": selected,
        "not_selected": unavailable,
    }


def select_adapter(understanding: dict[str, Any]) -> str:
    name = str(understanding.get("project_name") or "").lower()
    evidence_paths = {str(item.get("path") or "") for item in understanding.get("public_evidence", [])}
    if name == "orbit_360_workbench" and "pyproject.toml" in evidence_paths:
        return "orbit360_v1"
    raise ValidationError("No safe validation adapter matches this project; add a reviewed isolated adapter before execution")


def source_identity(project: pathlib.Path) -> dict[str, Any]:
    repo_root = pathlib.Path(git(project, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    commit = git(project, "rev-parse", "HEAD").stdout.strip()
    relative = project.resolve().relative_to(repo_root).as_posix()
    dirty = git(repo_root, "status", "--porcelain", "--", relative).stdout.strip().splitlines()
    if dirty:
        raise ValidationError("Target project has uncommitted changes; refusing a version-ambiguous A/B run")
    return {
        "repository_root": str(repo_root),
        "project_relative_path": relative,
        "commit_sha": commit,
        "project_public_tree_sha256": project_tree_hash(project),
        "target_path_clean": True,
    }


@contextlib.contextmanager
def isolated_worktree(identity: dict[str, Any], label: str) -> Iterator[tuple[pathlib.Path, dict[str, Any]]]:
    temp_parent = pathlib.Path(tempfile.mkdtemp(prefix=f"cgkn-role-validation-{label}-"))
    checkout = temp_parent / "source"
    repo_root = pathlib.Path(str(identity["repository_root"]))
    added = False
    try:
        completed = git(repo_root, "worktree", "add", "--detach", str(checkout), str(identity["commit_sha"]), check=False)
        if completed.returncode != 0:
            raise ValidationError(completed.stderr.strip() or "cannot create isolated git worktree")
        added = True
        project = checkout / str(identity["project_relative_path"])
        receipt = {
            "method": "git_worktree_detached",
            "source_commit": identity["commit_sha"],
            "checkout_root": str(checkout),
            "project_root": str(project),
            "created_at": now(),
        }
        yield project, receipt
    finally:
        if added:
            git(repo_root, "worktree", "remove", "--force", str(checkout), check=False)
        if temp_parent.exists():
            shutil.rmtree(temp_parent, ignore_errors=True)


def validation_env(database: pathlib.Path) -> dict[str, str]:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute("create table if not exists validation_session (id text primary key, created_at text not null)")
        connection.execute("insert into validation_session (id, created_at) values (?, ?)", (uuid.uuid4().hex, now()))
        connection.commit()
    finally:
        connection.close()
    env = dict(os.environ)
    env.update(
        {
            "APP_ENV": "test",
            "CGKN_VALIDATION_MODE": "1",
            "CGKN_TEST_DATABASE": str(database),
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def cli(project: pathlib.Path, env: dict[str, str], *args: str) -> dict[str, Any]:
    return run_process([sys.executable, "-m", "orbit360", *args], cwd=project, env=env)


def api_adapter(project: pathlib.Path, arm_dir: pathlib.Path, env: dict[str, str], workspace: pathlib.Path) -> dict[str, Any]:
    adapter = arm_dir / "isolated_test_adapter.py"
    adapter.write_text(
        """from __future__ import annotations
import json
import pathlib
import sys
from orbit360.planner import build_plan
from orbit360.workspace import materialize
from orbit360.runner import run_workspace, workspace_status
root = pathlib.Path(sys.argv[1])
materialize(build_plan(12, 4), root)
first = run_workspace(root, workers=4)
status = workspace_status(root)
print(json.dumps({\"ok\": True, \"first\": first, \"status\": status}, ensure_ascii=False))
""",
        encoding="utf-8",
    )
    api_env = dict(env)
    existing_pythonpath = str(api_env.get("PYTHONPATH") or "")
    api_env["PYTHONPATH"] = str(project) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    return run_process([sys.executable, str(adapter), str(workspace)], cwd=project, env=api_env)


def execute_scenario(
    scenario: Scenario,
    *,
    project: pathlib.Path,
    arm_dir: pathlib.Path,
    env: dict[str, str],
    reproduction: bool = False,
) -> dict[str, Any]:
    suffix = "reproduction" if reproduction else "initial"
    workspace = arm_dir / "workspaces" / f"{scenario.scenario_id}-{suffix}"
    if workspace.exists():
        shutil.rmtree(workspace)
    steps: list[dict[str, Any]] = []

    def call(*args: str) -> dict[str, Any]:
        step = cli(project, env, *args)
        steps.append(step)
        return step

    if scenario.executor == "help":
        call("--help")
    elif scenario.executor == "plan":
        call("plan", "--workspace", str(workspace), "--units", "12", "--width", "4")
    elif scenario.executor in {"resume", "operator"}:
        call("plan", "--workspace", str(workspace), "--units", "12", "--width", "4")
        call("run", "--workspace", str(workspace), "--workers", "4")
        if scenario.executor == "resume":
            call("run", "--workspace", str(workspace), "--workers", "4")
        call("status", "--workspace", str(workspace))
    elif scenario.executor == "repair_normal":
        call("plan", "--workspace", str(workspace), "--units", "12", "--width", "4")
        call("run", "--workspace", str(workspace), "--workers", "4")
        call("repair", "--workspace", str(workspace), "--target", "unit_003", "--delta", "1")
        call("run", "--workspace", str(workspace), "--workers", "4")
    elif scenario.executor == "api":
        steps.append(api_adapter(project, arm_dir, env, workspace))
    elif scenario.executor == "repair_extreme":
        call("plan", "--workspace", str(workspace), "--units", "12", "--width", "4")
        before_path = workspace / "units" / "unit_003.json"
        before = json.loads(before_path.read_text(encoding="utf-8")) if before_path.is_file() else {}
        repair_step = call("repair", "--workspace", str(workspace), "--target", "unit_003", "--delta", "-1000")
        after = json.loads(before_path.read_text(encoding="utf-8")) if before_path.is_file() else {}
        repair_step["independent_observation"] = {
            "before_weight": before.get("weight"),
            "after_weight": after.get("weight"),
            "actual_delta": (
                int(after["weight"]) - int(before["weight"])
                if isinstance(before.get("weight"), int) and isinstance(after.get("weight"), int)
                else None
            ),
            "requested_delta": -1000,
        }
    else:
        raise ValidationError(f"Unsupported executor: {scenario.executor}")
    return {
        "scenario": scenario.public_dict(),
        "workspace": str(workspace),
        "reproduction": reproduction,
        "steps": steps,
        "action_count": len(steps),
        "artifacts": artifact_inventory(workspace),
    }


def artifact_inventory(root: pathlib.Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    result = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": file_hash(path),
                }
            )
    return result


def evaluate(outcome: dict[str, Any], acceptance_id: str) -> dict[str, Any]:
    steps = outcome["steps"]
    observations = [read_json_output(step) for step in steps]
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, observed: Any, expected: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "observed": observed, "expected": expected})

    if acceptance_id == "help_ok":
        check("help_exit", steps[0]["returncode"] == 0, steps[0]["returncode"], "0")
        check("help_usage", "usage:" in steps[0]["stdout"].lower(), steps[0]["stdout"][:200], "contains usage")
    elif acceptance_id == "plan_ok":
        check("plan_exit", steps[0]["returncode"] == 0, steps[0]["returncode"], "0")
        check("plan_count", observations[0].get("unit_count") == 12, observations[0].get("unit_count"), "12")
    elif acceptance_id in {"resume_ok", "operator_ok"}:
        check("all_exit", all(step["returncode"] == 0 for step in steps), [step["returncode"] for step in steps], "all 0")
        if acceptance_id == "resume_ok":
            check("resume_reuses_all", observations[-2].get("reused_count") == 12, observations[-2].get("reused_count"), "12")
        check("status_valid", observations[-1].get("valid_checkpoint_results") == 12, observations[-1].get("valid_checkpoint_results"), "12")
    elif acceptance_id == "repair_normal_ok":
        check("all_exit", all(step["returncode"] == 0 for step in steps), [step["returncode"] for step in steps], "all 0")
        check("repair_closure", observations[2].get("affected_count") == 3, observations[2].get("affected_count"), "3")
        check("repair_rerun", observations[3].get("executed_count") == 3, observations[3].get("executed_count"), "3")
    elif acceptance_id == "api_ok":
        payload = observations[0]
        check("api_exit", steps[0]["returncode"] == 0, steps[0]["returncode"], "0")
        check("api_run", payload.get("first", {}).get("executed_count") == 12, payload.get("first", {}).get("executed_count"), "12")
        check("api_status", payload.get("status", {}).get("valid_checkpoint_results") == 12, payload.get("status", {}).get("valid_checkpoint_results"), "12")
    elif acceptance_id == "repair_extreme_truthful":
        repair = observations[-1]
        independent = steps[-1].get("independent_observation", {})
        rejected = steps[-1]["returncode"] != 0
        truthful_success = (
            steps[-1]["returncode"] == 0
            and independent.get("actual_delta") == independent.get("requested_delta")
            and repair.get("delta") == independent.get("actual_delta")
        )
        check(
            "repair_delta_truthful_or_rejected",
            rejected or truthful_success,
            {"returncode": steps[-1]["returncode"], "report_delta": repair.get("delta"), **independent},
            "reject an impossible decrement, or apply and report the exact requested delta",
        )
    else:
        raise ValidationError(f"Unknown independent acceptance id: {acceptance_id}")
    passed = all(item["passed"] for item in checks)
    return {
        "evaluator": "independent_deterministic_oracle_v1",
        "acceptance_id": acceptance_id,
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "production_claims_trusted": False,
        "subjective_llm_judgment": {
            "status": SUPPORT_STATUS,
            "model": None,
            "reason": "No LLM was used; subjective quality remains separately unevaluated.",
        },
    }


def issue_from(scenario: Scenario, evaluation: dict[str, Any]) -> dict[str, Any] | None:
    failed = [item for item in evaluation["checks"] if not item["passed"]]
    if not failed:
        return None
    fingerprint = canonical_hash({"scenario_id": scenario.scenario_id, "checks": [item["check"] for item in failed]})
    return {
        "issue_id": f"ISSUE-{fingerprint[:12]}",
        "scenario_id": scenario.scenario_id,
        "title": f"{scenario.title}: independent acceptance failed",
        "failed_checks": failed,
        "reproduction_status": "pending",
        "valid_defect": False,
        "false_positive": False,
    }


def failure_domain(outcome: dict[str, Any]) -> str:
    diagnostic = "\n".join(str(step.get("stderr") or "") for step in outcome.get("steps", []))
    infrastructure_markers = (
        "ModuleNotFoundError",
        "No such file or directory",
        "cannot create isolated git worktree",
        "is not recognized as an internal or external command",
    )
    return "validation_environment" if any(marker in diagnostic for marker in infrastructure_markers) else "project_behavior"


def append_jsonl(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def run_arm(
    name: str,
    scenarios: list[Scenario],
    *,
    identity: dict[str, Any],
    out_dir: pathlib.Path,
    scenario_budget: int,
    action_budget: int,
) -> dict[str, Any]:
    arm_dir = out_dir / name
    arm_dir.mkdir(parents=True, exist_ok=True)
    operation_log = arm_dir / "operations.jsonl"
    database = arm_dir / "test_database.sqlite3"
    env = validation_env(database)
    selected = scenarios[:scenario_budget]
    started = time.perf_counter()
    results = []
    issues = []
    with isolated_worktree(identity, name) as (project, isolation):
        isolation.update(
            {
                "test_database": str(database),
                "database_separate_from_production": True,
                "running_service_modified": False,
                "source_worktree_writable_only_for_test_process": True,
            }
        )
        used_actions = 0
        for scenario in selected:
            outcome = execute_scenario(scenario, project=project, arm_dir=arm_dir, env=env)
            used_actions += int(outcome["action_count"])
            if used_actions > action_budget:
                raise ValidationError(f"{name} exceeded action budget {action_budget}")
            evaluation = evaluate(outcome, scenario.acceptance_id)
            result = {**outcome, "evaluation": evaluation}
            results.append(result)
            append_jsonl(operation_log, result)
            issue = issue_from(scenario, evaluation)
            if issue:
                reproduction = execute_scenario(scenario, project=project, arm_dir=arm_dir, env=env, reproduction=True)
                reproduced_evaluation = evaluate(reproduction, scenario.acceptance_id)
                reproduced = reproduced_evaluation["status"] == "FAIL"
                domain = failure_domain(reproduction)
                valid_defect = reproduced and domain == "project_behavior"
                issue.update(
                    {
                        "reproduction_status": "reproduced" if reproduced else "not_reproduced",
                        "failure_domain": domain,
                        "valid_defect": valid_defect,
                        "false_positive": not valid_defect,
                        "reproduction": {**reproduction, "evaluation": reproduced_evaluation},
                    }
                )
                issues.append(issue)
                append_jsonl(operation_log, {"event": "reproduction", "issue": issue})
    valid = sum(1 for issue in issues if issue["valid_defect"])
    false_positive = sum(1 for issue in issues if issue["false_positive"])
    findings = len(issues)
    return {
        "arm": name,
        "source_identity": identity,
        "isolation": isolation,
        "budget": {
            "model": "none (deterministic)",
            "model_calls": 0,
            "token_budget": 0,
            "scenario_budget": scenario_budget,
            "action_budget": action_budget,
            "actions_used": sum(int(item["action_count"]) for item in results),
        },
        "scenario_results": results,
        "issues": issues,
        "metrics": {
            "scenario_count": len(results),
            "passed_scenarios": sum(1 for item in results if item["evaluation"]["status"] == "PASS"),
            "findings": findings,
            "valid_defects": valid,
            "valid_defect_discovery_rate": round(valid / len(results), 6) if results else None,
            "false_positive_rate": round(false_positive / findings, 6) if findings else 0.0,
            "reproduction_success_rate": round(valid / findings, 6) if findings else None,
            "wall_time_seconds": round(time.perf_counter() - started, 6),
            "model_calls": 0,
            "estimated_model_cost": 0,
        },
        "operation_log": str(operation_log),
        "formal_evidence_status": SUPPORT_STATUS,
    }


def markdown_report(report: dict[str, Any]) -> str:
    a = report["arms"]["baseline"]
    b = report["arms"]["role_driven"]
    lines = [
        "# Role-Driven Autonomous Validation A/B Report",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Project: `{report['project_understanding']['project_name']}`",
        f"- Source commit: `{report['source_identity']['commit_sha']}`",
        f"- Formal evidence status: `{SUPPORT_STATUS}` (support evaluation only)",
        "",
        "## Controlled comparison",
        "",
        "| Metric | A: generic agent | B: role-driven |",
        "| --- | ---: | ---: |",
        f"| Scenarios | {a['metrics']['scenario_count']} | {b['metrics']['scenario_count']} |",
        f"| Valid defects | {a['metrics']['valid_defects']} | {b['metrics']['valid_defects']} |",
        f"| Valid defects / scenario | {a['metrics']['valid_defect_discovery_rate']:.3f} | {b['metrics']['valid_defect_discovery_rate']:.3f} |",
        f"| False-positive rate | {a['metrics']['false_positive_rate']:.3f} | {b['metrics']['false_positive_rate']:.3f} |",
        f"| Reproduction success | {a['metrics']['reproduction_success_rate'] if a['metrics']['reproduction_success_rate'] is not None else 'N/A'} | {b['metrics']['reproduction_success_rate'] if b['metrics']['reproduction_success_rate'] is not None else 'N/A'} |",
        f"| Actions used / cap | {a['budget']['actions_used']} / {a['budget']['action_budget']} | {b['budget']['actions_used']} / {b['budget']['action_budget']} |",
        f"| Model calls / cost | 0 / 0 | 0 / 0 |",
        f"| Wall time (s) | {a['metrics']['wall_time_seconds']:.3f} | {b['metrics']['wall_time_seconds']:.3f} |",
        "",
        "## Roles and scenarios",
        "",
    ]
    for role in report["roles"]:
        lines.append(f"- **{role['name']}** — {role['goal']} Evidence: {', '.join(role['evidence_refs'])}.")
    lines.extend(["", "## Reproducible findings", ""])
    findings = [issue for arm in report["arms"].values() for issue in arm["issues"] if issue["valid_defect"]]
    if not findings:
        lines.append("No independently reproduced defect was found. This is a valid zero-defect result, not a PASS claim.")
    for issue in findings:
        failed = issue["failed_checks"][0]
        lines.extend(
            [
                f"### {issue['issue_id']} — {issue['title']}",
                "",
                f"- Expected: `{failed['expected']}`",
                f"- Observed: `{json.dumps(failed['observed'], ensure_ascii=False)}`",
                f"- Reproduction: `{issue['reproduction_status']}` in a fresh scenario workspace.",
                f"- Steps: run scenario `{issue['scenario_id']}` from `scenario_plan.json`; exact argv/stdout/stderr are in the arm operation log.",
                "",
            ]
        )
    conclusion = report["comparison"]["conclusion"]
    lines.extend(
        [
            "## Independent conclusion",
            "",
            conclusion,
            "",
            "Subjective LLM judgment was not used. These support results cannot authorize formal evidence, packaging, or delivery.",
            "",
            "## Next phase",
            "",
            "1. Add reviewed adapters for HTTP/API and GUI projects while keeping business validation on normal interfaces.",
            "2. Run a frozen defect-bearing corpus to measure recall, not only valid findings per scenario.",
            "3. Add an optional blinded LLM semantic evaluator whose judgment remains separate from deterministic checks.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_validation(project: pathlib.Path, out_dir: pathlib.Path, *, scenario_budget: int, action_budget: int) -> dict[str, Any]:
    if not 3 <= scenario_budget <= 5:
        raise ValidationError("scenario budget must be between 3 and 5")
    project = project.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    understanding = inspect_project(project)
    adapter = select_adapter(understanding)
    identity = source_identity(project)
    roles = generate_roles(understanding, limit=scenario_budget)
    role_scenarios = generate_scenarios(roles)
    public_plan = {
        "kind": "CGKNRoleDrivenValidationScenarioPlan",
        "schema_version": SCHEMA_VERSION,
        "project_understanding": understanding,
        "roles": roles,
        "baseline_scenarios": [item.public_dict() for item in BASELINE_SCENARIOS[:scenario_budget]],
        "role_driven_scenarios": [item.public_dict() for item in role_scenarios],
        "channel_selection": channel_selection(understanding, role_scenarios),
        "hidden_acceptance_included": False,
        "adapter": adapter,
        "formal_evidence_status": SUPPORT_STATUS,
    }
    write_json(out_dir / "scenario_plan.json", public_plan)
    baseline = run_arm(
        "baseline",
        BASELINE_SCENARIOS,
        identity=identity,
        out_dir=out_dir,
        scenario_budget=scenario_budget,
        action_budget=action_budget,
    )
    role_driven = run_arm(
        "role_driven",
        role_scenarios,
        identity=identity,
        out_dir=out_dir,
        scenario_budget=scenario_budget,
        action_budget=action_budget,
    )
    delta = role_driven["metrics"]["valid_defects"] - baseline["metrics"]["valid_defects"]
    if delta > 0:
        conclusion = (
            "Within this bounded trial, role-driven validation improved real-problem discovery: it found "
            f"{delta} additional independently reproduced defect(s) under the same model and scenario budgets."
        )
    else:
        conclusion = (
            "This bounded trial did not demonstrate an improvement in real-problem discovery. The main bottleneck is "
            "the limited single-project sample and absence of a frozen defect corpus; broader channel adapters and "
            "blinded semantic evaluation are needed before making a general claim."
        )
    report = {
        "kind": REPORT_KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": out_dir.name,
        "created_at": now(),
        "formal_evidence_status": SUPPORT_STATUS,
        "release_authority": False,
        "project_understanding": understanding,
        "source_identity": identity,
        "adapter": adapter,
        "roles": roles,
        "scenario_plan_ref": str(out_dir / "scenario_plan.json"),
        "arms": {"baseline": baseline, "role_driven": role_driven},
        "comparison": {
            "same_model": True,
            "same_model_budget": True,
            "same_scenario_budget": True,
            "same_project_version": baseline["source_identity"]["commit_sha"] == role_driven["source_identity"]["commit_sha"],
            "additional_valid_defects": delta,
            "conclusion": conclusion,
        },
        "known_limits": [
            "One existing CLI/Python project was evaluated.",
            "GUI was not selected because the project exposes no GUI.",
            "Defect recall is not measurable without a frozen known-defect corpus.",
            "No subjective LLM evaluator was used.",
        ],
    }
    report["report_sha256"] = canonical_hash(report)
    write_json(out_dir / "validation_report.json", report)
    (out_dir / "validation_report.md").write_text(markdown_report(report), encoding="utf-8")
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run bounded role-driven autonomous validation A/B support evidence.")
    value.add_argument("--project", required=True, help="Existing project root")
    value.add_argument("--out", required=True, help="Output directory for support evidence")
    value.add_argument("--scenario-budget", type=int, default=DEFAULT_SCENARIO_BUDGET)
    value.add_argument("--action-budget", type=int, default=DEFAULT_ACTION_BUDGET)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run_validation(
            pathlib.Path(args.project),
            pathlib.Path(args.out),
            scenario_budget=args.scenario_budget,
            action_budget=args.action_budget,
        )
    except ValidationError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "formal_evidence_status": SUPPORT_STATUS}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "report": str(pathlib.Path(args.out).resolve() / "validation_report.json"),
                "additional_valid_defects": report["comparison"]["additional_valid_defects"],
                "formal_evidence_status": SUPPORT_STATUS,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
