from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import uuid
from dataclasses import replace
from typing import Any, Mapping

from cgkn.capabilities import CapabilityDescriptor, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus
from cgkn.execution.contracts import utc_now
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import EventRecord

from .action_policy import CapabilityBuildActionPolicy
from .contracts import CapabilityBuildReceipt, CapabilityPackage, CapabilityRisk, CapabilitySpec
from .lifecycle_contracts import (
    ActionDecision,
    BuildLifecycleState,
    CandidateRevision,
    FailureDomain,
    RecommendedAction,
    ValidationReceipt,
)
from .revision_store import CandidateRevisionStore, canonical_hash, capability_slug
from .validators import ValidationContext, ValidationSuite


class _ValidationExecutor:
    def __init__(self, lifecycle: "CapabilityBuildLifecycleService", context: ValidationContext, suite: ValidationSuite, index: int):
        self.lifecycle, self.context, self.suite, self.index = lifecycle, context, suite, index
        validator = suite.validators[index]
        self.descriptor = ExecutorDescriptor(
            f"candidate.validator.{validator.phase.value.lower()}@1", "deterministic_validator",
            (f"candidate.validate.{validator.phase.value.lower()}@1",), (), True, False, "local",
        )

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        previous: list[dict[str, Any]] = []
        if request.task_context.dependency_results:
            only = next(iter(request.task_context.dependency_results.values()))
            previous = list(only.get("receipts", ()))
        receipt = self.suite.validate_one(self.suite.validators[self.index], self.context)
        self.lifecycle.revision_store.save_validation(receipt)
        return BlockExecutionResult(
            request.project_id, request.run_id, request.attempt_id, request.node_id,
            request.executor_ref, BlockStatus.SUCCEEDED,
            outputs={"receipts": previous + [receipt.as_dict()]},
            started_at=utc_now(), ended_at=utc_now(), duration_ms=receipt.duration_ms,
        )


class _ActionExecutor:
    def __init__(self, lifecycle: "CapabilityBuildLifecycleService", candidate_exists: bool, repair_budget: int, provider_operation: str):
        self.lifecycle = lifecycle
        self.candidate_exists = candidate_exists
        self.repair_budget = repair_budget
        self.provider_operation = provider_operation
        self.descriptor = ExecutorDescriptor(
            "candidate.action-policy@1", "deterministic_policy", ("candidate.action.decide@1",), (), True, False, "local",
        )

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        dependency = next(iter(request.task_context.dependency_results.values()), {})
        receipts = list(dependency.get("receipts", ()))
        failed = next((row for row in receipts if row.get("status") != "PASS"), None)
        domain = FailureDomain(str(failed["failure_domain"])) if failed and failed.get("failure_domain") else None
        decision = self.lifecycle.action_policy.decide(
            domain, candidate_exists=self.candidate_exists,
            repair_budget=self.repair_budget, provider_operation=self.provider_operation,
        )
        revision = self.lifecycle._active_revision
        self.lifecycle.revision_store.transition(
            revision.capability_ref, revision.build_run_id, decision.target_state,
            reason=decision.reason,
            evidence_refs=tuple(str(row.get("validation_id")) for row in receipts),
            actor="CapabilityBuildActionPolicy", current_revision_id=revision.revision_id,
            last_action=decision.action.value,
        )
        return BlockExecutionResult(
            request.project_id, request.run_id, request.attempt_id, request.node_id,
            request.executor_ref, BlockStatus.SUCCEEDED,
            outputs={"receipts": receipts, "decision": decision.as_dict()},
            started_at=utc_now(), ended_at=utc_now(), duration_ms=0,
        )


class CapabilityBuildLifecycleService:
    LIFECYCLE_VERSION = "1.0"

    def __init__(self, generation_adapter: Any, capability_store: Any, *, action_policy: CapabilityBuildActionPolicy | None = None):
        self.generation_adapter = generation_adapter
        self.capability_store = capability_store
        self.action_policy = action_policy or CapabilityBuildActionPolicy()
        self.revision_store: CandidateRevisionStore
        self._active_revision: CandidateRevision

    @staticmethod
    def lifecycle_tree() -> CapabilityTree:
        names = (
            "spec.validate", "route.freeze", "candidate.generate", "candidate.persist",
            "candidate.syntax.validate", "candidate.scope.validate", "candidate.interface.validate",
            "candidate.contract.validate", "candidate.dependency.validate", "candidate.risk.validate",
            "candidate.security.validate", "candidate.runtime.validate", "candidate.serialization.validate",
            "candidate.external.validate", "action.decide", "candidate.admission", "candidate.install", "original.resume",
        )
        nodes = []
        for index, name in enumerate(names):
            nodes.append(CapabilityNode(name, capability_ref=f"lifecycle.{name}@1", depends_on=(names[index - 1],) if index else (), config={"executor_ref": f"lifecycle.{name}@1"}))
        return CapabilityTree("Build one immutable capability candidate through governed lifecycle", tuple(nodes))

    @classmethod
    def lifecycle_dag(cls):
        return compile_tree(cls.lifecycle_tree())

    def build(self, artifact_root: pathlib.Path | str, spec: CapabilitySpec) -> CapabilityBuildReceipt:
        root = pathlib.Path(artifact_root).resolve()
        self.revision_store = CandidateRevisionStore(root)
        build_run_id = f"build-{uuid.uuid4().hex[:12]}"
        spec_hash = canonical_hash(spec.as_dict())
        route_hash = canonical_hash({"provider_id": self.generation_adapter.provider_id, "mode": self.generation_adapter.mode, "model": self.generation_adapter.config.model})
        self.revision_store.initialize_run(spec.ref, build_run_id, spec_hash=spec_hash, route_snapshot_hash=route_hash)
        self.revision_store.transition(spec.ref, build_run_id, BuildLifecycleState.ROUTE_FROZEN, reason="provider route snapshot frozen")
        calls = repairs = 0
        usage: dict[str, Any] = {}
        try:
            dependency_manifest = self.capability_store.resolve_dependency_manifest(spec) if spec.allowed_dependencies else []
        except Exception as exc:
            self.revision_store.transition(spec.ref, build_run_id, BuildLifecycleState.GENERATION_REQUESTED, reason="dependency resolution evaluated before generation")
            self.revision_store.transition(spec.ref, build_run_id, BuildLifecycleState.PROVIDER_BLOCKED, reason=f"dependency unavailable: {exc}")
            return self._receipt(spec, root, calls, repairs, None, False, False, False, usage, f"{type(exc).__name__}: {exc}")
        dependency_hash = canonical_hash(dependency_manifest)
        self.revision_store.transition(spec.ref, build_run_id, BuildLifecycleState.GENERATION_REQUESTED, reason="candidate generation authorized")
        staging = root / ".candidate_staging" / build_run_id / "generation"
        generated = self.generation_adapter.generate_candidate(staging, spec, route_snapshot_hash=route_hash)
        calls += 1
        usage = dict(generated.provider_receipt.actual_tokens)
        if not generated.source_path:
            self.revision_store.save_provider_attempt(spec.ref, build_run_id, generated.provider_receipt)
            decision = self.action_policy.decide(generated.failure_domain, candidate_exists=False, provider_operation="GENERATION")
            self.revision_store.transition(spec.ref, build_run_id, decision.target_state, reason=decision.reason, last_action=decision.action.value)
            return self._receipt(spec, root, calls, repairs, None, False, False, False, usage, generated.error)
        revision = self.revision_store.create_revision(
            generated.source_path, capability_ref=spec.ref, build_run_id=build_run_id,
            spec_hash=spec_hash, route_snapshot_hash=route_hash, provider_id=self.generation_adapter.provider_id,
            provider_request_id=generated.provider_receipt.request_id, provider_response_id=generated.provider_receipt.response_id,
            provider_operation="GENERATION", creation_reason="PROVIDER_GENERATION",
        )
        self.revision_store.save_provider_attempt(spec.ref, build_run_id, replace(generated.provider_receipt, candidate_revision_created=True))
        shutil.rmtree(pathlib.Path(generated.source_path).parent, ignore_errors=True)
        self.revision_store.transition(spec.ref, build_run_id, BuildLifecycleState.CANDIDATE_CREATED, reason="immutable revision published", current_revision_id=revision.revision_id)
        suite = ValidationSuite(contract_test_hashes=self._contract_hashes(revision), fixture_hashes={"capability_spec": spec_hash}, policy_version=self.action_policy.version)
        receipts, decision = self.revalidate_candidate(revision.revision_id, suite, spec=spec, dependency_manifest_hash=dependency_hash, repair_budget=1, external_status="BLOCKED_EXTERNAL")
        if decision.action is RecommendedAction.REPAIR_CANDIDATE:
            repairs = 1
            self.revision_store.transition(spec.ref, build_run_id, BuildLifecycleState.REPAIR_REQUESTED, reason="repair authorized only by action policy", evidence_refs=tuple(row.validation_id for row in receipts), last_action=decision.action.value)
            repair_staging = root / ".candidate_staging" / build_run_id / "repair"
            failed = next(row for row in receipts if row.status != "PASS")
            repaired = self.generation_adapter.repair_candidate(
                self.revision_store.source_path(revision.revision_id), repair_staging, spec,
                route_snapshot_hash=route_hash, failure_evidence=failed.as_dict(), decision=decision,
            )
            calls += 1
            usage = dict(repaired.provider_receipt.actual_tokens)
            if not repaired.source_path:
                self.revision_store.save_provider_attempt(spec.ref, build_run_id, repaired.provider_receipt)
                blocked = self.action_policy.decide(repaired.failure_domain, candidate_exists=True, provider_operation="REPAIR")
                self.revision_store.transition(spec.ref, build_run_id, blocked.target_state, reason=blocked.reason, current_revision_id=revision.revision_id, last_action=blocked.action.value)
                return self._receipt(spec, root, calls, repairs, revision, False, False, False, usage, repaired.error)
            child = self.revision_store.create_revision(
                repaired.source_path, capability_ref=spec.ref, build_run_id=build_run_id,
                spec_hash=spec_hash, route_snapshot_hash=route_hash, provider_id=self.generation_adapter.provider_id,
                provider_request_id=repaired.provider_receipt.request_id, provider_response_id=repaired.provider_receipt.response_id,
                provider_operation="REPAIR", creation_reason="ACTION_POLICY_AUTHORIZED_REPAIR",
                parent_revision_id=revision.revision_id,
            )
            self.revision_store.save_provider_attempt(spec.ref, build_run_id, replace(repaired.provider_receipt, candidate_revision_created=True))
            shutil.rmtree(pathlib.Path(repaired.source_path).parent, ignore_errors=True)
            self.revision_store.transition(spec.ref, build_run_id, BuildLifecycleState.CANDIDATE_CREATED, reason="repair created child immutable revision", current_revision_id=child.revision_id)
            receipts, decision = self.revalidate_candidate(child.revision_id, suite, spec=spec, dependency_manifest_hash=dependency_hash, repair_budget=0, external_status="BLOCKED_EXTERNAL", provider_operation="REPAIR")
            revision = child
        if decision.action is not RecommendedAction.ADMIT_CANDIDATE:
            failure = next((row.failure_code for row in receipts if row.status != "PASS"), decision.reason)
            return self._receipt(spec, root, calls, repairs, revision, False, False, False, usage, failure)
        installed = self._admit_and_install(revision, spec, dependency_manifest, external_status="BLOCKED_EXTERNAL")
        return self._receipt(spec, root, calls, repairs, revision, True, installed, installed, usage, "" if installed else "installation failed")

    def recover_candidate(
        self,
        artifact_root: pathlib.Path | str,
        source: pathlib.Path | str,
        spec: CapabilitySpec,
        *,
        build_run_id: str,
        provider_id: str,
        provider_request_id: str,
        route_snapshot_hash: str,
    ) -> CandidateRevision:
        self.revision_store = CandidateRevisionStore(artifact_root)
        spec_hash = canonical_hash(spec.as_dict())
        self.revision_store.initialize_run(spec.ref, build_run_id, spec_hash=spec_hash, route_snapshot_hash=route_snapshot_hash)
        self.revision_store.transition(spec.ref, build_run_id, BuildLifecycleState.ROUTE_FROZEN, reason="recovered historical frozen route")
        revision = self.revision_store.create_revision(
            source, capability_ref=spec.ref, build_run_id=build_run_id, spec_hash=spec_hash,
            route_snapshot_hash=route_snapshot_hash, provider_id=provider_id,
            provider_request_id=provider_request_id, provider_response_id=provider_request_id,
            provider_operation="GENERATION", creation_reason="RECOVERED_FROM_ITER_023_INITIAL_PROVIDER_OUTPUT",
        )
        self.revision_store.transition(spec.ref, build_run_id, BuildLifecycleState.CANDIDATE_CREATED, reason="verified historical initial candidate imported", current_revision_id=revision.revision_id)
        return revision

    def revalidate_candidate(
        self,
        revision_id: str,
        validator_suite: ValidationSuite,
        *,
        spec: CapabilitySpec | None = None,
        dependency_manifest_hash: str | None = None,
        repair_budget: int = 0,
        external_status: str = "NOT_PROBED",
        provider_operation: str = "GENERATION",
    ) -> tuple[tuple[ValidationReceipt, ...], ActionDecision]:
        revision = self.revision_store.load_revision(revision_id)
        source_hash = revision.source_hash
        if spec is None:
            spec = CapabilitySpec.from_dict(json.loads((self.revision_store.source_path(revision_id) / "capability.json").read_text(encoding="utf-8")))
        dependency_hash = dependency_manifest_hash or canonical_hash(self.capability_store.resolve_dependency_manifest(spec) if spec.allowed_dependencies else [])
        state = BuildLifecycleState(str(self.revision_store.load_state(revision.capability_ref, revision.build_run_id)["state"]))
        prior = self.revision_store.validation_receipts(revision_id)
        prior_hashes = {str(row.get("validator_suite_hash")) for row in prior}
        if prior_hashes and validator_suite.identity.validator_suite_hash not in prior_hashes:
            self.revision_store.file_store.append_event(EventRecord(
                f"event.{uuid.uuid4().hex}", capability_slug(revision.capability_ref), revision.build_run_id,
                "VALIDATION_RECEIPT_STALE", data={"status": "STALE_VALIDATOR_CHANGED", "old_suite_hashes": sorted(prior_hashes), "new_suite_hash": validator_suite.identity.validator_suite_hash, "action": RecommendedAction.REVALIDATE_EXISTING.value},
            ))
            if state is BuildLifecycleState.BLOCKED_FRAMEWORK:
                self.revision_store.transition(revision.capability_ref, revision.build_run_id, BuildLifecycleState.REVALIDATION_REQUIRED, reason="validator suite changed", current_revision_id=revision_id, last_action=RecommendedAction.REVALIDATE_EXISTING.value)
                state = BuildLifecycleState.REVALIDATION_REQUIRED
        if state is BuildLifecycleState.CANDIDATE_CREATED:
            self.revision_store.transition(revision.capability_ref, revision.build_run_id, BuildLifecycleState.VALIDATION_PENDING, reason="candidate awaits validation", current_revision_id=revision_id)
            state = BuildLifecycleState.VALIDATION_PENDING
        elif state is BuildLifecycleState.PROVIDER_BLOCKED:
            self.revision_store.transition(revision.capability_ref, revision.build_run_id, BuildLifecycleState.VALIDATION_PENDING, reason="resume existing candidate without Provider", current_revision_id=revision_id)
            state = BuildLifecycleState.VALIDATION_PENDING
        elif state is BuildLifecycleState.VALIDATION_FAILED:
            self.revision_store.transition(revision.capability_ref, revision.build_run_id, BuildLifecycleState.REVALIDATION_REQUIRED, reason="explicit revalidation requested", current_revision_id=revision_id)
            state = BuildLifecycleState.REVALIDATION_REQUIRED
        if state not in {BuildLifecycleState.VALIDATION_PENDING, BuildLifecycleState.REVALIDATION_REQUIRED}:
            raise ValueError(f"candidate cannot be revalidated from {state.value}")
        self.revision_store.transition(revision.capability_ref, revision.build_run_id, BuildLifecycleState.VALIDATING, reason="deterministic validator DAG started", current_revision_id=revision_id)
        self._active_revision = revision
        context = ValidationContext(revision, self.revision_store.source_path(revision_id), spec, dependency_hash, self.capability_store, external_status, False)
        registry = ExecutorRegistry()
        nodes = []
        previous = ""
        for index, validator in enumerate(validator_suite.validators):
            executor = _ValidationExecutor(self, context, validator_suite, index)
            registry.register(executor)
            node_id = f"validate-{index:02d}-{validator.phase.value.lower()}"
            nodes.append(CapabilityNode(node_id, capability_ref=executor.descriptor.supported_refs[0], depends_on=(previous,) if previous else (), config={"executor_ref": executor.descriptor.executor_ref}))
            previous = node_id
        action_executor = _ActionExecutor(self, True, repair_budget, provider_operation)
        registry.register(action_executor)
        nodes.append(CapabilityNode("action-decide", capability_ref="candidate.action.decide@1", depends_on=(previous,), config={"executor_ref": action_executor.descriptor.executor_ref}))
        tree = CapabilityTree("Validate one immutable candidate and decide one governed action", tuple(nodes))
        dag = compile_tree(tree)
        validation_run_id = f"{revision.build_run_id}-validation"
        run_path = self.revision_store.file_store.root / capability_slug(revision.capability_ref) / validation_run_id / "run_state.json"
        summary = DAGRunner(registry, self.revision_store.file_store).run(
            project_id=capability_slug(revision.capability_ref), run_id=validation_run_id,
            tree=tree, dag=dag, resume=run_path.is_file(), retry_node=nodes[0].id if run_path.is_file() else None,
        )
        if summary.status != "SUCCEEDED":
            raise RuntimeError("validator DAG failed")
        action_result = self.revision_store.file_store.load_result(capability_slug(revision.capability_ref), validation_run_id, "action-decide")
        rows = tuple(self._receipt_from_dict(row) for row in action_result.outputs["receipts"])
        raw = action_result.outputs["decision"]
        decision = ActionDecision(RecommendedAction(str(raw["action"])), BuildLifecycleState(str(raw["target_state"])), str(raw["reason"]))
        if self.revision_store.load_revision(revision_id).source_hash != source_hash:
            raise RuntimeError("REVALIDATION_AUTHORITY_VIOLATION: candidate source changed")
        return rows, decision

    def resume(self, revision_id: str, validator_suite: ValidationSuite) -> tuple[tuple[ValidationReceipt, ...], ActionDecision]:
        revision = self.revision_store.load_revision(revision_id)
        state = BuildLifecycleState(str(self.revision_store.load_state(revision.capability_ref, revision.build_run_id)["state"]))
        if state is BuildLifecycleState.ADMISSION_PENDING:
            self.admit_candidate(revision_id, external_status="NOT_PROBED")
            receipts = tuple(self._receipt_from_dict(row) for row in self.revision_store.validation_receipts(revision_id))
            return receipts, ActionDecision(RecommendedAction.ADMIT_CANDIDATE, BuildLifecycleState.ADMISSION_PENDING, "resumed directly from passed validation")
        return self.revalidate_candidate(revision_id, validator_suite)

    def admit_candidate(self, revision_id: str, *, external_status: str = "NOT_PROBED") -> bool:
        revision = self.revision_store.load_revision(revision_id)
        spec = CapabilitySpec.from_dict(json.loads((self.revision_store.source_path(revision_id) / "capability.json").read_text(encoding="utf-8")))
        dependency_manifest = self.capability_store.resolve_dependency_manifest(spec) if spec.allowed_dependencies else []
        return self._admit_and_install(revision, spec, dependency_manifest, external_status=external_status)

    def _admit_and_install(self, revision: CandidateRevision, spec: CapabilitySpec, dependency_manifest: list[dict[str, Any]], *, external_status: str) -> bool:
        state = BuildLifecycleState(str(self.revision_store.load_state(spec.ref, revision.build_run_id)["state"]))
        if state is not BuildLifecycleState.ADMISSION_PENDING:
            raise ValueError("admission requires ADMISSION_PENDING")
        staging_parent = self.revision_store.root / ".install_staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging = pathlib.Path(tempfile.mkdtemp(prefix="install-", dir=staging_parent))
        try:
            source = self.revision_store.source_path(revision.revision_id)
            shutil.copytree(source, staging / "package", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            package_root = staging / "package"
            component = ComponentSpec(spec.capability_id, spec.version, (PortSpec("value", "artifact.capability.value@1"),), (PortSpec("result", "artifact.capability.result@1"),), metadata={"risk": spec.risk.value})
            executor_ref = f"generated.{spec.capability_id}@{spec.version}"
            package = CapabilityPackage(spec, str(package_root), component.ref, executor_ref, revision.package_hash, ("tests/test_capability.py",))
            effects = ("public_network_read",) if spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK else (("capability_dependency_execute",) if spec.allowed_dependencies else ())
            descriptor = CapabilityDescriptor(spec.capability_id, spec.version, component.ref, executor_ref, ("generated_python",), ("value",), ("result",), effects, 10.0, "local", "LOW", "candidate_lifecycle", {"provider_id": revision.provider_id, "source_hash": revision.package_hash, "candidate_revision_id": revision.revision_id, "dependencies": spec.allowed_dependencies}, package.test_refs)
            registry = CapabilityRegistry({component.ref: component})
            registry.register_candidate(descriptor)
            registry.admit(spec.ref)
            admission = {
                "kind": "CapabilityAdmission", "schema_version": "1.2", "capability_ref": spec.ref,
                "status": "ADMITTED", "source_hash": revision.package_hash, "candidate_revision_id": revision.revision_id,
                "provider_id": revision.provider_id, "mode": self.generation_adapter.mode, "manual_edits": 0,
                "dependency_manifest": dependency_manifest, "local_status": "VALIDATED_LOCAL",
                "external_readiness": external_status, "contains_credentials": False,
            }
            (package_root / "admission.json").write_text(json.dumps(admission, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.revision_store.transition(spec.ref, revision.build_run_id, BuildLifecycleState.ADMITTED, reason="validated revision admitted", current_revision_id=revision.revision_id)
            self.capability_store.put(package)
            self.revision_store.transition(spec.ref, revision.build_run_id, BuildLifecycleState.INSTALLED, reason="admitted revision installed in capability store", current_revision_id=revision.revision_id)
            self.revision_store.transition(spec.ref, revision.build_run_id, BuildLifecycleState.RESUMED, reason="original task may resume", current_revision_id=revision.revision_id)
            return True
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _contract_hashes(revision: CandidateRevision) -> dict[str, str]:
        return {str(row["path"]): str(row["sha256"]) for row in revision.source_manifest if str(row["path"]).startswith("tests/")}

    @staticmethod
    def _receipt_from_dict(value: Mapping[str, Any]) -> ValidationReceipt:
        from .lifecycle_contracts import FailureOwner, ValidationPhase
        return ValidationReceipt(
            str(value["validation_id"]), str(value["candidate_revision_id"]), str(value["candidate_source_hash"]),
            str(value["spec_hash"]), str(value["dependency_manifest_hash"]), str(value["validator_suite_id"]),
            str(value["validator_suite_hash"]), str(value["validator_version"]), ValidationPhase(str(value["validation_phase"])),
            str(value["status"]), FailureDomain(str(value["failure_domain"])) if value.get("failure_domain") else None,
            str(value.get("failure_code", "")), FailureOwner(str(value["failure_owner"])) if value.get("failure_owner") else None,
            value.get("expected"), value.get("observed"), tuple(value.get("evidence_refs", ())),
            RecommendedAction(str(value["recommended_action"])), str(value["started_at"]), str(value["ended_at"]),
            int(value["duration_ms"]), str(value["receipt_hash"]),
        )

    def _receipt(self, spec: CapabilitySpec, root: pathlib.Path, calls: int, repairs: int, revision: CandidateRevision | None, tests: bool, executed: bool, stored: bool, usage: dict[str, Any], error: str) -> CapabilityBuildReceipt:
        return CapabilityBuildReceipt(
            spec.ref, self.generation_adapter.provider_id, self.generation_adapter.mode,
            str(self.revision_store.source_path(revision.revision_id)) if revision else str(root),
            calls, repairs, tests, stored, executed, stored, 0, "PASS" if stored else "FAIL", usage, error[:4000],
        )
