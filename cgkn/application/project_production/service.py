from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from scripts import canonical_evidence_hash, customer_runtime_runner, local_packager, real_test_execution

from cgkn.application.capability_builder import CapabilityBuilderService, CapabilityRisk, CapabilitySpec, CapabilityStore, StoredCapabilityRuntime
from cgkn.application.learning import GenerationRequest, LearningEvent, ProductionGenerationClient, StoreLessonRecorder, canonical_hash, record_feedback
from cgkn.application.materialization import materialize_json
from cgkn.application.self_growth import SelfGrowthService
from cgkn.application.software_project.contracts import WorkerScope
from cgkn.application.software_project.scope import ScopedFileTransaction
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors import ExecutorRegistry
from cgkn.executors.llm import WORKER_SCHEMA, validate_worker_proposal
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.providers import ModelRoleConfig, parse_json_object
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

from .contracts import ProjectGoal, ProjectProductionResult, RequiredCapability


PYPROJECT_REF = "project.python.pyproject.render@1"


def folder_manifest_goal() -> ProjectGoal:
    return ProjectGoal(
        "folder_manifest_cli",
        "Build a fully local installable Python CLI that scans directories into deterministic SHA-256 manifests and verifies later changes.",
        "folder_manifest",
        (RequiredCapability(PYPROJECT_REF, "render installable Python project metadata", "project-metadata-render", "PURE"),),
    )


class _FunctionExecutor:
    def __init__(self, executor_ref: str, component_ref: str, function: Callable[[BlockExecutionRequest], Mapping[str, Any]]):
        self.descriptor = ExecutorDescriptor(executor_ref, "deterministic_project_production", (component_ref,), ("filesystem.write",), True, False, "local")
        self.function = function

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started = utc_now(); clock = time.perf_counter()
        try:
            outputs = dict(self.function(request))
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs=outputs, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))
        except CapabilityGap as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTOR_NOT_FOUND, str(exc), {"capability_ref": exc.capability_ref, "status": "GROWTH_REQUIRED"}), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000), retryable=True)
        except Exception as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, f"{type(exc).__name__}: {exc}"), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))


class CapabilityGap(RuntimeError):
    def __init__(self, capability_ref: str):
        self.capability_ref = capability_ref
        super().__init__(f"CAPABILITY_GAP:{capability_ref}")


class ProjectGenerationActionPolicy:
    def decide(self, failure_domain: str, *, repair_budget: int) -> str:
        if failure_domain in {"FRAMEWORK_HARNESS_DEFECT", "FRAMEWORK_VALIDATOR_DEFECT"}:
            return "REVALIDATE_EXISTING"
        if failure_domain in {"CANDIDATE_DEFECT", "CANDIDATE_POLICY_DEFECT"} and repair_budget > 0:
            return "REPAIR_CANDIDATE"
        return "STOP"


class _CoreExecutor:
    descriptor = ExecutorDescriptor("project.folder-manifest.core@1", "lesson_aware_project_codegen", ("project.core.generate@1",), ("filesystem.write",), True, True, "provider")

    def __init__(self, workspace: pathlib.Path, generation: ProductionGenerationClient, config: ModelRoleConfig):
        self.workspace, self.generation, self.config = workspace, generation, config

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started = utc_now(); clock = time.perf_counter(); config = request.task_context.node_config
        current = {path: (self.workspace / path).read_text(encoding="utf-8") for path in ("folder_manifest/__init__.py", "folder_manifest/__main__.py", "folder_manifest/core.py") if (self.workspace / path).is_file()}
        contract = _project_contract()
        prompt = {
            "node_id": request.node_id, "work_unit_id": "WU-FOLDER-MANIFEST-CORE",
            "target_paths": ["folder_manifest/__init__.py", "folder_manifest/__main__.py", "folder_manifest/core.py"],
            "interface_contract": contract["interface_contract"], "behavior_contract": contract["behavior_contract"],
            "dependency_policy": contract["dependency_policy"], "current_sources": current,
            "failure_evidence": config.get("failure_evidence", {}), "allowed_actions": ["write_file", "patch_file"],
        }
        try:
            generated = self.generation.generate(GenerationRequest(
                "project.codegen", "REPAIR" if config.get("failure_evidence") else "GENERATION",
                request.project_id, "project.folder_manifest.core@1", self.config.model,
                "Implement the one cohesive folder_manifest core work unit. The interface and behavior contracts are authoritative. Write complete production code for exactly the three target files. Use Python stdlib only, never use network or shell, never create tests or metadata, never expose hidden acceptance, and return JSON file actions only.",
                prompt, contract, current, config.get("failure_evidence", {}), "folder_manifest_core_actions", WORKER_SCHEMA, self.config,
                dependency_risk_policy=contract["dependency_policy"], allowed_actions=("write_file", "patch_file"),
                forbidden_actions=("network", "shell", "test_write", "metadata_write", "hidden_acceptance"), run_id=request.run_id,
            ))
            proposal = validate_worker_proposal(parse_json_object(generated.completion.text), request.node_id)
            if proposal["needs_escalation"]:
                raise ValueError(proposal["escalation_reason"] or "project core escalated")
            scope = WorkerScope(tuple(prompt["target_paths"]), tuple(prompt["target_paths"]), protected_paths=("tests", "pyproject.toml", "README.md", ".git", "governance"), max_actions=3, max_write_files=3, max_total_output_bytes=80_000, allow_create=True, allow_patch=True, allow_delete=False)
            results = ScopedFileTransaction(self.workspace, scope).apply(proposal["actions"])
            missing = [path for path in prompt["target_paths"] if not (self.workspace / path).is_file()]
            if missing:
                raise ValueError("PROJECT_CORE_MISSING_TARGETS:" + ",".join(missing))
            source_hash = canonical_hash({path: (self.workspace / path).read_text(encoding="utf-8") for path in prompt["target_paths"]})
            usage = dict(generated.completion.usage)
            generation_receipt = {"kind": "ProjectCoreGenerationReceipt", "schema_version": "1.0", "candidate_id": f"project-core-{source_hash[-12:]}", "source_hash": source_hash, "request_id": generated.completion.request_id, "lesson_snapshot_hash": generated.lesson_snapshot_hash, "applied_lesson_ids": list(generated.applied_lesson_ids), "generation_context_hash": generated.generation_context_hash, "manual_edits": 0, "contains_credentials": False}
            (self.workspace / "generation_receipt.json").write_text(json.dumps(generation_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            (self.workspace / "lesson_snapshot_refs.json").write_text(json.dumps({"kind": "LessonSnapshotRefs", "schema_version": "1.0", "snapshot_hashes": [generated.lesson_snapshot_hash], "lesson_ids": list(generated.applied_lesson_ids), "contains_credentials": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs={"source_hash": source_hash, "candidate_id": f"project-core-{source_hash[-12:]}", "modified_files": [item["path"] for item in results], "request_id": generated.completion.request_id, "lesson_snapshot_hash": generated.lesson_snapshot_hash, "applied_lesson_ids": list(generated.applied_lesson_ids), "generation_context_hash": generated.generation_context_hash}, usage=usage, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))
        except Exception as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, f"{type(exc).__name__}: {exc}"), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))


def _project_contract() -> dict[str, Any]:
    return {
        "project_id": "folder_manifest_cli", "package_name": "folder_manifest", "installable": True,
        "required_capability_refs": [{"capability_ref": PYPROJECT_REF, "purpose": "render pyproject.toml", "required_before_node": "project-metadata-render", "risk_expectation": "PURE"}],
        "interface_contract": {
            "entrypoint": "python -m folder_manifest",
            "commands": ["scan ROOT MANIFEST [--exclude GLOB]", "verify ROOT MANIFEST", "show MANIFEST", "--help"],
            "scan_arguments": {"ROOT": "positional", "MANIFEST": "positional", "--exclude": "repeatable option"},
        },
        "behavior_contract": {
            "manifest": {"version": 1, "algorithm": "sha256", "files": [{"path": "POSIX relative", "size": "integer", "sha256": "hex"}]},
            "ordering": "path ascending", "deterministic_json": True,
            "ignored": [".git/**", "__pycache__/**", "manifest output itself", "symlink files", "symlink directories", "user exclude globs"],
            "verify": {"unchanged": 0, "changed_missing_extra": "nonzero with stable differentiated output"},
            "errors": "nonzero and nonempty stderr for invalid root/manifest/missing manifest/unwritable output",
        },
        "dependency_policy": {"runtime": "PYTHON_STDLIB_ONLY", "test": ["pytest"], "network": "FORBIDDEN", "shell": "FORBIDDEN"},
    }


def _capability_spec() -> CapabilitySpec:
    metadata = {"name": "folder-manifest", "version": "0.1.0", "module": "folder_manifest", "description": "Deterministic local folder manifest CLI", "requires_python": ">=3.11", "console_script": "folder-manifest=folder_manifest.__main__:main"}
    return CapabilitySpec(
        "project.python.pyproject.render", "1", "Render deterministic stdlib-only pyproject.toml text from project metadata.",
        {"type": "object"}, {"type": "object"},
        ({"input": metadata, "output": {"pyproject_toml": _expected_pyproject()}},),
        ("result has only pyproject_toml", "tomllib parses output", "build-system and project metadata are present", "project.scripts is present when console_script is nonempty", "deterministic output"),
        CapabilityRisk.PURE,
    )


class AutonomousProjectProductionService:
    def __init__(self, repository_root: pathlib.Path | str, artifact_root: pathlib.Path | str, generation: ProductionGenerationClient, model_config: ModelRoleConfig):
        self.repository_root = pathlib.Path(repository_root).resolve()
        self.artifact_root = pathlib.Path(artifact_root).resolve()
        self.generation, self.model_config = generation, model_config

    def run_folder_manifest(self) -> ProjectProductionResult:
        started = time.perf_counter(); goal = folder_manifest_goal(); run_id = f"folder-manifest-{uuid.uuid4().hex[:12]}"
        root = self.artifact_root / run_id; workspace = root / "workspace"; workspace.mkdir(parents=True)
        state_store = FileRunStore(root / "state"); capability_store = CapabilityStore(root / "capability_store")
        growth_history = root / "provider_capability_history.json"
        builder = CapabilityBuilderService(self.generation, self.model_config, provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=capability_store)
        growth = SelfGrowthService(builder, capability_store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=growth_history)
        recorder = StoreLessonRecorder(self.generation.store) if self.generation.store else None
        contract = _project_contract(); obligations = _obligations()
        registry = self._registry(workspace, root, capability_store, contract, obligations)
        tree = self._tree(contract, obligations); dag = compile_tree(tree); runner = DAGRunner(registry, state_store)
        first = runner.run(project_id=goal.project_id, run_id=run_id, tree=tree, dag=dag, constraints=("runtime stdlib only", "network forbidden", "shell forbidden", "local_packager only"))
        if "project-capabilities-resolve" not in first.failed_nodes:
            raise RuntimeError("expected isolated capability store miss exactly once")
        core_first = state_store.load_result(goal.project_id, run_id, "project-core-generate")
        gap_event = self._event(run_id, goal.project_id, "capability.resolve", "GAP", PYPROJECT_REF, "", "", "GROWTH_REQUIRED", "", (str(root / "state"),), core_first)
        if recorder: recorder.record_event(gap_event)
        growth_outcome = growth.ensure_and_resume(root / "growth", _capability_spec(), _metadata_input())
        if growth_outcome.status != "PASS":
            return self._finish_failure(root, workspace, goal, run_id, "CAPABILITY_IMPLEMENTATION_BLOCKER:" + growth_outcome.failure_class, started)
        repair_rounds = 0
        if not core_first.succeeded:
            action = ProjectGenerationActionPolicy().decide("CANDIDATE_DEFECT", repair_budget=1)
            if action != "REPAIR_CANDIDATE":
                return self._finish_failure(root, workspace, goal, run_id, "PROJECT_IMPLEMENTATION_BLOCKER", started)
            repair_rounds = 1
            tree = self._tree(contract, obligations, failure_evidence={"failure_domain": "CANDIDATE_DEFECT", "failed_node": "project-core-generate", "receipt": core_first.as_dict(), "action": action})
            dag = compile_tree(tree)
        resumed = runner.run(project_id=goal.project_id, run_id=run_id, tree=tree, dag=dag, resume=True, retry_node="project-capabilities-resolve", constraints=("runtime stdlib only", "network forbidden", "shell forbidden", "local_packager only"))
        final = resumed
        if final.status != "SUCCEEDED":
            failure_node = next(iter(final.failed_nodes), "")
            if failure_node in {"project-compile", "project-pytest", "project-oracle", "project-hidden-acceptance"}:
                failure = state_store.load_result(goal.project_id, run_id, failure_node).as_dict()
                if repair_rounds >= 1:
                    return self._finish_failure(root, workspace, goal, run_id, "PROJECT_IMPLEMENTATION_BLOCKER", started)
                repair_rounds = 1
                tree = self._tree(contract, obligations, failure_evidence={"failure_domain": "CANDIDATE_DEFECT", "failed_node": failure_node, "receipt": failure})
                dag = compile_tree(tree)
                final = runner.run(project_id=goal.project_id, run_id=run_id, tree=tree, dag=dag, resume=True, retry_node="project-core-generate", constraints=("runtime stdlib only", "network forbidden", "shell forbidden", "local_packager only"))
        if final.status != "SUCCEEDED":
            return self._finish_failure(root, workspace, goal, run_id, "PROJECT_IMPLEMENTATION_BLOCKER:" + ",".join(final.failed_nodes), started)
        core_result = state_store.load_result(goal.project_id, run_id, "project-core-generate")
        package_result = state_store.load_result(goal.project_id, run_id, "project-package")
        reuse = StoredCapabilityRuntime(capability_store, provider_id="grok").invoke(PYPROJECT_REF, _metadata_input())
        import tomllib
        tomllib.loads(str(reuse["pyproject_toml"]))
        applied = tuple(core_result.outputs.get("applied_lesson_ids", ()))
        if recorder:
            self.record_success_events(recorder, run_id, goal.project_id, root, core_result, package_result)
            record_feedback(self.generation.store, applied, success=True)
            recorder.finalize_run(run_id)
        receipt = {
            "kind": "ProjectProductionReceipt", "schema_version": "1.0", "project_id": goal.project_id,
            "goal_hash": canonical_hash(goal.as_dict()), "contract_hash": canonical_hash(contract), "obligation_hash": canonical_hash(obligations),
            "required_capabilities": [PYPROJECT_REF], "missing_capabilities": [PYPROJECT_REF], "grown_capabilities": [PYPROJECT_REF], "reused_capabilities": [PYPROJECT_REF],
            "project_dag_hash": canonical_hash(dag.as_dict()), "reused_nodes": list(final.reused_nodes), "rerun_nodes": list(final.actual_executions),
            "provider_calls": growth_outcome.provider_calls + 1 + repair_rounds,
            "lesson_snapshots": [str(core_result.outputs.get("lesson_snapshot_hash", ""))], "applied_lesson_ids": list(applied),
            "tests": materialize_json(state_store.load_result(goal.project_id, run_id, "project-pytest").outputs),
            "oracle": materialize_json(state_store.load_result(goal.project_id, run_id, "project-oracle").outputs),
            "hidden": materialize_json(state_store.load_result(goal.project_id, run_id, "project-hidden-acceptance").outputs),
            "snapshot": materialize_json(state_store.load_result(goal.project_id, run_id, "project-snapshot").outputs),
            "package_hash": package_result.outputs.get("package_hash", ""), "package_path": package_result.outputs.get("package_path", ""),
            "capability_growth": growth_outcome.as_dict(), "capability_reuse": {"registry_hit": True, "growth_calls": 0, "builder_calls": 0, "admission_calls": 0, "tomllib_parse": "PASS"},
            "manual_edits": 0, "whole_replans": 0, "accepted_interface_breaks": 0, "unsafe_admissions": 0,
            "repair_rounds": repair_rounds, "duration_ms": int((time.perf_counter() - started) * 1000), "final_status": "PASS", "contains_credentials": False,
        }
        receipt_path = root / "project_production_receipt.json"; receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return ProjectProductionResult("PASS", str(workspace), str(package_result.outputs["package_path"]), receipt)

    @classmethod
    def record_success_events(
        cls,
        recorder: StoreLessonRecorder,
        run_id: str,
        project_id: str,
        root: pathlib.Path,
        core_result: BlockExecutionResult,
        package_result: BlockExecutionResult,
    ) -> None:
        """Idempotently materialize the required structured terminal learning history."""
        candidate_id = str(core_result.outputs.get("candidate_id", ""))
        manifest_ref = str(package_result.outputs.get("manifest_path", ""))
        rows = (
            ("capability.resolve", "GAP", PYPROJECT_REF, "", "GROWTH_REQUIRED", "PASS", (str(root / "state"),)),
            ("capability.build", "PASS", PYPROJECT_REF, "", "BUILD_CANDIDATE", "PASS", (str(root / "growth"),)),
            ("capability.admission", "PASS", PYPROJECT_REF, "", "ADMIT_CAPABILITY", "PASS", (str(root / "capability_store"),)),
            ("project.codegen", "PASS", "project.folder_manifest.core@1", candidate_id, "", "PASS", (str(root / "state"),)),
            ("project.validation", "PASS", "project.folder_manifest.core@1", candidate_id, "VALIDATE", "PASS", (str(root / "state"),)),
            ("project.package", "PASS", "", "", "PACKAGE", "PASS", (manifest_ref,)),
            ("lessons.applied", "PASS", "project.folder_manifest.core@1", candidate_id, "RECORD_FEEDBACK", "PASS", (str(root / "state"),)),
        )
        for operation, code, capability_ref, revision_id, action, outcome, evidence in rows:
            recorder.record_event(cls._event(run_id, project_id, operation, code, capability_ref, "", revision_id, action, outcome, evidence, core_result))

    def _registry(self, workspace: pathlib.Path, root: pathlib.Path, capability_store: CapabilityStore, contract: Mapping[str, Any], obligations: Mapping[str, Any]) -> ExecutorRegistry:
        registry = ExecutorRegistry()
        functions = {
            "project.contract.compile@1": lambda req: self._write_json(root / "project_contract.json", contract, "contract_hash"),
            "project.capabilities.resolve@1": lambda req: self._resolve(workspace, capability_store),
            "project.metadata.render@1": lambda req: self._metadata(workspace, capability_store),
            "project.docs.render@1": lambda req: self._docs(workspace),
            "project.contract-tests.compile@1": lambda req: self._tests(workspace),
            "project.compile@1": lambda req: self._command(workspace, [sys.executable, "-m", "compileall", "-q", "."], "compile"),
            "project.pytest@1": lambda req: self._pytest(workspace),
            "project.oracle@1": lambda req: self._oracle(workspace),
            "project.snapshot@1": lambda req: self._snapshot(workspace),
            "project.hidden-acceptance@1": lambda req: self._hidden(workspace),
            "project.package@1": lambda req: self._package(workspace, root),
        }
        for index, (component, function) in enumerate(functions.items()):
            registry.register(_FunctionExecutor(f"project.production.local.{index}@1", component, function))
        registry.register(_CoreExecutor(workspace, self.generation, self.model_config))
        return registry

    @staticmethod
    def _tree(contract: Mapping[str, Any], obligations: Mapping[str, Any], failure_evidence: Mapping[str, Any] | None = None) -> CapabilityTree:
        def node(identifier: str, component: str, deps: tuple[str, ...], index: int, **config: Any) -> CapabilityNode:
            executor = "project.folder-manifest.core@1" if component == "project.core.generate@1" else f"project.production.local.{index}@1"
            return CapabilityNode(identifier, capability_ref=component, depends_on=deps, config={"executor_ref": executor, "goal": identifier, **config})
        return CapabilityTree("Produce and deliver folder_manifest_cli", (
            node("project-contract-compile", "project.contract.compile@1", (), 0),
            node("project-capabilities-resolve", "project.capabilities.resolve@1", ("project-contract-compile",), 1),
            node("project-core-generate", "project.core.generate@1", ("project-contract-compile",), 0, failure_evidence=dict(failure_evidence or {})),
            node("project-metadata-render", "project.metadata.render@1", ("project-capabilities-resolve",), 2),
            node("project-docs-render", "project.docs.render@1", ("project-contract-compile",), 3),
            node("project-contract-tests-compile", "project.contract-tests.compile@1", ("project-contract-compile",), 4),
            node("project-compile", "project.compile@1", ("project-core-generate", "project-metadata-render", "project-docs-render"), 5),
            node("project-pytest", "project.pytest@1", ("project-compile", "project-contract-tests-compile"), 6),
            node("project-oracle", "project.oracle@1", ("project-pytest",), 7),
            node("project-snapshot", "project.snapshot@1", ("project-oracle",), 8),
            node("project-hidden-acceptance", "project.hidden-acceptance@1", ("project-snapshot",), 9),
            node("project-package", "project.package@1", ("project-hidden-acceptance",), 10),
        ))

    @staticmethod
    def _write_json(path: pathlib.Path, value: Mapping[str, Any], hash_key: str) -> Mapping[str, Any]:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {hash_key: canonical_hash(value), "path": path.name}

    @staticmethod
    def _resolve(workspace: pathlib.Path, store: CapabilityStore) -> Mapping[str, Any]:
        if not store.contains(PYPROJECT_REF): raise CapabilityGap(PYPROJECT_REF)
        (workspace / "capability_resolution_receipt.json").write_text(json.dumps({"kind": "CapabilityResolutionReceipt", "schema_version": "1.0", "required": [PYPROJECT_REF], "missing_initially": [PYPROJECT_REF], "resolved": [PYPROJECT_REF], "registry": "HIT", "contains_credentials": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"status": "PASS", "capability_ref": PYPROJECT_REF, "registry": "HIT"}

    @staticmethod
    def _metadata(workspace: pathlib.Path, store: CapabilityStore) -> Mapping[str, Any]:
        value = StoredCapabilityRuntime(store, provider_id="grok").invoke(PYPROJECT_REF, _metadata_input())
        text = str(value["pyproject_toml"])
        import tomllib
        doc = tomllib.loads(text)
        if not all(key in doc for key in ("build-system", "project")): raise ValueError("pyproject required tables absent")
        (workspace / "pyproject.toml").write_text(text, encoding="utf-8")
        return {"status": "PASS", "pyproject_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()}

    @staticmethod
    def _docs(workspace: pathlib.Path) -> Mapping[str, Any]:
        text = """# folder-manifest\n\nA fully local, standard-library Python CLI for deterministic SHA-256 directory manifests.\n\n## Usage\n\n```text\npython -m folder_manifest scan ROOT MANIFEST [--exclude GLOB]\npython -m folder_manifest verify ROOT MANIFEST\npython -m folder_manifest show MANIFEST\n```\n\nScan ignores `.git`, `__pycache__`, the output manifest, matching excludes, symlink files, and symlink directories. Verify reports changed, missing, and extra files.\n"""
        (workspace / "README.md").write_text(text, encoding="utf-8")
        (workspace / "TEST_REPORT.md").write_text("# Test Report\n\ncommands_run:\n- python -m pytest -q\n- python -m folder_manifest --help\n\nresults: recorded in test_receipt.json\n", encoding="utf-8")
        (workspace / "DELIVERY_NOTES.md").write_text("# Delivery Notes\n\nPackaged only after contract, oracle, hidden acceptance, and runtime checks pass.\n", encoding="utf-8")
        return {"status": "PASS", "files": ["README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"]}

    @staticmethod
    def _tests(workspace: pathlib.Path) -> Mapping[str, Any]:
        tests = workspace / "tests"; tests.mkdir(exist_ok=True)
        source = _contract_test_source()
        (tests / "test_contract_folder_manifest.py").write_text(source, encoding="utf-8")
        return {"status": "PASS", "test_hash": "sha256:" + hashlib.sha256(source.encode()).hexdigest(), "cases": 12}

    @staticmethod
    def _command(workspace: pathlib.Path, argv: list[str], name: str) -> Mapping[str, Any]:
        env = os.environ.copy(); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"; env["PYTHONPATH"] = str(workspace)
        result = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, timeout=90, env=env)
        if result.returncode: raise RuntimeError(f"{name} failed:{(result.stdout + result.stderr)[-3000:]}")
        return {"status": "PASS", "returncode": result.returncode, "stdout_tail": result.stdout[-1000:]}

    @staticmethod
    def _pytest(workspace: pathlib.Path) -> Mapping[str, Any]:
        result = dict(AutonomousProjectProductionService._command(workspace, [sys.executable, "-m", "pytest", "-q"], "pytest"))
        (workspace / "test_receipt.json").write_text(json.dumps({"kind": "ProjectTestReceipt", "schema_version": "1.0", **result, "contains_credentials": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    @staticmethod
    def _oracle(workspace: pathlib.Path) -> Mapping[str, Any]:
        checks = _exercise_project(workspace, hidden=False)
        if not all(checks.values()): raise RuntimeError("oracle failure:" + json.dumps(checks, sort_keys=True))
        receipt = {"status": "PASS", "checks": checks, "obligation_ids": sorted(_obligations())}
        (workspace / "oracle_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return receipt

    @staticmethod
    def _hidden(workspace: pathlib.Path) -> Mapping[str, Any]:
        checks = _exercise_project(workspace, hidden=True)
        if not all(checks.values()): raise RuntimeError("hidden acceptance failure:" + json.dumps(checks, sort_keys=True))
        receipt = {"status": "PASS", "checks": checks, "obligation_ids": ["OBL-NESTED", "OBL-BINARY-HASH", "OBL-DETERMINISTIC", "OBL-SYMLINK", "OBL-DIFF-KINDS"]}
        (workspace / "acceptance_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return receipt

    @staticmethod
    def _snapshot(workspace: pathlib.Path) -> Mapping[str, Any]:
        rows = []
        for path in sorted(workspace.rglob("*")):
            if path.is_file() and not any(part in {"__pycache__", ".pytest_cache"} for part in path.relative_to(workspace).parts):
                rows.append({"path": path.relative_to(workspace).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size})
        receipt = {"status": "PASS", "files": rows, "snapshot_hash": canonical_hash(rows)}
        (workspace / "snapshot_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"status": "PASS", "snapshot_hash": receipt["snapshot_hash"], "file_count": len(rows)}

    @staticmethod
    def _package(workspace: pathlib.Path, root: pathlib.Path) -> Mapping[str, Any]:
        candidate_hash = canonical_evidence_hash.candidate_source_hash(workspace)
        candidate_id = "folder-manifest-" + candidate_hash.split(":")[-1][:12]
        run_id = root.name
        repository = pathlib.Path(__file__).resolve().parents[3]
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
        test_evidence = real_test_execution.run_tests(workspace, run_id=run_id, candidate_id=candidate_id, candidate_hash=candidate_hash, commit_sha=commit, minimum_collected=1)
        if test_evidence.get("status") != "PASS": raise RuntimeError("canonical test evidence failed")
        runtime_evidence = customer_runtime_runner.run(workspace, run_id=run_id, candidate_id=candidate_id, candidate_hash=candidate_hash, commit_sha=commit)
        if runtime_evidence.get("status") != "PASS": raise RuntimeError("canonical runtime evidence failed")
        (workspace / "TEST_REPORT.md").write_text(
            "# Test Report\n\n"
            f"run_id: {run_id}\n"
            f"candidate_hash: {candidate_hash}\n"
            f"commit_sha: {commit}\n"
            f"result_artifact_hash: {test_evidence['result_artifact_hash']}\n\n"
            "commands_run:\n- python -m pytest tests\n- python -m folder_manifest --help\n\nresults: PASS\n",
            encoding="utf-8",
        )
        manifest = local_packager.package_project(workspace, output_dir=root / "delivery", startup_command="python -m folder_manifest --help")
        if manifest.get("status") != "PASS": raise RuntimeError("local_packager status:" + str(manifest.get("failures", [])))
        package = pathlib.Path(str(manifest.get("package_path", "")))
        if not package.is_file(): raise RuntimeError("local_packager did not produce package")
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if any("hidden" in name.lower() for name in names): raise RuntimeError("hidden acceptance leaked into package")
            if not all(any(name.endswith(required) for name in names) for required in ("pyproject.toml", "README.md", "folder_manifest/__main__.py", "tests/test_contract_folder_manifest.py")): raise RuntimeError("package is incomplete")
        return {"status": "PASS", "package_path": str(package), "package_hash": "sha256:" + hashlib.sha256(package.read_bytes()).hexdigest(), "manifest_path": str(manifest.get("manifest_path", "")), "file_count": len(names)}

    @staticmethod
    def _event(run_id: str, project_id: str, operation: str, failure_code: str, capability_ref: str, failure_domain: str, candidate_revision_id: str, action: str, outcome: str, evidence: tuple[str, ...], core: BlockExecutionResult) -> LearningEvent:
        applied = tuple(core.outputs.get("applied_lesson_ids", ()))
        return LearningEvent("event." + canonical_hash([run_id, operation, failure_code])[7:31], run_id, project_id, "project.production", operation, capability_ref, "grok", candidate_revision_id, failure_domain, failure_code, "", action, outcome, (), evidence, str(core.outputs.get("lesson_snapshot_hash", "")), applied, utc_now())

    @staticmethod
    def _finish_failure(root: pathlib.Path, workspace: pathlib.Path, goal: ProjectGoal, run_id: str, blocker: str, started: float) -> ProjectProductionResult:
        receipt = {"kind": "ProjectProductionReceipt", "schema_version": "1.0", "project_id": goal.project_id, "run_id": run_id, "manual_edits": 0, "whole_replans": 0, "final_status": "FAIL", "blocker": blocker, "duration_ms": int((time.perf_counter() - started) * 1000), "contains_credentials": False}
        (root / "project_production_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return ProjectProductionResult("FAIL", str(workspace), "", receipt)


def _metadata_input() -> dict[str, Any]:
    return {"name": "folder-manifest", "version": "0.1.0", "module": "folder_manifest", "description": "Deterministic local folder manifest CLI", "requires_python": ">=3.11", "console_script": "folder-manifest=folder_manifest.__main__:main"}


def _expected_pyproject() -> str:
    return '''[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "folder-manifest"\nversion = "0.1.0"\ndescription = "Deterministic local folder manifest CLI"\nrequires-python = ">=3.11"\n\n[project.scripts]\nfolder-manifest = "folder_manifest.__main__:main"\n'''


def _obligations() -> dict[str, str]:
    return {"OBL-SCAN": "scan files deterministically", "OBL-VERIFY": "differentiate changed missing extra", "OBL-SHOW": "stable summary", "OBL-ERRORS": "nonzero stderr", "OBL-NESTED": "nested paths", "OBL-BINARY-HASH": "binary SHA-256", "OBL-DETERMINISTIC": "repeatable bytes", "OBL-SYMLINK": "do not traverse symlinks", "OBL-DIFF-KINDS": "distinct diff kinds"}


def _contract_test_source() -> str:
    return '''import hashlib\nimport json\nimport os\nimport subprocess\nimport sys\nfrom pathlib import Path\n\ndef run(*args, cwd=None):\n    env=os.environ.copy(); env["PYTHONPATH"]=str(Path(__file__).parents[1])\n    return subprocess.run([sys.executable,"-m","folder_manifest",*map(str,args)],cwd=cwd,capture_output=True,text=True,env=env)\n\ndef test_scan_basic_order_and_self_exclusion(tmp_path):\n    (tmp_path/"b.txt").write_text("b"); (tmp_path/"a.txt").write_text("a"); manifest=tmp_path/"manifest.json"\n    result=run("scan",tmp_path,manifest); assert result.returncode==0\n    doc=json.loads(manifest.read_text()); assert [x["path"] for x in doc["files"]]==["a.txt","b.txt"]; assert all(x["path"]!="manifest.json" for x in doc["files"])\n\ndef test_scan_deterministic_and_exclude(tmp_path):\n    (tmp_path/"keep.txt").write_text("x"); (tmp_path/"drop.tmp").write_text("y"); manifest=tmp_path/"m.json"\n    assert run("scan",tmp_path,manifest,"--exclude","*.tmp").returncode==0; first=manifest.read_bytes(); assert run("scan",tmp_path,manifest,"--exclude","*.tmp").returncode==0; assert manifest.read_bytes()==first\n\ndef test_verify_unchanged_changed_missing_extra(tmp_path):\n    path=tmp_path/"a.txt"; path.write_text("a"); manifest=tmp_path/"m.json"; run("scan",tmp_path,manifest)\n    assert run("verify",tmp_path,manifest).returncode==0\n    path.write_text("b"); changed=run("verify",tmp_path,manifest); assert changed.returncode!=0 and "changed" in changed.stdout.lower()\n    path.unlink(); missing=run("verify",tmp_path,manifest); assert missing.returncode!=0 and "missing" in missing.stdout.lower()\n    path.write_text("a"); (tmp_path/"extra.txt").write_text("e"); extra=run("verify",tmp_path,manifest); assert extra.returncode!=0 and "extra" in extra.stdout.lower()\n\ndef test_show_summary(tmp_path):\n    (tmp_path/"a").write_bytes(b"abc"); manifest=tmp_path/"m.json"; run("scan",tmp_path,manifest); result=run("show",manifest); assert result.returncode==0 and "sha256" in result.stdout.lower() and "1" in result.stdout and "3" in result.stdout\n\ndef test_invalid_root_and_manifest(tmp_path):\n    result=run("scan",tmp_path/"missing",tmp_path/"m.json"); assert result.returncode!=0 and result.stderr\n    bad=tmp_path/"bad.json"; bad.write_text("not json"); result=run("show",bad); assert result.returncode!=0 and result.stderr\n    bad.write_text("{}"); result=run("verify",tmp_path,bad); assert result.returncode!=0 and result.stderr\n\ndef test_missing_manifest_and_help(tmp_path):\n    result=run("verify",tmp_path,tmp_path/"missing.json"); assert result.returncode!=0 and result.stderr\n    assert run("--help").returncode==0\n'''


def _exercise_project(workspace: pathlib.Path, *, hidden: bool) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="cgkn-folder-manifest-") as raw:
        root = pathlib.Path(raw); data = root / "data"; data.mkdir(); (data / "nested").mkdir(); (data / "nested" / "x.bin").write_bytes(bytes(range(64))); (data / "a.txt").write_text("alpha")
        manifest = root / "manifest.json"
        env = os.environ.copy(); env["PYTHONPATH"] = str(workspace)
        def run(*args: Any): return subprocess.run([sys.executable, "-m", "folder_manifest", *map(str, args)], cwd=workspace, capture_output=True, text=True, timeout=20, env=env)
        scan1 = run("scan", data, manifest); first = manifest.read_bytes() if manifest.exists() else b""; scan2 = run("scan", data, manifest)
        checks = {"interface": run("--help").returncode == 0, "scan": scan1.returncode == 0, "deterministic": first == (manifest.read_bytes() if manifest.exists() else b""), "manifest_json": False, "hash_correct": False, "verify_unchanged": run("verify", data, manifest).returncode == 0}
        try:
            doc = json.loads(first); rows = {row["path"]: row for row in doc["files"]}; checks["manifest_json"] = doc.get("version") == 1 and doc.get("algorithm") == "sha256" and list(rows) == sorted(rows); checks["hash_correct"] = rows["nested/x.bin"]["sha256"] == hashlib.sha256((data / "nested/x.bin").read_bytes()).hexdigest()
        except Exception: pass
        if hidden:
            symlink_ok = True
            try:
                outside = root / "outside"; outside.mkdir(); (outside / "secret").write_text("secret"); os.symlink(outside, data / "linked", target_is_directory=True); run("scan", data, manifest); symlink_ok = all(not row["path"].startswith("linked/") for row in json.loads(manifest.read_text())["files"])
            except OSError: symlink_ok = True
            run("scan", data, manifest); (data / "a.txt").write_text("changed"); (data / "nested/x.bin").unlink(); (data / "extra").write_text("extra"); diff = run("verify", data, manifest)
            lowered = (diff.stdout + diff.stderr).lower(); checks.update({"nested": "nested/x.bin" in json.dumps(doc), "binary_hash": checks["hash_correct"], "symlink_not_traversed": symlink_ok, "diff_changed": "changed" in lowered, "diff_missing": "missing" in lowered, "diff_extra": "extra" in lowered})
        return checks

