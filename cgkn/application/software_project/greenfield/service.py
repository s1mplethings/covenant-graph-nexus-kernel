from __future__ import annotations

import ast
import json
import pathlib
import shutil
import tempfile
import time
import uuid
from dataclasses import replace
from typing import Any, Callable, Mapping

from cgkn.application.capability_builder import CandidateRevisionStore, ProviderAttemptReceipt
from cgkn.application.learning import GenerationRequest, ProductionGenerationClient
from cgkn.application.software_project.contracts import WorkerScope
from cgkn.application.software_project.scope import ScopedFileTransaction
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors import ExecutorRegistry
from cgkn.executors.llm import WORKER_SCHEMA, validate_worker_proposal
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.providers import GatewayCompletionError, ModelRoleConfig, ProviderConnectionError, parse_json_object
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

from .assembly import ProjectAssembler
from .contracts import AssemblyReceipt, BundleAttempt, BundleSpec, GenerationManifest, canonical_hash
from .cli import DeterministicCLICompiler, StructuredCLIPlan


class BundleValidationError(RuntimeError):
    pass


class _CallableExecutor:
    def __init__(self, ref: str, function: Callable[[BlockExecutionRequest], Mapping[str, Any]]) -> None:
        self.descriptor = ExecutorDescriptor(ref, "greenfield_bundle", (ref,), ("filesystem.write",), True, False, "local")
        self.function = function

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started = utc_now(); clock = time.perf_counter()
        try:
            output = dict(self.function(request))
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs=output, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))
        except BundleValidationError as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, str(exc), {"failure_domain": "BUNDLE_CANDIDATE_DEFECT"}), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))
        except Exception as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, f"{type(exc).__name__}: {exc}"), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))


class _ProviderBundleExecutor:
    def __init__(self, service: "GreenfieldBundleProductionService", manifest: GenerationManifest, spec: BundleSpec,
                 project_contract: Mapping[str, Any], run_id: str) -> None:
        self.service, self.manifest, self.spec = service, manifest, spec
        self.project_contract, self.run_id = project_contract, run_id
        self.descriptor = ExecutorDescriptor(spec.bundle_id, "greenfield_bundle_provider", (spec.bundle_id,), ("filesystem.write",), True, True, "provider")

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started = utc_now(); clock = time.perf_counter()
        try:
            attempt = self.service.generate_bundle(self.manifest, self.spec, self.project_contract, self.run_id)
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs=attempt.as_dict(), usage={"input_tokens": attempt.input_tokens, "output_tokens": attempt.output_tokens}, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))
        except (ProviderConnectionError, GatewayCompletionError) as exc:
            error_class = getattr(exc, "error_class", getattr(exc, "category", "PROVIDER_TRANSPORT_FAILURE"))
            outcome_unknown = bool(getattr(exc, "outcome_unknown", False))
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, f"{error_class}: {exc}", {"failure_domain": "PROVIDER_TRANSPORT_FAILURE", "provider_error_class": error_class, "outcome_unknown": outcome_unknown}), retryable=not outcome_unknown, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))
        except Exception as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, f"{type(exc).__name__}: {exc}", {"failure_domain": "BUNDLE_CANDIDATE_DEFECT"}), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter() - clock) * 1000))


class GreenfieldBundleProductionService:
    """Canonical Greenfield V2 producer over the existing DAG, state, lesson, and candidate authorities."""

    def __init__(self, generation: ProductionGenerationClient, model_config: ModelRoleConfig,
                 artifact_root: pathlib.Path | str, *, provider_id: str = "grok", route_snapshot_hash: str = "",
                 call_authorizer: Callable[[BundleSpec, str], None] | None = None) -> None:
        self.generation, self.model_config, self.provider_id = generation, model_config, provider_id
        self.root = pathlib.Path(artifact_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.revisions = CandidateRevisionStore(self.root / "candidate_lifecycle")
        self.route_snapshot_hash = route_snapshot_hash or canonical_hash({"provider": provider_id, "model": model_config.model, "fallback": "deny"})
        self.call_authorizer = call_authorizer
        self.current_revisions: dict[str, str] = {}
        self.attempts: list[BundleAttempt] = []
        self.assembly_receipt: AssemblyReceipt | None = None

    @staticmethod
    def build_tree(manifest: GenerationManifest) -> CapabilityTree:
        nodes: list[CapabilityNode] = [CapabilityNode("generation-manifest", capability_ref="project.generation-manifest.compile@1", config={"executor_ref": "project.generation-manifest.compile@1"})]
        validations: list[str] = []
        labels = {spec.bundle_id: spec.bundle_kind.value.lower().replace("_", "-") for spec in manifest.bundle_specs}
        for index, spec in enumerate(manifest.bundle_specs):
            short = labels[spec.bundle_id]
            dependency_validations = tuple(f"bundle-{labels[dependency]}-validate" for dependency in spec.depends_on)
            generate = f"bundle-{short}-generate"
            persist = f"bundle-{short}-persist"
            validate = f"bundle-{short}-validate"
            nodes.extend((
                CapabilityNode(generate, capability_ref=spec.bundle_id, depends_on=("generation-manifest",) + dependency_validations, config={"executor_ref": spec.bundle_id}),
                CapabilityNode(persist, capability_ref=f"{spec.bundle_id}.persist", depends_on=(generate,), config={"executor_ref": f"{spec.bundle_id}.persist"}),
                CapabilityNode(validate, capability_ref=f"{spec.bundle_id}.validate", depends_on=(persist,), config={"executor_ref": f"{spec.bundle_id}.validate"}),
            ))
            validations.append(validate)
        nodes.append(CapabilityNode("project-assemble", capability_ref="project.bundle.assemble@1", depends_on=tuple(validations), config={"executor_ref": "project.bundle.assemble@1"}))
        return CapabilityTree(f"Generate cohesive bundles for {manifest.project_id}", tuple(nodes))

    def run_initial(self, manifest: GenerationManifest, project_contract: Mapping[str, Any], workspace: pathlib.Path | str,
                    *, run_id: str | None = None, retry_transport: bool = True, repair_candidate: bool = True) -> Mapping[str, Any]:
        run_id = run_id or f"greenfield-{manifest.project_id}-{uuid.uuid4().hex[:10]}"
        workspace_path = pathlib.Path(workspace).resolve()
        tree = self.build_tree(manifest); dag = compile_tree(tree)
        state = FileRunStore(self.root / "state")
        registry = ExecutorRegistry()
        registry.register(_CallableExecutor("project.generation-manifest.compile@1", lambda _request: {"manifest_hash": manifest.manifest_hash}))
        for spec in manifest.bundle_specs:
            if spec.execution_mode == "PROVIDER":
                registry.register(_ProviderBundleExecutor(self, manifest, spec, project_contract, run_id))
            else:
                registry.register(_CallableExecutor(spec.bundle_id, lambda _request, bundle=spec: self.render_bundle(manifest, bundle, run_id).as_dict()))
            registry.register(_CallableExecutor(f"{spec.bundle_id}.persist", lambda _request, bundle=spec: {"revision_id": self.current_revisions[bundle.bundle_id]}))
            registry.register(_CallableExecutor(f"{spec.bundle_id}.validate", lambda _request, bundle=spec: self.validate_bundle(bundle, self.current_revisions[bundle.bundle_id])))
        registry.register(_CallableExecutor("project.bundle.assemble@1", lambda _request: self._assemble(manifest, workspace_path)))
        runner = DAGRunner(registry, state)
        result = runner.run(project_id=manifest.project_id, run_id=run_id, tree=tree, dag=dag, constraints=("stdlib only", "network forbidden", "shell forbidden", "routing frozen", "bundle targets only"))
        if result.status != "SUCCEEDED" and retry_transport:
            failed = next(iter(result.failed_nodes), "")
            if failed.endswith("-generate"):
                failed_result = state.load_result(manifest.project_id, run_id, failed)
                if failed_result.retryable and failed_result.error and failed_result.error.details.get("failure_domain") == "PROVIDER_TRANSPORT_FAILURE":
                    result = runner.run(project_id=manifest.project_id, run_id=run_id, tree=tree, dag=dag, resume=True, retry_node=failed, constraints=("stdlib only", "network forbidden", "shell forbidden", "routing frozen", "bundle targets only"))
        if result.status != "SUCCEEDED" and repair_candidate:
            failed = next(iter(result.failed_nodes), "")
            if failed.endswith("-validate"):
                label = failed.removeprefix("bundle-").removesuffix("-validate")
                labels = {spec.bundle_kind.value.lower().replace("_", "-"): spec for spec in manifest.bundle_specs}
                spec = labels.get(label)
                if spec is not None and spec.execution_mode == "PROVIDER":
                    self.repair_bundle(manifest, spec, project_contract, run_id, {"failure_domain": "BUNDLE_CANDIDATE_DEFECT", "failed_node": failed, "details": "VALIDATION_FAILED"})
                    result = runner.run(project_id=manifest.project_id, run_id=run_id, tree=tree, dag=dag, resume=True, retry_node=failed, constraints=("stdlib only", "network forbidden", "shell forbidden", "routing frozen", "bundle targets only"))
        return {"status": result.status, "run_id": run_id, "failed_nodes": list(result.failed_nodes), "revision_ids": dict(self.current_revisions), "attempts": [item.as_dict() for item in self.attempts], "assembly": self.assembly_receipt.as_dict() if self.assembly_receipt else {}, "state_root": str(state.root)}

    def render_bundle(self, manifest: GenerationManifest, spec: BundleSpec, run_id: str) -> BundleAttempt:
        if spec.execution_mode != "DETERMINISTIC" or manifest.cli_plan is None:
            raise BundleValidationError("DETERMINISTIC_BUNDLE_CONTRACT_MISSING")
        compiler = DeterministicCLICompiler(); plan = StructuredCLIPlan.from_dict(manifest.cli_plan)
        build_run_id = run_id + "-" + spec.bundle_kind.value.lower()
        self.revisions.initialize_run(spec.bundle_id, build_run_id, spec_hash=spec.bundle_hash, route_snapshot_hash=self.route_snapshot_hash)
        staging = pathlib.Path(tempfile.mkdtemp(prefix="deterministic-bundle-", dir=self.root))
        started = time.perf_counter()
        try:
            relative = spec.target_paths[0]
            target = staging / pathlib.PurePosixPath(relative); target.parent.mkdir(parents=True, exist_ok=True)
            if spec.bundle_kind.value == "CLI":
                source = compiler.render_main(plan); operation = "CLI_RENDER"
            elif spec.bundle_kind.value == "INIT":
                domain = next(item for item in manifest.bundle_specs if item.execution_mode == "PROVIDER")
                source = compiler.render_init(domain_module=domain.interface_contract.module, exports=domain.interface_contract.exports)
                operation = "INIT_RENDER"
            else:
                raise BundleValidationError("CLI_CONTRACT_UNSUPPORTED")
            target.write_text(source, encoding="utf-8", newline="\n")
            revision = self.revisions.create_revision(
                staging, capability_ref=spec.bundle_id, build_run_id=build_run_id, spec_hash=spec.bundle_hash,
                route_snapshot_hash=self.route_snapshot_hash, provider_id="deterministic", provider_operation=operation,
                creation_reason=operation, lesson_snapshot_hash=plan.plan_hash,
                generation_context_hash=canonical_hash({"compiler_version": compiler.VERSION, "plan_hash": plan.plan_hash}),
                subject_kind="DETERMINISTIC_PROJECT_BUNDLE", subject_ref=spec.bundle_id,
            )
            self.current_revisions[spec.bundle_id] = revision.revision_id
            attempt = BundleAttempt(spec.bundle_id, f"attempt.{uuid.uuid4().hex}", "CANDIDATE_CREATED", revision.revision_id,
                                    lesson_snapshot_hash=plan.plan_hash, generation_context_hash=compiler.VERSION,
                                    duration_ms=int((time.perf_counter() - started) * 1000))
            self.attempts.append(attempt)
            return attempt
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def generate_bundle(self, manifest: GenerationManifest, spec: BundleSpec, project_contract: Mapping[str, Any], run_id: str,
                        *, parent_revision_id: str = "", failure_evidence: Mapping[str, Any] | None = None) -> BundleAttempt:
        attempt_id = f"attempt.{uuid.uuid4().hex}"
        operation = "REPAIR" if parent_revision_id else "GENERATION"
        build_run_id = run_id + "-" + spec.bundle_id.split(".")[-2]
        self.revisions.initialize_run(spec.bundle_id, build_run_id, spec_hash=spec.bundle_hash, route_snapshot_hash=self.route_snapshot_hash)
        staging = pathlib.Path(tempfile.mkdtemp(prefix="bundle-candidate-", dir=self.root))
        started = time.perf_counter()
        try:
            if parent_revision_id:
                shutil.copytree(self.revisions.source_path(parent_revision_id), staging, dirs_exist_ok=True)
            current = {path.relative_to(staging).as_posix(): path.read_text(encoding="utf-8") for path in staging.rglob("*.py")}
            prompt = {
                "node_id": spec.bundle_id, "project_id": manifest.project_id, "bundle": spec.as_dict(),
                "project_contract": dict(project_contract), "frozen_interface_contract": spec.interface_contract.as_dict(),
                "dependency_interfaces": [item.interface_contract.as_dict() for item in manifest.bundle_specs if item.bundle_id in spec.depends_on],
                "dependency_interface_hashes": list(spec.required_interfaces), "current_sources": current,
                "failure_evidence": dict(failure_evidence or {}),
            }
            if self.call_authorizer is not None:
                self.call_authorizer(spec, operation)
            config = replace(self.model_config, timeout_seconds=spec.timeout_seconds, max_output_tokens=1200 if parent_revision_id else spec.max_output_tokens, reasoning_effort=spec.reasoning_effort)
            generated = self.generation.generate(GenerationRequest(
                task_class=str(spec.lesson_query["task_class"]), operation=operation, project_id=manifest.project_id,
                capability_ref=spec.bundle_id, provider_id=self.provider_id,
                system="Implement one cohesive project bundle. The frozen project and interface contracts are authoritative. Return JSON file actions only for target_paths. Do not edit tests, metadata, docs, hidden acceptance, governance, artifacts, or another bundle. Do not use network or shell.",
                goal=prompt, contract={"manifest_hash": manifest.manifest_hash, "bundle": spec.as_dict(), "project_contract_hash": manifest.project_contract_hash},
                state=current, failure_evidence=dict(failure_evidence or {}), schema_name="greenfield_bundle_actions", schema=WORKER_SCHEMA,
                model_config=config, dependency_risk_policy={"runtime": "PYTHON_STDLIB_ONLY", "network": "FORBIDDEN", "shell": "FORBIDDEN"},
                allowed_actions=spec.allowed_actions, forbidden_actions=spec.forbidden_actions, run_id=run_id,
            ))
            proposal = validate_worker_proposal(parse_json_object(generated.completion.text), spec.bundle_id)
            if proposal["needs_escalation"]:
                raise BundleValidationError(str(proposal["escalation_reason"] or "bundle escalated"))
            scope = WorkerScope(spec.target_paths, spec.target_paths, protected_paths=("tests", "pyproject.toml", "README.md", "LICENSE", ".git", "governance", "artifacts"), max_actions=len(spec.target_paths) + 1, max_write_files=len(spec.target_paths), max_total_output_bytes=spec.max_output_bytes, allow_create=True, allow_patch=bool(parent_revision_id), allow_delete=False)
            ScopedFileTransaction(staging, scope).apply(proposal["actions"])
            present = {path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file()}
            if present != set(spec.target_paths):
                raise BundleValidationError(f"BUNDLE_TARGET_MANIFEST_MISMATCH:{sorted(present)}")
            revision = self.revisions.create_revision(
                staging, capability_ref=spec.bundle_id, build_run_id=build_run_id, spec_hash=spec.bundle_hash,
                route_snapshot_hash=self.route_snapshot_hash, provider_id=self.provider_id,
                provider_request_id=str(generated.completion.request_id), provider_response_id=str(getattr(generated.completion, "response_id", "") or ""),
                provider_operation=operation, creation_reason="PROVIDER_REPAIR" if parent_revision_id else "PROVIDER_GENERATION",
                parent_revision_id=parent_revision_id or None, lesson_snapshot_hash=generated.lesson_snapshot_hash,
                applied_lesson_ids=generated.applied_lesson_ids, generation_context_hash=generated.generation_context_hash,
                subject_kind="PROJECT_BUNDLE", subject_ref=spec.bundle_id,
            )
            self.current_revisions[spec.bundle_id] = revision.revision_id
            usage = dict(generated.completion.usage)
            attempt = BundleAttempt(spec.bundle_id, attempt_id, "CANDIDATE_CREATED", revision.revision_id, parent_revision_id,
                                    lesson_snapshot_hash=generated.lesson_snapshot_hash, applied_lesson_ids=generated.applied_lesson_ids,
                                    generation_context_hash=generated.generation_context_hash, duration_ms=int((time.perf_counter() - started) * 1000),
                                    input_tokens=int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0), output_tokens=int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0), response_bytes=len(generated.completion.text.encode("utf-8")))
            self.attempts.append(attempt)
            self.revisions.save_provider_attempt(spec.bundle_id, build_run_id, ProviderAttemptReceipt(attempt_id, operation, self.provider_id, self.model_config.model, str(generated.completion.request_id), str(getattr(generated.completion, "response_id", "") or ""), self.route_snapshot_hash, utc_now(), utc_now(), "PASS", "", False, {"max_output_tokens": config.max_output_tokens}, usage, usage.get("cost_in_usd_ticks", 0), True, generated.lesson_snapshot_hash, generated.applied_lesson_ids, generated.generation_context_hash))
            return attempt
        except (ProviderConnectionError, GatewayCompletionError) as exc:
            error_class = getattr(exc, "error_class", getattr(exc, "category", "PROVIDER_TRANSPORT_FAILURE"))
            outcome_unknown = bool(getattr(exc, "outcome_unknown", False))
            attempt = BundleAttempt(spec.bundle_id, attempt_id, "PROVIDER_BLOCKED", failure_class=error_class, duration_ms=int((time.perf_counter() - started) * 1000))
            self.attempts.append(attempt)
            failure_usage = dict(getattr(exc, "evidence", {}) or {})
            self.revisions.save_provider_attempt(spec.bundle_id, build_run_id, ProviderAttemptReceipt(attempt_id, operation, self.provider_id, self.model_config.model, "", "", self.route_snapshot_hash, utc_now(), utc_now(), "FAIL", error_class, outcome_unknown, {"max_output_tokens": spec.max_output_tokens}, failure_usage, 0, False))
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def validate_bundle(self, spec: BundleSpec, revision_id: str) -> Mapping[str, Any]:
        revision = self.revisions.load_revision(revision_id)
        source = self.revisions.source_path(revision_id)
        names: set[str] = set()
        for relative in spec.target_paths:
            path = source / pathlib.PurePosixPath(relative)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            except SyntaxError as exc:
                raise BundleValidationError(f"BUNDLE_SYNTAX_ERROR:{relative}:{exc}") from exc
            module_path = spec.interface_contract.module.replace(".", "/")
            if relative in {module_path + ".py", module_path + "/__init__.py", module_path + "/__main__.py"}:
                names.update(node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
                for node in tree.body:
                    if isinstance(node, ast.ImportFrom):
                        names.update(alias.asname or alias.name for alias in node.names)
        missing = sorted(name for name in spec.interface_contract.exports if name not in names)
        if missing:
            raise BundleValidationError("BUNDLE_INTERFACE_MISSING:" + ",".join(missing))
        return {"status": "PASS", "revision_id": revision_id, "source_hash": revision.source_hash, "interface_hash": spec.interface_contract.interface_hash}

    def repair_bundle(self, manifest: GenerationManifest, spec: BundleSpec, project_contract: Mapping[str, Any], run_id: str,
                      failure_evidence: Mapping[str, Any]) -> BundleAttempt:
        parent = self.current_revisions[spec.bundle_id]
        attempt = self.generate_bundle(manifest, spec, project_contract, run_id, parent_revision_id=parent, failure_evidence=failure_evidence)
        self.validate_bundle(spec, attempt.revision_id)
        return attempt

    def adopt_repository_patch(self, manifest: GenerationManifest, spec: BundleSpec, workspace: pathlib.Path | str,
                               run_id: str, *, request_id: str = "repository.patch@1") -> str:
        parent = self.current_revisions[spec.bundle_id]
        staging = pathlib.Path(tempfile.mkdtemp(prefix="bundle-patch-", dir=self.root))
        build_run_id = run_id + "-" + spec.bundle_id.split(".")[-2]
        try:
            base = pathlib.Path(workspace).resolve()
            for relative in spec.target_paths:
                source = base / pathlib.PurePosixPath(relative)
                if not source.is_file():
                    raise BundleValidationError("PATCH_REMOVED_BUNDLE_TARGET:" + relative)
                target = staging / pathlib.PurePosixPath(relative); target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            revision = self.revisions.create_revision(
                staging, capability_ref=spec.bundle_id, build_run_id=build_run_id, spec_hash=spec.bundle_hash,
                route_snapshot_hash=self.route_snapshot_hash, provider_id=self.provider_id,
                provider_request_id=request_id, provider_operation="REPOSITORY_PATCH",
                creation_reason="REPOSITORY_PATCH_REPAIR", parent_revision_id=parent,
                subject_kind="PROJECT_BUNDLE", subject_ref=spec.bundle_id,
            )
            self.validate_bundle(spec, revision.revision_id)
            self.current_revisions[spec.bundle_id] = revision.revision_id
            return revision.revision_id
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def reassemble(self, manifest: GenerationManifest, workspace: pathlib.Path | str) -> AssemblyReceipt:
        self.assembly_receipt = ProjectAssembler(self.revisions).assemble(manifest, self.current_revisions, workspace)
        return self.assembly_receipt

    def _assemble(self, manifest: GenerationManifest, workspace: pathlib.Path) -> Mapping[str, Any]:
        self.assembly_receipt = ProjectAssembler(self.revisions).assemble(manifest, self.current_revisions, workspace)
        return self.assembly_receipt.as_dict()
