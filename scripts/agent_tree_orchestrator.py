from __future__ import annotations

import argparse
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
    from agent_tree_action_protocol import AgentActionRecorder, validate_action_log
    from agent_tree_checkpoint import run_checkpoint
    from agent_tree_context_reducer import reduce_context, save_local_context
    from agent_tree_contracts import DEFAULT_EVAL_DIR, now, read_json, write_json
    from agent_tree_feedback_router import create_feedback_task
    from agent_tree_goal_alignment import evaluate_goal_alignment
    from agent_tree_leaf_builder import build_controlled_stage
    from agent_tree_planner import build_agent_tree_dag, can_execute_stage, save_build_dag
    from agent_tree_shared_context import create_shared_context, save_shared_context
    from agent_tree_trace_bundle import create_trace_bundle
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_action_protocol import AgentActionRecorder, validate_action_log
    from scripts.agent_tree_checkpoint import run_checkpoint
    from scripts.agent_tree_context_reducer import reduce_context, save_local_context
    from scripts.agent_tree_contracts import DEFAULT_EVAL_DIR, now, read_json, write_json
    from scripts.agent_tree_feedback_router import create_feedback_task
    from scripts.agent_tree_goal_alignment import evaluate_goal_alignment
    from scripts.agent_tree_leaf_builder import build_controlled_stage
    from scripts.agent_tree_planner import build_agent_tree_dag, can_execute_stage, save_build_dag
    from scripts.agent_tree_shared_context import create_shared_context, save_shared_context
    from scripts.agent_tree_trace_bundle import create_trace_bundle

import telegram_live_bridge


def _next_stage_ids(dag: dict[str, Any], stage_id: str) -> list[str]:
    result: list[str] = []
    for stage in dag.get("stages", []):
        if stage_id in stage.get("depends_on", []):
            result.append(str(stage["id"]))
    return result


def _write_public_gate(project_dir: pathlib.Path, out_dir: pathlib.Path, manifest: dict[str, Any], shared_context: dict[str, Any]) -> dict[str, Any]:
    session = {
        "messages": [{"role": "user", "text": shared_context["user_goal"]}],
        "whiteboard": {
            "project_summary": shared_context["user_goal"],
            "target_project_architecture": shared_context["target_project_model"],
            "delivery_requirements": ["project package"],
            "acceptance_criteria": shared_context.get("acceptance_contract", []),
        },
    }
    gate = telegram_live_bridge.evaluate_public_delivery_gate(project_dir, manifest, session, phase="final")
    write_json(out_dir / "contract_checks" / "public_delivery_gate.json", gate)
    return gate


def run_controlled_agent_tree(
    *,
    goal: str,
    project_name: str,
    out_dir: str | pathlib.Path = DEFAULT_EVAL_DIR,
    provider_mode: str = "controlled",
) -> dict[str, Any]:
    if provider_mode != "controlled":
        raise ValueError("only controlled provider mode is supported in this lane")
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "agent_actions.jsonl").write_text("", encoding="utf-8")
    (out / "feedback_tasks.jsonl").write_text("", encoding="utf-8")
    project = out / "generated_project"
    project.mkdir(parents=True, exist_ok=True)

    shared_context = create_shared_context(project_name, goal)
    save_shared_context(shared_context, out)

    clean_plan = "document import + knowledge base + search + reports + tasks + local model adapter"
    alignment = evaluate_goal_alignment(shared_context, clean_plan)
    write_json(out / "goal_alignment.json", alignment)
    if alignment["verdict"] != "PASS":
        verdict = {"verdict": "FAIL", "reason": "goal_alignment_failed", "created_at": now()}
        bundle = create_trace_bundle(out_dir=out, project_dir=project, final_verdict=verdict)
        verdict["trace_bundle"] = str(bundle)
        return verdict

    dag = build_agent_tree_dag(shared_context)
    save_build_dag(dag, out)
    recorder = AgentActionRecorder(out)
    checkpoints: dict[str, dict[str, Any]] = {}
    stage_results: list[dict[str, Any]] = []

    raw_context = goal + " + 视频素材 + 鉴挂判别 + 背景立绘 + 鼠标键盘动作"
    for stage in dag["stages"]:
        stage_id = str(stage["id"])
        if not can_execute_stage(dag, checkpoints, stage_id):
            blocked = {
                "stage": stage_id,
                "agent_id": stage["agent"],
                "expected_files": list(stage.get("expected_files", [])),
                "present_files": [],
                "missing_files": list(stage.get("expected_files", [])),
                "verification": [],
                "failed_verification": ["dependency_not_passed"],
                "verdict": "FAIL",
                "can_continue": False,
                "next_allowed_stages": [],
            }
            write_json(out / "checkpoints" / f"{stage_id}.json", blocked)
            create_feedback_task(blocked, out_dir=out)
            checkpoints[stage_id] = blocked
            stage_results.append(blocked)
            break

        local_context = reduce_context(
            shared_context,
            agent_id=str(stage["agent"]),
            stage=stage_id,
            raw_context=raw_context,
            required_files=list(stage.get("expected_files", [])),
            verification=list(stage.get("verify", [])),
        )
        save_local_context(local_context, out)
        result = build_controlled_stage(
            stage,
            shared_context=shared_context,
            local_context=local_context,
            project_dir=project,
            out_dir=out,
            recorder=recorder,
        )
        if stage_id == "delivery":
            _write_public_gate(project, out, result.get("manifest", {}), shared_context)
        checkpoint = run_checkpoint(
            stage=stage_id,
            agent_id=str(stage["agent"]),
            project_dir=project,
            out_dir=out,
            expected_files=list(stage.get("expected_files", [])),
            outputs=list(stage.get("outputs", [])),
            verification=list(stage.get("verify", [])),
            next_allowed_stages=_next_stage_ids(dag, stage_id),
            shared_context=shared_context,
        )
        checkpoints[stage_id] = checkpoint
        stage_results.append(checkpoint)
        if checkpoint["verdict"] != "PASS":
            create_feedback_task(checkpoint, out_dir=out)
            break

    action_validation = validate_action_log(out / "agent_actions.jsonl")
    write_json(out / "contract_checks" / "action_protocol.json", action_validation)
    public_gate = read_json(out / "contract_checks" / "public_delivery_gate.json", {})
    final_verdict = {
        "kind": "AgentTreeControlledFinalVerdict",
        "provider_mode": provider_mode,
        "verdict": "PASS"
        if stage_results
        and stage_results[-1].get("stage") == "delivery"
        and all(item.get("verdict") == "PASS" for item in stage_results)
        and action_validation["verdict"] == "PASS"
        and public_gate.get("delivery_allowed") is True
        else "NEEDS_REWORK",
        "stage_results": stage_results,
        "action_protocol": action_validation,
        "public_delivery_gate": public_gate,
        "controlled_lane_only": True,
        "real_provider_proof": False,
        "created_at": now(),
    }
    bundle = create_trace_bundle(out_dir=out, project_dir=project, final_verdict=final_verdict)
    final_verdict["trace_bundle"] = str(bundle)
    acceptance_verifier.write_canonical_verdict(out / "final_verdict.json", final_verdict)
    return final_verdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--out", default=str(DEFAULT_EVAL_DIR / "run_001"))
    parser.add_argument("--provider-mode", default="controlled")
    args = parser.parse_args()
    result = run_controlled_agent_tree(goal=args.goal, project_name=args.project_name, out_dir=args.out, provider_mode=args.provider_mode)
    print(result["verdict"])
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
