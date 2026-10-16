from __future__ import annotations

import ast
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.agent import AgentProjectLoop
from cgkn.agent.composer import AGENT_SCHEMA, AgentDecision, AgentDecisionContext, parse_agent_decision
from cgkn.executors import CommandExecutor, ExecutorRegistry, FileExecutor, PythonTestExecutor
from cgkn.providers import CompletionClient, ModelRoleConfig, OpenAICompatibleClient, parse_json_object
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

from .acceptance import ExternalAcceptanceExecutor
from .bundle import SoftwareProjectBundle
from .catalog import ProjectCase, get_case
from .contracts import ProjectResultStatus, canonical_hash
from .receipt import ProjectGenerationReceipt
from .scope import ScopedProjectLLMExecutor
from .snapshot import ProjectSnapshotExecutor, snapshot_project


class SoftwareProjectAgentComposer:
    """Application prompt adapter; canonical AgentDecision/TreeEdit remains authoritative."""

    def __init__(self, client: CompletionClient, config: ModelRoleConfig):
        if config.role != "agent":
            raise ValueError("software project composer requires agent model config")
        self.client, self.config = client, config
        self.last_provider_payload: dict[str, Any] = {}

    def decide(self, context: AgentDecisionContext) -> AgentDecision:
        raw = json.dumps(context.as_dict(), ensure_ascii=False, sort_keys=True)
        completion = self.client.complete(
            system=(
                "You are the CGKN high-capability software-project composition Agent. Return only one JSON AgentDecision with validated TreeEdits. "
                "You decide the project file structure and dependencies, but never output source file content, execute commands, or claim tests passed. "
                "For a new project, create one workspace.inspect node, one project.file.generate node per principal source or documentation file, a project.tests.generate node for each public test file, then compile, pytest, runtime smoke, snapshot, and external acceptance nodes. "
                "Generation or patch node config must contain executor_ref='llm.cheap@1', goal, target_paths (one path, or two tightly bound tiny files), allowed_paths (target paths plus only explicit relevant read paths), file_purpose, interfaces, acceptance, allowed_effects=['filesystem.write'], max_actions<=4, max_write_files<=2, max_total_output_bytes<=64000, allow_create, allow_patch, allow_delete=false, protected_paths. "
                "Inspect uses local.file@1 action=list_files path='.'. Compile uses local.command@1 with argv command. Pytest uses local.python-test@1 and pytest_args. Smoke uses local.command@1. Snapshot uses project.snapshot@1. Acceptance uses project.acceptance@1 and only the public case_id. "
                "Dependencies must ensure every source is generated before tests, all file nodes before compile, compile before pytest and smoke, those before snapshot, and snapshot before acceptance. "
                "On a failed run, add or update only the smallest patch node and retry the failed node/subgraph. Finish only after the external acceptance node succeeded. "
                "Diagnose from the first concrete traceback location. A NameError, missing import, syntax error, or fixture defect located in a generated public test file must repair the corresponding project.tests.generate node, never application source. Only patch application source when a valid public test demonstrates application behavior contradicting the public contract. "
                "update_config payload is exactly {config: object}; it cannot contain capability_ref. If you update a node that already succeeded, also emit exactly one retry_node edit for the earliest changed node so the canonical DAG invalidates its downstream closure. Do not update downstream nodes when their config is unchanged. "
                "Allowed operations are canonical TreeEdits only; use exact capability_ref and executor_ref names from the catalog. Never mention or request hidden test paths or values."
            ),
            user=raw,
            schema_name="cgkn_software_project_agent_decision",
            schema=AGENT_SCHEMA,
            config=self.config,
        )
        self.last_provider_payload = parse_json_object(completion.text)
        normalized = self._normalize_decision(self.last_provider_payload, context)
        decision = parse_agent_decision(normalized, completion, raw)
        worker_edits = [item for item in decision.edits if item.operation == "add_node" and item.payload.get("capability_ref") in {"project.file.generate@1", "project.file.patch@1", "project.tests.generate@1"}]
        if len(worker_edits) > 20:
            raise ValueError("Agent exceeded worker-call budget")
        for edit in worker_edits:
            config = dict(edit.payload.get("config", {}))
            if not config.get("target_paths") or config.get("allow_delete") is not False:
                raise ValueError("Agent worker node omitted mandatory scope")
        return decision

    @staticmethod
    def _normalize_decision(value: Mapping[str, Any], context: AgentDecisionContext) -> dict[str, Any]:
        """Project-adapter normalization for common Provider placement errors."""
        result = dict(value)
        edits: list[dict[str, Any]] = []
        protected = [".git", ".github", ".cgkn", "benchmarks", "artifacts", "governance", "cgkn"]
        dependency_aliases: dict[str, list[str]] = {}
        for item in value.get("edits", []):
            if isinstance(item, Mapping) and item.get("operation") == "add_dependency" and isinstance(item.get("payload"), Mapping) and isinstance(item["payload"].get("depends_on"), list):
                dependency_aliases.setdefault(str(item.get("node_id", "")), []).extend(str(dep) for dep in item["payload"]["depends_on"])
        retry_candidate = ""
        for raw_edit in value.get("edits", []):
            edit = dict(raw_edit)
            payload = dict(edit.get("payload", {}))
            if edit.get("operation") == "add_dependency" and isinstance(payload.get("depends_on"), list):
                continue
            if edit.get("operation") == "add_node":
                config = dict(payload.get("config", {}))
                if payload.get("executor_ref") and not config.get("executor_ref"):
                    config["executor_ref"] = payload["executor_ref"]
                capability_ref = str(payload.get("capability_ref", ""))
                catalog_row = context.capability_catalog.get(capability_ref, {}) if isinstance(context.capability_catalog, Mapping) else {}
                if not config.get("executor_ref") and isinstance(catalog_row, Mapping) and catalog_row.get("executor_ref"):
                    config["executor_ref"] = str(catalog_row["executor_ref"])
                if isinstance(config.get("acceptance"), str):
                    config["acceptance"] = [config["acceptance"]]
                if config.get("protected_paths") == []:
                    config["protected_paths"] = protected
                if capability_ref in {"project.file.generate@1", "project.tests.generate@1"}:
                    config["allow_patch"] = True
                if capability_ref == "project.tests.generate@1":
                    config["goal"] = str(config.get("goal", "")) + " Test only the declared public contract. Fixtures must be structurally valid unless a test explicitly expects an input error; never assert successful behavior from malformed fixtures or invent alternate CLI flags. Subprocess tests must run from the project root or set an explicit project-root PYTHONPATH."
                dependencies = list(payload.get("depends_on", [])) + dependency_aliases.get(str(edit.get("node_id", "")), [])
                payload = {"capability_ref": payload.get("capability_ref", ""), "parent_id": payload.get("parent_id", ""), "depends_on": list(dict.fromkeys(dependencies)), "config": config}
            elif edit.get("operation") == "update_config":
                config = dict(payload.get("config", {}))
                if isinstance(config.get("acceptance"), str):
                    config["acceptance"] = [config["acceptance"]]
                if config.get("target_paths") and config.get("protected_paths") == []:
                    config["protected_paths"] = protected
                payload = {"config": config}
                existing = context.tree.by_id.get(str(edit.get("node_id", "")))
                effective_executor = config.get("executor_ref") or (existing.config.get("executor_ref") if existing else "")
                if effective_executor == "llm.cheap@1" and not retry_candidate:
                    config["allow_patch"] = True
                    retry_candidate = str(edit.get("node_id", ""))
            edit["payload"] = payload
            edits.append(edit)
        if result.get("request_run") and retry_candidate:
            edits = [item for item in edits if item.get("operation") != "retry_node"]
            edits.append({"edit_id": f"normalized-retry-{retry_candidate}", "operation": "retry_node", "node_id": retry_candidate, "payload": {}, "provenance": {"adapter": "software_project", "reason": "updated completed worker node requires affected-subgraph retry"}})
        result["edits"] = edits
        return result


@dataclass(frozen=True)
class GenerationRunResult:
    case_id: str
    run_id: str
    run_dir: pathlib.Path
    workspace: pathlib.Path
    status: ProjectResultStatus
    receipt: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "run_id": self.run_id, "run_dir": str(self.run_dir), "workspace": str(self.workspace), "status": self.status.value, "receipt": dict(self.receipt)}


class SoftwareProjectGenerationService:
    def __init__(self, repository_root: pathlib.Path | str, artifact_root: pathlib.Path | str, *, client: CompletionClient | None = None, config: Mapping[str, Any] | None = None):
        self.repository_root = pathlib.Path(repository_root).resolve()
        self.artifact_root = pathlib.Path(artifact_root).resolve()
        self.client = client or OpenAICompatibleClient()
        self.config = dict(config or {})
        self.bundle = SoftwareProjectBundle.build()
        self.acceptance_root = self.repository_root / "benchmarks" / "real_project_generation" / "acceptance"

    def run_case(self, case_id: str, *, max_repair_rounds: int = 2) -> GenerationRunResult:
        if max_repair_rounds not in {0, 1, 2}:
            raise ValueError("application repair rounds must be between zero and two")
        case = get_case(case_id)
        previous_workspace: pathlib.Path | None = None
        failure_summary = ""
        final: GenerationRunResult | None = None
        for round_number in range(max_repair_rounds + 1):
            run_id = f"{case_id}-{uuid.uuid4().hex[:12]}-r{round_number}"
            run_dir = self.artifact_root / case_id / run_id
            workspace = run_dir / "workspace"
            run_dir.mkdir(parents=True, exist_ok=False)
            if previous_workspace:
                shutil.copytree(previous_workspace, workspace)
            elif case.seeded_fixture:
                shutil.copytree(self.repository_root / case.seeded_fixture, workspace)
            else:
                workspace.mkdir()
            final = self._run_round(case, run_id, run_dir, workspace, round_number, failure_summary)
            if final.status is ProjectResultStatus.PASS:
                return final
            previous_workspace = workspace
            failure_summary = str(final.receipt.get("sanitized_failure_summary", "previous acceptance did not pass"))
        assert final is not None
        return final

    def _run_round(self, case: ProjectCase, run_id: str, run_dir: pathlib.Path, workspace: pathlib.Path, round_number: int, failure_summary: str) -> GenerationRunResult:
        started = time.perf_counter()
        config = self._resolved_config()
        high = self._role("agent", config["high_capability_agent"])
        worker = self._role("worker", config["cheap_worker"])
        if high.model == worker.model:
            raise ValueError("Agent and worker models must differ")
        registry = ExecutorRegistry()
        registry.register(FileExecutor(workspace))
        registry.register(CommandExecutor(workspace))
        registry.register(PythonTestExecutor(workspace))
        registry.register(ScopedProjectLLMExecutor(workspace, self.client, worker))
        registry.register(ProjectSnapshotExecutor(workspace))
        registry.register(ExternalAcceptanceExecutor(workspace, self.acceptance_root))
        store = FileRunStore(self.artifact_root)
        public_case = {"case_id": case.case_id, "public_goal": case.public_goal, "public_acceptance": list(case.public_acceptance), "entrypoint": case.entrypoint, "runtime_command": list(case.runtime_command)}
        self._write(run_dir / "public_case.json", public_case)
        initial_test = self._initial_test(workspace) if case.seeded_fixture else None
        goal = self._goal(case, round_number, failure_summary, workspace)
        catalog = self._catalog(case)
        composer = SoftwareProjectAgentComposer(self.client, high)
        loop = AgentProjectLoop(
            composer, DAGRunner(registry, store), store,
            known_capabilities=self.bundle.known_capabilities, worker_model=worker.model,
            capability_catalog=catalog, max_decisions=int(config.get("max_agent_decisions", 4)),
        )
        try:
            result = loop.run(project_id=case.case_id, run_id=run_id, goal=goal, constraints=(f"public project contract: {case.public_goal}", f"public acceptance: {list(case.public_acceptance)}", "stdlib-only", "no outbound network", "no hidden acceptance access", "no absolute paths", "no placeholders", "worker writes only declared target_paths"))
            status, validation = self._validate_completion(case, run_id, workspace, store, result)
            usage = self._provider_usage(run_dir)
            if usage["worker_calls"] > 20 or usage["provider_call_count"] > 24:
                status = ProjectResultStatus.NEEDS_REWORK
                validation = dict(validation) | {"sanitized_failure_summary": "provider call budget exceeded"}
        except Exception as exc:
            result = None
            status, validation = ProjectResultStatus.BLOCKED_PROVIDER, {"sanitized_failure_summary": f"generation framework stopped: {type(exc).__name__}"}
            self._write(run_dir / "framework_error.json", {"type": type(exc).__name__, "message": str(exc)})
            if composer.last_provider_payload:
                self._write(run_dir / "agent" / "rejected-decision.json", composer.last_provider_payload)
        receipt = self._receipt(case, run_id, run_dir, workspace, round_number, result, status, validation, initial_test, high, worker, int((time.perf_counter() - started) * 1000))
        self._write(run_dir / "generation_receipt.json", receipt)
        self._write(run_dir / "provider_usage.json", self._provider_usage(run_dir))
        if (run_dir / "node_results").is_dir():
            for name, target in (("internal_test_receipt.json", "pytest"), ("runtime_receipt.json", "smoke"), ("external_acceptance_receipt.json", "accept"), ("project_snapshot.json", "snapshot")):
                match = next((p for p in (run_dir / "node_results").glob("*.json") if target in p.stem.lower()), None)
                if match:
                    shutil.copyfile(match, run_dir / name)
        return GenerationRunResult(case.case_id, run_id, run_dir, workspace, status, receipt)

    def _validate_completion(self, case: ProjectCase, run_id: str, workspace: pathlib.Path, store: FileRunStore, result: Any) -> tuple[ProjectResultStatus, dict[str, Any]]:
        if result.status != "SUCCEEDED" or not result.run_summary:
            summary = "Agent/DAG run did not complete"
            if result.run_summary and result.run_summary.failed_nodes:
                failed = result.run_summary.failed_nodes[-1]
                block = store.load_result(case.case_id, run_id, failed)
                summary = block.error.message if block.error else summary
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": summary}
        snapshot_rows = []
        acceptance_rows = []
        for node in result.tree.nodes:
            if not node.executable:
                continue
            block = store.load_result(case.case_id, run_id, node.id)
            if node.capability_ref == "project.snapshot@1": snapshot_rows.append(dict(block.outputs))
            if node.capability_ref == "project.acceptance.external@1": acceptance_rows.append(dict(block.outputs))
        if len(snapshot_rows) != 1 or len(acceptance_rows) != 1:
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": "completion nodes are missing or duplicated"}
        snap, acceptance = snapshot_rows[0], acceptance_rows[0]
        if acceptance.get("status") != "PASS" or acceptance.get("snapshot_hash") != snap.get("snapshot_hash"):
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": acceptance.get("sanitized_summary", "external acceptance failed"), "snapshot": snap, "acceptance": acceptance}
        if not workspace.exists() or not snap.get("files") or not (workspace / case.entrypoint).is_file():
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": "project snapshot or entrypoint is incomplete", "snapshot": snap, "acceptance": acceptance}
        scan = self._forbidden_scan(workspace)
        if scan:
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": "generated project failed forbidden-content scan", "forbidden_findings": scan, "snapshot": snap, "acceptance": acceptance}
        return ProjectResultStatus.PASS, {"sanitized_failure_summary": "", "snapshot": snap, "acceptance": acceptance}

    def _receipt(self, case: ProjectCase, run_id: str, run_dir: pathlib.Path, workspace: pathlib.Path, round_number: int, result: Any, status: ProjectResultStatus, validation: Mapping[str, Any], initial_test: Mapping[str, Any] | None, high: ModelRoleConfig, worker: ModelRoleConfig, wall_ms: int) -> dict[str, Any]:
        usage_evidence = self._provider_usage(run_dir)
        snapshot = dict(validation.get("snapshot", {}))
        tree_doc = json.loads((run_dir / "capability_tree.json").read_text(encoding="utf-8")) if (run_dir / "capability_tree.json").is_file() else {}
        dag_doc = json.loads((run_dir / "execution_dag.json").read_text(encoding="utf-8")) if (run_dir / "execution_dag.json").is_file() else {}
        token_totals = self._token_totals(usage_evidence["provider_usage"])
        attempt_count = usage_evidence["worker_execution_attempts"] + usage_evidence["deterministic_calls"]
        source_loc = sum(
            len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            for path in workspace.rglob("*.py") if "__pycache__" not in path.parts
        )
        internal_test = self._capability_status(result, "project.python.pytest@1")
        runtime_result = self._capability_status(result, "project.command.smoke@1")
        hidden_result = dict(validation.get("acceptance", {})).get("status", "NOT_EVALUATED")
        values = {
            "case_id": case.case_id, "project_id": case.case_id, "run_id": run_id, "generation_round": round_number,
            **self._git_identity(), "goal_hash": "sha256:" + hashlib.sha256(case.public_goal.encode()).hexdigest(),
            "agent_model": high.model, "worker_model": worker.model,
            "agent_request_ids": usage_evidence["agent_request_ids"],
            "worker_request_ids": usage_evidence["worker_request_ids"],
            "provider_usage": usage_evidence["provider_usage"], "provider_call_count": usage_evidence["provider_call_count"],
            "agent_calls": usage_evidence["agent_calls"], "worker_calls": usage_evidence["worker_calls"], "deterministic_calls": usage_evidence["deterministic_calls"],
            "tree_hash": canonical_hash(tree_doc) if tree_doc else "", "dag_hash": canonical_hash(dag_doc) if dag_doc else "",
            "tree_nodes": len(tree_doc.get("nodes", [])), "dag_nodes": len(dag_doc.get("nodes", [])),
            "snapshot_hash": snapshot.get("snapshot_hash", ""), "generated_file_count": snapshot.get("total_file_count", 0),
            "generated_source_loc": source_loc,
            "internal_compile_result": self._capability_status(result, "project.python.compile@1"),
            "internal_test_result": internal_test,
            "runtime_result": runtime_result,
            "hidden_acceptance_result": hidden_result,
            "functional_success": status is ProjectResultStatus.PASS,
            "tree_edit_success": bool(tree_doc.get("nodes")),
            "dag_compile_success": bool(dag_doc.get("nodes")),
            "worker_proposal_success": usage_evidence["worker_calls"] > 0,
            "file_materialization_success": any(path.is_file() for path in workspace.rglob("*.py")),
            "repair_success": bool(round_number and status is ProjectResultStatus.PASS),
            "false_pass": internal_test == "PASS" and hidden_result != "PASS",
            "false_fail": False,
            "retry_count": max(0, attempt_count - len({path.parent.name for path in (run_dir / "attempts").glob("*/attempt-*.json")})),
            **token_totals,
            "initial_test": dict(initial_test or {}), "repair_rounds": round_number,
            "manual_intervention": 0, "human_intervention": False, "wall_time_ms": wall_ms,
            "final_status": status.value, "sanitized_failure_summary": str(validation.get("sanitized_failure_summary", "")),
            "secrets_persisted": False,
        }
        return ProjectGenerationReceipt(values).as_dict()

    @staticmethod
    def _provider_usage(run_dir: pathlib.Path) -> dict[str, Any]:
        agent_docs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((run_dir / "agent").glob("decision-*.json"))] if (run_dir / "agent").is_dir() else []
        attempt_docs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((run_dir / "attempts").glob("*/attempt-*.json"))] if (run_dir / "attempts").is_dir() else []
        agent_rows = [{"role": "agent", **dict(doc.get("provider", {}))} for doc in agent_docs]
        worker_rows: list[dict[str, Any]] = []
        worker_request_ids: list[str] = []
        for doc in attempt_docs:
            if doc.get("executor_ref") != "llm.cheap@1":
                continue
            usage = dict(doc.get("usage", {}))
            request_ids = [str(item) for item in usage.get("request_ids", ()) if item]
            if not request_ids and usage.get("request_id"):
                request_ids = [str(usage["request_id"])]
            worker_request_ids.extend(request_ids)
            worker_rows.append({"role": "worker", "node_id": doc.get("node_id"), "attempt_id": doc.get("attempt_id"), **usage})
        agent_request_ids = [str(row.get("request_id")) for row in agent_rows if row.get("request_id")]
        return {
            "agent_request_ids": agent_request_ids,
            "worker_request_ids": worker_request_ids,
            "provider_usage": agent_rows + worker_rows,
            "provider_call_count": len(agent_request_ids) + len(worker_request_ids),
            "agent_calls": len(agent_request_ids),
            "worker_calls": len(worker_request_ids),
            "deterministic_calls": sum(1 for doc in attempt_docs if doc.get("executor_ref") != "llm.cheap@1"),
            "worker_execution_attempts": sum(1 for doc in attempt_docs if doc.get("executor_ref") == "llm.cheap@1"),
        }

    @staticmethod
    def _token_totals(rows: list[dict[str, Any]]) -> dict[str, int]:
        totals = {"agent_input_tokens": 0, "agent_output_tokens": 0, "worker_input_tokens": 0, "worker_output_tokens": 0, "context_chars": 0}
        for row in rows:
            role = str(row.get("role", ""))
            usage = row.get("usage", row)
            if not isinstance(usage, Mapping):
                continue
            if role == "agent":
                totals["agent_input_tokens"] += int(usage.get("prompt_tokens", 0))
                totals["agent_output_tokens"] += int(usage.get("completion_tokens", 0))
            elif role == "worker":
                totals["worker_input_tokens"] += int(usage.get("prompt_tokens", 0))
                totals["worker_output_tokens"] += int(usage.get("completion_tokens", 0))
                totals["context_chars"] += int(usage.get("context_chars", 0))
        return totals

    @staticmethod
    def _capability_status(result: Any, capability_ref: str) -> str:
        if not result or not result.run_summary:
            return "NOT_EVALUATED"
        nodes = [node.id for node in result.tree.nodes if node.capability_ref == capability_ref]
        return "PASS" if len(nodes) == 1 and nodes[0] not in result.run_summary.failed_nodes and nodes[0] not in result.run_summary.blocked_nodes else "FAIL"

    def _goal(self, case: ProjectCase, round_number: int, failure_summary: str, workspace: pathlib.Path) -> str:
        mode = "Build from an empty workspace." if round_number == 0 and not case.seeded_fixture else "Repair the existing workspace with the smallest scoped changes."
        existing = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file())
        return f"{case.public_goal}\n{mode}\nPublic acceptance: {list(case.public_acceptance)}\nRequired entrypoint: {case.entrypoint}\nRuntime smoke argv: {list(case.runtime_command)}\nExisting public files: {existing}\nSanitized previous failure: {failure_summary or 'none'}."

    def _catalog(self, case: ProjectCase) -> dict[str, Any]:
        catalog = self.bundle.catalog
        catalog["workspace.inspect@1"] |= {"executor_ref": "local.file@1", "config": {"action": "list_files", "path": ".", "goal": "Inspect public workspace files"}}
        catalog["project.python.compile@1"] |= {"executor_ref": "local.command@1", "config": {"command": [sys.executable, "-m", "compileall", "-q", "."], "goal": "Compile all Python sources"}}
        catalog["project.python.pytest@1"] |= {"executor_ref": "local.python-test@1", "config": {"pytest_args": ["-q"], "goal": "Run public project tests"}}
        catalog["project.command.smoke@1"] |= {"executor_ref": "local.command@1", "config": {"command": [sys.executable, *case.runtime_command[1:]], "goal": "Run the declared public runtime smoke"}}
        catalog["project.snapshot@1"] |= {"executor_ref": "project.snapshot@1", "config": {"entrypoints": [case.entrypoint], "test_commands": [f"{sys.executable} -m pytest -q"], "runtime_commands": [" ".join((sys.executable, *case.runtime_command[1:]))], "goal": "Create deterministic project snapshot"}}
        catalog["project.acceptance.external@1"] |= {"executor_ref": "project.acceptance@1", "config": {"case_id": case.case_id, "goal": "Run isolated external acceptance"}}
        return catalog

    def _resolved_config(self) -> dict[str, Any]:
        return {
            "high_capability_agent": {"model": "qwen3.8-max", "timeout_seconds": 90, "max_output_tokens": 7000, "reasoning_effort": "none"},
            "cheap_worker": {"model": "qwen3.7-flash", "timeout_seconds": 90, "max_output_tokens": 6000, "temperature": 0.0, "reasoning_effort": "none"},
            "max_agent_decisions": 4,
        } | self.config

    @staticmethod
    def _role(role: str, value: Mapping[str, Any]) -> ModelRoleConfig:
        return ModelRoleConfig(role, str(value["model"]), int(value.get("timeout_seconds", 90)), int(value.get("max_output_tokens", 6000)), float(value.get("temperature", 0.0)), str(value.get("reasoning_effort", "none")))

    @staticmethod
    def _initial_test(workspace: pathlib.Path) -> dict[str, Any]:
        env = os.environ.copy(); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=workspace, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=60, env=env)
        return {"returncode": completed.returncode, "stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:]}

    @staticmethod
    def _forbidden_scan(workspace: pathlib.Path) -> list[str]:
        findings: list[str] = []
        suspicious = ("benchmarks/real_project_generation", "CGKN_GENERATED_PROJECT", "hidden_acceptance", "TODO", "FIXME")
        for path in workspace.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(workspace).as_posix()
            if path.name in {"generation_receipt.json", "external_acceptance_receipt.json", "project_snapshot.json"}:
                findings.append(f"forged-evidence:{relative}")
            if path.stat().st_size == 0 and path.suffix == ".py": findings.append(f"zero-byte:{relative}")
            if path.suffix.lower() in {".py", ".md", ".txt", ".json", ".html", ".js", ".css"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                if any(token in text for token in suspicious): findings.append(f"suspicious-literal:{relative}")
                if re.search(r"(?i)(?:[A-Z]:\\\\(?:Users|Documents|Desktop)\\\\|/(?:home|Users)/[^/]+/)", text): findings.append(f"absolute-machine-path:{relative}")
                if re.search(r"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*['\"][^'\"]{8,}", text): findings.append(f"secret-like-literal:{relative}")
                is_test = relative.startswith("tests/") or path.name.startswith("test_")
                if not is_test and ("requests." in text or "urllib.request" in text or "http.client" in text): findings.append(f"network-usage:{relative}")
                if path.suffix.lower() == ".py":
                    try:
                        tree = ast.parse(text)
                    except SyntaxError:
                        findings.append(f"invalid-python:{relative}")
                        continue
                    for node in ast.walk(tree):
                        names: list[str] = []
                        if isinstance(node, ast.Import): names = [alias.name.split(".")[0] for alias in node.names]
                        elif isinstance(node, ast.ImportFrom) and node.level == 0: names = [str(node.module or "").split(".")[0]]
                        for name in names:
                            if name and name not in sys.stdlib_module_names and not (workspace / name).exists() and not (workspace / f"{name}.py").exists():
                                findings.append(f"undeclared-dependency:{relative}:{name}")
        return sorted(set(findings))

    def _git_identity(self) -> dict[str, str]:
        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=self.repository_root, text=True, encoding="utf-8", errors="replace", capture_output=True, check=True).stdout.strip()
        return {"source_commit": git("rev-parse", "HEAD"), "source_tree": git("rev-parse", "HEAD^{tree}")}

    @staticmethod
    def _write(path: pathlib.Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
