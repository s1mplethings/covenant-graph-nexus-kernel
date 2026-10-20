from __future__ import annotations

import argparse
import ast
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
from cgkn.application.materialization import materialize_json
from cgkn.application.project_loop import BlueprintUnitExecutor, MinimalProjectLoop
from cgkn.application.software_project.catalog import get_case
from cgkn.execution import BlockExecutionRequest, TaskContext
from cgkn.providers import (
    CGKNModelRouting, GatewayCompletionClient, ModelRoleConfig, ProviderCompletion,
    completion_client_from_environment,
)
from cgkn.providers.gateway_client import API_LAB_COMMIT
from cgkn.providers.structured_output import SELECTOR_VERSION, StructuredAnswerSelector


PHASE_B_PROFILES = {"fake-parallel", "fake-conflict", "fake-standup", "live-parallel"}


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _summarize_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    def token(call: dict[str, Any], name: str) -> int | None:
        value = call.get(name)
        if value is None:
            value = dict(call.get("usage") or {}).get(name)
        return int(value) if isinstance(value, int) else None

    def total(name: str) -> int | None:
        values = [token(call, name) for call in calls]
        return sum(value for value in values if value is not None) if calls and all(value is not None for value in values) else (0 if not calls else None)

    failed = sum(call.get("unit_result") == "FAILED" or call.get("result") == "FAILED" for call in calls)
    return {
        "logical_calls": len(calls), "successful_calls": len(calls) - failed, "failed_calls": failed,
        "prompt_tokens": total("prompt_tokens"), "completion_tokens": total("completion_tokens"),
        "cached_tokens": total("cached_tokens"), "reasoning_tokens": total("reasoning_tokens"),
        "finish_reasons": [call.get("finish_reason") or dict(call.get("selection_receipt") or {}).get("finish_reason") for call in calls],
        "transport_attempts": [call.get("transport_attempts") for call in calls],
    }


def _source_identity() -> dict[str, Any]:
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--short", "--untracked-files=no"], cwd=ROOT, text=True,
    ).strip()
    return {"cgkn_source_commit": sha, "tracked_worktree_clean": not bool(dirty)}


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


def _coordinator_model_config(provider: str = "deepseek") -> ModelRoleConfig:
    return ModelRoleConfig(
        role="agent", model=provider, timeout_seconds=150, max_output_tokens=3500,
        temperature=0.0, reasoning_effort="none", task_class="project.blueprint",
        operation="BLUEPRINT_DESIGN", outer_deadline_seconds=180,
        deadline_reserve_seconds=30, thinking_mode="disabled",
    )


def _worker_generation_model_config(provider: str = "deepseek") -> ModelRoleConfig:
    return ModelRoleConfig(
        role="worker", model=provider, timeout_seconds=150, max_output_tokens=6000,
        temperature=0.0, reasoning_effort="none", task_class="project.codegen",
        operation="EXECUTE", outer_deadline_seconds=180, deadline_reserve_seconds=30,
        thinking_mode="disabled",
    )


def _worker_repair_model_config(provider: str = "deepseek") -> ModelRoleConfig:
    return ModelRoleConfig(
        role="worker", model=provider, timeout_seconds=150, max_output_tokens=6000,
        temperature=0.0, reasoning_effort="none", task_class="project.codegen",
        operation="REPAIR", outer_deadline_seconds=180, deadline_reserve_seconds=30,
        thinking_mode="default",
    )


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
    agent_config = _coordinator_model_config(agent_provider)
    worker_config = _worker_generation_model_config(routing.worker.model)
    worker_repair_config = _worker_repair_model_config(routing.worker.model)
    loop = MinimalProjectLoop(ROOT, artifact_root, run_client, agent_config, worker_config, worker_repair_config)
    contract = _public_contract(case_id)
    blueprint, decisions = loop.design(case_id, contract)
    workspace = artifact_root / "workspaces" / run_token
    initial_failure = None
    if case_id == "seeded_repair":
        shutil.copytree(ROOT / get_case(case_id).seeded_fixture, workspace)
        owners = [unit.unit_id for unit in blueprint.units if "math_utils.py" in unit.owns]
        if len(owners) != 1: raise ValueError("seeded repair blueprint must have one math_utils.py owner")
        initial_failure = FailureReport(owners[0], "TEST_FAILURE", failure_stage=FailureStage.TEST.value, owner_unit_id=owners[0], recovery_action=FailureAction.REPAIR_EXISTING.value, materialized_baseline=True, owner_file="math_utils.py", owner_interface="add(a,b)", first_project_frame="math_utils.py:2", failed_check="initial pytest", expected="add(2,3) == 5", observed="add(2,3) == -1", affected_units=(owners[0],), suggested_action="patch subtraction to addition while preserving add(a,b)", evidence_refs=("initial_test",))
    outcome = loop.run(blueprint, workspace, case_id=case_id, initial_failure=initial_failure)
    worker_calls = list(json.loads((outcome.run_root / "provider_calls.json").read_text(encoding="utf-8")).get("calls") or ())
    coordinator_calls = list(loop.coordinator_calls)
    attribution_calls = list(loop.attribution_calls)
    generations = [call for call in worker_calls if call.get("call_class") == "GENERATION"]
    continuations = [call for call in worker_calls if call.get("call_class") == "GENERATION_CONTINUATION"]
    generation_retries = [call for call in worker_calls if call.get("call_class") == "GENERATION_RETRY"]
    repairs = [call for call in worker_calls if call.get("call_class") == "REPAIR"]
    ledger = {
        "coordinator_design": _summarize_calls(coordinator_calls),
        "coordinator_attribution": _summarize_calls(attribution_calls),
        "generation": _summarize_calls(generations),
        "generation_continuation": _summarize_calls(continuations),
        "generation_retry": _summarize_calls(generation_retries),
        "repair": _summarize_calls(repairs),
        "calls": {"coordinator_design": coordinator_calls, "coordinator_attribution": attribution_calls, "worker": worker_calls},
    }
    value = outcome.as_dict() | {"agent_decisions": decisions + len(attribution_calls), "design_calls": decisions, "attribution_calls": len(attribution_calls), "total_logical_calls": decisions + outcome.provider_calls, "manual_edits": 0, "profile": profile, "provider_ledger": ledger}
    target = outcome.run_root / f"{profile}_receipt.json"; target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def _coordinator_receipt_complete(call: dict[str, Any]) -> bool:
    receipt = call.get("selection_receipt")
    if not isinstance(receipt, dict):
        return False
    required_text = (
        "selected_candidate_hash", "raw_response_hash", "schema_hash", "prompt_hash",
        "api_lab_commit", "selector_version", "blueprint_hash",
    )
    return (
        receipt.get("final_status") == "ACCEPTED"
        and receipt.get("schema_valid_candidate_count") == 1
        and receipt.get("selected_candidate_index") is not None
        and all(str(receipt.get(key) or "").strip() for key in required_text)
    )


def _coordinator_qualify(
    artifact_root: pathlib.Path,
    *,
    count: int,
    provider: str,
    diagnostic: bool = False,
) -> dict[str, Any]:
    expected = 1 if diagnostic else 3
    if count != expected or provider != "deepseek":
        raise ValueError(f"coordinator {'diagnostic' if diagnostic else 'qualification'} requires exactly {expected} DeepSeek run{'s' if expected != 1 else ''}")
    identity = _source_identity()
    if not identity["tracked_worktree_clean"]:
        raise RuntimeError("coordinator qualification requires a frozen clean Source Closure")
    base_client = completion_client_from_environment()
    if not isinstance(base_client, GatewayCompletionClient):
        raise RuntimeError("coordinator qualification requires the reviewed API Lab Gateway route")
    contract = _public_contract("cli_csv_cleaner")
    runs: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        run_id = f"coordinator-qualify-{index}-{uuid.uuid4().hex[:10]}"
        started = time.perf_counter()
        row: dict[str, Any] = {"run_id": run_id, "provider": provider, "logical_calls": 1}
        try:
            client = base_client.bind_run(run_id, "cli_csv_cleaner", budget_purpose="PLANNING")
            agent = _coordinator_model_config(provider)
            worker = ModelRoleConfig("worker", "deepseek")
            loop = MinimalProjectLoop(ROOT, artifact_root / "coordinator", client, agent, worker)
            blueprint, decisions = loop.design("cli_csv_cleaner", contract)
            call = loop.coordinator_calls[-1]
            receipt = dict(call.get("selection_receipt") or {})
            serialized_blueprint = json.dumps(blueprint.as_dict(), ensure_ascii=False)
            no_source = not any(marker in serialized_blueprint for marker in ("```", "\ndef ", "\nclass "))
            row.update({
                "model": call.get("model"), "request_id": call.get("request_id"),
                "transport_attempts": call.get("transport_attempts"),
                "effective_timeout": receipt.get("effective_request_timeout_seconds"),
                "finish_reason": receipt.get("finish_reason"), "usage": receipt.get("usage"),
                "thinking_mode": receipt.get("thinking_mode"),
                "thinking_mode_forwarded": call.get("transport_metadata", {}).get("thinking_mode_forwarded"),
                "reasoning_effort": receipt.get("reasoning_effort"),
                "reasoning_tokens": receipt.get("reasoning_tokens"),
                "cached_tokens": receipt.get("cached_tokens"),
                "reasoning_text_present": receipt.get("reasoning_text_present"),
                "reasoning_text_length": receipt.get("reasoning_text_length"),
                "raw_final_content_length": receipt.get("raw_length"),
                "candidate_count": receipt.get("json_candidate_count"),
                "valid_candidate_count": receipt.get("schema_valid_candidate_count"),
                "selection_receipt": receipt, "selection_receipt_hash": _hash(receipt),
                "blueprint": blueprint.as_dict(), "blueprint_hash": blueprint.blueprint_hash,
                "unit_count": len(blueprint.units), "check_count": len(blueprint.checks),
                "agent_decisions": decisions, "no_source_code": no_source,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            })
            row["status"] = "PASS" if (
                _coordinator_receipt_complete(call)
                and 2 <= len(blueprint.units) <= 4
                and len(blueprint.checks) == 4
                and no_source
                and int(call.get("transport_attempts") or 0) <= 2
            ) else "FAIL"
        except Exception as exc:
            evidence = dict(getattr(exc, "evidence", {}) or {})
            row.update({
                "status": "FAIL", "error_type": str(getattr(exc, "category", type(exc).__name__)),
                "redacted_error": str(exc)[:1000], "selection_receipt": evidence,
                "selection_receipt_hash": _hash(evidence) if evidence else None,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            })
        target = artifact_root / "coordinator_qualification" / f"{run_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(row | identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        runs.append(row)
    passed = all(row["status"] == "PASS" for row in runs)
    result = {
        "profile": "coordinator-diagnostic" if diagnostic else "coordinator-qualify",
        "status": ("PASS" if passed else "DIAGNOSTIC_FAILED") if diagnostic else ("PASS" if passed else "COORDINATOR_NOT_QUALIFIED"),
        "qualification": None if diagnostic else ("3/3" if passed else f"{sum(row['status'] == 'PASS' for row in runs)}/3"),
        "provider": provider, "model_limits": {"temperature": 0, "max_output_tokens": 3500, "configured_timeout": 150, "outer_deadline": 180, "reserve": 30},
        "source_identity": identity, "runs": runs,
    }
    index = artifact_root / "coordinator_qualification" / ("diagnostic_index.json" if diagnostic else "index.json")
    index.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _worker_receipt_complete(call: dict[str, Any]) -> bool:
    receipt = call.get("selection_receipt")
    required = (
        "selected_candidate_hash", "raw_response_hash", "schema_hash", "prompt_hash",
        "api_lab_commit", "selector_version",
    )
    return isinstance(receipt, dict) and receipt.get("final_status") == "ACCEPTED" and receipt.get("schema_valid_candidate_count") == 1 and receipt.get("selected_candidate_index") is not None and all(str(receipt.get(key) or "").strip() for key in required)


def _worker_probe(artifact_root: pathlib.Path, *, patch_mode: bool) -> dict[str, Any]:
    identity = _source_identity()
    if not identity["tracked_worktree_clean"]:
        raise RuntimeError("worker qualification requires a frozen clean Source Closure")
    base_client = completion_client_from_environment()
    if not isinstance(base_client, GatewayCompletionClient):
        raise RuntimeError("worker qualification requires the reviewed API Lab Gateway route")
    probe = "patch" if patch_mode else "file"
    run_id = f"worker-{probe}-probe-{uuid.uuid4().hex[:10]}"
    workspace = artifact_root / "worker_qualification" / run_id / "workspace"
    workspace.mkdir(parents=True, exist_ok=False)
    client = base_client.bind_run(run_id, f"worker_{probe}_probe", budget_purpose="REPAIR" if patch_mode else "GENERATION")
    worker_config = ModelRoleConfig(
        role="worker", model="deepseek", timeout_seconds=150, max_output_tokens=6000,
        temperature=0.0, reasoning_effort="none", task_class="project.codegen",
        operation="REPAIR" if patch_mode else "EXECUTE", outer_deadline_seconds=180,
        deadline_reserve_seconds=30,
    )
    if patch_mode:
        (workspace / "math_utils.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (workspace / "test_math_utils.py").write_text("from math_utils import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
        unit = BlueprintUnit(
            "repair_add", "repair addition", "implementation", ("math_utils.py",),
            reads=("test_math_utils.py",), executor_ref="llm.cheap@1",
            instruction="Make the smallest patch so add(a, b) returns their sum.",
            required_interfaces=("add",), acceptance=("pytest passes",),
            allowed_effects=("filesystem.read", "filesystem.write"),
        )
    else:
        unit = BlueprintUnit(
            "hello_file", "generate hello application", "implementation", ("hello_app.py",),
            executor_ref="llm.cheap@1",
            instruction="Create a standard-library Python file that prints exactly HELLO_CGKN followed by a newline when run.",
            required_interfaces=(), acceptance=("prints HELLO_CGKN",),
            allowed_effects=("filesystem.read", "filesystem.write"),
        )
    executor = BlueprintUnitExecutor(workspace, client, worker_config)
    if patch_mode:
        executor.failure_reports[unit.unit_id] = FailureReport(
            unit.unit_id, "TEST_FAILURE", failure_stage=FailureStage.TEST.value,
            owner_unit_id=unit.unit_id, recovery_action=FailureAction.REPAIR_EXISTING.value,
            materialized_baseline=True, owner_file="math_utils.py", owner_interface="add(a,b)",
            first_project_frame="math_utils.py:2", failed_check="pytest", expected="add(2,3) == 5",
            observed="add(2,3) == -1", affected_units=(unit.unit_id,),
            suggested_action="replace subtraction with addition and preserve add(a,b)", evidence_refs=("pytest",),
        )
        executor.register_materialized_baseline(unit)
    request = BlockExecutionRequest(
        project_id=f"worker_{probe}_probe", run_id=run_id, attempt_id="attempt-1",
        node_id=unit.unit_id, component_ref=f"project.unit.{'implementation' if not patch_mode else 'implementation'}@1",
        executor_ref="llm.cheap@1",
        task_context=TaskContext(
            unit.instruction, node_config={"unit": unit.as_dict()},
            project_constraints=("stdlib only", "offline"), acceptance=unit.acceptance,
        ),
        timeout_seconds=150, declared_effects=unit.allowed_effects,
    )
    started = time.perf_counter()
    result = executor.execute(request)
    call = executor.calls[-1] if executor.calls else {}
    receipt = dict(call.get("selection_receipt") or {})
    syntax = False
    runtime = False
    pytest_passed = False
    interface_guard = result.succeeded and "interface guard" not in str(result.as_dict())
    if result.succeeded and not patch_mode:
        compiled = subprocess.run([sys.executable, "-m", "py_compile", str(workspace / "hello_app.py")], capture_output=True, text=True)
        syntax = compiled.returncode == 0
        ran = subprocess.run([sys.executable, str(workspace / "hello_app.py")], capture_output=True, text=True)
        runtime = ran.returncode == 0 and ran.stdout == "HELLO_CGKN\n"
    elif result.succeeded:
        tested = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=workspace, capture_output=True, text=True, env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        pytest_passed = tested.returncode == 0
    passed = result.succeeded and _worker_receipt_complete(call) and len(executor.calls) == 1 and (pytest_passed and interface_guard if patch_mode else syntax and runtime)
    outcome = {
        "profile": f"worker-{probe}-probe", "run_id": run_id,
        "provider": "deepseek", "model": call.get("model"), "logical_calls": len(executor.calls),
        "tokens": {
            "input": call.get("prompt_tokens"), "output": call.get("completion_tokens"),
            "cached": call.get("cached_tokens"), "reasoning": call.get("reasoning_tokens"),
            "total": call.get("total_tokens"), "usage_status": call.get("usage_status"),
        },
        "finish_reason": call.get("finish_reason"),
        "transport_attempts": call.get("transport_attempts"),
        "provider_call": call, "selection_receipt": receipt,
        "selection_receipt_hash": _hash(receipt) if receipt else None,
        "scope": "PASS" if result.succeeded else "FAIL", "syntax": syntax,
        "runtime": runtime, "interface_guard": interface_guard, "pytest": pytest_passed,
        "block_result": result.as_dict(), "duration_ms": int((time.perf_counter() - started) * 1000),
        "status": "PASS" if passed else "WORKER_NOT_QUALIFIED", "source_identity": identity,
    }
    target = artifact_root / "worker_qualification" / f"{run_id}.json"
    target.write_text(json.dumps(outcome, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return outcome


def _required_interfaces_present(workspace: pathlib.Path, unit: BlueprintUnit) -> bool:
    definitions: set[str] = set()
    for relative in unit.owns:
        target = workspace / pathlib.PurePosixPath(relative)
        if target.suffix != ".py" or not target.is_file():
            continue
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=relative)
        definitions.update(node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    required = {
        item.split("(", 1)[0].rsplit(".", 1)[-1]
        for item in unit.required_interfaces if str(item).strip()
    }
    return required <= definitions


class _AcceptedBundleReplayClient:
    """Re-run accepted raw Provider text through the current selector without network I/O."""

    def __init__(self, evidence: dict[str, Any]):
        self.evidence = evidence
        self.replay_invocations = 0
        self.identity: dict[str, Any] = {}

    def complete(self, *, system: str, user: str, schema_name: str, schema: dict[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        self.replay_invocations += 1
        if self.replay_invocations != 1:
            raise RuntimeError("accepted bundle replay permits exactly one deterministic invocation")
        call = dict(self.evidence.get("provider_call") or {})
        receipt = dict(call.get("selection_receipt") or {})
        metadata = dict(call.get("transport_metadata") or {})
        raw_text = str(metadata.get("raw_text") or "")
        prompt_hash = "sha256:" + hashlib.sha256(
            json.dumps({"system": system, "user": user}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        selected, replay_receipt = StructuredAnswerSelector().select(
            raw_text, schema, schema_name=schema_name,
            provider_id=str(receipt.get("provider_id") or call.get("provider") or ""),
            model=str(receipt.get("model") or call.get("model") or ""),
            task_class=config.task_class, operation=config.operation, prompt_hash=prompt_hash,
            transport_attempts=0, usage_status=str(receipt.get("usage_status") or "REPORTED"),
            configured_timeout_seconds=config.timeout_seconds,
            max_output_tokens=config.max_output_tokens, finish_reason=str(receipt.get("finish_reason") or ""),
            usage=dict(receipt.get("usage") or {}), api_lab_commit=API_LAB_COMMIT,
            api_lab_contract_version=str(receipt.get("api_lab_contract_version") or ""),
            route_mode=str(receipt.get("route_mode") or "raw_defer"), request_id=str(receipt.get("request_id") or ""),
            thinking_mode=config.thinking_mode, reasoning_effort=config.reasoning_effort,
            reasoning_tokens=receipt.get("reasoning_tokens"),
            reasoning_text_present=bool(receipt.get("reasoning_text_present")),
            reasoning_text_length=int(receipt.get("reasoning_text_length") or 0),
            prompt_tokens=receipt.get("prompt_tokens"), completion_tokens=receipt.get("completion_tokens"),
            total_tokens=receipt.get("total_tokens"), cached_tokens=receipt.get("cached_tokens"),
        )
        checks = {
            "provider": str(call.get("provider") or "") == "deepseek",
            "model": str(call.get("model") or "") == "deepseek-flash",
            "thinking_mode": config.thinking_mode == receipt.get("thinking_mode") == "disabled",
            "reasoning_effort": config.reasoning_effort == receipt.get("reasoning_effort") == "none",
            "operation": config.operation == receipt.get("operation") == "EXECUTE",
            "prompt_hash": replay_receipt.prompt_hash == receipt.get("prompt_hash"),
            "schema_hash": replay_receipt.schema_hash == receipt.get("schema_hash"),
            "raw_response_hash": replay_receipt.raw_response_hash == receipt.get("raw_response_hash"),
            "selected_candidate_hash": replay_receipt.selected_candidate_hash == receipt.get("selected_candidate_hash"),
            "candidate_count": replay_receipt.json_candidate_count == receipt.get("json_candidate_count") == 1,
            "valid_candidate_count": replay_receipt.schema_valid_candidate_count == receipt.get("schema_valid_candidate_count") == 1,
            "api_lab_commit": receipt.get("api_lab_commit") == API_LAB_COMMIT,
            "selector_version": receipt.get("selector_version") == SELECTOR_VERSION,
            "finish_reason": receipt.get("finish_reason") == "stop",
        }
        self.identity = {
            "checks": checks,
            "hashes": {
                "prompt_hash": prompt_hash, "schema_hash": replay_receipt.schema_hash,
                "raw_response_hash": replay_receipt.raw_response_hash,
                "selected_candidate_hash": replay_receipt.selected_candidate_hash,
            },
        }
        failed = sorted(key for key, value in checks.items() if value is not True)
        if failed:
            raise ValueError("PROVIDER_EVIDENCE_IDENTITY_MISMATCH:" + ",".join(failed))
        return ProviderCompletion(
            json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            str(call.get("model") or "deepseek-flash"), str(call.get("request_id") or ""),
            dict(receipt.get("usage") or {}), 0, receipt,
            {"evidence_replay": True, "external_provider_calls": 0},
        )


def _worker_cohesive_replay(artifact_root: pathlib.Path, *, replay_index: pathlib.Path) -> dict[str, Any]:
    identity = _source_identity()
    if not identity["tracked_worktree_clean"]:
        raise RuntimeError("worker evidence replay requires a frozen clean Source Closure")
    prior = json.loads(replay_index.read_text(encoding="utf-8"))
    prior_runs = list(prior.get("runs") or ())
    if len(prior_runs) != 3:
        raise ValueError("worker evidence replay requires exactly three prior runs")
    blueprint_path = pathlib.Path(str(prior.get("blueprint_path") or "")).resolve()
    blueprint = ProjectBlueprint.from_dict(json.loads(blueprint_path.read_text(encoding="utf-8")))
    implementations = [item for item in blueprint.units if item.kind == "implementation"]
    if not implementations:
        raise ValueError("replay blueprint has no implementation unit")
    unit = implementations[0]
    unit_hash = _hash(unit.as_dict())
    constraints_hash = _hash({"constraints": list(blueprint.constraints)})
    interface_hash = _hash({"required_interfaces": list(unit.required_interfaces)})
    output_rows: list[dict[str, Any]] = []
    for index, prior_row in enumerate(prior_runs, 1):
        run_id = f"worker-cohesive-replay-{index}-{uuid.uuid4().hex[:10]}"
        workspace = artifact_root / "worker_scope_replay" / run_id / "workspace"
        workspace.mkdir(parents=True, exist_ok=False)
        semantic_checks = {
            "blueprint_hash": prior_row.get("blueprint_hash") == blueprint.blueprint_hash,
            "unit_hash": prior_row.get("unit_hash") == unit_hash,
            "unit_semantics": prior_row.get("unit") == unit.as_dict(),
            "api_lab_commit": prior_row.get("api_lab_commit") == API_LAB_COMMIT,
        }
        if not all(semantic_checks.values()):
            failed = sorted(key for key, value in semantic_checks.items() if not value)
            raise ValueError("PROVIDER_EVIDENCE_SEMANTIC_IDENTITY_MISMATCH:" + ",".join(failed))
        replay_client = _AcceptedBundleReplayClient(prior_row)
        executor = BlueprintUnitExecutor(workspace, replay_client, _worker_generation_model_config("deepseek"))
        request = BlockExecutionRequest(
            project_id=blueprint.project_id, run_id=run_id, attempt_id="replay-1",
            node_id=unit.unit_id, component_ref="project.unit.implementation@1", executor_ref="llm.cheap@1",
            task_context=TaskContext(
                unit.instruction or unit.purpose, node_config={"unit": unit.as_dict()},
                dependency_results={}, project_constraints=blueprint.constraints, acceptance=unit.acceptance,
            ),
            timeout_seconds=unit.timeout_seconds, declared_effects=unit.allowed_effects,
        )
        started = time.perf_counter()
        result = executor.execute(request)
        files = [path for path in unit.owns if (workspace / pathlib.PurePosixPath(path)).is_file()]
        syntax = result.succeeded and all(
            not path.endswith(".py") or subprocess.run(
                [sys.executable, "-m", "py_compile", str(workspace / pathlib.PurePosixPath(path))],
                capture_output=True, text=True,
            ).returncode == 0
            for path in unit.owns
        )
        interface = result.succeeded and _required_interfaces_present(workspace, unit)
        identity_checks = dict(replay_client.identity.get("checks") or {})
        passed = result.succeeded and len(files) == len(unit.owns) == 4 and syntax and interface and all(identity_checks.get(key) is True for key in (
            "provider", "model", "thinking_mode", "reasoning_effort", "operation", "prompt_hash", "schema_hash",
            "raw_response_hash", "selected_candidate_hash", "candidate_count", "valid_candidate_count",
            "api_lab_commit", "selector_version", "finish_reason",
        ))
        row = {
            "run_id": run_id, "prior_run_id": prior_row.get("run_id"), "status": "PASS" if passed else "FAIL",
            "provider_evidence_reused": True, "external_provider_calls": 0,
            "deterministic_replay_invocations": replay_client.replay_invocations,
            "source_commit": identity["cgkn_source_commit"], "prior_source_commit": prior_row.get("source_commit"),
            "blueprint_hash": blueprint.blueprint_hash, "unit_hash": unit_hash,
            "public_constraints_hash": constraints_hash, "interface_contract_hash": interface_hash,
            "provider_identity": replay_client.identity, "semantic_identity": semantic_checks,
            "selection_receipt_hash": prior_row.get("selection_receipt_hash"),
            "file_count": len(files), "files": files,
            "scope": "PASS" if result.succeeded else "FAIL", "syntax": "PASS" if syntax else "FAIL",
            "interface": "PASS" if interface else "FAIL", "atomic_apply": "PASS" if len(files) == len(unit.owns) else "FAIL",
            "no_undeclared_write": set(files) == set(unit.owns), "block_result": result.as_dict(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        target = artifact_root / "worker_scope_replay" / f"{run_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output_rows.append(row)
    passed = all(row["status"] == "PASS" for row in output_rows)
    result = {
        "profile": "worker-cohesive-replay", "status": "PASS" if passed else "WORKER_SCOPE_REPLAY_FAILED",
        "qualification": "3/3" if passed else f"{sum(row['status'] == 'PASS' for row in output_rows)}/3",
        "provider_evidence_reused": True, "external_provider_calls": 0, "provider_calls_saved": 3,
        "replay_index": str(replay_index), "blueprint_path": str(blueprint_path),
        "source_identity": identity, "runs": output_rows,
    }
    index = artifact_root / "worker_scope_replay" / "index.json"
    index.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _worker_real_unit(
    artifact_root: pathlib.Path, *, blueprint_path: pathlib.Path, count: int, diagnostic: bool,
) -> dict[str, Any]:
    expected = 1 if diagnostic else 3
    if count != expected:
        raise ValueError(f"worker real-unit {'diagnostic' if diagnostic else 'qualification'} requires exactly {expected} run(s)")
    identity = _source_identity()
    if not identity["tracked_worktree_clean"]:
        raise RuntimeError("worker real-unit validation requires a frozen clean Source Closure")
    base_client = completion_client_from_environment()
    if not isinstance(base_client, GatewayCompletionClient):
        raise RuntimeError("worker real-unit validation requires the reviewed API Lab Gateway route")
    blueprint = ProjectBlueprint.from_dict(json.loads(blueprint_path.read_text(encoding="utf-8")))
    implementations = [unit for unit in blueprint.units if unit.kind == "implementation"]
    if not implementations:
        raise ValueError("frozen blueprint has no implementation unit")
    unit = implementations[0]
    runs: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        run_id = f"worker-real-unit-{'diagnostic' if diagnostic else 'qualify'}-{index}-{uuid.uuid4().hex[:10]}"
        workspace = artifact_root / "worker_real_unit" / run_id / "workspace"
        workspace.mkdir(parents=True, exist_ok=False)
        client = base_client.bind_run(run_id, blueprint.project_id, budget_purpose="GENERATION")
        worker_config = _worker_generation_model_config("deepseek")
        executor = BlueprintUnitExecutor(workspace, client, worker_config)
        request = BlockExecutionRequest(
            project_id=blueprint.project_id, run_id=run_id, attempt_id="attempt-1",
            node_id=unit.unit_id, component_ref="project.unit.implementation@1", executor_ref="llm.cheap@1",
            task_context=TaskContext(
                unit.instruction or unit.purpose, node_config={"unit": unit.as_dict()},
                dependency_results={}, project_constraints=blueprint.constraints, acceptance=unit.acceptance,
            ),
            timeout_seconds=unit.timeout_seconds, declared_effects=unit.allowed_effects,
        )
        started = time.perf_counter(); result = executor.execute(request)
        call = executor.calls[-1] if executor.calls else {}
        receipt = dict(call.get("selection_receipt") or {})
        file_lengths = {
            relative: len((workspace / pathlib.PurePosixPath(relative)).read_text(encoding="utf-8"))
            for relative in unit.owns if (workspace / pathlib.PurePosixPath(relative)).is_file()
        }
        syntax = result.succeeded
        if result.succeeded:
            for relative in unit.owns:
                target = workspace / pathlib.PurePosixPath(relative)
                if target.suffix == ".py":
                    syntax = syntax and subprocess.run(
                        [sys.executable, "-m", "py_compile", str(target)], capture_output=True, text=True,
                    ).returncode == 0
        interface = result.succeeded and _required_interfaces_present(workspace, unit)
        passed = (
            result.succeeded and _worker_receipt_complete(call) and syntax and interface
            and receipt.get("finish_reason") not in {"length", "max_tokens"}
            and int(receipt.get("completion_tokens") or receipt.get("usage", {}).get("completion_tokens") or 0) < 6000
            and call.get("thinking_mode_requested") == call.get("thinking_mode_forwarded") == "disabled"
        )
        row = {
            "run_id": run_id, "source_commit": identity["cgkn_source_commit"],
            "api_lab_commit": receipt.get("api_lab_commit"), "project_id": blueprint.project_id,
            "blueprint_hash": blueprint.blueprint_hash, "unit_id": unit.unit_id,
            "unit_hash": _hash(unit.as_dict()), "unit": unit.as_dict(),
            "provider": call.get("provider"), "model": call.get("model"),
            "thinking_mode_requested": call.get("thinking_mode_requested"),
            "thinking_mode_forwarded": call.get("thinking_mode_forwarded"),
            "reasoning_effort": call.get("reasoning_effort"), "request_id": call.get("request_id"),
            "transport_attempts": call.get("transport_attempts"),
            "input_context_chars": result.outputs.get("context_chars") if result.succeeded else None,
            "input_tokens": call.get("prompt_tokens"), "output_tokens": call.get("completion_tokens"),
            "reasoning_tokens": call.get("reasoning_tokens"), "cached_tokens": call.get("cached_tokens"),
            "reasoning_text_present": receipt.get("reasoning_text_present"),
            "reasoning_text_length": receipt.get("reasoning_text_length"),
            "finish_reason": call.get("finish_reason"), "raw_final_content_length": receipt.get("raw_length"),
            "json_candidate_count": receipt.get("json_candidate_count"),
            "schema_valid_candidate_count": receipt.get("schema_valid_candidate_count"),
            "file_count": len(file_lengths), "per_file_content_lengths": file_lengths,
            "selection_receipt_hash": call.get("selection_receipt_hash"),
            "syntax": "PASS" if syntax else "FAIL", "scope": "PASS" if result.succeeded else "FAIL",
            "interface": "PASS" if interface else "FAIL", "manual_edits": 0,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "provider_call": call, "block_result": result.as_dict(),
            "status": "PASS" if passed else "FAIL",
        }
        target = artifact_root / "worker_real_unit" / f"{run_id}.json"
        target.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        runs.append(row)
    passed = all(row["status"] == "PASS" for row in runs)
    result = {
        "profile": "worker-real-unit-diagnostic" if diagnostic else "worker-cohesive-qualify",
        "status": "PASS" if passed else "WORKER_COHESIVE_UNIT_NOT_QUALIFIED",
        "qualification": None if diagnostic else ("3/3" if passed else f"{sum(row['status'] == 'PASS' for row in runs)}/3"),
        "source_identity": identity, "blueprint_path": str(blueprint_path), "runs": runs,
    }
    index = artifact_root / "worker_real_unit" / ("diagnostic_index.json" if diagnostic else "qualification_index.json")
    index.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _worker_cohesive_live(artifact_root: pathlib.Path, *, count: int) -> dict[str, Any]:
    if count != 2:
        raise ValueError("worker cohesive live probe requires exactly two independent runs")
    identity = _source_identity()
    if not identity["tracked_worktree_clean"]:
        raise RuntimeError("worker cohesive live probe requires a frozen clean Source Closure")
    base_client = completion_client_from_environment()
    if not isinstance(base_client, GatewayCompletionClient):
        raise RuntimeError("worker cohesive live probe requires the reviewed API Lab Gateway route")
    runs: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        run_id = f"worker-cohesive-live-{index}-{uuid.uuid4().hex[:10]}"
        workspace = artifact_root / "worker_cohesive_live" / run_id / "workspace"
        (workspace / "csv_cleaner").mkdir(parents=True, exist_ok=False)
        (workspace / "csv_cleaner" / "cleaner.py").write_text(
            "def dedupe_rows(header, rows, column=None):\n"
            "    index = header.index(column) if column else None\n"
            "    seen = set(); result = []\n"
            "    for row in rows:\n"
            "        key = row[index] if index is not None else tuple(row)\n"
            "        if key not in seen:\n"
            "            seen.add(key); result.append(row)\n"
            "    return result\n\n"
            "def fill_empty(header, rows, value):\n"
            "    return [[value if item == '' else item for item in row] for row in rows]\n",
            encoding="utf-8",
        )
        (workspace / "csv_cleaner" / "cli.py").write_text(
            "def main(argv=None):\n    return 0\n", encoding="utf-8",
        )
        unit = BlueprintUnit(
            "tests", "public CSV cleaner tests", "tests",
            ("tests/test_cleaner.py", "tests/test_cli.py"),
            reads=("csv_cleaner/cleaner.py", "csv_cleaner/cli.py"),
            executor_ref="llm.cheap@1",
            instruction=(
                "Create cohesive pytest coverage in both owned files. test_cleaner.py covers whole-row and selected-column "
                "dedupe plus fill_empty. test_cli.py covers the public main(argv) entrypoint. Use only stdlib and pytest."
            ),
            required_interfaces=("csv_cleaner.cleaner.dedupe_rows", "csv_cleaner.cleaner.fill_empty", "csv_cleaner.cli.main"),
            acceptance=("both owned test files are complete and syntactically valid", "tests cover the declared public interfaces"),
            allowed_effects=("filesystem.read", "filesystem.write"), max_actions=2, max_files=2,
        )
        client = base_client.bind_run(run_id, "worker_cohesive_tests_probe", budget_purpose="GENERATION")
        executor = BlueprintUnitExecutor(workspace, client, _worker_generation_model_config("deepseek"))
        request = BlockExecutionRequest(
            project_id="worker_cohesive_tests_probe", run_id=run_id, attempt_id="attempt-1",
            node_id=unit.unit_id, component_ref="project.unit.tests@1", executor_ref="llm.cheap@1",
            task_context=TaskContext(
                unit.instruction, node_config={"unit": unit.as_dict()},
                dependency_results={"core": {"public_interfaces": list(unit.required_interfaces)}},
                project_constraints=("stdlib implementation", "offline", "no hidden acceptance access"),
                acceptance=unit.acceptance,
            ),
            timeout_seconds=150, declared_effects=unit.allowed_effects,
        )
        started = time.perf_counter()
        block = executor.execute(request)
        owned_present = [path for path in unit.owns if (workspace / pathlib.PurePosixPath(path)).is_file()]
        syntax = block.succeeded and all(
            subprocess.run(
                [sys.executable, "-m", "py_compile", str(workspace / pathlib.PurePosixPath(path))],
                capture_output=True, text=True,
            ).returncode == 0
            for path in unit.owns
        )
        receipts_complete = bool(executor.calls) and all(_worker_receipt_complete(call) for call in executor.calls)
        materialization = dict(block.outputs.get("unit_materialization") or {})
        passed = (
            block.succeeded and len(executor.calls) <= 2 and len(owned_present) == len(unit.owns)
            and syntax and receipts_complete and materialization.get("status") == "COMMITTED"
        )
        row = materialize_json({
            "run_id": run_id, "status": "PASS" if passed else "FAIL",
            "source_commit": identity["cgkn_source_commit"], "unit_id": unit.unit_id,
            "owns": list(unit.owns), "logical_calls": len(executor.calls),
            "call_classes": [call.get("call_class") for call in executor.calls],
            "calls": [
                {
                    "call_class": call.get("call_class"), "requested_paths": call.get("requested_paths"),
                    "returned_paths": call.get("returned_paths"), "missing_paths_after_call": call.get("missing_paths_after_call"),
                    "staged_paths_before_call": call.get("staged_paths_before_call"), "context_chars": call.get("context_chars"),
                    "input_tokens": call.get("prompt_tokens"), "output_tokens": call.get("completion_tokens"),
                    "cached_tokens": call.get("cached_tokens"), "reasoning_tokens": call.get("reasoning_tokens"),
                    "selection_receipt_hash": call.get("selection_receipt_hash"),
                }
                for call in executor.calls
            ],
            "file_count": len(owned_present), "files": owned_present,
            "syntax": "PASS" if syntax else "FAIL", "atomic_commit": materialization.get("status"),
            "materialization": materialization, "manual_edits": 0,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "block_result": block.as_dict(),
        })
        target = artifact_root / "worker_cohesive_live" / f"{run_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        runs.append(row)
    passed = all(row["status"] == "PASS" for row in runs)
    result = {
        "profile": "worker-cohesive-live", "status": "PASS" if passed else "BLOCKED_WORKER_MATERIALIZATION",
        "qualification": "2/2" if passed else f"{sum(row['status'] == 'PASS' for row in runs)}/2",
        "source_identity": identity, "runs": runs,
    }
    index = artifact_root / "worker_cohesive_live" / "index.json"
    index.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the CGKN minimal ProjectBlueprint MVP profiles")
    parser.add_argument("--profile", required=True, choices=("unit", "unit-materialization", "fake-single", "fake-repair", "coordinator-diagnostic", "coordinator-qualify", "worker-file-probe", "worker-patch-probe", "worker-real-unit-diagnostic", "worker-cohesive-qualify", "worker-cohesive-replay", "worker-cohesive-live", "live-single", "live-repair", "fake-parallel", "fake-conflict", "fake-standup", "live-parallel", "live-repeat", "final"))
    parser.add_argument("--artifact-root", type=pathlib.Path, default=ROOT / ".service_evidence" / "project_mvp")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--blueprint-path", type=pathlib.Path)
    parser.add_argument("--replay-index", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv); args.artifact_root.mkdir(parents=True, exist_ok=True)
    if args.profile in PHASE_B_PROFILES:
        result = {"profile": args.profile, "status": "BLOCKED_BY_PHASE_A", "reason": "PHASE B may start only after the complete PHASE A gate passes"}
    elif args.profile == "unit": result = _run_pytest("")
    elif args.profile == "unit-materialization": result = _run_pytest("materialization or continuation")
    elif args.profile == "fake-single": result = _run_pytest("fake_greenfield")
    elif args.profile == "fake-repair": result = _run_pytest("fake_repair")
    elif args.profile == "coordinator-diagnostic": result = _coordinator_qualify(args.artifact_root.resolve(), count=1, provider=args.provider, diagnostic=True)
    elif args.profile == "coordinator-qualify": result = _coordinator_qualify(args.artifact_root.resolve(), count=args.count, provider=args.provider)
    elif args.profile == "worker-file-probe": result = _worker_probe(args.artifact_root.resolve(), patch_mode=False)
    elif args.profile == "worker-patch-probe": result = _worker_probe(args.artifact_root.resolve(), patch_mode=True)
    elif args.profile in {"worker-real-unit-diagnostic", "worker-cohesive-qualify"}:
        if args.blueprint_path is None:
            raise ValueError("worker real-unit profiles require --blueprint-path")
        result = _worker_real_unit(
            args.artifact_root.resolve(), blueprint_path=args.blueprint_path.resolve(), count=args.count,
            diagnostic=args.profile == "worker-real-unit-diagnostic",
        )
    elif args.profile == "worker-cohesive-replay":
        if args.replay_index is None:
            raise ValueError("worker cohesive replay requires --replay-index")
        result = _worker_cohesive_replay(args.artifact_root.resolve(), replay_index=args.replay_index.resolve())
    elif args.profile == "worker-cohesive-live":
        result = _worker_cohesive_live(args.artifact_root.resolve(), count=args.count)
    elif args.profile in {"live-single", "live-repair"}: result = _live(args.profile, args.artifact_root.resolve())
    else:
        result = {"profile": "final", "status": "NOT_READY", "reason": "run the ordered PHASE A and PHASE B profiles first"}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) if args.json else f"{args.profile}: {result.get('status', 'UNKNOWN')}")
    return 0 if result.get("status") in {"PASS", "SUCCEEDED", "BLOCKED_BY_PHASE_A", "NOT_READY"} else 1


if __name__ == "__main__": raise SystemExit(main())
