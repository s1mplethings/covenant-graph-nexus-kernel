from __future__ import annotations

import ast
import json
import pathlib
import sys
import time
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.application.software_project.scope import ScopedFileTransaction, ScopeViolation, _plain
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors.llm import WORKER_SCHEMA, validate_worker_proposal
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object

from .policy import DependencyPolicy


@dataclass(frozen=True)
class _ScopeAdapter:
    allowed_paths: tuple[str, ...]
    target_paths: tuple[str, ...]
    protected_paths: tuple[str, ...]
    max_actions: int = 7
    max_write_files: int = 5
    max_total_output_bytes: int = 64_000
    allow_create: bool = True
    allow_patch: bool = True
    allow_delete: bool = False


def validate_dependency_actions(root: pathlib.Path, actions: list[Mapping[str, Any]], policy: DependencyPolicy) -> None:
    project_modules = {path.name for path in root.iterdir()} if root.exists() else set()
    project_modules.update(pathlib.PurePosixPath(str(action.get("path", ""))).parts[0] for action in actions if action.get("path"))
    for action in actions:
        path = str(action.get("path", ""))
        if not path.endswith(".py") or action.get("action") != "write_file":
            continue
        domain = "test" if pathlib.PurePosixPath(path).parts[0] == "tests" else "runtime"
        tree = ast.parse(str(action.get("content", "")), filename=path)
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
        }
        for package in imports:
            if package in sys.stdlib_module_names or package in project_modules:
                continue
            if not policy.allows(domain, package):
                raise ScopeViolation(f"dependency policy rejects {package} in {domain} source: {path}")


class ObligationWorkUnitExecutor:
    descriptor = ExecutorDescriptor(
        "project.obligation-worker@1", "obligation_work_unit", ("project.obligation-work-unit@1",),
        ("filesystem.read", "filesystem.write"), supports_cost_reporting=True,
    )

    def __init__(self, root: pathlib.Path, client: CompletionClient, config: ModelRoleConfig):
        self.root, self.client, self.config = root.resolve(), client, config

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        usage: dict[str, Any] = {}
        try:
            config = request.task_context.node_config
            unit = _plain(config["work_unit_contract"])
            targets = tuple(str(item) for item in unit["target_paths"])
            reads = tuple(str(item) for item in unit.get("allowed_read_paths", ()))
            scope = _ScopeAdapter(tuple(dict.fromkeys((*targets, *reads))), targets, (".git", ".github", ".cgkn", "benchmarks", "artifacts", "governance", "cgkn"))
            current = {}
            for relative in scope.allowed_paths:
                path = self.root / pathlib.PurePosixPath(relative)
                if path.is_file():
                    current[relative] = path.read_text(encoding="utf-8")
            prompt = {
                "node_id": request.node_id,
                "work_unit_contract": unit,
                "obligations": _plain(config["obligations"]),
                "dependency_policy": _plain(config["dependency_policy"]),
                "test_plan": _plain(config.get("test_plan", {})),
                "interface_manifest": _plain(config.get("interface_manifest", {})),
                "executable_interface_contracts": _plain(config.get("executable_interface_contracts", ())),
                "dependency_interface_contracts": _plain(config.get("dependency_interface_contracts", ())),
                "current_sources": current,
                "failure_evidence": _plain(config.get("failure_evidence")),
                "target_paths": list(targets),
                "allowed_actions": ["write_file", "patch_file", "read_file"],
            }
            policy = DependencyPolicy.from_dict(config["dependency_policy"])
            serialized = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
            attempts: list[dict[str, Any]] = []
            rejection: list[dict[str, Any]] = []
            proposal: dict[str, Any] = {}
            results: list[dict[str, Any]] = []
            for attempt_number in range(1, 3):
                attempt_prompt = serialized
                if rejection:
                    attempt_prompt = json.dumps(prompt | {"interface_contract_evidence": rejection}, ensure_ascii=False, sort_keys=True)
                completion = self.client.complete(
                    system=("Implement only the supplied WorkUnitContract. Obligation objects, DependencyPolicy, TestPlan, FailureEvidence, and ExecutableInterfaceContracts are authoritative public requirements. "
                            "You MUST preserve exact positional and optional argument shapes. Do not introduce aliases or alternate invocation styles unless explicitly allowed. Forbidden interfaces must not appear. Do not reinterpret positional arguments as options. "
                            "You may change only declared target source files; never modify obligations, contracts, Oracles, or canonical tests. Return bounded JSON file actions only."),
                    user=attempt_prompt, schema_name="cgkn_obligation_worker", schema=WORKER_SCHEMA, config=self.config,
                )
                attempts.append({"request_id": completion.request_id, "usage": dict(completion.usage), "transport_attempts": completion.attempts})
                usage = self._usage(attempts, len(serialized), len(rejection))
                proposal = validate_worker_proposal(parse_json_object(completion.text), request.node_id)
                if proposal["needs_escalation"]:
                    raise ScopeViolation(proposal["escalation_reason"] or "worker escalation")
                validate_dependency_actions(self.root, proposal["actions"], policy)
                transaction = ScopedFileTransaction(self.root, scope)
                _, planned = transaction.validate(proposal["actions"])
                rejection = self._interface_rejections(config, current, planned)
                if rejection:
                    if attempt_number == 2:
                        raise ScopeViolation("executable interface guard rejected staged candidate: " + json.dumps(rejection, sort_keys=True))
                    continue
                results = transaction.apply(proposal["actions"])
                break
            return self._result(
                request, BlockStatus.SUCCEEDED, started, clock,
                {"action_results": results, "modified_files": [item["path"] for item in results if item["action"] == "write_file"], "interface_contract_evidence": rejection, "interface_guard_rejects": attempt_number - 1},
                None, usage,
            )
        except (ValueError, OSError, PermissionError) as exc:
            return self._result(request, BlockStatus.FAILED, started, clock, {}, ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, str(exc)), usage)

    @staticmethod
    def _interface_rejections(config: Mapping[str, Any], current: Mapping[str, str], planned: list[Any]) -> list[dict[str, Any]]:
        from cgkn.application.interfaces import (
            ExecutableInterfaceContract, ExecutableInterfaceContractSet, InterfaceContractStatus,
            extract_interfaces, guard_interfaces,
        )

        rows = config.get("executable_interface_contracts", ())
        if not rows or not any(item.relative.endswith(".py") for item in planned):
            return []
        contracts = tuple(ExecutableInterfaceContract.from_dict(_plain(item)) for item in rows)
        contract_set = ExecutableInterfaceContractSet(contracts, str(config.get("interface_contract_set_hash", "sha256:unknown")))
        candidate = dict(current)
        candidate.update({item.relative: item.content.decode("utf-8") for item in planned})
        evidence = guard_interfaces(contract_set, extract_interfaces(candidate))
        return [item.as_dict() for item in evidence if item.status is not InterfaceContractStatus.PASS]

    def _usage(self, attempts: list[dict[str, Any]], context_chars: int, interface_guard_rejects: int) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "request_id": attempts[-1]["request_id"],
            "request_ids": [item["request_id"] for item in attempts],
            "provider_attempts": sum(int(item["transport_attempts"]) for item in attempts),
            "proposal_attempts": len(attempts),
            "interface_guard_rejects": interface_guard_rejects,
            "context_chars": context_chars,
            "prompt_tokens": sum(int(item["usage"].get("prompt_tokens", 0)) for item in attempts),
            "completion_tokens": sum(int(item["usage"].get("completion_tokens", 0)) for item in attempts),
            "total_tokens": sum(int(item["usage"].get("total_tokens", 0)) for item in attempts),
        }

    @staticmethod
    def _result(request: BlockExecutionRequest, status: BlockStatus, started: str, clock: float, outputs: Mapping[str, Any], error: ExecutionError | None, usage: Mapping[str, Any]) -> BlockExecutionResult:
        return BlockExecutionResult(
            project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id,
            executor_ref=request.executor_ref, status=status, outputs=outputs, error=error, started_at=started, ended_at=utc_now(),
            duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage=usage,
            metadata={"obligation_authority": True}, retryable=False,
        )
