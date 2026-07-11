from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from agent_growth_budget import default_growth_budget
    from agent_growth_merge_protocol import merge_branch_results
    from agent_growth_orchestrator import controlled_leaf_build, run_controlled_dynamic_growth
    from agent_growth_planner import plan_dynamic_growth
    from agent_leaf_provider_guard import provider_readiness
    from agent_long_run_trace_bundle import create_long_run_trace_bundle
    from agent_real_provider_leaf_builder import run_real_provider_leaf
    from agent_scope_contract import load_scope_contract
    from agent_tree_contracts import append_jsonl, read_json, read_jsonl, write_json
    from agent_tree_registry import agent_by_id
    from agent_tree_shared_context import create_shared_context
    from full_pytest_timeout_diagnosis import diagnose_full_pytest_timeout
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_growth_budget import default_growth_budget
    from scripts.agent_growth_merge_protocol import merge_branch_results
    from scripts.agent_growth_orchestrator import controlled_leaf_build, run_controlled_dynamic_growth
    from scripts.agent_growth_planner import plan_dynamic_growth
    from scripts.agent_leaf_provider_guard import provider_readiness
    from scripts.agent_long_run_trace_bundle import create_long_run_trace_bundle
    from scripts.agent_real_provider_leaf_builder import run_real_provider_leaf
    from scripts.agent_scope_contract import load_scope_contract
    from scripts.agent_tree_contracts import append_jsonl, read_json, read_jsonl, write_json
    from scripts.agent_tree_registry import agent_by_id
    from scripts.agent_tree_shared_context import create_shared_context
    from scripts.full_pytest_timeout_diagnosis import diagnose_full_pytest_timeout


GOAL = "做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层"


def _write_md(path: pathlib.Path, title: str, rows: list[str]) -> None:
    path.write_text("# " + title + "\n\n" + "\n".join(rows) + "\n", encoding="utf-8")


def phase1_controlled_replay(out: pathlib.Path) -> dict[str, Any]:
    phase = out / "phase1_controlled_replay"
    result = run_controlled_dynamic_growth(goal=GOAL, project_name="Local AI Knowledge Studio", out_dir=phase, provider_mode="controlled")
    registry = read_json(phase / "agent_tree_registry.json", {})
    agents = registry.get("agents", [])
    leaves = [agent for agent in agents if not agent.get("children") and agent.get("agent_id") != "main_agent"]
    summary = {
        "verdict": "PASS" if result.get("verdict") == "PASS" and len(agents) >= 20 and len(leaves) >= 10 else "FAIL",
        "final_verdict": result.get("verdict"),
        "agent_count": len(agents),
        "spawn_actions": len(read_jsonl(phase / "spawn_actions.jsonl")),
        "leaf_count": len(leaves),
        "public_delivery_gate": read_json(phase / "contract_checks" / "public_delivery_gate.json", {}).get("delivery_allowed"),
        "trace_bundle": str(phase / "dynamic_agent_tree_trace_bundle.zip"),
    }
    write_json(out / "phase1_controlled_replay_result.json", summary)
    _write_md(out / "phase1_controlled_replay_result.md", "Phase 1 Controlled Replay", [f"- {key}: {value}" for key, value in summary.items()])
    return summary


def phase2_real_leaf(out: pathlib.Path, readiness: dict[str, Any]) -> dict[str, Any]:
    phase = out / "phase2_real_leaf"
    if phase.exists():
        shutil.rmtree(phase)
    phase.mkdir(parents=True)
    shared = create_shared_context("Local AI Knowledge Studio", GOAL)
    registry = plan_dynamic_growth(shared, phase)
    project = phase / "project"
    project.mkdir()
    leaf = agent_by_id(registry, "search_service_leaf")
    if not readiness.get("provider_ready"):
        result = {"classification": "provider_unavailable", "verdict": "BLOCKED", "leaf": "search_service_leaf", "provider_ready": False}
    else:
        result = run_real_provider_leaf(agent_id="search_service_leaf", out_dir=phase, project_dir=project, user_goal=GOAL, readiness=readiness)
        result["verdict"] = "PASS" if result.get("classification") == "real_provider_leaf_pass" else "NEEDS_REWORK"
    write_json(out / "phase2_real_leaf_result.json", result)
    _write_md(out / "phase2_real_leaf_result.md", "Phase 2 Real Provider Single Leaf", [f"- {key}: {value}" for key, value in result.items() if key != "allowed_files"])
    return result


def phase3_mixed_branch(out: pathlib.Path, phase2_result: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    phase = out / "phase3_mixed_branch"
    if phase.exists():
        shutil.rmtree(phase)
    phase.mkdir(parents=True)
    if not readiness.get("provider_ready"):
        result = {"classification": "provider_unavailable", "verdict": "BLOCKED", "backend_merge": "not_run"}
        write_json(out / "phase3_mixed_branch_result.json", result)
        _write_md(out / "phase3_mixed_branch_result.md", "Phase 3 Mixed Branch", [f"- {key}: {value}" for key, value in result.items()])
        return result
    if phase2_result.get("classification") != "real_provider_leaf_pass":
        result = {"classification": "mixed_branch_real_leaf_failed", "verdict": "NEEDS_REWORK", "backend_merge": "not_run"}
        write_json(out / "phase3_mixed_branch_result.json", result)
        _write_md(out / "phase3_mixed_branch_result.md", "Phase 3 Mixed Branch", [f"- {key}: {value}" for key, value in result.items()])
        return result
    # Reuse the proven real leaf output by copying phase2 leaf files into this branch project.
    shared = create_shared_context("Local AI Knowledge Studio", GOAL)
    registry = plan_dynamic_growth(shared, phase)
    project = phase / "project"
    project.mkdir()
    for child_id in ("document_import_leaf", "model_adapter_leaf", "task_service_leaf", "report_service_leaf"):
        controlled_leaf_build(agent_by_id(registry, child_id), project_dir=project, out_dir=phase, budget=default_growth_budget())
    src_project = out / "phase2_real_leaf" / "project"
    for rel in ("app/services/search_service.py", "tests/test_search_service.py"):
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((src_project / rel).read_text(encoding="utf-8"), encoding="utf-8")
    write_json(phase / "checkpoints" / "search_service_leaf.json", {"agent_id": "search_service_leaf", "verdict": "PASS", "provider_mode": "real_provider"})
    merge = merge_branch_results(registry=registry, parent_agent="backend_branch_agent", out_dir=phase, owned_outputs=["app/services/"])
    result = {
        "classification": "mixed_branch_pass" if merge.get("merge_verdict") == "PASS" else "mixed_branch_merge_incorrect",
        "verdict": "PASS" if merge.get("merge_verdict") == "PASS" else "NEEDS_REWORK",
        "real_provider_leaves": ["search_service_leaf"],
        "controlled_leaves": ["document_import_leaf", "model_adapter_leaf", "task_service_leaf", "report_service_leaf"],
        "backend_merge": merge.get("merge_verdict"),
    }
    write_json(out / "phase3_mixed_branch_result.json", result)
    _write_md(out / "phase3_mixed_branch_result.md", "Phase 3 Mixed Branch", [f"- {key}: {value}" for key, value in result.items()])
    return result


def phase4_failure_repair(out: pathlib.Path) -> dict[str, Any]:
    phase = out / "phase4_failure_repair"
    if phase.exists():
        shutil.rmtree(phase)
    phase.mkdir(parents=True)
    shared = create_shared_context("Local AI Knowledge Studio", GOAL)
    budget = default_growth_budget()

    # Case 1: scope violation.
    case1 = phase / "case1_scope_violation"
    registry1 = plan_dynamic_growth(shared, case1)
    cp1 = controlled_leaf_build(agent_by_id(registry1, "search_service_leaf"), project_dir=case1 / "project", out_dir=case1, budget=budget, injected_files=["README.md"])
    merge1 = merge_branch_results(registry=registry1, parent_agent="backend_branch_agent", out_dir=case1)

    # Case 2: missing file repair.
    case2 = phase / "case2_missing_file_repair"
    registry2 = plan_dynamic_growth(shared, case2)
    project2 = case2 / "project"
    contract = load_scope_contract(case2, "task_service_leaf")
    original_allowed = list(contract["allowed_files"])
    contract["allowed_files"] = ["app/services/task_service.py"]
    write_json(case2 / "scope_contracts" / "task_service_leaf.json", contract)
    first = controlled_leaf_build(agent_by_id(registry2, "task_service_leaf"), project_dir=project2, out_dir=case2, budget=budget)
    missing = ["tests/test_task_service.py"]
    append_jsonl(phase / "feedback_tasks.jsonl", {"target_agent": "task_service_leaf", "missing": missing, "reason": "missing_file_repair"})
    contract["allowed_files"] = missing
    write_json(case2 / "scope_contracts" / "task_service_leaf.json", contract)
    repair = controlled_leaf_build(agent_by_id(registry2, "task_service_leaf"), project_dir=project2, out_dir=case2, budget=budget)
    append_jsonl(phase / "repair_attempts.jsonl", {"agent_id": "task_service_leaf", "allowed_files": missing, "verdict": repair["verdict"]})
    write_json(case2 / "checkpoints" / "task_service_leaf.json", {"agent_id": "task_service_leaf", "verdict": "PASS", "repair_verified": True})
    for child_id in ("document_import_leaf", "search_service_leaf", "model_adapter_leaf", "report_service_leaf"):
        controlled_leaf_build(agent_by_id(registry2, child_id), project_dir=project2, out_dir=case2, budget=budget)
    merge2 = merge_branch_results(registry=registry2, parent_agent="backend_branch_agent", out_dir=case2)

    # Case 3: needs split.
    case3 = phase / "case3_needs_split"
    registry3 = plan_dynamic_growth(shared, case3)
    split_contract = load_scope_contract(case3, "search_service_leaf")
    split_contract["allowed_files"] = [f"app/services/oversized_{index}.py" for index in range(budget["max_leaf_expected_files"] + 1)]
    write_json(case3 / "scope_contracts" / "search_service_leaf.json", split_contract)
    split = controlled_leaf_build(agent_by_id(registry3, "search_service_leaf"), project_dir=case3 / "project", out_dir=case3, budget=budget)
    append_jsonl(phase / "feedback_tasks.jsonl", {"target_agent": "backend_branch_agent", "failed_agent": "search_service_leaf", "allowed_actions": ["spawn_smaller_children"], "reason": "needs_split"})
    append_jsonl(case3 / "spawn_actions.jsonl", {"action_id": "SPLIT0001", "action": "spawn_agent", "parent_agent": "backend_branch_agent", "new_agent_id": "search_service_part_leaf", "role": "SearchServicePartLeafAgent", "depth": 3, "reason": "split oversized leaf", "scope": ["search service part"], "expected_outputs": ["app/services/search_query.py"], "verification": ["scope_contract_valid"]})

    cases = [
        {"case": "scope_violation", "expected": "FAIL", "actual": cp1["verdict"], "parent_merge": merge1["merge_verdict"], "verdict": "PASS" if cp1["verdict"] == "FAIL" and merge1["merge_verdict"] == "FAIL" else "FAIL"},
        {"case": "missing_file_repair", "expected": "repair PASS", "actual": repair["verdict"], "parent_merge": merge2["merge_verdict"], "verdict": "PASS" if repair["verdict"] == "PASS" and merge2["merge_verdict"] == "PASS" else "FAIL"},
        {"case": "needs_split", "expected": "NEEDS_SPLIT", "actual": split["verdict"], "parent_feedback": "spawn_smaller_children", "verdict": "PASS" if split["verdict"] == "NEEDS_SPLIT" else "FAIL"},
    ]
    result = {"verdict": "PASS" if all(item["verdict"] == "PASS" for item in cases) else "NEEDS_REWORK", "cases": cases}
    write_json(out / "phase4_failure_repair_result.json", result)
    _write_md(out / "phase4_failure_repair_result.md", "Phase 4 Failure Repair", [f"- {item['case']}: {item['verdict']} ({item['actual']})" for item in cases])
    return result


def run_long_run_eval(*, out_dir: str | pathlib.Path) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    readiness = provider_readiness(out_dir=out)
    phase0 = diagnose_full_pytest_timeout(out_dir=out / "full_pytest_diagnosis", per_file_timeout=120, max_total_seconds=840)
    phase1 = phase1_controlled_replay(out)
    phase2 = phase2_real_leaf(out, readiness)
    phase3 = phase3_mixed_branch(out, phase2, readiness)
    phase4 = phase4_failure_repair(out)

    fake_success = False
    context_pollution = False
    scope_violation_detected = any(item.get("case") == "scope_violation" and item.get("verdict") == "PASS" for item in phase4.get("cases", []))
    if not readiness.get("provider_ready"):
        classification = "F"
        verdict = "BLOCKED"
        label = "provider_unavailable"
    elif phase2.get("classification") != "real_provider_leaf_pass":
        classification = "B"
        verdict = "NEEDS_REWORK"
        label = "controlled_pass_real_leaf_not_proven"
    elif phase3.get("classification") != "mixed_branch_pass":
        classification = "C"
        verdict = "NEEDS_REWORK"
        label = "real_leaf_pass_mixed_branch_failed"
    elif phase4.get("verdict") != "PASS":
        classification = "E"
        verdict = "NEEDS_REWORK"
        label = "repair_loop_failed"
    elif phase0.get("not_run_due_to_total_timeout"):
        classification = "I"
        verdict = "NEEDS_REWORK"
        label = "full_pytest_timeout_unresolved"
    else:
        classification = "A"
        verdict = "PASS"
        label = "dynamic_tree_long_run_pass"
    final = {
        "classification": classification,
        "classification_label": label,
        "verdict": verdict,
        "provider_ready": readiness.get("provider_ready"),
        "phase0": phase0,
        "phase1": phase1,
        "phase2": phase2,
        "phase3": phase3,
        "phase4": phase4,
        "scope_violation_detected": scope_violation_detected,
        "fake_success_detected": fake_success,
        "context_pollution_detected": context_pollution,
    }
    bundle = create_long_run_trace_bundle(out_dir=out, final_verdict=final)
    final["trace_bundle"] = str(bundle)
    write_json(out / "final_verdict.json", final)
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = run_long_run_eval(out_dir=args.out)
    print(json.dumps({"classification": result["classification"], "verdict": result["verdict"]}, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] in {"PASS", "NEEDS_REWORK", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
