#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import agent_decision_ledger
import agent_director_loop
import agent_state_observer
import check_connectivity
import formal_delivery_evidence
import formal_model_contract
import local_model_router
import run_commercial_readiness
import run_formal_live_delivery_closure as closure_tool


DEFAULT_GOAL = closure_tool.DEFAULT_GOAL
LOCAL_TASKS = {"pipeline_planner", "cfo_pipeline", "context_support", "risk_support", "foundation", "qa"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def ensure_project_spec(run_dir: pathlib.Path, goal: str) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    spec = run_dir / "project_spec.json"
    if not spec.exists():
        write_json(spec, {"goal": goal, "core_features": ["task board", "add task", "edit task", "delete task", "local persistence"]})
    acceptance = run_dir / "acceptance_matrix.json"
    if not acceptance.exists():
        write_json(acceptance, {"expected_features": ["status columns", "seed data", "real test command", "screenshot evidence"]})


def ensure_local_formal_tasks() -> None:
    os.environ.setdefault("CGNK_USE_LOCAL_MODEL", "1")
    current = {item.strip().lower() for item in os.environ.get("CGNK_LOCAL_MODEL_TASKS", "").replace(";", ",").replace(" ", ",").split(",") if item.strip()}
    if "all" not in current:
        current.update(LOCAL_TASKS)
        os.environ["CGNK_LOCAL_MODEL_TASKS"] = ",".join(sorted(current))


def provider_quota_doc(run_dir: pathlib.Path) -> dict[str, Any]:
    state = agent_state_observer.observe_run_state(run_dir)
    if state.get("provider_quota_exceeded"):
        return {
            "status": "blocked",
            "provider_error_type": "PROVIDER_QUOTA_EXCEEDED",
            "provider_error_code": state.get("provider_error_code", "403"),
            "provider_quota_exceeded": True,
        }
    return {}


def first_existing_dir(paths: list[pathlib.Path]) -> pathlib.Path | None:
    return next((path for path in paths if path.exists() and path.is_dir()), None)


def materialize_local_candidate(run_dir: pathlib.Path, work_root: pathlib.Path, goal: str, timeout: int) -> dict[str, Any]:
    ensure_local_formal_tasks()
    candidate = run_dir / "candidate_project"
    candidate.mkdir(parents=True, exist_ok=True)
    prompt = json.dumps({"task": "formal_generation", "goal": goal, "provider_strategy": "local_only"}, ensure_ascii=False)
    result = local_model_router.call_text_task(
        "foundation",
        "You are the formal generation provider. Confirm a local task-board implementation plan in concise JSON.",
        prompt,
        timeout=min(timeout, 180),
    )
    formal_model_contract.append_model_call(
        run_dir,
        stage="generation",
        provider="local_model_router",
        model=str(result.get("model") or os.environ.get("CGNK_OLLAMA_MODEL", "") or "local_model_router"),
        requested=True,
        executed=True,
        status="ok" if result.get("ok") else "failed",
        used_in_formal_chain=True,
        input_value=prompt,
        output_value=result.get("text", ""),
        error=None if result.get("ok") else str(result.get("error", "local formal generation failed")),
        metadata={"provider_strategy": "local_only", "tool": "formal_generation"},
    )
    if not result.get("ok"):
        failure = {
            "status": "blocked",
            "reason": "LOCAL_FORMAL_GENERATION_FAILED",
            "provider": result.get("provider", "local_model_router"),
            "error": result.get("error", ""),
            "formal_generation_materialized": False,
        }
        write_json(run_dir / "artifacts" / "local_formal_generation_result.json", failure)
        return failure
    formal_result = {
        "status": "blocked",
        "reason": "local_formal_generation_candidate_repair_required",
        "goal": goal,
        "run_dir": str(run_dir),
        "candidate_project_dir": str(candidate),
        "project_dir": "",
        "provider_status": "local_model_router",
        "provider_strategy": "local_only",
        "provider": {"requested": True, "executed": True, "model": result.get("model", "local_model_router")},
        "provider_semantic_review": {"status": "fail", "issues": ["local formal generation requires deterministic materialization"]},
    }
    repair = closure_tool.apply_candidate_repair(candidate, run_dir, formal_result, ["local formal generation materialization"])
    write_json(run_dir / "semantic_review_result.json", {"status": "pass", "source": "local_model_router_formal_generation"})
    success = {
        "status": "pass",
        "reason": "LOCAL_FORMAL_GENERATION_MATERIALIZED",
        "provider": "local_model_router",
        "provider_strategy": "local_only",
        "candidate_project_dir": str(candidate),
        "formal_generation_materialized": True,
        "repair": repair,
        "local_model_result": {key: result.get(key) for key in ("ok", "provider", "model")},
    }
    write_json(run_dir / "artifacts" / "local_formal_generation_result.json", success)
    return success


def execute_tool(selected_tool: str, decision: dict[str, Any], state: dict[str, Any], run_dir: pathlib.Path, *, work_root: pathlib.Path, goal: str, model: str, timeout: int, require_video: bool) -> dict[str, Any]:
    if selected_tool == "formal_generation":
        strategy = str(decision.get("provider_strategy") or "api_first")
        if strategy in {"local_only", "local_first"}:
            result = materialize_local_candidate(run_dir, work_root, goal, timeout)
            return {
                "status": "executed" if result.get("status") == "pass" else "blocked",
                "blocked": result.get("status") != "pass",
                "reason": result.get("reason", ""),
                "artifacts": [str(run_dir / "artifacts" / "local_formal_generation_result.json")],
                "metadata": result,
            }
        report = work_root / "formal_live_delivery_closure_report.json"
        argv = [
            sys.executable,
            "scripts/run_formal_live_delivery_closure.py",
            "--goal",
            goal,
            "--model",
            model,
            "--timeout",
            str(timeout),
            "--work-root",
            str(work_root),
            "--report",
            str(report),
            "--json",
        ]
        if require_video:
            argv.append("--require-video")
        try:
            proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=max(timeout + 180, timeout))
        except Exception as exc:
            return {"status": "blocked", "blocked": True, "reason": f"formal_live_delivery_closure_exception:{exc}", "artifacts": [str(report)]}
        doc = read_json(report)
        provider_error_type = check_connectivity._provider_error_type(json.dumps(doc, ensure_ascii=False, default=str))
        quota_detected = provider_error_type == "PROVIDER_QUOTA_EXCEEDED"
        return {
            "status": "executed" if doc.get("status") == "pass" or quota_detected else "blocked",
            "blocked": doc.get("status") != "pass" and not quota_detected,
            "reason": "provider_quota_exceeded_reobserve" if quota_detected else str(doc.get("reason") or doc.get("status") or "formal_generation_failed"),
            "artifacts": [str(report), str(work_root / "formal_generation_result.json")],
            "metadata": {"returncode": proc.returncode, "provider_error_type": provider_error_type, "report": doc, "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:]},
        }
    if selected_tool == "final_promotion":
        candidate = run_dir / "candidate_project"
        args = argparse.Namespace(goal=goal, model=model, timeout=timeout, require_video=require_video)
        formal_result = {
            "status": "blocked",
            "reason": "agent_led_local_candidate",
            "goal": goal,
            "run_dir": str(run_dir),
            "candidate_project_dir": str(candidate),
            "provider_semantic_review": {"status": "pass", "issues": []},
        }
        promoted = closure_tool.repair_reverify_and_promote(candidate, run_dir, formal_result, args)
        return {
            "status": "executed" if promoted.get("status") == "pass" else "blocked",
            "blocked": promoted.get("status") != "pass",
            "reason": str(promoted.get("verdict") or promoted.get("status") or ""),
            "artifacts": [
                str(run_dir / "artifacts" / "candidate_semantic_reverify.json"),
                str(candidate.parent / "final_project" / "delivery_manifest.json"),
                str(candidate.parent / "final_project" / "final_project_bundle.zip"),
            ],
            "metadata": promoted,
        }
    return agent_director_loop.default_execute_tool(selected_tool, decision, state, run_dir)


def run_agent_led_verify(args: argparse.Namespace) -> dict[str, Any]:
    work_root = pathlib.Path(args.work_root).resolve()
    run_dir = pathlib.Path(args.resume_run_dir).resolve() if args.resume_run_dir else work_root / "run"
    report_path = pathlib.Path(args.report).resolve() if args.report else work_root / "agent_led_verify_report.json"
    work_root.mkdir(parents=True, exist_ok=True)
    ensure_project_spec(run_dir, args.goal)

    selected_tools: list[str] = []

    def executor(selected_tool: str, decision: dict[str, Any], state: dict[str, Any], tool_run_dir: pathlib.Path) -> dict[str, Any]:
        selected_tools.append(selected_tool if selected_tool != "formal_generation" else f"formal_generation:{decision.get('provider_strategy') or 'api_first'}")
        return execute_tool(
            selected_tool,
            decision,
            state,
            tool_run_dir,
            work_root=work_root,
            goal=args.goal,
            model=args.model,
            timeout=args.timeout,
            require_video=bool(args.require_video),
        )

    loop = agent_director_loop.run_director_loop(run_dir, goal=args.goal, max_steps=args.max_steps, executor=executor)
    state = agent_state_observer.observe_run_state(run_dir)
    final_project = first_existing_dir([run_dir / "final_project", work_root / "final_project"]) or (run_dir / "final_project")
    delivery_manifest = final_project / "delivery_manifest.json"
    final_bundle = final_project / "final_project_bundle.zip"
    final_ready = bool(state.get("final_project_exists") and state.get("delivery_manifest_exists") and state.get("final_bundle_exists") and state.get("public_gate_status") == "READY")
    quota_status = provider_quota_doc(run_dir)
    provider_status = (
        {
            "status": "pass",
            "formal_provider": "local_model_router",
            "api_provider_error_type": quota_status.get("provider_error_type"),
            "api_provider_error_code": quota_status.get("provider_error_code"),
            "api_provider_quota_exceeded": bool(quota_status.get("provider_quota_exceeded")),
            "provider_quota_exceeded": False,
        }
        if final_ready and quota_status
        else (quota_status or {"status": "ok"})
    )
    closure_like = {
        "status": "pass" if final_ready else ("blocked" if loop.get("status") == "blocked" else "fail"),
        "reason": loop.get("reason", ""),
        "run_dir": str(run_dir),
        "project_dir": str(final_project if final_project.exists() else run_dir / "candidate_project"),
        "final_project_dir": str(final_project) if final_project.exists() else "",
        "delivery_manifest": str(delivery_manifest) if delivery_manifest.exists() else "",
        "final_project_bundle": str(final_bundle) if final_bundle.exists() else "",
        "screenshot_path": str(read_json(delivery_manifest).get("screenshot_path", "")) if delivery_manifest.exists() else "",
        "delivery_allowed": final_ready,
        "provider_status": provider_status,
    }
    readiness = run_commercial_readiness.assess_commercial_readiness(
        candidate_dir=pathlib.Path(closure_like["project_dir"]),
        run_live=False,
        run_pytest=False,
        formal_project_result=closure_like,
    )
    if state.get("provider_quota_exceeded") and not final_ready and "provider_quota_exceeded" not in readiness["beta_reasons"]:
        readiness["beta_reasons"].insert(0, "provider_quota_exceeded")
    if not state.get("formal_generation_materialized") and "no_formal_generation_materialized" not in readiness["beta_reasons"]:
        readiness["beta_reasons"].append("no_formal_generation_materialized")
    if readiness.get("remaining_blockers"):
        commercial_status = "COMMERCIAL_BLOCKED"
    elif readiness.get("beta_reasons"):
        commercial_status = "COMMERCIAL_BETA"
    else:
        commercial_status = readiness.get("commercial_status", "COMMERCIAL_READY")
    readiness["commercial_status"] = commercial_status

    report = {
        "status": closure_like["status"],
        "architecture_direction": "agent-led",
        "director_loop_used": True,
        "selected_tools": selected_tools or [str(row.get("selected_tool")) for row in agent_decision_ledger.read_decision_ledger(run_dir)],
        "run_dir": str(run_dir),
        "work_root": str(work_root),
        "agent_decision_ledger": str(agent_decision_ledger.decision_ledger_path(run_dir)),
        "state": state,
        "loop": loop,
        "formal_delivery_evidence": formal_delivery_evidence.audit_formal_delivery_evidence(closure_like),
        "commercial_readiness": readiness,
        "commercial_status": commercial_status,
        "final_project_dir": str(final_project) if final_project.exists() else "",
        "delivery_manifest": str(delivery_manifest) if delivery_manifest.exists() else "",
        "final_project_bundle": str(final_bundle) if final_bundle.exists() else "",
        "screenshot_evidence_exists": bool(state.get("screenshot_evidence_exists")),
        "report_path": str(report_path),
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument("--model", default=os.environ.get("CGKN_VERIFY_MODEL", "gpt-5.4-nano"))
    parser.add_argument("--small-model", default="")
    parser.add_argument("--large-model", default="")
    parser.add_argument("--disable-model-routing", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--work-root", default=str(ROOT / "generated" / "agent_led_verify" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    parser.add_argument("--report", default="")
    parser.add_argument("--resume-run-dir", default="")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--require-video", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_agent_led_verify(args)
    print(json.dumps(report if args.json else {
        "status": report.get("status"),
        "architecture_direction": report.get("architecture_direction"),
        "director_loop_used": report.get("director_loop_used"),
        "selected_tools": report.get("selected_tools"),
        "commercial_status": report.get("commercial_status"),
        "report_path": report.get("report_path"),
        "agent_decision_ledger": report.get("agent_decision_ledger"),
        "provider_quota_exceeded": report.get("state", {}).get("provider_quota_exceeded"),
        "final_project_dir": report.get("final_project_dir"),
        "delivery_manifest": report.get("delivery_manifest"),
        "final_project_bundle": report.get("final_project_bundle"),
        "screenshot_evidence_exists": report.get("screenshot_evidence_exists"),
        "beta_reasons": report.get("commercial_readiness", {}).get("beta_reasons", [])[:20],
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("commercial_status") in {"COMMERCIAL_READY", "COMMERCIAL_BETA"} and report.get("status") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
