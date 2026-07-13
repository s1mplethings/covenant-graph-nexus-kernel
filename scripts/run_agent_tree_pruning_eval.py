from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Any

try:
    import acceptance_verifier
except ModuleNotFoundError:  # pragma: no cover
    from scripts import acceptance_verifier  # type: ignore

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_branch_replanner import replan_branch
from scripts.agent_growth_feedback_router import create_growth_feedback_task
from scripts.agent_growth_merge_protocol import merge_branch_results
from scripts.agent_leaf_failure_classifier import classify_leaf_failure
from scripts.agent_leaf_scope_enforcer import enforce_leaf_scope
from scripts.agent_pruning_policy import decide_pruning
from scripts.agent_pruning_protocol import record_pruning_event
from scripts.agent_pruning_trace_bundle import create_pruning_trace_bundle
from scripts.agent_scope_contract import create_scope_contract, save_scope_contract
from scripts.agent_tree_contracts import append_jsonl, read_jsonl, write_json
from scripts.agent_tree_registry import add_agent, agent_by_id, initial_registry, save_registry
from scripts.agent_upward_pruning_router import route_pruning_event


DEFAULT_OUT = ROOT / "generated" / "agent_tree_pruning_eval" / "run_001"


def _repo_state() -> dict[str, str]:
    def git(*args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        return (proc.stdout or proc.stderr).strip()

    return {
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "--short", "HEAD"),
        "worktree": "dirty" if git("status", "--porcelain") else "clean",
    }


def _profile_results(parent: pathlib.Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for profile in ("quick", "regression", "provider"):
        path = parent / "test_profiles" / f"{profile}_result.json"
        if path.exists():
            results[profile] = json.loads(path.read_text(encoding="utf-8"))
    return results


def _spawn(registry: dict[str, Any], parent: str, agent_id: str, role: str, scope: list[str]) -> None:
    parent_agent = agent_by_id(registry, parent)
    depth = int(parent_agent.get("depth", 0)) + 1
    add_agent(
        registry,
        {
            "action_id": f"EVAL-{len(registry['agents']):04d}",
            "parent_agent": parent,
            "new_agent_id": agent_id,
            "role": role,
            "depth": depth,
            "scope": scope,
        },
    )


def _classify(out: pathlib.Path, payload: dict[str, Any]) -> dict[str, Any]:
    result = classify_leaf_failure(payload)
    append_jsonl(out / "failure_classifications.jsonl", result)
    return result


def _prune_and_replan(
    *,
    out: pathlib.Path,
    registry: dict[str, Any],
    classification: dict[str, Any],
    policy: dict[str, Any],
    parent: str,
    evidence: list[str],
    action: str,
    new_leaf_id: str | None = None,
    new_children: list[str] | None = None,
    scope: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    event = record_pruning_event(
        out_dir=out,
        leaf_id=str(classification["leaf_id"]),
        parent_agent=parent,
        classification=classification,
        policy=policy,
        evidence_refs=evidence,
    )
    signal = route_pruning_event(
        out_dir=out,
        event=event,
        requested_parent_action=policy["next_action"],
    )
    replan = replan_branch(
        out_dir=out,
        registry=registry,
        signal=signal,
        action=action,
        new_leaf_id=new_leaf_id,
        new_children=new_children,
        scope=scope,
        reason=policy["reason"],
    )
    return event, signal, replan


def run_eval(out_dir: str | pathlib.Path = DEFAULT_OUT) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for directory in ("checkpoints", "merge_results", "test_execution", "scope_contracts"):
        (out / directory).mkdir(parents=True, exist_ok=True)
    for filename in (
        "failure_classifications.jsonl",
        "pruning_events.jsonl",
        "upward_signals.jsonl",
        "branch_replans.jsonl",
        "feedback_tasks.jsonl",
    ):
        (out / filename).write_text("", encoding="utf-8")

    registry = initial_registry()
    branch_specs = [
        ("backend_branch_agent", "BackendBranchAgent"),
        ("scope_branch_agent", "BackendBranchAgent"),
        ("report_branch_agent", "BackendBranchAgent"),
        ("model_branch_agent", "BackendBranchAgent"),
        ("trust_branch_agent", "QualityBranchAgent"),
    ]
    for branch, role in branch_specs:
        _spawn(registry, "main_agent", branch, role, [])
    leaf_specs = [
        ("backend_branch_agent", "task_service_leaf", ["app/services/task_service.py", "tests/test_task_service.py"]),
        ("scope_branch_agent", "search_service_leaf", ["app/services/search_service.py", "tests/test_search_service.py"]),
        ("report_branch_agent", "report_service_leaf", ["app/services/report_service.py"]),
        ("model_branch_agent", "model_adapter_leaf", ["app/services/model_adapter.py"]),
        ("trust_branch_agent", "fake_success_leaf", ["tests/test_claim.py"]),
    ]
    for parent, leaf, scope in leaf_specs:
        _spawn(registry, parent, leaf, "ControlledLeafAgent", scope)
        save_scope_contract(
            create_scope_contract(agent_id=leaf, role="ControlledLeafAgent", parent_id=parent, allowed_files=scope),
            out,
        )
    save_registry(registry, out, "agent_tree_registry_before.json")

    cases: list[dict[str, Any]] = []

    # T1: first missing-file failure repairs in place; the repeated failure is pruned.
    task_checkpoint = {
        "agent_id": "task_service_leaf",
        "verdict": "FAIL",
        "missing_files": ["tests/test_task_service.py"],
    }
    write_json(out / "checkpoints" / "task_service_leaf.json", task_checkpoint)
    first = _classify(
        out,
        {"leaf_id": "task_service_leaf", "checkpoint": task_checkpoint, "repair_attempts": 1},
    )
    first_policy = decide_pruning(first, parent_agent="backend_branch_agent")
    create_growth_feedback_task(
        out_dir=out,
        target_agent="task_service_leaf",
        failed_agent="task_service_leaf",
        reason=first["reason"],
    )
    second = _classify(
        out,
        {"leaf_id": "task_service_leaf", "checkpoint": task_checkpoint, "repair_attempts": 2},
    )
    second_policy = decide_pruning(second, parent_agent="backend_branch_agent")
    task_event, task_signal, task_replan = _prune_and_replan(
        out=out,
        registry=registry,
        classification=second,
        policy=second_policy,
        parent="backend_branch_agent",
        evidence=["checkpoints/task_service_leaf.json"],
        action="spawn_replacement_leaf",
        new_leaf_id="task_service_leaf_v2",
        scope=["app/services/task_service.py", "tests/test_task_service.py"],
    )
    write_json(
        out / "checkpoints" / "task_service_leaf_v2.json",
        {"agent_id": "task_service_leaf_v2", "verdict": "PASS", "missing_files": []},
    )
    replacement_merge = merge_branch_results(
        registry=registry,
        parent_agent="backend_branch_agent",
        out_dir=out,
    )
    cases.append(
        {
            "case": "missing_file_repair_then_prune",
            "leaf": "task_service_leaf",
            "failure": "missing_files",
            "decision": f"{first_policy['decision']} -> {second_policy['decision']}",
            "parent_action": task_replan["action"],
            "verdict": "PASS"
            if first_policy["decision"] == "REPAIR"
            and second_policy["decision"] == "PRUNE"
            and replacement_merge["merge_verdict"] == "PASS"
            else "FAIL",
        }
    )

    # T2: scope violation is blocked before the forbidden file is written.
    scope_contract = create_scope_contract(
        agent_id="search_service_leaf",
        role="ControlledLeafAgent",
        parent_id="scope_branch_agent",
        allowed_files=["app/services/search_service.py", "tests/test_search_service.py"],
    )
    scope_result = enforce_leaf_scope(
        contract=scope_contract,
        candidate_files={"README.md": "forbidden"},
        project_dir=out / "scope_project",
        out_dir=out / "scope_evidence",
    )
    scope_checkpoint = {"agent_id": "search_service_leaf", "verdict": "FAIL", "issues": ["scope_violation"]}
    write_json(out / "checkpoints" / "search_service_leaf.json", scope_checkpoint)
    scope_class = _classify(
        out,
        {
            "leaf_id": "search_service_leaf",
            "checkpoint": scope_checkpoint,
            "scope_enforcement": scope_result,
        },
    )
    scope_policy = decide_pruning(scope_class, parent_agent="scope_branch_agent")
    _, _, scope_replan = _prune_and_replan(
        out=out,
        registry=registry,
        classification=scope_class,
        policy=scope_policy,
        parent="scope_branch_agent",
        evidence=["scope_evidence/scope_enforcement_result.json", "checkpoints/search_service_leaf.json"],
        action="spawn_replacement_leaf",
        new_leaf_id="search_service_leaf_v2",
    )
    scope_merge = merge_branch_results(registry=registry, parent_agent="scope_branch_agent", out_dir=out)
    cases.append(
        {
            "case": "scope_violation_immediate_prune",
            "leaf": "search_service_leaf",
            "failure": scope_class["failure_type"],
            "decision": scope_policy["decision"],
            "parent_action": scope_replan["action"],
            "verdict": "PASS"
            if not (out / "scope_project" / "README.md").exists()
            and scope_merge["merge_verdict"] == "FAIL"
            else "FAIL",
        }
    )

    # T3: oversized leaf is never executed and is replaced by smaller leaves.
    split_checkpoint = {"agent_id": "report_service_leaf", "verdict": "NEEDS_SPLIT", "missing_files": []}
    write_json(out / "checkpoints" / "report_service_leaf.json", split_checkpoint)
    split_class = _classify(
        out,
        {"leaf_id": "report_service_leaf", "checkpoint": split_checkpoint, "needs_split": True},
    )
    split_policy = decide_pruning(split_class, parent_agent="report_branch_agent")
    _, _, split_replan = _prune_and_replan(
        out=out,
        registry=registry,
        classification=split_class,
        policy=split_policy,
        parent="report_branch_agent",
        evidence=["checkpoints/report_service_leaf.json"],
        action="split_leaf_into_smaller_leaves",
        new_children=["report_markdown_leaf", "report_source_tracking_leaf"],
    )
    cases.append(
        {
            "case": "needs_split_prune",
            "leaf": "report_service_leaf",
            "failure": split_class["failure_type"],
            "decision": split_policy["decision"],
            "parent_action": split_replan["action"],
            "verdict": "PASS"
            if agent_by_id(registry, "report_service_leaf")["status"] == "pruned"
            and all(agent_by_id(registry, child) for child in split_replan["new_children"])
            else "FAIL",
        }
    )

    # T4: first provider outage remains blocked; repetition escalates without fake output.
    provider_status = {"provider_ready": False, "classification": "provider_unavailable"}
    provider_checkpoint = {"agent_id": "model_adapter_leaf", "verdict": "BLOCKED", "missing_files": []}
    write_json(out / "checkpoints" / "model_adapter_leaf.json", provider_checkpoint)
    provider_first = _classify(
        out,
        {
            "leaf_id": "model_adapter_leaf",
            "checkpoint": provider_checkpoint,
            "provider_status": provider_status,
            "repair_attempts": 1,
        },
    )
    provider_first_policy = decide_pruning(
        provider_first,
        parent_agent="model_branch_agent",
        consecutive_provider_failures=1,
    )
    provider_repeat = _classify(
        out,
        {
            "leaf_id": "model_adapter_leaf",
            "checkpoint": provider_checkpoint,
            "provider_status": provider_status,
            "repair_attempts": 2,
        },
    )
    provider_repeat_policy = decide_pruning(
        provider_repeat,
        parent_agent="model_branch_agent",
        consecutive_provider_failures=2,
    )
    _, _, provider_replan = _prune_and_replan(
        out=out,
        registry=registry,
        classification=provider_repeat,
        policy=provider_repeat_policy,
        parent="model_branch_agent",
        evidence=["checkpoints/model_adapter_leaf.json"],
        action="switch_leaf_provider_mode",
        new_leaf_id="model_adapter_leaf_v2",
    )
    cases.append(
        {
            "case": "provider_unavailable_upward_block",
            "leaf": "model_adapter_leaf",
            "failure": provider_repeat["failure_type"],
            "decision": f"{provider_first_policy['decision']} -> {provider_repeat_policy['decision']}",
            "parent_action": provider_replan["action"],
            "verdict": "PASS"
            if provider_first_policy["decision"] == "BLOCKED"
            and provider_repeat_policy["upward_signal"]
            and not (out / "provider_project").exists()
            else "FAIL",
        }
    )

    # T6: a PASS claim cannot override a failed checkpoint; the branch is stopped.
    fake_checkpoint = {"agent_id": "fake_success_leaf", "verdict": "FAIL", "missing_files": []}
    write_json(out / "checkpoints" / "fake_success_leaf.json", fake_checkpoint)
    fake_class = _classify(
        out,
        {
            "leaf_id": "fake_success_leaf",
            "checkpoint": fake_checkpoint,
            "delivery_status": "PASS",
        },
    )
    fake_policy = decide_pruning(fake_class, parent_agent="trust_branch_agent")
    _, fake_signal, fake_replan = _prune_and_replan(
        out=out,
        registry=registry,
        classification=fake_class,
        policy=fake_policy,
        parent="trust_branch_agent",
        evidence=["checkpoints/fake_success_leaf.json"],
        action="stop_branch",
    )
    cases.append(
        {
            "case": "fake_success_prune",
            "leaf": "fake_success_leaf",
            "failure": fake_class["failure_type"],
            "decision": fake_policy["decision"],
            "parent_action": fake_replan["action"],
            "verdict": "PASS"
            if agent_by_id(registry, "trust_branch_agent")["status"] == "blocked"
            and "delivery" in fake_signal["blocked_downstream"]
            else "FAIL",
        }
    )

    save_registry(registry, out, "agent_tree_registry_after.json")
    events = read_jsonl(out / "pruning_events.jsonl")
    signals = read_jsonl(out / "upward_signals.jsonl")
    replans = read_jsonl(out / "branch_replans.jsonl")
    pruned = [agent for agent in registry["agents"] if agent.get("status") == "pruned"]
    replacements = [agent for agent in registry["agents"] if agent.get("replaces")]
    downstream = sorted({item for signal in signals for item in signal.get("blocked_downstream", [])})
    verdict = "PASS" if all(case["verdict"] == "PASS" for case in cases) and len(events) == 5 else "NEEDS_REWORK"
    final = {
        "classification": "control_path_proven" if verdict == "PASS" else "control_path_not_proven",
        "verdict": verdict,
        "pruned_leaves": [agent["agent_id"] for agent in pruned],
        "replacement_leaves": [agent["agent_id"] for agent in replacements],
        "event_count": len(events),
        "upward_signal_count": len(signals),
        "branch_replan_count": len(replans),
        "replacement_merge_verdict": replacement_merge["merge_verdict"],
        "downstream_blocked": downstream,
        "telegram_mainline": "not_connected",
        "delivery_executed": False,
    }
    acceptance_verifier.write_canonical_verdict(out / "final_verdict.json", final)
    index = _render_index(cases, final, events, replans)
    (out / "00_INDEX.md").write_text(index, encoding="utf-8")
    bundle = create_pruning_trace_bundle(
        out,
        out.parent / "agent_tree_pruning_trace_bundle.zip",
    )
    report = {
        "repo": _repo_state(),
        "cases": cases,
        "registry_changes": {
            "pruned_leaves": final["pruned_leaves"],
            "replacement_leaves": final["replacement_leaves"],
            "split_leaves": split_replan["new_children"],
            "blocked_branches": ["trust_branch_agent"],
        },
        "downstream_blocking": downstream,
        "replacement_merge": {
            "original_leaf": "task_service_leaf",
            "replacement_leaf": "task_service_leaf_v2",
            "verdict": replacement_merge["merge_verdict"],
            "excluded_children": replacement_merge["excluded_children"],
        },
        "trace_bundle": bundle,
        "test_results": _profile_results(out.parent),
        "verdict": verdict,
    }
    write_json(out.parent / "pruning_report.json", report)
    (out.parent / "pruning_report.md").write_text(_render_report(report), encoding="utf-8")
    acceptance_verifier.write_canonical_verdict(out.parent / "final_verdict.json", final)
    return report


def _render_index(
    cases: list[dict[str, Any]],
    final: dict[str, Any],
    events: list[dict[str, Any]],
    replans: list[dict[str, Any]],
) -> str:
    lines = [
        "# Agent Tree Pruning Trace",
        "",
        "This bundle preserves failed leaf evidence; pruning never deletes or rewrites the original checkpoint.",
        "",
        "## Pruned Leaves",
    ]
    replan_by_leaf = {item["failed_leaf"]: item for item in replans}
    for event in events:
        replan = replan_by_leaf.get(event["leaf_id"], {})
        replacement = replan.get("new_leaf_id") or ", ".join(replan.get("new_children", [])) or "none"
        lines.append(
            f"- {event['leaf_id']}: {event['failure_type']}; parent action={replan.get('action', 'none')}; replacement={replacement}"
        )
    lines.extend(
        [
            "",
            "## Downstream Blocking",
            *[f"- {item}" for item in final["downstream_blocked"]],
            "",
            "## Eval Cases",
            *[f"- {case['case']}: {case['verdict']}" for case in cases],
            "",
            f"## Final Verdict\n\n{final['verdict']}",
            "",
        ]
    )
    return "\n".join(lines)


def _render_report(report: dict[str, Any]) -> str:
    repo = report["repo"]
    lines = [
        "# Agent Tree Upward Pruning 报告",
        "",
        "## Repo 状态",
        f"- Branch: {repo['branch']}",
        f"- HEAD: {repo['head']}",
        f"- Worktree: {repo['worktree']}",
        "",
        "## Pruning Policy",
        "| Failure Type | Decision | Upward Signal | Parent Action |",
        "|---|---|---|---|",
        "| missing_files/test_failed | REPAIR, then PRUNE | after repeated failure | replacement leaf |",
        "| scope_violation | PRUNE | yes | replacement leaf |",
        "| needs_split | SPLIT | yes | smaller leaves |",
        "| provider_unavailable | BLOCKED, then PRUNE | after repetition | switch or delay |",
        "| fake_success_detected | PRUNE | yes | stop branch |",
        "",
        "## Eval Cases",
        "| Case | Leaf | Failure | Decision | Parent Action | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['case']} | {case['leaf']} | {case['failure']} | {case['decision']} | {case['parent_action']} | {case['verdict']} |"
        )
    changes = report["registry_changes"]
    merge = report["replacement_merge"]
    bundle = report["trace_bundle"]
    lines.extend(
        [
            "",
            "## Registry Changes",
            f"- pruned leaves: {', '.join(changes['pruned_leaves'])}",
            f"- replacement leaves: {', '.join(changes['replacement_leaves'])}",
            f"- split leaves: {', '.join(changes['split_leaves'])}",
            f"- blocked branches: {', '.join(changes['blocked_branches'])}",
            "",
            "## Downstream Blocking",
            *[f"- {item}" for item in report["downstream_blocking"]],
            "",
            "## Replacement Merge",
            f"- original leaf: {merge['original_leaf']}",
            f"- replacement leaf: {merge['replacement_leaf']}",
            f"- merge verdict: {merge['verdict']}",
            "",
            "## Trace Bundle",
            f"- path: {bundle['path']}",
            f"- size: {bundle.get('size_bytes', 0)} bytes",
            f"- sections: {', '.join(bundle.get('sections', []))}",
            "",
            "## Test Results",
            *[
                f"- {name}: {result.get('status')} ({result.get('stdout_tail', '').strip().splitlines()[-1] if result.get('stdout_tail', '').strip() else result.get('classification')})"
                for name, result in report["test_results"].items()
            ],
            "",
            f"## Verdict\n\n{report['verdict']}",
            "",
            "## Next Steps",
            "1. Exercise replacement generation with a stable real provider.",
            "2. Keep pruning in the experimental Dynamic Agent Tree lane.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    report = run_eval(args.out)
    print(json.dumps({"verdict": report["verdict"], "trace_bundle": report["trace_bundle"]}, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
