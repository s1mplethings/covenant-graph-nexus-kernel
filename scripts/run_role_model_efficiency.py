from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import uuid
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.project_loop import MinimalProjectLoop, ProviderBlueprintDesigner
from cgkn.application.software_project.catalog import get_case
from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, ModelRoleConfig, completion_client_from_environment


PROFILES = ("ingress", "coordinator", "generation", "worker-strength", "tier1", "tier2", "tier3", "analyze", "final")


def _source_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=True)
    return result.stdout.strip()


def _public_contract() -> dict[str, Any]:
    case = get_case("cli_csv_cleaner")
    return {
        "case_id": case.case_id, "public_goal": case.public_goal,
        "public_acceptance": list(case.public_acceptance), "entrypoint": case.entrypoint,
        "runtime_command": list(case.runtime_command),
        "constraints": ["stdlib only", "offline", "no hidden acceptance access", "no placeholders", "worker writes exactly unit.owns"],
    }


def _ingress() -> dict[str, Any]:
    env = os.environ.copy(); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    command = [sys.executable, "-m", "pytest", "-q", "tests/providers/test_structured_output_selector.py", "tests/providers/test_gateway_client.py"]
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    return {"profile": "ingress", "status": "PASS" if completed.returncode == 0 else "FAIL", "command": command,
            "exit": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr,
            "duration_ms": int((time.perf_counter() - started) * 1000)}


def _coordinator(repeat: int, artifact_root: pathlib.Path, provider: str) -> dict[str, Any]:
    client = completion_client_from_environment()
    if not isinstance(client, GatewayCompletionClient):
        raise RuntimeError("coordinator qualification requires the reviewed local Gateway route")
    routing = CGKNModelRouting.load(ROOT / "config" / "provider_profiles" / "gateway_model_routing.json")
    if provider not in routing.allowed_providers:
        raise ValueError("coordinator Provider is not allowlisted")
    source = _source_commit()
    destination = artifact_root / source / "coordinator"
    destination.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    contract = _public_contract()
    for index in range(1, repeat + 1):
        started = time.perf_counter()
        run_id = f"coordinator-{index}-{uuid.uuid4().hex[:8]}"
        designer = None
        try:
            bound = client.bind_run(run_id, "cli_csv_cleaner", budget_purpose="PLANNING")
            agent = ModelRoleConfig(
                "agent", provider, timeout_seconds=150, max_output_tokens=7000, temperature=0.0,
                reasoning_effort="none", task_class="project.compose", operation="COMPOSITION",
                outer_deadline_seconds=180, deadline_reserve_seconds=30,
            )
            worker = ModelRoleConfig("worker", routing.worker.model)
            loop = MinimalProjectLoop(ROOT, destination / run_id, bound, agent, worker)
            designer = ProviderBlueprintDesigner(bound, agent)
            blueprint, decisions = loop.design(f"cli_csv_cleaner_probe_{index}", contract, designer=designer)
            provider_units = [unit for unit in blueprint.units if unit.kind in {"implementation", "tests", "documentation"}]
            accepted = 2 <= len(provider_units) <= 4 and bool(blueprint.checks)
            row = {
                "run_id": run_id, "provider": provider, "model": provider, "logical_calls": 1,
                "transport_attempts": designer.calls[0]["transport_attempts"], "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "usage": designer.calls[0]["usage"], "usage_status": designer.calls[0]["usage_status"],
                "selection_receipt": designer.calls[0]["selection_receipt"], "blueprint_edit_count": "APPLIED",
                "blueprint_hash": blueprint.blueprint_hash, "unit_count": len(provider_units), "check_count": len(blueprint.checks),
                "agent_decisions": decisions, "manual_repairs": 0, "status": "PASS" if accepted else "FAIL",
                "blueprint": blueprint.as_dict(),
            }
        except Exception as exc:
            evidence = dict(getattr(exc, "evidence", {}) or {})
            row = {"run_id": run_id, "provider": provider, "model": provider, "logical_calls": 1,
                   "transport_attempts": evidence.get("transport_attempts"), "elapsed_ms": int((time.perf_counter() - started) * 1000),
                   "usage": None, "usage_status": "UNKNOWN_AFTER_TRANSPORT_FAILURE", "selection_receipt": evidence,
                   "error_class": str(getattr(exc, "category", type(exc).__name__)), "error": str(exc)[:1000], "status": "FAIL"}
        (destination / f"{run_id}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        runs.append(row)
    passed = sum(row["status"] == "PASS" for row in runs)
    status = "PASS" if passed == repeat else "PASS_WITH_LIMITS" if passed == repeat - 1 else "FAIL"
    result = {"profile": "coordinator", "source_commit": source, "provider": provider, "repeat": repeat, "passed": passed, "status": status, "runs": runs}
    (destination / "qualification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the gated CGKN role/model efficiency validation")
    parser.add_argument("--profile", required=True, choices=PROFILES)
    parser.add_argument("--variant", choices=("V0", "V0B", "V1", "V2", "V3"))
    parser.add_argument("--case", default="cli_csv_cleaner")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--provider", choices=("qwen", "deepseek", "grok"), default="deepseek")
    parser.add_argument("--artifact-root", type=pathlib.Path, default=ROOT / "artifacts" / "role_model_efficiency")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.repeat < 1 or args.repeat > 5:
        parser.error("repeat must be between 1 and 5")
    if args.profile == "ingress":
        result = _ingress()
    elif args.profile == "coordinator":
        result = _coordinator(args.repeat, args.artifact_root.resolve(), args.provider)
    else:
        result = {"profile": args.profile, "status": "BLOCKED_BY_PRIOR_GATE", "reason": "complete Coordinator 3/3 before later profiles"}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) if args.json else f"{args.profile}: {result['status']}")
    return 0 if result["status"] in {"PASS", "BLOCKED_BY_PRIOR_GATE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
