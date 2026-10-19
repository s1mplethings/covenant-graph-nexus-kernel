from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import uuid
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.project_blueprint import FailureReport
from cgkn.application.project_loop import MinimalProjectLoop
from cgkn.application.software_project.catalog import get_case
from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, ModelRoleConfig, completion_client_from_environment


PHASE_B_PROFILES = {"fake-parallel", "fake-conflict", "fake-standup", "live-parallel", "live-repeat"}


def _run_pytest(expression: str) -> dict[str, Any]:
    started = time.perf_counter(); env = os.environ.copy(); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    command = [sys.executable, "-m", "pytest", "-q", "tests/application/test_project_blueprint.py", "tests/application/test_project_loop.py"]
    if expression: command.extend(["-k", expression])
    completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, env=env)
    return {"command": command, "exit": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "duration_ms": int((time.perf_counter() - started) * 1000), "status": "PASS" if completed.returncode == 0 else "FAIL"}


def _public_contract(case_id: str) -> dict[str, Any]:
    case = get_case(case_id)
    return {
        "case_id": case.case_id, "public_goal": case.public_goal,
        "public_acceptance": list(case.public_acceptance), "entrypoint": case.entrypoint,
        "runtime_command": list(case.runtime_command),
        "constraints": ["stdlib only", "offline", "no hidden acceptance access", "no placeholders", "worker writes exactly unit.owns"],
    }


def _live(profile: str, artifact_root: pathlib.Path) -> dict[str, Any]:
    case_id = "cli_csv_cleaner" if profile == "live-single" else "seeded_repair"
    client = completion_client_from_environment()
    route_path = ROOT / "config" / "provider_profiles" / "gateway_model_routing.json"
    routing = CGKNModelRouting.load(route_path) if isinstance(client, GatewayCompletionClient) else None
    if routing is None: raise RuntimeError("live project MVP requires the reviewed local Gateway route")
    run_token = f"mvp-{case_id}-{uuid.uuid4().hex[:10]}"
    run_client = client.bind_run(run_token, case_id)
    agent_provider = str(os.environ.get("CGKN_PROJECT_MVP_AGENT_PROVIDER", routing.agent.model)).strip().lower()
    if agent_provider not in routing.allowed_providers:
        raise ValueError("explicit project MVP Agent Provider is not allowlisted")
    agent_config = ModelRoleConfig("agent", agent_provider, 180, min(3500, routing.agent.max_output_tokens), routing.agent.temperature, routing.agent.reasoning_effort)
    worker_config = ModelRoleConfig("worker", routing.worker.model, 180, routing.worker.max_output_tokens, routing.worker.temperature, routing.worker.reasoning_effort)
    loop = MinimalProjectLoop(ROOT, artifact_root, run_client, agent_config, worker_config)
    contract = _public_contract(case_id)
    blueprint, decisions = loop.design(case_id, contract)
    workspace = artifact_root / "workspaces" / run_token
    initial_failure = None
    if case_id == "seeded_repair":
        shutil.copytree(ROOT / get_case(case_id).seeded_fixture, workspace)
        owners = [unit.unit_id for unit in blueprint.units if "math_utils.py" in unit.owns]
        if len(owners) != 1: raise ValueError("seeded repair blueprint must have one math_utils.py owner")
        initial_failure = FailureReport(owners[0], "TEST_FAILURE", owner_file="math_utils.py", owner_interface="add(a,b)", first_project_frame="math_utils.py:2", failed_check="initial pytest", expected="add(2,3) == 5", observed="add(2,3) == -1", affected_units=(owners[0],), suggested_action="patch subtraction to addition while preserving add(a,b)", evidence_refs=("initial_test",))
    outcome = loop.run(blueprint, workspace, case_id=case_id, initial_failure=initial_failure)
    value = outcome.as_dict() | {"agent_decisions": decisions, "manual_edits": 0, "profile": profile}
    target = outcome.run_root / f"{profile}_receipt.json"; target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the CGKN minimal ProjectBlueprint MVP profiles")
    parser.add_argument("--profile", required=True, choices=("unit", "fake-single", "fake-repair", "live-single", "live-repair", "fake-parallel", "fake-conflict", "fake-standup", "live-parallel", "live-repeat", "final"))
    parser.add_argument("--artifact-root", type=pathlib.Path, default=ROOT / ".service_evidence" / "project_mvp")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv); args.artifact_root.mkdir(parents=True, exist_ok=True)
    if args.profile in PHASE_B_PROFILES:
        result = {"profile": args.profile, "status": "BLOCKED_BY_PHASE_A", "reason": "PHASE B may start only after the complete PHASE A gate passes"}
    elif args.profile == "unit": result = _run_pytest("")
    elif args.profile == "fake-single": result = _run_pytest("fake_greenfield")
    elif args.profile == "fake-repair": result = _run_pytest("fake_repair")
    elif args.profile in {"live-single", "live-repair"}: result = _live(args.profile, args.artifact_root.resolve())
    else:
        result = {"profile": "final", "status": "NOT_READY", "reason": "run the ordered PHASE A and PHASE B profiles first"}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) if args.json else f"{args.profile}: {result.get('status', 'UNKNOWN')}")
    return 0 if result.get("status") in {"PASS", "SUCCEEDED", "BLOCKED_BY_PHASE_A", "NOT_READY"} else 1


if __name__ == "__main__": raise SystemExit(main())
