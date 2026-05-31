#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "examples" / "test_results" / "test_pipeline_composition_result.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", str(text or "").strip().lower())
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "modular-test-pipeline"


def rel(path: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def has_any(goal: str, words: tuple[str, ...]) -> bool:
    lowered = goal.lower()
    return any(word in lowered for word in words)


def detect_project_dir(goal: str, requested: str) -> pathlib.Path | None:
    if requested:
        path = pathlib.Path(requested)
        if not path.is_absolute():
            path = ROOT / path
        return path.resolve()
    candidates = sorted((ROOT / "generated").glob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    goal_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", goal.lower()))
    best: pathlib.Path | None = None
    best_score = 0
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        name_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", candidate.name.lower()))
        score = len(goal_tokens & name_tokens)
        if (candidate / "index.html").exists():
            score += 2
        if score > best_score:
            best = candidate
            best_score = score
    return best if best_score > 1 else None


def environment_catalog(goal: str, project_dir: pathlib.Path | None, profile: str, explicit: list[str], live_browser: bool) -> list[dict[str, Any]]:
    available: dict[str, dict[str, Any]] = {
        "contract_catalog": {
            "id": "contract_catalog",
            "label": "CGNK contract catalog",
            "scope": ["schemas/**", "examples/artifacts/**", "examples/modules/**", "examples/flows/**", "examples/policies/**"],
            "default": True,
            "external": "none",
        },
        "module_smoke": {
            "id": "module_smoke",
            "label": "Modular project-generation module smoke harness",
            "scope": ["examples/flows/modular_project_generation.flow.json", "examples/modules/**"],
            "default": True,
            "external": "none",
        },
        "connectivity_live_probe": {
            "id": "connectivity_live_probe",
            "label": "Live external API/Telegram connectivity probe",
            "scope": ["scripts/check_connectivity.py --live", "environment variable presence"],
            "default": False,
            "external": "live API probe",
        },
        "local_runtime_artifacts": {
            "id": "local_runtime_artifacts",
            "label": "Existing local runtime artifact directory",
            "scope": ["examples/runtime_runs/**"],
            "default": False,
            "external": "none",
        },
    }
    if project_dir:
        available["generated_static_browser"] = {
            "id": "generated_static_browser",
            "label": "Generated static browser project",
            "project_dir": str(project_dir),
            "scope": [rel(project_dir / "index.html"), rel(project_dir / "tests")],
            "default": (project_dir / "index.html").exists(),
            "external": "none",
        }
        available["local_browser_runtime"] = {
            "id": "local_browser_runtime",
            "label": "Headless browser against loopback static server",
            "project_dir": str(project_dir),
            "scope": [rel(project_dir / "index.html"), rel(project_dir / "tests")],
            "default": live_browser and (project_dir / "index.html").exists(),
            "external": "loopback only",
        }
        available["industrial_io_fixtures"] = {
            "id": "industrial_io_fixtures",
            "label": "Generated industrial I/O fixture set",
            "project_dir": str(project_dir),
            "scope": [
                rel(project_dir / "docs" / "INPUT_OUTPUT_SPEC.md"),
                rel(project_dir / "data" / "industrial_input_bundle.json"),
                rel(project_dir / "data" / "expected_outputs.json"),
                rel(project_dir / "tests" / "industrial_io_smoke_test.js"),
            ],
            "default": all(
                path.exists()
                for path in (
                    project_dir / "data" / "industrial_input_bundle.json",
                    project_dir / "data" / "expected_outputs.json",
                    project_dir / "tests" / "industrial_io_smoke_test.js",
                )
            ),
            "external": "none",
        }
    selected_ids: list[str]
    if explicit:
        selected_ids = explicit
    elif profile == "contracts":
        selected_ids = ["contract_catalog"]
    elif profile == "generated-project":
        selected_ids = ["contract_catalog", "generated_static_browser", "industrial_io_fixtures"]
        if live_browser:
            selected_ids.append("local_browser_runtime")
    elif profile == "connectivity":
        selected_ids = ["contract_catalog", "connectivity_live_probe"]
    elif profile == "full":
        selected_ids = list(available.keys())
    else:
        selected_ids = [env_id for env_id, row in available.items() if row.get("default")]
        if has_any(goal, ("api", "telegram", "connectivity", "连通", "接口")):
            selected_ids.append("connectivity_live_probe")
        if has_any(goal, ("runtime", "运行产物", "执行产物", "artifact")):
            selected_ids.append("local_runtime_artifacts")
    rows = []
    for env_id in dict.fromkeys(selected_ids):
        row = available.get(env_id)
        if row is None:
            rows.append({"id": env_id, "available": False, "reason": "unknown environment id"})
        else:
            row = {**row, "available": True}
            rows.append(row)
    return rows


def method_catalog(goal: str, environments: list[dict[str, Any]], profile: str, explicit: list[str], live_browser: bool) -> list[dict[str, Any]]:
    env_ids = {row["id"] for row in environments if row.get("available")}
    available: dict[str, dict[str, Any]] = {
        "schema_validation": {
            "id": "schema_validation",
            "label": "Validate JSON schemas and contract document shapes",
            "compatible_environments": ["contract_catalog"],
            "gate": "blocking",
        },
        "contract_compile": {
            "id": "contract_compile",
            "label": "Compile target flows and check typed edges/policies",
            "compatible_environments": ["contract_catalog"],
            "gate": "blocking",
        },
        "module_smoke": {
            "id": "module_smoke",
            "label": "Run deterministic module smoke fixtures",
            "compatible_environments": ["module_smoke"],
            "gate": "blocking",
        },
        "connectivity_live_probe": {
            "id": "connectivity_live_probe",
            "label": "Check external API/Telegram configuration with live API probes",
            "compatible_environments": ["connectivity_live_probe"],
            "gate": "warning",
        },
        "runtime_artifact_inspection": {
            "id": "runtime_artifact_inspection",
            "label": "Inspect existing runtime artifact set",
            "compatible_environments": ["local_runtime_artifacts"],
            "gate": "warning",
        },
        "static_project_contract": {
            "id": "static_project_contract",
            "label": "Inspect generated static project file and DOM contract",
            "compatible_environments": ["generated_static_browser"],
            "gate": "blocking",
        },
        "browser_smoke_declared": {
            "id": "browser_smoke_declared",
            "label": "Verify declared browser smoke test entrypoint and anti-fake-test constraints",
            "compatible_environments": ["generated_static_browser"],
            "gate": "blocking",
        },
        "browser_smoke_live": {
            "id": "browser_smoke_live",
            "label": "Execute window.runSmokeTest in a real headless browser",
            "compatible_environments": ["local_browser_runtime"],
            "gate": "blocking",
        },
        "industrial_io_contract": {
            "id": "industrial_io_contract",
            "label": "Inspect industrial input/output fixtures and smoke test declaration",
            "compatible_environments": ["industrial_io_fixtures"],
            "gate": "blocking",
        },
        "industrial_io_live": {
            "id": "industrial_io_live",
            "label": "Execute window.runIndustrialIOSmokeTest in a real headless browser",
            "compatible_environments": ["local_browser_runtime", "industrial_io_fixtures"],
            "gate": "blocking",
        },
    }
    if explicit:
        selected_ids = explicit
    elif profile == "contracts":
        selected_ids = ["schema_validation", "contract_compile"]
    elif profile == "generated-project":
        selected_ids = ["static_project_contract", "browser_smoke_declared", "industrial_io_contract"]
        if live_browser:
            selected_ids.extend(["browser_smoke_live", "industrial_io_live"])
    elif profile == "connectivity":
        selected_ids = ["schema_validation", "connectivity_live_probe"]
    elif profile == "full":
        selected_ids = list(available.keys())
    else:
        selected_ids = ["schema_validation", "contract_compile", "module_smoke"]
        if "generated_static_browser" in env_ids:
            selected_ids.extend(["static_project_contract", "browser_smoke_declared"])
        if "industrial_io_fixtures" in env_ids:
            selected_ids.append("industrial_io_contract")
        if live_browser and "local_browser_runtime" in env_ids:
            selected_ids.extend(["browser_smoke_live", "industrial_io_live"])
        if "connectivity_live_probe" in env_ids:
            selected_ids.append("connectivity_live_probe")
        if "local_runtime_artifacts" in env_ids:
            selected_ids.append("runtime_artifact_inspection")
    rows = []
    for method_id in dict.fromkeys(selected_ids):
        row = available.get(method_id)
        if row is None:
            rows.append({"id": method_id, "available": False, "reason": "unknown method id"})
            continue
        compatible = bool(env_ids & set(row["compatible_environments"]))
        rows.append({**row, "available": compatible, "reason": "" if compatible else "no selected compatible environment"})
    return rows


def build_steps(methods: list[dict[str, Any]], project_dir: pathlib.Path | None, run_dir: pathlib.Path) -> list[dict[str, Any]]:
    step_defs: dict[str, dict[str, Any]] = {
        "schema_validation": {
            "id": "schema_validation",
            "kind": "command",
            "command": ["python", "scripts/validate_bundle.py", "--schema"],
            "timeout_seconds": 120,
        },
        "contract_compile": {
            "id": "contract_compile",
            "kind": "command",
            "command": ["python", "scripts/validate_bundle.py", "--flow", "flow.modular_project_testing@1"],
            "timeout_seconds": 120,
        },
        "module_smoke": {
            "id": "module_smoke",
            "kind": "command",
            "command": ["python", "scripts/test_modular_modules.py"],
            "timeout_seconds": 180,
        },
        "connectivity_live_probe": {
            "id": "connectivity_live_probe",
            "kind": "command",
            "command": ["python", "scripts/check_connectivity.py", "--live"],
            "timeout_seconds": 120,
            "non_blocking": True,
        },
        "runtime_artifact_inspection": {
            "id": "runtime_artifact_inspection",
            "kind": "internal",
            "check": "runtime_artifact_inspection",
            "run_dir": str(run_dir),
            "non_blocking": True,
        },
        "static_project_contract": {
            "id": "static_project_contract",
            "kind": "internal",
            "check": "static_project_contract",
            "project_dir": str(project_dir) if project_dir else "",
        },
        "browser_smoke_declared": {
            "id": "browser_smoke_declared",
            "kind": "internal",
            "check": "browser_smoke_declared",
            "project_dir": str(project_dir) if project_dir else "",
        },
        "browser_smoke_live": {
            "id": "browser_smoke_live",
            "kind": "browser",
            "check": "browser_smoke_live",
            "project_dir": str(project_dir) if project_dir else "",
            "function_name": "runSmokeTest",
            "test_file": "tests/browser_smoke_test.js",
            "timeout_seconds": 60,
        },
        "industrial_io_contract": {
            "id": "industrial_io_contract",
            "kind": "internal",
            "check": "industrial_io_contract",
            "project_dir": str(project_dir) if project_dir else "",
        },
        "industrial_io_live": {
            "id": "industrial_io_live",
            "kind": "browser",
            "check": "industrial_io_live",
            "project_dir": str(project_dir) if project_dir else "",
            "function_name": "runIndustrialIOSmokeTest",
            "test_file": "tests/industrial_io_smoke_test.js",
            "timeout_seconds": 90,
        },
    }
    steps = []
    for method in methods:
        if not method.get("available"):
            continue
        step = step_defs.get(method["id"])
        if step:
            steps.append({**step, "method": method["id"], "gate": method.get("gate", "blocking")})
    return steps


def compose(goal: str, project_dir_arg: str, profile: str, environments_arg: list[str], methods_arg: list[str], run_dir_arg: str, live_browser: bool) -> dict[str, Any]:
    project_dir = detect_project_dir(goal, project_dir_arg)
    run_dir = pathlib.Path(run_dir_arg)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    environments = environment_catalog(goal, project_dir, profile, environments_arg, live_browser)
    methods = method_catalog(goal, environments, profile, methods_arg, live_browser)
    steps = build_steps(methods, project_dir, run_dir.resolve())
    matrix = [
        {
            "environment": env["id"],
            "methods": [
                method["id"]
                for method in methods
                if method.get("available") and env["id"] in method.get("compatible_environments", [])
            ],
        }
        for env in environments
        if env.get("available")
    ]
    target = {
        "goal": goal,
        "workspace_root": str(ROOT),
        "project_dir": str(project_dir) if project_dir else "",
        "profile": profile,
        "run_id": slug(goal),
    }
    gates = [
        {"id": f"gate_{step['id']}", "step": step["id"], "on_fail": "warn" if step.get("non_blocking") else "block"}
        for step in steps
    ]
    environment_plan = {
        "kind": "TestEnvironmentPlan",
        "created_at": now(),
        "payload": {
            "target": target,
            "environments": environments,
            "constraints": {
                "network": "enabled for live connectivity probes",
                "provider": "enabled for API-backed validation probes",
                "live_browser_execution": "declared-only unless a browser runner is explicitly added",
                "loopback_browser": "enabled" if live_browser else "disabled",
            },
        },
    }
    method_plan = {
        "kind": "TestMethodPlan",
        "created_at": now(),
        "payload": {
            "target": target,
            "methods": methods,
            "gates": gates,
        },
    }
    test_pipeline_plan = {
        "kind": "TestPipelinePlan",
        "created_at": now(),
        "payload": {
            "target": target,
            "matrix": matrix,
            "steps": steps,
            "gates": gates,
            "runner": {
                "flow": "flow.modular_project_testing@1",
                "command": "python scripts/run_test_pipeline.py --plan examples/test_results/test_pipeline_composition_result.json",
            },
        },
    }
    edges = [["goal", env["id"]] for env in environments if env.get("available")]
    for row in matrix:
        edges.extend([[row["environment"], method_id] for method_id in row["methods"]])
    edges.extend([[step["method"], step["id"]] for step in steps])
    test_graph = {
        "kind": "TestGraph",
        "created_at": now(),
        "payload": {
            "nodes": ["goal"] + [env["id"] for env in environments if env.get("available")] + [method["id"] for method in methods if method.get("available")] + [step["id"] for step in steps],
            "edges": edges,
            "coverage_targets": [row["environment"] for row in matrix],
            "quality_gates": gates,
        },
    }
    return {
        "kind": "ModularTestPipelineCompositionRun",
        "created_at": now(),
        "goal": goal,
        "environment_plan": environment_plan,
        "method_plan": method_plan,
        "test_pipeline_plan": test_pipeline_plan,
        "test_graph": test_graph,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--project-dir", default="")
    parser.add_argument("--profile", choices=["auto", "contracts", "generated-project", "connectivity", "full"], default="auto")
    parser.add_argument("--environment", action="append", default=[], help="Select an environment id. Can be passed multiple times.")
    parser.add_argument("--method", action="append", default=[], help="Select a method id. Can be passed multiple times.")
    parser.add_argument("--live-browser", action="store_true", help="Add loopback headless-browser smoke execution for generated browser projects.")
    parser.add_argument("--run-dir", default="examples/runtime_runs/local-pipeline-execution")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = compose(args.goal, args.project_dir, args.profile, args.environment, args.method, args.run_dir, args.live_browser)
    out_path = pathlib.Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    write_json(out_path, result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        steps = result["test_pipeline_plan"]["payload"]["steps"]
        envs = result["environment_plan"]["payload"]["environments"]
        methods = result["method_plan"]["payload"]["methods"]
        print(f"TEST_PIPELINE_COMPOSITION: OK environments={len(envs)} methods={len(methods)} steps={len(steps)}")
        print(f"out={out_path}")
        for step in steps:
            print(f"  {step['id']} [{step['kind']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
