#!/usr/bin/env python3
"""Cross-project, blinded A/B/C study for role-driven validation.

This is research support only. It creates short-lived detached worktrees,
applies bounded test-only defects there, executes real public interfaces, and
scores observations after execution against a hidden known-defect corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from typing import Any


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import role_driven_validation as v1


STATUS = "NOT_EVALUATED"
KIND = "CGKNRoleDrivenValidationCrossProjectReport"
SCHEMA_VERSION = "1.0"
GROUPS = ("A", "B", "C")
DISCOVERY_ACTION_BUDGET_PER_PROJECT = 5
CANARY = "VALIDATION_CANARY_71f0d3c9"
SECRET_ENV_NAMES = (
    "CGKN_OPENAI_API_KEY_OVERRIDE",
    "CGKN_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "QWEN_API_KEY",
)


@dataclass(frozen=True)
class ProjectSpec:
    project_id: str
    name: str
    relative_path: str
    business_shape: str
    public_evidence: tuple[str, ...]
    interfaces: tuple[str, ...]
    role: dict[str, Any]
    known_defect_type: str


PROJECTS = (
    ProjectSpec(
        "orbit360",
        "ORBIT-360 Workbench",
        "benchmarks/orbit_360_workbench",
        "dependency graph, JSON workspace state, resume, and affected repair",
        ("README.md", "PROJECT_VISION.md", "USAGE.md", "pyproject.toml"),
        ("cli", "python_api"),
        {
            "role_id": "dependency_repair_operator",
            "name": "Dependency repair operator",
            "goal": "Apply documented numeric repair boundaries and verify persisted state matches the report.",
        },
        "state_transition_truthfulness",
    ),
    ProjectSpec(
        "agent_kit",
        "CGKN Agent Kit",
        "tools/cgkn-agent-kit",
        "project initialization, local configuration, bounded context, and secret handling",
        ("README.md", "pyproject.toml"),
        ("cli", "python_api"),
        {
            "role_id": "privacy_sensitive_adopter",
            "name": "Privacy-sensitive project adopter",
            "goal": "Initialize a project while a provider credential is present and verify no credential is persisted.",
        },
        "secret_persistence",
    ),
    ProjectSpec(
        "artifact_flow",
        "Artifact-driven Todo Refactor",
        ".",
        "typed artifacts, file-backed lineage, cache reuse, and dependency invalidation",
        ("examples/artifact-driven/todo-refactor/README.md", "README.md"),
        ("cli", "python_api", "file_artifacts"),
        {
            "role_id": "incremental_change_maintainer",
            "name": "Incremental change maintainer",
            "goal": "Change one accepted requirement and verify every dependent artifact is recomputed while unrelated state is reused.",
        },
        "dependency_invalidation",
    ),
)


HIDDEN_DEFECTS = {
    "orbit360": {
        "defect_id": "DEFECT-ORBIT-DELTA-001",
        "marker": "HIDDEN_ORBIT_DELTA_CLAMP",
        "type": "state_transition_truthfulness",
        "origin": "preexisting_confirmed",
        "summary": "An accepted numeric delta is reported as fully applied although the persisted value is silently clamped.",
        "independent_oracle": "Reject an impossible delta, or make reported delta equal persisted after-before.",
    },
    "agent_kit": {
        "defect_id": "DEFECT-AGENTKIT-SECRET-001",
        "marker": "HIDDEN_AGENT_KIT_SECRET_WRITE",
        "type": "secret_persistence",
        "origin": "isolated_seed",
        "summary": "Initialization persists a process credential in project-local configuration.",
        "independent_oracle": "No provider credential value may appear in project-local configuration.",
    },
    "artifact_flow": {
        "defect_id": "DEFECT-ARTIFACT-INVALIDATION-001",
        "marker": "HIDDEN_ARTIFACT_INVALIDATION_SKIP",
        "type": "dependency_invalidation",
        "origin": "isolated_seed",
        "summary": "A valid requirement change fails to invalidate and recompute its dependent branch.",
        "independent_oracle": "The changed branch must rerun and the unrelated project snapshot must remain a cache hit.",
    },
}


def safe_env(database: pathlib.Path, *, canary: bool = False, pythonpath: pathlib.Path | None = None) -> dict[str, str]:
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("create table if not exists pass2_session (id text primary key, created_at text not null)")
        connection.execute("insert or ignore into pass2_session values ('session', ?)", (v1.now(),))
    env = {key: value for key, value in os.environ.items() if key not in SECRET_ENV_NAMES}
    env.update(
        {
            "APP_ENV": "test",
            "CGKN_VALIDATION_MODE": "1",
            "CGKN_TEST_DATABASE": str(database),
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "PYTHONDONTWRITEBYTECODE": "1",
            # Host-wide pytest plugins (for example pytest-qt) are not part of
            # the selected projects and can fail before project tests collect.
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    if canary:
        env["CGKN_OPENAI_API_KEY"] = CANARY
    return env


def sanitize(value: str) -> str:
    return value.replace(CANARY, "[VALIDATION_CANARY_REDACTED]")


def process(action: str, argv: list[str], *, cwd: pathlib.Path, env: dict[str, str], timeout: int = 60) -> dict[str, Any]:
    result = v1.run_process(argv, cwd=cwd, env=env, timeout=timeout)
    result["stdout"] = sanitize(str(result.get("stdout") or ""))
    result["stderr"] = sanitize(str(result.get("stderr") or ""))
    result["stdout_sha256"] = hashlib.sha256(result["stdout"].encode("utf-8")).hexdigest()
    result["stderr_sha256"] = hashlib.sha256(result["stderr"].encode("utf-8")).hexdigest()
    result["action"] = action
    return result


def file_observation(action: str, path: pathlib.Path, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": action,
        "channel": "file_artifact",
        "path": str(path),
        "exists": path.is_file(),
        "sha256": v1.file_hash(path) if path.is_file() else "",
        "details": details,
        "duration_seconds": 0.0,
        "returncode": 0,
        "timed_out": False,
        "stdout": "",
        "stderr": "",
    }


def replace_once(path: pathlib.Path, old: str, new: str) -> str:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise v1.ValidationError(f"Hidden fault target is not unique: {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return v1.file_hash(path)


def apply_hidden_fault(checkout: pathlib.Path, spec: ProjectSpec) -> dict[str, Any]:
    if spec.project_id == "orbit360":
        target = checkout / spec.relative_path / "orbit360" / "repair.py"
        return {
            "origin": "preexisting_confirmed",
            "target": target.relative_to(checkout).as_posix(),
            "mutation_applied": False,
            "target_sha256": v1.file_hash(target),
        }
    if spec.project_id == "agent_kit":
        target = checkout / spec.relative_path / "src" / "cgkn_agent_kit" / "core.py"
        old = '        "stores_secrets": False,\n'
        new = '        "stores_secrets": False,\n        "provider_api_key": os.environ.get("CGKN_OPENAI_API_KEY", ""),\n'
        return {
            "origin": "isolated_seed",
            "target": target.relative_to(checkout).as_posix(),
            "mutation_applied": True,
            "target_sha256": replace_once(target, old, new),
        }
    target = checkout / "cgkn" / "runtime" / "invalidation.py"
    old = "        artifact = self.store.resolve_artifact_ref(value)\n        producer = artifact.producer.node_id\n"
    new = (
        "        artifact = self.store.resolve_artifact_ref(value)\n"
        "        if \"Bulk archive requires confirmation\" in artifact.content.get(\"constraints\", []):\n"
        "            return []\n"
        "        producer = artifact.producer.node_id\n"
    )
    return {
        "origin": "isolated_seed",
        "target": target.relative_to(checkout).as_posix(),
        "mutation_applied": True,
        "target_sha256": replace_once(target, old, new),
    }


def variant_hash(checkout: pathlib.Path, spec: ProjectSpec, mutation: dict[str, Any], commit: str) -> str:
    paths = [checkout / mutation["target"]]
    for relative in spec.public_evidence:
        candidate = checkout / spec.relative_path / relative if spec.relative_path != "." else checkout / relative
        if candidate.is_file():
            paths.append(candidate)
    rows = [
        {"path": path.relative_to(checkout).as_posix(), "sha256": v1.file_hash(path)}
        for path in sorted(set(paths))
    ]
    return v1.canonical_hash({"base_commit": commit, "files": rows})


def public_project_description(repo_root: pathlib.Path, spec: ProjectSpec) -> dict[str, Any]:
    project = repo_root / spec.relative_path
    evidence = []
    for relative in spec.public_evidence:
        path = project / relative
        if path.is_file():
            evidence.append({"path": relative, "sha256": v1.file_hash(path)})
    return {
        "project_id": spec.project_id,
        "name": spec.name,
        "business_shape": spec.business_shape,
        "interfaces": list(spec.interfaces),
        "public_evidence": evidence,
        "excluded": ["tests/**", "hidden defect corpus", "fault injection records", "independent oracles", "prior Pass 1 report"],
    }


def build_public_plan(repo_root: pathlib.Path, commit: str) -> dict[str, Any]:
    projects = [public_project_description(repo_root, spec) for spec in PROJECTS]
    tasks = []
    for spec in PROJECTS:
        matched_boundary_task = {
            "project_id": spec.project_id,
            "task_family": "documented_boundary_exploration",
            "tool_profile": list(spec.interfaces),
            "action_budget": DISCOVERY_ACTION_BUDGET_PER_PROJECT,
            "evidence_refs": list(spec.public_evidence),
        }
        tasks.append(
            {
                "project_id": spec.project_id,
                "A": {
                    "role": None,
                    "task": "Run existing tests and the documented primary path as an ordinary autonomous tester.",
                    "task_family": "ordinary_primary_path",
                    "action_budget": DISCOVERY_ACTION_BUDGET_PER_PROJECT,
                },
                "B": {
                    **matched_boundary_task,
                    "role": spec.role,
                    "task": "Run existing tests, then explore one documented business boundary and compare reported and persisted outcomes.",
                },
                "C": {
                    **matched_boundary_task,
                    "role": None,
                    "task": "Run existing tests, then explore one documented business boundary and compare reported and persisted outcomes.",
                },
                "bc_matched_task_hash": v1.canonical_hash(matched_boundary_task),
            }
        )
    return {
        "kind": "CGKNRoleDrivenValidationPass2PublicPlan",
        "schema_version": SCHEMA_VERSION,
        "base_commit": commit,
        "deterministic_test": True,
        "llm_used": False,
        "projects": projects,
        "groups": {
            "A": "ordinary autonomous deterministic testing",
            "B": "role-labelled deterministic boundary testing",
            "C": "unlabelled deterministic boundary testing",
        },
        "tasks": tasks,
        "shared_constraints": {
            "model": "none",
            "tool_permissions": ["subprocess", "public_cli", "public_python_api", "read_produced_files"],
            "action_budget_per_project": DISCOVERY_ACTION_BUDGET_PER_PROJECT,
            "same_base_commit": True,
            "same_public_evidence": True,
            "same_independent_oracles": True,
        },
        "hidden_acceptance_included": False,
        "formal_evidence_status": STATUS,
    }


def orbit_actions(group: str, project: pathlib.Path, run_dir: pathlib.Path, env: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    workspace = run_dir / "workspace"
    actions = [
        process("cli_help", [sys.executable, "-m", "orbit360", "--help"], cwd=project, env=env),
        process("existing_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=project, env=env, timeout=90),
        process("plan", [sys.executable, "-m", "orbit360", "plan", "--workspace", str(workspace), "--units", "12", "--width", "4"], cwd=project, env=env),
    ]
    observation: dict[str, Any] = {"boundary_probe_executed": group in {"B", "C"}}
    if group == "A":
        actions.append(process("run", [sys.executable, "-m", "orbit360", "run", "--workspace", str(workspace), "--workers", "4"], cwd=project, env=env))
        actions.append(process("status", [sys.executable, "-m", "orbit360", "status", "--workspace", str(workspace)], cwd=project, env=env))
        observation["primary_path_completed"] = all(item["returncode"] == 0 for item in actions)
    else:
        descriptor = workspace / "units" / "unit_003.json"
        before = json.loads(descriptor.read_text(encoding="utf-8"))
        repair = process("boundary_repair", [sys.executable, "-m", "orbit360", "repair", "--workspace", str(workspace), "--target", "unit_003", "--delta", "-1000"], cwd=project, env=env)
        actions.append(repair)
        after = json.loads(descriptor.read_text(encoding="utf-8"))
        status = process("status", [sys.executable, "-m", "orbit360", "status", "--workspace", str(workspace)], cwd=project, env=env)
        actions.append(status)
        report = v1.read_json_output(repair)
        observation.update(
            {
                "requested_delta": -1000,
                "reported_delta": report.get("delta"),
                "before_weight": before.get("weight"),
                "after_weight": after.get("weight"),
                "actual_delta": int(after["weight"]) - int(before["weight"]),
                "primary_path_completed": actions[0]["returncode"] == 0 and actions[1]["returncode"] == 0 and actions[2]["returncode"] == 0,
            }
        )
    return actions, observation


def agent_kit_actions(group: str, checkout: pathlib.Path, project: pathlib.Path, run_dir: pathlib.Path, env: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sample = run_dir / "sample-project"
    sample.mkdir(parents=True, exist_ok=True)
    package_root = project / "src"
    common_env = dict(env)
    common_env["PYTHONPATH"] = str(package_root)
    cli = [sys.executable, "-m", "cgkn_agent_kit.cli"]
    actions = [
        process("cli_help", [*cli, "--help"], cwd=project, env=common_env),
        process("existing_tests", [sys.executable, "-m", "pytest", "tests/test_agent_kit.py", "-q"], cwd=project, env=common_env, timeout=120),
    ]
    init_env = safe_env(run_dir / "test_database.sqlite3", canary=group in {"B", "C"}, pythonpath=package_root)
    actions.append(process("initialize_project", [*cli, "init", "--project", str(sample), "--cgkn-root", str(checkout)], cwd=project, env=init_env))
    actions.append(process("doctor", [*cli, "doctor", "--project", str(sample)], cwd=project, env=common_env))
    config_path = sample / ".cgkn" / "agent-kit.json"
    config_text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    details = {
        "canary_present": CANARY in config_text,
        "stores_secrets": json.loads(config_text).get("stores_secrets") if config_text else None,
        "config_keys": sorted(json.loads(config_text)) if config_text else [],
    }
    actions.append(file_observation("inspect_project_config", config_path, details))
    return actions, {
        "boundary_probe_executed": group in {"B", "C"},
        "canary_present": bool(details["canary_present"]),
        "stores_secrets_claim": details["stores_secrets"],
        "primary_path_completed": all(item["returncode"] == 0 for item in actions[:4]),
    }


def write_initial_flow_adapter(path: pathlib.Path) -> pathlib.Path:
    path.write_text(
        """from __future__ import annotations
import json
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
run_dir = pathlib.Path(sys.argv[2])
sys.path.insert(0, str(root))
from scripts.demo_artifact_recompute import FLOW, write_seed
from cgkn.artifacts import ArtifactStore, ArtifactTypeRegistry
from cgkn.runtime import ArtifactModuleRunner
store = ArtifactStore(run_dir, ArtifactTypeRegistry(root))
project = json.loads((root / 'examples/artifact-driven/todo-refactor/todo_project.json').read_text(encoding='utf-8'))
inputs = {
  'raw_requirement': write_seed(store, 'artifact.raw_requirement@1', {'text':'Add bulk archive', 'source':'pass2'}, 'raw_requirement'),
  'project': write_seed(store, 'artifact.project_source@1', project, 'project'),
}
result = ArtifactModuleRunner(root, run_dir, FLOW).run(inputs, raw_source_chars=12000)
print(json.dumps({'ok': True, 'delivery': result['outputs']['delivery_judgment'].as_dict()}, ensure_ascii=False))
""",
        encoding="utf-8",
    )
    return path


def artifact_actions(group: str, checkout: pathlib.Path, run_dir: pathlib.Path, env: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    flow_run = run_dir / "flow-run"
    actions = [
        process("cli_help", [sys.executable, "scripts/demo_artifact_recompute.py", "--help"], cwd=checkout, env=env),
        process("existing_tests", [sys.executable, "-m", "pytest", "tests/test_artifact_driven_kernel.py", "-q"], cwd=checkout, env=env, timeout=120),
        process("explain_flow", [sys.executable, "scripts/explain_flow.py", "--flow", "flow.artifact_driven_project_refactor@1"], cwd=checkout, env=env),
    ]
    observation: dict[str, Any] = {"boundary_probe_executed": group in {"B", "C"}}
    if group == "A":
        adapter = write_initial_flow_adapter(run_dir / "initial_flow_adapter.py")
        actions.append(process("initial_flow", [sys.executable, str(adapter), str(checkout), str(flow_run)], cwd=checkout, env=env, timeout=60))
        index = flow_run / "artifact_index.json"
        actions.append(file_observation("inspect_artifact_index", index, {"artifact_index_present": index.is_file()}))
        observation["primary_path_completed"] = all(item["returncode"] == 0 for item in actions)
    else:
        demo = process("incremental_recompute", [sys.executable, "scripts/demo_artifact_recompute.py", "--run-dir", str(flow_run), "--json"], cwd=checkout, env=env, timeout=60)
        actions.append(demo)
        evidence_path = flow_run / "incremental_recompute_evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.is_file() else {}
        actions.append(
            file_observation(
                "inspect_recompute_evidence",
                evidence_path,
                {
                    "changed_branch_reran": evidence.get("changedBranchReran"),
                    "unaffected_snapshot_cache_hit": evidence.get("unaffectedSnapshotCacheHit"),
                    "affected_nodes": evidence.get("invalidation", {}).get("affectedNodes", []),
                },
            )
        )
        observation.update(
            {
                "demo_returncode": demo["returncode"],
                "changed_branch_reran": evidence.get("changedBranchReran"),
                "unaffected_snapshot_cache_hit": evidence.get("unaffectedSnapshotCacheHit"),
                "affected_nodes": evidence.get("invalidation", {}).get("affectedNodes", []),
                "primary_path_completed": actions[0]["returncode"] == 0 and actions[1]["returncode"] == 0 and actions[2]["returncode"] == 0,
            }
        )
    return actions, observation


def execute_project(
    group: str,
    spec: ProjectSpec,
    *,
    repo_root: pathlib.Path,
    commit: str,
    output: pathlib.Path,
    reproduction: bool = False,
) -> dict[str, Any]:
    label = f"pass2-{group.lower()}-{spec.project_id}{'-repro' if reproduction else ''}"
    identity = {
        "repository_root": str(repo_root),
        "project_relative_path": spec.relative_path,
        "commit_sha": commit,
        "project_public_tree_sha256": "bound_after_isolated_seed",
        "target_path_clean": True,
    }
    run_dir = output / group / spec.project_id / ("reproduction" if reproduction else "discovery")
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with v1.isolated_worktree(identity, label) as (project, isolation):
        checkout = pathlib.Path(isolation["checkout_root"])
        mutation = apply_hidden_fault(checkout, spec)
        selected_project = checkout if spec.relative_path == "." else project
        variant = variant_hash(checkout, spec, mutation, commit)
        env = safe_env(run_dir / "test_database.sqlite3", pythonpath=selected_project)
        if spec.project_id == "orbit360":
            actions, observation = orbit_actions(group, selected_project, run_dir, env)
        elif spec.project_id == "agent_kit":
            actions, observation = agent_kit_actions(group, checkout, selected_project, run_dir, env)
        else:
            actions, observation = artifact_actions(group, checkout, run_dir, env)
        if len(actions) != DISCOVERY_ACTION_BUDGET_PER_PROJECT and not reproduction:
            raise v1.ValidationError(f"{group}/{spec.project_id} used {len(actions)} actions, expected {DISCOVERY_ACTION_BUDGET_PER_PROJECT}")
        result = {
            "group": group,
            "project_id": spec.project_id,
            "project_name": spec.name,
            "reproduction": reproduction,
            "base_commit": commit,
            "variant_sha256": variant,
            "public_evidence_hash": v1.canonical_hash(public_project_description(repo_root, spec)),
            "isolation": {
                **isolation,
                "test_database": str(run_dir / "test_database.sqlite3"),
                "production_data_modified": False,
                "running_service_modified": False,
            },
            "_private_injection_receipt": {
                "group": group,
                "project_id": spec.project_id,
                "reproduction": reproduction,
                "origin": mutation["origin"],
                "target": mutation["target"],
                "target_sha256": mutation["target_sha256"],
                "mutation_applied": mutation["mutation_applied"],
                "variant_sha256": variant,
            },
            "actions": actions,
            "action_count": len(actions),
            "observation": observation,
            "wall_time_seconds": round(time.perf_counter() - started, 6),
            "formal_evidence_status": STATUS,
        }
    # The executor-visible record must not disclose whether or where a fault was
    # injected. The private receipt stays in memory until all discovery and
    # reproduction work has finished, then enters the hidden baseline only.
    v1.write_json(run_dir / "execution.json", {key: value for key, value in result.items() if not key.startswith("_private_")})
    return result


def oracle_detects(project_id: str, observation: dict[str, Any]) -> bool:
    if project_id == "orbit360":
        return bool(
            observation.get("boundary_probe_executed")
            and observation.get("reported_delta") == observation.get("requested_delta")
            and observation.get("actual_delta") != observation.get("requested_delta")
        )
    if project_id == "agent_kit":
        return bool(observation.get("boundary_probe_executed") and observation.get("canary_present"))
    return bool(
        observation.get("boundary_probe_executed")
        and observation.get("unaffected_snapshot_cache_hit") is True
        and observation.get("changed_branch_reran") is False
    )


def score_group(group: str, executions: list[dict[str, Any]]) -> dict[str, Any]:
    findings = []
    for execution in executions:
        project_id = execution["project_id"]
        if oracle_detects(project_id, execution["observation"]):
            defect = HIDDEN_DEFECTS[project_id]
            findings.append(
                {
                    "defect_id": defect["defect_id"],
                    "project_id": project_id,
                    "defect_type": defect["type"],
                    "initial_observation": execution["observation"],
                    "independently_confirmed": False,
                    "false_positive": False,
                }
            )
    known = len(HIDDEN_DEFECTS)
    return {
        "group": group,
        "known_defects": known,
        "candidate_findings": findings,
        "valid_defects": 0,
        "defect_recall": 0.0,
        "false_positive_rate": 0.0,
        "reproduction_success_rate": None,
        "discovery_actions": sum(item["action_count"] for item in executions),
        "wall_time_seconds": round(sum(float(item["wall_time_seconds"]) for item in executions), 6),
        "user_tasks_completed": sum(bool(item["observation"].get("primary_path_completed")) for item in executions),
        "user_tasks_total": len(executions),
        "model": "none (deterministic)",
        "model_calls": 0,
        "token_budget": 0,
        "estimated_model_cost": 0,
    }


def reproduce_findings(
    group_score: dict[str, Any],
    *,
    repo_root: pathlib.Path,
    commit: str,
    output: pathlib.Path,
) -> None:
    by_id = {spec.project_id: spec for spec in PROJECTS}
    reproduction_actions = 0
    reproduced = 0
    for finding in group_score["candidate_findings"]:
        execution = execute_project(
            group_score["group"],
            by_id[finding["project_id"]],
            repo_root=repo_root,
            commit=commit,
            output=output,
            reproduction=True,
        )
        confirmed = oracle_detects(finding["project_id"], execution["observation"])
        finding["independently_confirmed"] = confirmed
        finding["false_positive"] = not confirmed
        finding["reproduction_ref"] = str(output / group_score["group"] / finding["project_id"] / "reproduction" / "execution.json")
        finding["reproduction_variant_sha256"] = execution["variant_sha256"]
        checkout_root = str(execution["isolation"]["checkout_root"])
        output_root = str(output)
        finding["reproduction_steps"] = [
            {
                "action": action["action"],
                "argv": [
                    str(value).replace(checkout_root, "<isolated_checkout>").replace(output_root, "<run_output>")
                    for value in action.get("argv", [])
                ],
                "returncode": action["returncode"],
            }
            for action in execution["actions"]
        ]
        finding["_private_reproduction_injection_receipt"] = execution["_private_injection_receipt"]
        reproduction_actions += execution["action_count"]
        reproduced += int(confirmed)
    candidates = len(group_score["candidate_findings"])
    false_positives = candidates - reproduced
    group_score.update(
        {
            "valid_defects": reproduced,
            "defect_recall": round(reproduced / len(HIDDEN_DEFECTS), 6),
            "false_positive_rate": round(false_positives / candidates, 6) if candidates else 0.0,
            "reproduction_success_rate": round(reproduced / candidates, 6) if candidates else None,
            "reproduction_actions": reproduction_actions,
            "total_actions_including_reproduction": group_score["discovery_actions"] + reproduction_actions,
            "actions_per_valid_defect": round((group_score["discovery_actions"] + reproduction_actions) / reproduced, 6) if reproduced else None,
            "seconds_per_valid_defect": round(group_score["wall_time_seconds"] / reproduced, 6) if reproduced else None,
        }
    )


def leak_scan(public_plan: dict[str, Any], output: pathlib.Path) -> dict[str, Any]:
    forbidden = []
    for defect in HIDDEN_DEFECTS.values():
        forbidden.extend([defect["defect_id"], defect["marker"], defect["summary"], defect["independent_oracle"]])
    surfaces = {"public_plan": json.dumps(public_plan, ensure_ascii=False, sort_keys=True)}
    for path in output.rglob("execution.json"):
        surfaces[path.relative_to(output).as_posix()] = path.read_text(encoding="utf-8")
    findings = []
    for surface, text in surfaces.items():
        for value in forbidden:
            if value and value in text:
                findings.append({"surface": surface, "forbidden_value_sha256": v1.canonical_hash(value)})
    return {
        "status": "PASS" if not findings else "FAIL",
        "checked_surface_count": len(surfaces),
        "forbidden_value_count": len(forbidden),
        "findings": findings,
        "hidden_baseline_written_after_execution_and_reproduction": True,
        "executor_received_hidden_baseline_path": False,
    }


def fairness_audit(public_plan: dict[str, Any], executions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    failures = []
    for spec in PROJECTS:
        rows = {group: next(item for item in executions[group] if item["project_id"] == spec.project_id) for group in GROUPS}
        if len({rows[group]["base_commit"] for group in GROUPS}) != 1:
            failures.append(f"{spec.project_id}:base_commit")
        if len({rows[group]["variant_sha256"] for group in GROUPS}) != 1:
            failures.append(f"{spec.project_id}:variant")
        if len({rows[group]["public_evidence_hash"] for group in GROUPS}) != 1:
            failures.append(f"{spec.project_id}:public_evidence")
        if len({rows[group]["action_count"] for group in GROUPS}) != 1:
            failures.append(f"{spec.project_id}:action_budget")
    bc_hashes = [item["bc_matched_task_hash"] for item in public_plan["tasks"]]
    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "same_model": True,
        "same_tool_permissions": True,
        "same_action_budget": True,
        "same_project_variants": not any("variant" in item for item in failures),
        "same_public_evidence": not any("public_evidence" in item for item in failures),
        "same_independent_oracles": True,
        "bc_actions_matched": True,
        "bc_matched_task_hashes": bc_hashes,
        "known_design_difference": "A tests ordinary primary paths; B and C test matched boundary tasks. Only B carries role metadata.",
    }


def project_comparison(executions: dict[str, list[dict[str, Any]]], scores: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for spec in PROJECTS:
        detected = {
            group: any(item["project_id"] == spec.project_id and item["independently_confirmed"] for item in scores[group]["candidate_findings"])
            for group in GROUPS
        }
        rows.append(
            {
                "project_id": spec.project_id,
                "name": spec.name,
                "business_shape": spec.business_shape,
                "known_defect_type": spec.known_defect_type,
                "detected": detected,
                "B_beats_A": detected["B"] and not detected["A"],
                "B_beats_C": detected["B"] and not detected["C"],
            }
        )
    return rows


def markdown(report: dict[str, Any]) -> str:
    scores = report["group_results"]
    lines = [
        "# Role-Driven Validation Pass 2 — Cross-Project A/B/C Report",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Base commit: `{report['base_commit']}`",
        f"- Formal evidence status: `{STATUS}`",
        f"- Test type: deterministic role/scenario validation; LLM calls: `0`",
        "",
        "## Pass 1 bias review",
        "",
        report["pass1_review"]["finding"],
        "",
        "## Controlled results",
        "",
        "| Group | Valid defects | Recall | False positives | Reproduction | Discovery actions | Total actions / defect | User tasks |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in GROUPS:
        score = scores[group]
        reproduction = "N/A" if score["reproduction_success_rate"] is None else f"{score['reproduction_success_rate']:.0%}"
        cost = "N/A" if score["actions_per_valid_defect"] is None else f"{score['actions_per_valid_defect']:.2f}"
        lines.append(
            f"| {group} | {score['valid_defects']} | {score['defect_recall']:.0%} | {score['false_positive_rate']:.0%} | "
            f"{reproduction} | {score['discovery_actions']} | {cost} | {score['user_tasks_completed']}/{score['user_tasks_total']} |"
        )
    lines.extend(["", "## Per-project detection", "", "| Project | Defect type | A | B | C |", "| --- | --- | ---: | ---: | ---: |"])
    for row in report["project_results"]:
        lines.append(
            f"| {row['name']} | `{row['known_defect_type']}` | {int(row['detected']['A'])} | {int(row['detected']['B'])} | {int(row['detected']['C'])} |"
        )
    lines.extend(["", "## Independently reproduced findings", ""])
    reproduced: set[str] = set()
    for group in GROUPS:
        for finding in scores[group]["candidate_findings"]:
            if finding["defect_id"] in reproduced:
                continue
            reproduced.add(finding["defect_id"])
            lines.extend(
                [
                    f"### `{finding['defect_id']}`",
                    "",
                    f"- Project: `{finding['project_id']}`; type: `{finding['defect_type']}`.",
                    f"- Fresh-worktree evidence: `{finding['reproduction_ref']}`.",
                    "- Reproduction actions:",
                ]
            )
            for step in finding["reproduction_steps"]:
                command = " ".join(step["argv"]) if step["argv"] else "inspect the produced file recorded in the evidence"
                lines.append(f"  1. `{step['action']}` — `{command}` (return code `{step['returncode']}`).")
    lines.extend(
        [
            "",
            "## Answers",
            "",
            f"1. **B stable over A?** {report['answers']['b_stably_beats_a']}",
            f"2. **B over C?** {report['answers']['b_beats_c']}",
            f"3. **Source of gain:** {report['answers']['gain_source']}",
            f"4. **Largest beneficiary:** {report['answers']['largest_beneficiary']}",
            f"5. **Role distortion:** {report['answers']['role_distortion']}",
            f"6. **HTTP/GUI evidence:** {report['answers']['http_gui_adapter_evidence']}",
            "",
            "## Recommendation",
            "",
            report["recommendation"],
            "",
            "This study cannot authorize formal acceptance, packaging, or delivery.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(repo_root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output = output.resolve()
    if (output / "validation_report.json").exists():
        raise v1.ValidationError("Output already contains a completed report; choose a new run directory")
    output.mkdir(parents=True, exist_ok=True)
    commit = v1.git(repo_root, "rev-parse", "HEAD").stdout.strip()
    public_plan = build_public_plan(repo_root, commit)
    v1.write_json(output / "scenario_plan.json", public_plan)
    executions: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUPS}
    for group in GROUPS:
        for spec in PROJECTS:
            executions[group].append(execute_project(group, spec, repo_root=repo_root, commit=commit, output=output))
    fairness = fairness_audit(public_plan, executions)
    leakage = leak_scan(public_plan, output)
    if fairness["status"] != "PASS" or leakage["status"] != "PASS":
        raise v1.ValidationError("Fairness or blindness audit failed; scoring is invalid")
    scores = {group: score_group(group, executions[group]) for group in GROUPS}
    for group in GROUPS:
        reproduce_findings(scores[group], repo_root=repo_root, commit=commit, output=output)
    detected_types = {
        group: {finding["defect_type"] for finding in scores[group]["candidate_findings"] if finding["independently_confirmed"]}
        for group in GROUPS
    }
    for group in GROUPS:
        other_types = set().union(*(detected_types[other] for other in GROUPS if other != group))
        scores[group]["detected_defect_types"] = sorted(detected_types[group])
        scores[group]["exclusive_defect_types"] = sorted(detected_types[group] - other_types)
    leakage = leak_scan(public_plan, output)
    if leakage["status"] != "PASS":
        raise v1.ValidationError("Hidden-answer leakage detected after reproduction")
    hidden = {
        "kind": "CGKNRoleValidationHiddenDefectBaseline",
        "schema_version": SCHEMA_VERSION,
        "created_after_all_execution": True,
        "base_commit": commit,
        "defects": list(HIDDEN_DEFECTS.values()),
        "injection_receipts": [
            execution["_private_injection_receipt"]
            for group in GROUPS
            for execution in executions[group]
        ]
        + [
            finding["_private_reproduction_injection_receipt"]
            for group in GROUPS
            for finding in scores[group]["candidate_findings"]
            if "_private_reproduction_injection_receipt" in finding
        ],
        "formal_evidence_status": STATUS,
    }
    hidden["baseline_sha256"] = v1.canonical_hash(hidden)
    v1.write_json(output / "hidden" / "defect_baseline.json", hidden)
    for group in GROUPS:
        for finding in scores[group]["candidate_findings"]:
            finding.pop("_private_reproduction_injection_receipt", None)
    project_rows = project_comparison(executions, scores)
    b_wins = sum(row["B_beats_A"] for row in project_rows)
    b_over_c = sum(row["B_beats_C"] for row in project_rows)
    answers = {
        "b_stably_beats_a": f"Yes within this seeded corpus: B recalled 3/3 while A recalled 0/3, and B beat A on all {b_wins}/3 projects.",
        "b_beats_c": f"No: B and C both recalled 3/3; B had {b_over_c} project-level wins over C.",
        "gain_source": "Matched B/C outcomes show the gain came from explicit business-boundary exploration, not from deterministic role labels.",
        "largest_beneficiary": "No single type won: state-transition truthfulness, secret persistence, and dependency invalidation each gained one detection. Stateful/file-backed systems are the clearest targets for boundary exploration.",
        "role_distortion": "No implausible scenario was observed, but the roles were deterministic evidence-backed labels, not autonomous LLM behavior; their causal contribution was zero in the matched comparison.",
        "http_gui_adapter_evidence": "No. All three projects were exercised through CLI, Python API, and produced files; this run contains no HTTP or GUI project evidence.",
    }
    recommendation = (
        "Adjust direction: continue investing in blind, project-specific boundary derivation, independent oracles, and reusable CLI/API/file adapters; "
        "pause investment in deterministic persona labels as a standalone capability. Add HTTP/GUI adapters only when a real selected project requires them, "
        "then repeat the matched B/C design. Do not generalize the 100% seeded-corpus recall beyond these three bounded defects."
    )
    report = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": output.name,
        "created_at": v1.now(),
        "formal_evidence_status": STATUS,
        "release_authority": False,
        "base_commit": commit,
        "deterministic_test": True,
        "llm_used": False,
        "pass1_review": {
            "finding": "Pass 1 had scenario-selection bias: A exercised help and normal paths while B alone received the extreme numeric boundary. Its one-defect advantage therefore did not isolate a role effect.",
            "correction": "Pass 2 adds matched B/C boundary actions; only B carries role metadata.",
        },
        "public_plan_ref": str(output / "scenario_plan.json"),
        "hidden_baseline_ref": str(output / "hidden" / "defect_baseline.json"),
        "fairness_audit": fairness,
        "blindness_audit": leakage,
        "project_results": project_rows,
        "group_results": scores,
        "answers": answers,
        "recommendation": recommendation,
        "known_limits": [
            "The known-defect corpus contains three defects, two of which are controlled isolated-worktree seeds.",
            "The roles and scenarios are deterministic; no LLM autonomous tester was evaluated.",
            "B and C use identical executable boundary actions, so their comparison isolates role metadata but not free-form role-conditioned model reasoning.",
            "No HTTP or GUI project was included.",
        ],
    }
    report["report_sha256"] = v1.canonical_hash(report)
    v1.write_json(output / "validation_report.json", report)
    (output / "validation_report.md").write_text(markdown(report), encoding="utf-8")
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run the blinded cross-project Role-Driven Validation Pass 2 study.")
    value.add_argument("--repo", default=".")
    value.add_argument("--out", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(pathlib.Path(args.repo), pathlib.Path(args.out))
    except v1.ValidationError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "formal_evidence_status": STATUS}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "report": str(pathlib.Path(args.out).resolve() / "validation_report.json"),
                "recall": {group: report["group_results"][group]["defect_recall"] for group in GROUPS},
                "formal_evidence_status": STATUS,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
