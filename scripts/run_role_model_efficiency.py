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

from cgkn.application.project_blueprint import BlueprintUnit, FailureAction, FailureReport, FailureStage, ProjectBlueprint
from cgkn.application.project_loop import BlueprintUnitExecutor, MinimalProjectLoop, ProviderBlueprintDesigner
from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.application.software_project.catalog import get_case
from cgkn.execution import BlockExecutionRequest, TaskContext
from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, ModelRoleConfig, completion_client_from_environment


PROFILES = ("ingress", "coordinator", "generation", "worker-strength", "materialization-benchmark", "tier1-efficiency", "tier1", "tier2", "tier3", "analyze", "final")


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


def _load_pricing_snapshot(path: pathlib.Path | None, provider: str) -> dict[str, Any] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "provider", "model", "input_price_per_million", "output_price_per_million",
        "currency", "unit", "captured_at", "source",
    }
    if not isinstance(value, dict) or not required <= set(value) or value.get("provider") != provider:
        raise ValueError("pricing snapshot is incomplete or does not match the selected Provider")
    if not str(value.get("source") or "").startswith(("https://", "provider_billing_config:")):
        raise ValueError("pricing snapshot source must be official or a Provider billing configuration reference")
    return value


def _materialization_metrics(
    calls: list[dict[str, Any]], *, final_file_count: int, success: bool,
    pricing: dict[str, Any] | None,
) -> dict[str, Any]:
    seen: set[str] = set()
    duplicate_output_tokens = 0
    repeated_context_tokens = 0
    for call in calls:
        returned = [str(path) for path in call.get("returned_paths") or ()]
        requested = [str(path) for path in call.get("requested_paths") or ()]
        byte_map = {str(key): int(value) for key, value in dict(call.get("returned_bytes_by_path") or {}).items()}
        repeated_returned = [path for path in returned if path in seen]
        output_tokens = call.get("completion_tokens")
        if isinstance(output_tokens, int) and byte_map and sum(byte_map.values()) > 0:
            duplicate_output_tokens += round(
                output_tokens * sum(byte_map.get(path, 0) for path in repeated_returned) / sum(byte_map.values())
            )
        prompt_tokens = call.get("prompt_tokens")
        if isinstance(prompt_tokens, int) and requested:
            repeated_context_tokens += round(prompt_tokens * len([path for path in requested if path in seen]) / len(requested))
        seen.update(returned)

    def total(name: str) -> int | None:
        values = [call.get(name) for call in calls]
        return sum(int(value) for value in values) if all(isinstance(value, int) for value in values) else None

    input_tokens, output_tokens = total("prompt_tokens"), total("completion_tokens")
    total_tokens = None if input_tokens is None or output_tokens is None else input_tokens + output_tokens
    cost = None
    if pricing is not None and input_tokens is not None and output_tokens is not None:
        cached = total("cached_tokens") or 0
        uncached_input = max(0, input_tokens - cached)
        cached_price = float(pricing.get("cached_input_price_per_million") or pricing["input_price_per_million"])
        cost = (
            uncached_input * float(pricing["input_price_per_million"])
            + cached * cached_price
            + output_tokens * float(pricing["output_price_per_million"])
        ) / 1_000_000
    useful_files = final_file_count if success else len(seen)
    return {
        "success": success, "generation_calls": len(calls),
        "continuation_calls": sum(call.get("call_class") == "GENERATION_CONTINUATION" for call in calls),
        "retry_calls": sum(call.get("call_class") == "GENERATION_RETRY" for call in calls),
        "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens,
        "cached_tokens": total("cached_tokens"),
        "repeated_file_output_tokens": duplicate_output_tokens,
        "repeated_context_tokens": repeated_context_tokens,
        "duplicate_generation_token_waste": duplicate_output_tokens + repeated_context_tokens,
        "useful_newly_materialized_files": useful_files,
        "materialization_efficiency": useful_files / len(calls) if calls else 0,
        "tokens_per_materialized_file": total_tokens / useful_files if total_tokens is not None and useful_files else None,
        "cost": cost, "cost_per_successful_unit": cost if success else None,
    }


def _materialization_benchmark(
    repeat: int, artifact_root: pathlib.Path, provider: str,
    pricing_path: pathlib.Path | None,
) -> dict[str, Any]:
    if repeat != 3:
        raise ValueError("materialization benchmark requires exactly three runs per policy")
    source = _source_commit()
    if subprocess.check_output(["git", "status", "--short", "--untracked-files=no"], cwd=ROOT, text=True).strip():
        raise RuntimeError("materialization benchmark requires a frozen clean Source Closure")
    base_client = completion_client_from_environment()
    if not isinstance(base_client, GatewayCompletionClient):
        raise RuntimeError("materialization benchmark requires the reviewed local Gateway route")
    pricing = _load_pricing_snapshot(pricing_path, provider)
    destination = artifact_root / source / "materialization_benchmark"
    destination.mkdir(parents=True, exist_ok=True)
    policies: dict[str, list[dict[str, Any]]] = {"M0_FULL_RETRY": [], "M1_INCREMENTAL": []}
    for label, policy in (("M0_FULL_RETRY", "FULL_RETRY"), ("M1_INCREMENTAL", "INCREMENTAL")):
        for index in range(1, repeat + 1):
            run_id = f"{label.lower()}-{index}-{uuid.uuid4().hex[:8]}"
            workspace = destination / run_id / "workspace"
            (workspace / "csv_cleaner").mkdir(parents=True, exist_ok=False)
            (workspace / "csv_cleaner" / "cleaner.py").write_text(
                "def dedupe_rows(header, rows, column=None):\n    return list(rows)\n\n"
                "def fill_empty(header, rows, value):\n    return list(rows)\n",
                encoding="utf-8",
            )
            (workspace / "csv_cleaner" / "cli.py").write_text("def main(argv=None):\n    return 0\n", encoding="utf-8")
            unit = BlueprintUnit(
                "tests", "public CSV cleaner tests", "tests",
                ("tests/test_cleaner.py", "tests/test_cli.py"),
                reads=("csv_cleaner/cleaner.py", "csv_cleaner/cli.py"),
                executor_ref="llm.cheap@1",
                instruction="Create both cohesive pytest files covering the declared cleaner functions and CLI main entrypoint.",
                required_interfaces=("csv_cleaner.cleaner.dedupe_rows", "csv_cleaner.cleaner.fill_empty", "csv_cleaner.cli.main"),
                acceptance=("both owned files are complete and syntactically valid",),
                allowed_effects=("filesystem.read", "filesystem.write"), max_actions=2, max_files=2,
            )
            client = base_client.bind_run(run_id, "materialization_tests_probe", budget_purpose="GENERATION")
            config = ModelRoleConfig(
                "worker", provider, timeout_seconds=150, max_output_tokens=6000, temperature=0.0,
                reasoning_effort="none", task_class="project.codegen", operation="EXECUTE",
                outer_deadline_seconds=180, deadline_reserve_seconds=30, thinking_mode="disabled",
            )
            executor = BlueprintUnitExecutor(workspace, client, config, materialization_policy=policy)
            request = BlockExecutionRequest(
                "materialization_tests_probe", run_id, "attempt-1", unit.unit_id,
                "project.unit.tests@1", "llm.cheap@1",
                TaskContext(
                    unit.instruction, node_config={"unit": unit.as_dict()},
                    dependency_results={"core": {"public_interfaces": list(unit.required_interfaces)}},
                    project_constraints=("offline", "no hidden acceptance"), acceptance=unit.acceptance,
                ),
            )
            started = time.perf_counter()
            block = executor.execute(request)
            while (
                policy == "FULL_RETRY" and not block.succeeded and len(executor.calls) < 3
                and block.error is not None and block.error.details.get("failure_type") == "UNIT_OUTPUT_INCOMPLETE"
            ):
                block = executor.execute(request)
            files = [path for path in unit.owns if (workspace / pathlib.PurePosixPath(path)).is_file()]
            syntax = block.succeeded and all(
                subprocess.run([sys.executable, "-m", "py_compile", str(workspace / pathlib.PurePosixPath(path))], capture_output=True, text=True).returncode == 0
                for path in unit.owns
            )
            receipts = bool(executor.calls) and all(bool(call.get("selection_receipt_hash")) for call in executor.calls)
            success = block.succeeded and len(files) == len(unit.owns) and syntax and receipts
            row = {
                "run_id": run_id, "policy": policy, "status": "PASS" if success else "FAIL",
                "source_commit": source, "provider": provider,
                "calls": executor.calls, "files": files, "syntax": syntax,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "metrics": _materialization_metrics(executor.calls, final_file_count=len(unit.owns), success=success, pricing=pricing),
                "block_result": block.as_dict(),
            }
            (destination / f"{run_id}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            policies[label].append(row)
    summary: dict[str, Any] = {}
    for label, rows in policies.items():
        successes = [row for row in rows if row["status"] == "PASS"]
        generation_tokens = sum(int(row["metrics"].get("total_tokens") or 0) for row in rows)
        summary[label] = {
            "runs": len(rows), "successes": len(successes),
            "generation_tokens": generation_tokens,
            "tokens_per_success": generation_tokens / len(successes) if successes else None,
            "duplicate_generation_token_waste": sum(row["metrics"]["duplicate_generation_token_waste"] for row in rows),
            "materialization_efficiency": sum(row["metrics"]["materialization_efficiency"] for row in rows) / len(rows),
            "cost": sum(row["metrics"]["cost"] for row in rows) if pricing is not None else None,
        }
    m0, m1 = summary["M0_FULL_RETRY"], summary["M1_INCREMENTAL"]
    reduction = None
    if m0["tokens_per_success"] and m1["tokens_per_success"] is not None:
        reduction = 1 - m1["tokens_per_success"] / m0["tokens_per_success"]
    benefit = "PROVEN" if (
        m1["successes"] >= m0["successes"]
        and (m1["successes"] > m0["successes"] or (reduction is not None and reduction >= 0.20))
    ) else "HARMFUL" if m1["successes"] < m0["successes"] else "NEUTRAL"
    result = {
        "profile": "materialization-benchmark", "status": "PASS",
        "source_commit": source, "repeat": repeat, "pricing_snapshot": pricing,
        "cost_evaluated": pricing is not None, "policies": policies, "summary": summary,
        "generation_token_reduction": reduction,
        "incremental_materialization_benefit": benefit,
        "statistical_claim": "DIRECTIONAL_ONLY",
    }
    (destination / "index.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _direct_strong_run(case_id: str, artifact_root: pathlib.Path, provider: str) -> dict[str, Any]:
    source = _source_commit()
    run_id = f"v0-{case_id}-{uuid.uuid4().hex[:8]}"
    workspace = artifact_root / source / "tier1" / run_id / "workspace"
    workspace.mkdir(parents=True, exist_ok=False)
    base = completion_client_from_environment()
    if not isinstance(base, GatewayCompletionClient):
        return {"run_id": run_id, "status": "BLOCKED_PROVIDER"}
    client = base.bind_run(run_id, case_id, budget_purpose="BENCHMARK")
    config = ModelRoleConfig(
        "worker", provider, timeout_seconds=150, max_output_tokens=6000, temperature=0.0,
        reasoning_effort="none", task_class="project.direct", operation="EXECUTE",
        outer_deadline_seconds=180, deadline_reserve_seconds=30, thinking_mode="disabled",
    )
    executor = BlueprintUnitExecutor(workspace, client, config, config)
    if case_id == "seeded_repair":
        shutil.rmtree(workspace)
        shutil.copytree(ROOT / get_case(case_id).seeded_fixture, workspace)
        unit = BlueprintUnit(
            "direct", "repair arithmetic", "implementation", ("math_utils.py",),
            reads=("test_math_utils.py",), executor_ref="llm.cheap@1",
            instruction="Repair add(a,b) with the smallest exact patch and preserve its signature.",
            required_interfaces=("add",), acceptance=("pytest passes",),
            allowed_effects=("filesystem.read", "filesystem.write"),
        )
        failure = FailureReport(
            unit.unit_id, "TEST_FAILURE", failure_stage=FailureStage.TEST.value,
            owner_unit_id=unit.unit_id, recovery_action=FailureAction.REPAIR_EXISTING.value,
            materialized_baseline=True, owner_file="math_utils.py", owner_interface="add(a,b)",
            first_project_frame="math_utils.py:2", failed_check="pytest", expected="add(2,3) == 5",
            observed="add(2,3) == -1", affected_units=(unit.unit_id,),
            suggested_action="replace subtraction with addition", evidence_refs=("public_pytest",),
        )
        executor.register_materialized_baseline(unit)
        executor.failure_reports[unit.unit_id] = failure
    else:
        unit = BlueprintUnit(
            "direct", "complete CSV cleaner", "implementation",
            ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py", "tests/test_csv_cleaner.py", "README.md"),
            executor_ref="llm.cheap@1",
            instruction=get_case(case_id).public_goal,
            required_interfaces=("clean_rows",), acceptance=get_case(case_id).public_acceptance,
            allowed_effects=("filesystem.write",), max_actions=5, max_files=5,
        )
    request = BlockExecutionRequest(
        case_id, run_id, "attempt-1", unit.unit_id, "project.unit.implementation@1", "llm.cheap@1",
        TaskContext(
            unit.instruction, node_config={"unit": unit.as_dict()},
            project_constraints=("stdlib only", "offline", "no hidden acceptance access"),
            acceptance=unit.acceptance,
        ),
        timeout_seconds=150, declared_effects=unit.allowed_effects,
    )
    started = time.perf_counter()
    block = executor.execute(request)
    compile_result = subprocess.run([sys.executable, "-m", "compileall", "-q", "."], cwd=workspace, capture_output=True, text=True)
    pytest_result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=workspace, capture_output=True, text=True)
    runtime_result = subprocess.run(list(get_case(case_id).runtime_command), cwd=workspace, capture_output=True, text=True)
    acceptance = ExternalAcceptanceExecutor(
        workspace, ROOT / "benchmarks" / "real_project_generation" / "acceptance",
    ).execute(BlockExecutionRequest(
        case_id, run_id, "acceptance", "accept", "project.acceptance.external@1", "project.acceptance@1",
        TaskContext(
            "external acceptance", node_config={"case_id": case_id},
            acceptance=get_case(case_id).public_acceptance,
        ), timeout_seconds=120,
    ))
    success = block.succeeded and compile_result.returncode == pytest_result.returncode == runtime_result.returncode == 0 and acceptance.succeeded
    row = {
        "run_id": run_id, "variant": "V0", "case_id": case_id,
        "provider": provider, "status": "PASS" if success else "FAIL",
        "logical_provider_calls": len(executor.calls), "calls": executor.calls,
        "compile": compile_result.returncode == 0, "pytest": pytest_result.returncode == 0,
        "runtime": runtime_result.returncode == 0, "hidden_acceptance": acceptance.succeeded,
        "manual_intervention": 0, "whole_project_replan": 0, "interface_regression": 0,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "metrics": _materialization_metrics(executor.calls, final_file_count=len(unit.owns), success=success, pricing=None),
        "block_result": block.as_dict(), "acceptance_result": acceptance.as_dict(),
    }
    target = workspace.parent / "receipt.json"
    target.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return row


def _tier1_efficiency(
    variant: str, case_id: str, repeat: int, artifact_root: pathlib.Path,
    provider: str, blueprint_path: pathlib.Path | None,
) -> dict[str, Any]:
    if variant not in {"V0", "V0B", "V1", "V2"}:
        raise ValueError("Tier 1 requires V0, V0B, V1, or V2")
    if case_id not in {"seeded_repair", "cli_csv_cleaner"}:
        raise ValueError("Tier 1 case must be seeded_repair or cli_csv_cleaner")
    if subprocess.check_output(["git", "status", "--short", "--untracked-files=no"], cwd=ROOT, text=True).strip():
        raise RuntimeError("Tier 1 requires a frozen clean Source Closure")
    routing = CGKNModelRouting.load(ROOT / "config" / "provider_profiles" / "gateway_model_routing.json")
    strong = routing.agent.model
    cheap = routing.worker.model
    frozen = None
    if variant == "V0B":
        if blueprint_path is None:
            raise ValueError("V0B requires --blueprint-path")
        frozen = ProjectBlueprint.from_dict(json.loads(blueprint_path.read_text(encoding="utf-8")))
        if frozen.project_id != case_id:
            raise ValueError("frozen Blueprint case does not match --case")
    runs: list[dict[str, Any]] = []
    for index in range(1, repeat + 1):
        destination = artifact_root / _source_commit() / "tier1" / f"{variant.lower()}-{case_id}-{index}"
        if variant == "V0":
            row = _direct_strong_run(case_id, artifact_root, strong)
        else:
            from scripts.run_project_mvp import _live

            row = _live(
                "live-single" if case_id == "cli_csv_cleaner" else "live-repair",
                destination,
                agent_provider_override=strong,
                worker_provider_override=strong if variant in {"V0B", "V1"} else cheap,
                frozen_blueprint=frozen,
            )
            row["variant"] = variant
            row["case_id"] = case_id
            row["status"] = "PASS" if row.get("status") == "SUCCEEDED" else "FAIL"
        runs.append(row)
    passed = sum(row.get("status") == "PASS" for row in runs)
    result = {
        "profile": "tier1-efficiency", "variant": variant, "case_id": case_id,
        "repeat": repeat, "passed": passed, "status": "PASS" if passed == repeat else "FAIL",
        "strong_provider": strong, "cheap_provider": cheap, "runs": runs,
        "cost_evaluated": False,
        "cost_status": "NOT_EVALUATED_WITHOUT_MODEL_SPECIFIC_OFFICIAL_PRICING",
        "statistical_claim": "DIRECTIONAL_ONLY",
    }
    target = artifact_root / _source_commit() / "tier1" / f"{variant.lower()}-{case_id}-index.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the gated CGNK role/model efficiency validation")
    parser.add_argument("--profile", required=True, choices=PROFILES)
    parser.add_argument("--variant", choices=("V0", "V0B", "V1", "V2", "V3"))
    parser.add_argument("--case", default="cli_csv_cleaner")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--provider", choices=("qwen", "deepseek", "grok"), default="deepseek")
    parser.add_argument("--artifact-root", type=pathlib.Path, default=ROOT / "artifacts" / "role_model_efficiency")
    parser.add_argument("--pricing-snapshot", type=pathlib.Path)
    parser.add_argument("--blueprint-path", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.repeat < 1 or args.repeat > 5:
        parser.error("repeat must be between 1 and 5")
    if args.profile == "ingress":
        result = _ingress()
    elif args.profile == "coordinator":
        result = _coordinator(args.repeat, args.artifact_root.resolve(), args.provider)
    elif args.profile == "materialization-benchmark":
        result = _materialization_benchmark(
            args.repeat, args.artifact_root.resolve(), args.provider,
            args.pricing_snapshot.resolve() if args.pricing_snapshot else None,
        )
    elif args.profile == "tier1-efficiency":
        if not args.variant:
            parser.error("tier1-efficiency requires --variant")
        result = _tier1_efficiency(
            args.variant, args.case, args.repeat, args.artifact_root.resolve(), args.provider,
            args.blueprint_path.resolve() if args.blueprint_path else None,
        )
    else:
        result = {"profile": args.profile, "status": "BLOCKED_BY_PRIOR_GATE", "reason": "complete Coordinator 3/3 before later profiles"}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) if args.json else f"{args.profile}: {result['status']}")
    return 0 if result["status"] in {"PASS", "BLOCKED_BY_PRIOR_GATE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
