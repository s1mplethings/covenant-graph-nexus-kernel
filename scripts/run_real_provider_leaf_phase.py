from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

try:
    import acceptance_verifier
except ModuleNotFoundError:  # pragma: no cover
    from scripts import acceptance_verifier  # type: ignore

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from agent_growth_planner import plan_dynamic_growth
    from agent_leaf_provider_guard import provider_readiness
    from agent_real_provider_leaf_builder import run_real_provider_leaf
    from agent_tree_contracts import read_json, write_json
    from agent_tree_shared_context import create_shared_context
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_growth_planner import plan_dynamic_growth
    from scripts.agent_leaf_provider_guard import provider_readiness
    from scripts.agent_real_provider_leaf_builder import run_real_provider_leaf
    from scripts.agent_tree_contracts import read_json, write_json
    from scripts.agent_tree_shared_context import create_shared_context


DEFAULT_GOAL = "做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层"


def run_leaf_phase(
    *,
    leaf: str,
    out_dir: str | pathlib.Path,
    project_name: str,
    goal: str = DEFAULT_GOAL,
    model: str = "gpt-5.4-nano",
    readiness_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    project = out / "project"
    project.mkdir(parents=True, exist_ok=True)
    shared = create_shared_context(project_name, goal)
    plan_dynamic_growth(shared, out)
    readiness = readiness_override if isinstance(readiness_override, dict) else provider_readiness(out_dir=out, model=model)
    if not readiness.get("provider_ready"):
        result = {
            "leaf": leaf,
            "provider_ready": False,
            "classification": "provider_unavailable",
            "verdict": "BLOCKED",
            "fake_success_detected": False,
            "provider_called": False,
            "project_files_created": len([p for p in project.rglob("*") if p.is_file()]),
            "message": "生成接口当前不可用或额度不足，真实 provider leaf 未运行。",
        }
        write_json(out / f"checkpoint_{leaf}.json", result)
        acceptance_verifier.write_canonical_verdict(out / "final_verdict.json", result)
        return result

    result = run_real_provider_leaf(agent_id=leaf, out_dir=out, project_dir=project, user_goal=goal, model=model, readiness=readiness)
    if result.get("classification") == "real_provider_leaf_pass":
        test_result = read_json(out / "test_execution_result.json", {})
        write_json(out / "test_execution.json", test_result)
        report = [
            "# Leaf Test Report",
            "",
            f"commands_run:",
            f"- {test_result.get('command', '')}",
            "",
            f"exit_code: {test_result.get('exit_code')}",
            "",
            f"verdict: {'PASS' if test_result.get('exit_code') == 0 else 'FAIL'}",
        ]
        (out / "TEST_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    final = {
        "leaf": leaf,
        "provider_ready": True,
        "classification": result.get("classification"),
        "verdict": result.get("verdict"),
        "checkpoint": result.get("checkpoint"),
        "fake_success_detected": False,
        "scope_enforcement": read_json(out / "scope_enforcement_result.json", {}),
        "written_files": result.get("written_files", []),
        "forbidden_write_attempts": result.get("forbidden_write_attempts", []),
        "harness_scaffold_files": result.get("harness_scaffold_files", []),
    }
    acceptance_verifier.write_canonical_verdict(out / "final_verdict.json", final)
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leaf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument("--model", default="gpt-5.4-nano")
    args = parser.parse_args()
    result = run_leaf_phase(leaf=args.leaf, out_dir=args.out, project_name=args.project_name, goal=args.goal, model=args.model)
    print(json.dumps({"classification": result["classification"], "verdict": result["verdict"]}, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] in {"PASS", "NEEDS_REWORK", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
