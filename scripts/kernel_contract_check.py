#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import re
import sys
from dataclasses import dataclass


ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def read_rel(path: str) -> str:
    full = ROOT / path
    if not full.exists():
        raise FileNotFoundError(path)
    return full.read_text(encoding="utf-8", errors="replace")


def section_between(text: str, start_pattern: str, end_pattern: str) -> str:
    start = re.search(start_pattern, text, flags=re.S | re.M)
    if not start:
        return ""
    end = re.search(end_pattern, text[start.end() :], flags=re.S | re.M)
    if not end:
        return text[start.start() :]
    return text[start.start() : start.end() + end.start()]


def function_body(text: str, name: str) -> str:
    match = re.search(rf"^def\s+{re.escape(name)}\s*\(", text, flags=re.M)
    if not match:
        return ""
    next_match = re.search(r"^def\s+\w+\s*\(", text[match.end() :], flags=re.M)
    if not next_match:
        return text[match.start() :]
    return text[match.start() : match.end() + next_match.start()]


def contains_all(text: str, needles: list[str]) -> tuple[bool, list[str]]:
    missing = [needle for needle in needles if needle not in text]
    return not missing, missing


def add(results: list[CheckResult], name: str, ok: bool, detail: str = "") -> None:
    results.append(CheckResult(name, ok, "" if ok else detail))


def check_telegram(results: list[CheckResult]) -> None:
    text = read_rel("scripts/telegram_live_bridge.py")
    ok, missing = contains_all(
        text,
        [
            "start_agent_generation",
            "run_agent_generation_job",
            "backend_dialogue_loop",
            "apply_backend_dialogue_tick",
            "agent_session_path",
            "finish_agent_loop_delivery",
        ],
    )
    add(results, "telegram bridge exposes required kernel functions", ok, ", ".join(missing))

    backend_control = function_body(text, "append_backend_control")
    ok, missing = contains_all(backend_control, ['"BackendControlLog"', '"log_only": True', 'status: str = "logged"'])
    add(results, "backend_controls remain log-only compatibility records", ok, ", ".join(missing))

    generation_branch = section_between(text, r'if\s+intent\s*==\s*"generation_confirmation"\s*:', r'^\s*if\s+intent\s*==\s*"escalation_request"\s*:')
    forbidden = [item for item in ["generate_project.py", "run_local_pipeline", "simulator", "run_generation_subprocess"] if item in generation_branch]
    add(results, "generation_confirmation does not call legacy pipeline", bool(generation_branch) and not forbidden, ", ".join(forbidden))

    gate_pattern = r'if[^\n]*(soft_questions|blocking_questions)[^\n]*:\s*\n(?:\s+.*\n){0,6}?\s+return\b'
    gate = re.search(gate_pattern, generation_branch)
    add(results, "soft/blocking questions are not hard generation gates", bool(generation_branch) and gate is None, "return under question branch" if gate else "")

    job = function_body(text, "run_agent_generation_job")
    planner_index = job.find("pipeline_planner_agent.plan_pipeline")
    runner_index = job.find("dynamic_pipeline_runner.run_dynamic_pipeline")
    manifest_index = job.find("write_pipeline_manifest")
    fallback_index = job.find('"pipeline_fallback"')
    add(
        results,
        "run_agent_generation_job plans manifest before dynamic runner",
        planner_index >= 0 and runner_index > planner_index and manifest_index > planner_index and manifest_index < runner_index,
        "planner/write/runner order missing",
    )
    add(results, "pipeline fallback is explicitly recorded", fallback_index >= 0, "pipeline_fallback missing")


def check_planner(results: list[CheckResult]) -> None:
    text = read_rel("scripts/pipeline_planner_agent.py")
    ok, missing = contains_all(text, ["plan_pipeline", "pipeline_manifest", "default_minimal_pipeline_manifest"])
    add(results, "pipeline planner exists with fallback", ok, ", ".join(missing))
    forbidden = [item for item in [".write_text(", "write_file", "LocalAgentActionExecutor"] if item in function_body(text, "plan_pipeline")]
    add(results, "pipeline planner does not directly write project files", not forbidden, ", ".join(forbidden))


def check_manifest(results: list[CheckResult]) -> None:
    text = read_rel("scripts/pipeline_manifest.py")
    ok, missing = contains_all(
        text,
        [
            "validate_pipeline_manifest",
            "normalize_pipeline_manifest",
            "default_minimal_pipeline_manifest",
            "ALLOWED_STEP_TYPES",
            "steps[{index}].type is not allowed",
        ],
    )
    add(results, "pipeline manifest validates allowed step types", ok, ", ".join(missing))


def check_runner(results: list[CheckResult]) -> None:
    text = read_rel("scripts/dynamic_pipeline_runner.py")
    ok, missing = contains_all(
        text,
        [
            "run_dynamic_pipeline",
            "pipeline_manifest",
            "pipeline_step_result",
            "package_project",
            "local_agent_actions.LocalAgentActionExecutor",
        ],
    )
    add(results, "dynamic runner interprets manifest through local actions", ok, ", ".join(missing))
    forbidden = [item for item in ["exec(", "eval(", "compile("] if item in text]
    add(results, "dynamic runner does not expose arbitrary Python execution", not forbidden, ", ".join(forbidden))


def check_local_actions(results: list[CheckResult]) -> None:
    text = read_rel("scripts/local_agent_actions.py")
    ok, missing = contains_all(
        text,
        ["write_file", "read_file", "list_files", "run_command", "package_project", "search_skills", "use_skill", "propose_skill", "_project_path", "_inside"],
    )
    add(results, "local agent actions keep tool and path boundary", ok, ", ".join(missing))


def check_packager(results: list[CheckResult]) -> None:
    text = read_rel("scripts/local_packager.py")
    ok, missing = contains_all(text, ["package_project", "final_project_bundle.zip", "delivery_manifest.json"])
    add(results, "local packager remains delivery exit", ok, ", ".join(missing))


def run_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    for checker in (check_telegram, check_planner, check_manifest, check_runner, check_local_actions, check_packager):
        try:
            checker(results)
        except Exception as exc:
            add(results, checker.__name__, False, str(exc))
    return results


def main() -> int:
    results = run_checks()
    overall = all(result.ok for result in results)
    print("PASS" if overall else "FAIL")
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        suffix = f" - {result.detail}" if result.detail else ""
        print(f"{status}: {result.name}{suffix}")
    if not overall:
        missing = [result.name for result in results if not result.ok]
        print("Missing or broken checks:")
        for name in missing:
            print(f"- {name}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
