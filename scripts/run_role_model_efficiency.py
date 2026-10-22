from __future__ import annotations

import argparse
import copy
import hashlib
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
from cgkn.providers import (
    CGKNModelRouting, GatewayCompletionClient, ModelRoleConfig, ProviderCompletion,
    completion_client_from_environment, parse_json_object,
)


PROFILES = ("ingress", "coordinator", "generation", "worker-strength", "materialization-benchmark", "tier1-efficiency", "tier1", "tier2", "tier3", "analyze", "final")


def _source_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=True)
    return result.stdout.strip()


def _validated_product_source_commit() -> str:
    receipt = ROOT / "governance" / "software_project_generation_receipt.json"
    value = json.loads(receipt.read_text(encoding="utf-8"))
    source = str(value.get("source_commit") or "").strip()
    if len(source) != 40:
        raise RuntimeError("validated product Source Closure is unavailable")
    return source


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


def _controlled_partial_schema(schema: dict[str, Any], allowed_paths: tuple[str, ...]) -> dict[str, Any]:
    """Constrain only the benchmark capture call to an exact non-empty partial slice."""

    if not allowed_paths:
        raise ValueError("controlled partial paths are required")
    value = copy.deepcopy(schema)
    branches = value.get("oneOf")
    if not isinstance(branches, list):
        raise ValueError("controlled partial requires the FileBundle union schema")
    bundle = next(
        (
            branch for branch in branches
            if isinstance(branch, dict)
            and branch.get("properties", {}).get("kind", {}).get("const") == "file_bundle"
        ),
        None,
    )
    if bundle is None:
        raise ValueError("controlled partial FileBundle branch is unavailable")
    files = bundle["properties"]["files"]
    files["minItems"] = len(allowed_paths)
    files["maxItems"] = len(allowed_paths)
    files["items"]["properties"]["path"] = {"enum": list(allowed_paths)}
    return value


class _ControlledPartialCaptureClient:
    """Make one real Provider call whose schema guarantees the paired partial condition."""

    def __init__(self, client: GatewayCompletionClient, allowed_paths: tuple[str, ...]):
        self.client = client
        self.allowed_paths = allowed_paths
        self.completion: ProviderCompletion | None = None

    def complete(self, *, system: str, user: str, schema_name: str, schema: dict[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        if self.completion is not None:
            raise RuntimeError("controlled partial capture permits exactly one Provider call")
        controlled = _controlled_partial_schema(schema, self.allowed_paths)
        completion = self.client.complete(
            system=system, user=user, schema_name=schema_name, schema=controlled, config=config,
        )
        value = parse_json_object(completion.text)
        paths = tuple(str(item.get("path") or "") for item in value.get("files", ()))
        if value.get("kind") != "file_bundle" or set(paths) != set(self.allowed_paths):
            raise RuntimeError("Provider did not satisfy the controlled first-partial condition")
        receipt = dict(completion.selection_receipt)
        receipt["benchmark_control"] = {
            "kind": "CONTROLLED_FIRST_PARTIAL",
            "allowed_paths": list(self.allowed_paths),
            "schema_changed_for_capture_only": True,
        }
        self.completion = ProviderCompletion(
            completion.text, completion.model, completion.request_id, dict(completion.usage),
            completion.attempts, receipt, dict(completion.transport_metadata),
        )
        return self.completion


class _ReplayFirstThenLiveClient:
    """Replay the pair's exact capture once, then use policy-specific live transport."""

    def __init__(self, first: ProviderCompletion, live: GatewayCompletionClient):
        self.first = first
        self.live = live
        self.calls = 0

    def complete(self, *, system: str, user: str, schema_name: str, schema: dict[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        self.calls += 1
        if self.calls == 1:
            return self.first
        return self.live.complete(
            system=system, user=user, schema_name=schema_name, schema=schema, config=config,
        )


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
    harness_source = _source_commit()
    product_source = _validated_product_source_commit()
    if subprocess.check_output(["git", "status", "--short", "--untracked-files=no"], cwd=ROOT, text=True).strip():
        raise RuntimeError("materialization benchmark requires a frozen clean Source Closure")
    base_client = completion_client_from_environment()
    if not isinstance(base_client, GatewayCompletionClient):
        raise RuntimeError("materialization benchmark requires the reviewed local Gateway route")
    pricing = _load_pricing_snapshot(pricing_path, provider)
    destination = artifact_root / harness_source / "materialization_benchmark"
    destination.mkdir(parents=True, exist_ok=True)
    policies: dict[str, list[dict[str, Any]]] = {"M0_FULL_RETRY": [], "M1_INCREMENTAL": []}
    unit = BlueprintUnit(
        "tests", "public CSV cleaner tests", "tests",
        ("tests/__init__.py", "tests/test_cleaner.py", "tests/test_cli.py"),
        reads=("csv_cleaner/cleaner.py", "csv_cleaner/cli.py"),
        executor_ref="llm.cheap@1",
        instruction=(
            "Create all three cohesive pytest package files. Cover dedupe_rows, fill_empty, and the CLI main entrypoint. "
            "Keep every test deterministic, offline, and compatible with the declared interfaces."
        ),
        required_interfaces=(
            "csv_cleaner.cleaner.dedupe_rows", "csv_cleaner.cleaner.fill_empty", "csv_cleaner.cli.main",
        ),
        acceptance=("all three owned files are complete, syntactically valid, and pytest passes",),
        allowed_effects=("filesystem.read", "filesystem.write"), max_actions=3, max_files=3,
    )
    config = ModelRoleConfig(
        "worker", provider, timeout_seconds=150, max_output_tokens=6000, temperature=0.0,
        reasoning_effort="none", task_class="project.codegen", operation="EXECUTE",
        outer_deadline_seconds=180, deadline_reserve_seconds=30, thinking_mode="disabled",
    )

    def prepare(workspace: pathlib.Path) -> None:
        (workspace / "csv_cleaner").mkdir(parents=True, exist_ok=False)
        (workspace / "csv_cleaner" / "cleaner.py").write_text(
            "def dedupe_rows(header, rows, column=None):\n"
            "    index = header.index(column) if column else None\n"
            "    seen = set(); result = []\n"
            "    for row in rows:\n"
            "        key = row[index] if index is not None else tuple(row)\n"
            "        if key not in seen:\n"
            "            seen.add(key); result.append(list(row))\n"
            "    return result\n\n"
            "def fill_empty(header, rows, value):\n"
            "    return [[value if cell == '' else cell for cell in row] for row in rows]\n",
            encoding="utf-8",
        )
        (workspace / "csv_cleaner" / "cli.py").write_text(
            "def main(argv=None):\n    return 0\n", encoding="utf-8",
        )

    def request(run_id: str) -> BlockExecutionRequest:
        return BlockExecutionRequest(
            "materialization_tests_probe", run_id, "attempt-1", unit.unit_id,
            "project.unit.tests@1", "llm.cheap@1",
            TaskContext(
                unit.instruction, node_config={"unit": unit.as_dict()},
                dependency_results={"core": {"public_interfaces": list(unit.required_interfaces)}},
                project_constraints=("offline", "no hidden acceptance"), acceptance=unit.acceptance,
            ),
        )

    pairs: list[dict[str, Any]] = []
    first_partial_paths = unit.owns[:2]
    for index in range(1, repeat + 1):
        pair_id = f"controlled-pair-{index}-{uuid.uuid4().hex[:8]}"
        capture_workspace = destination / pair_id / "capture-workspace"
        prepare(capture_workspace)
        capture_client = _ControlledPartialCaptureClient(
            base_client.bind_run(f"{pair_id}-capture", "materialization_tests_probe", budget_purpose="GENERATION"),
            first_partial_paths,
        )
        capture_executor = BlueprintUnitExecutor(
            capture_workspace, capture_client, config, materialization_policy="FULL_RETRY",
        )
        capture_block = capture_executor.execute(request(f"{pair_id}-capture"))
        if capture_client.completion is None or capture_block.succeeded:
            raise RuntimeError("controlled capture did not produce the required partial failure")
        captured = capture_client.completion
        captured_value = parse_json_object(captured.text)
        captured_files = {
            str(item["path"]): str(item["content"])
            for item in captured_value.get("files", ())
        }
        capture_hash = "sha256:" + hashlib.sha256(captured.text.encode("utf-8")).hexdigest()
        pair = {
            "pair_id": pair_id,
            "capture": {
                "status": "PASS", "actual_current_provider_call": True,
                "response_hash": capture_hash, "returned_paths": list(first_partial_paths),
                "usage": dict(captured.usage), "request_id": captured.request_id,
                "selection_receipt": dict(captured.selection_receipt),
                "token_evidence": "REAL_CURRENT_PROVIDER_USAGE",
            },
            "policies": {},
        }
        for label, policy in (("M0_FULL_RETRY", "FULL_RETRY"), ("M1_INCREMENTAL", "INCREMENTAL")):
            run_id = f"{label.lower()}-{index}-{uuid.uuid4().hex[:8]}"
            workspace = destination / pair_id / label.lower() / "workspace"
            prepare(workspace)
            replay = _ReplayFirstThenLiveClient(
                captured,
                base_client.bind_run(run_id, "materialization_tests_probe", budget_purpose="GENERATION"),
            )
            executor = BlueprintUnitExecutor(workspace, replay, config, materialization_policy=policy)
            started = time.perf_counter()
            block = executor.execute(request(run_id))
            while (
                policy == "FULL_RETRY" and not block.succeeded and len(executor.calls) < 3
                and block.error is not None and block.error.details.get("failure_type") == "UNIT_OUTPUT_INCOMPLETE"
            ):
                block = executor.execute(request(run_id))
            if executor.calls:
                executor.calls[0].update({
                    "benchmark_evidence_mode": "REPLAYED_CURRENT_PAIR_CAPTURE",
                    "actual_current_provider_call": False,
                    "counterfactual_token_basis": "REAL_CURRENT_PAIR_CAPTURE_USAGE",
                    "controlled_capture_response_hash": capture_hash,
                    # FULL_RETRY rejects the partial before production records
                    # returned paths.  Preserve the controlled capture facts in
                    # the benchmark ledger so duplicate-work metrics remain
                    # symmetric with INCREMENTAL.
                    "returned_paths": list(captured_files),
                    "returned_bytes_by_path": {
                        path: len(content.encode("utf-8"))
                        for path, content in captured_files.items()
                    },
                    "missing_paths_after_call": [
                        path for path in unit.owns if path not in captured_files
                    ],
                })
            for call in executor.calls[1:]:
                call["benchmark_evidence_mode"] = "LIVE_POLICY_CALL"
                call["actual_current_provider_call"] = True
            files = [path for path in unit.owns if (workspace / pathlib.PurePosixPath(path)).is_file()]
            syntax = block.succeeded and all(
                subprocess.run(
                    [sys.executable, "-m", "py_compile", str(workspace / pathlib.PurePosixPath(path))],
                    capture_output=True, text=True,
                ).returncode == 0
                for path in unit.owns
            )
            pytest_run = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"], cwd=workspace,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            receipts = bool(executor.calls) and all(bool(call.get("selection_receipt_hash")) for call in executor.calls)
            success = (
                block.succeeded and len(files) == len(unit.owns) and syntax and receipts
                and pytest_run.returncode == 0
            )
            row = {
                "run_id": run_id, "pair_id": pair_id, "policy": policy,
                "status": "PASS" if success else "FAIL",
                "product_source_commit": product_source,
                "experiment_harness_commit": harness_source,
                "provider": provider, "calls": executor.calls, "files": files,
                "syntax": syntax, "pytest": "PASS" if pytest_run.returncode == 0 else "FAIL",
                "pytest_stdout": pytest_run.stdout[-2000:],
                "controlled_first_partial": {
                    "same_pair_response_hash": capture_hash,
                    "returned_paths": list(first_partial_paths),
                    "missing_paths": list(unit.owns[2:]),
                    "response_replayed": True,
                    "token_evidence": "REAL_CAPTURED_USAGE_REPLAYED_COUNTERFACTUALLY",
                    "current_run_incurred_provider_cost": False,
                },
                "actual_current_provider_calls": max(0, len(executor.calls) - 1),
                "counterfactual_policy_calls": len(executor.calls),
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "metrics": _materialization_metrics(
                    executor.calls, final_file_count=len(unit.owns), success=success, pricing=pricing,
                ),
                "block_result": block.as_dict(),
            }
            (destination / f"{run_id}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8",
            )
            policies[label].append(row)
            pair["policies"][label] = {
                "run_id": run_id, "status": row["status"],
                "first_response_hash": capture_hash, "counterfactual_policy_calls": len(executor.calls),
            }
        pairs.append(pair)
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
        "product_source_commit": product_source,
        "experiment_harness_commit": harness_source,
        "repeat": repeat, "pricing_snapshot": pricing,
        "cost_evaluated": pricing is not None, "policies": policies, "summary": summary,
        "controlled_pairs": pairs,
        "first_partial_control": {
            "method": "one real schema-constrained capture per pair, replayed once into each policy",
            "same_prompt_foundation": True,
            "same_first_partial_within_pair": True,
            "capture_tokens": "real current Provider usage",
            "policy_first_call_tokens": "counterfactual replay of the pair capture",
            "policy_followup_tokens": "real current Provider usage",
            "actual_cost_note": "capture cost is incurred once per pair; per-policy totals model the mutually exclusive counterfactuals",
        },
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
