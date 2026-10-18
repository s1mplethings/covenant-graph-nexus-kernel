from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cgkn.application.capability_builder import (
    ActionDecision,
    BuildLifecycleState,
    CandidateRevisionStore,
    CapabilityBuildActionPolicy,
    CapabilityBuildLifecycleService,
    CapabilityBuilderService,
    CapabilityRisk,
    CapabilitySpec,
    CapabilityStore,
    FailureDomain,
    FailureOwner,
    ProviderAttemptReceipt,
    RecommendedAction,
    ValidationPhase,
    ValidationSuite,
)
from cgkn.application.capability_builder.lifecycle_contracts import ValidationReceipt
from cgkn.application.capability_builder.revision_store import canonical_hash
from cgkn.application.capability_builder.validators import (
    CandidateValidator,
    DependencyValidator,
    ExternalSmokeValidator,
    RuntimeExampleValidator,
    ValidationContext,
    ValidationObservation,
)
from cgkn.providers import ModelRoleConfig, ProviderCompletion


def _spec(*, output="ok", dependencies=()) -> CapabilitySpec:
    runtime = {"dependency_results": {dependencies[0]: []}} if dependencies else {}
    return CapabilitySpec(
        "example.echo", "1", "return a deterministic value", {}, {},
        ({"input": "x", "output": output, "runtime": runtime},), ("matches the example",),
        CapabilityRisk.READ_ONLY_PUBLIC_NETWORK_COMPOSITE if dependencies else CapabilityRisk.PURE,
        tuple(dependencies),
    )


def _source(root: Path, spec: CapabilitySpec, code: str = "def execute(value):\n    return 'ok'\n") -> Path:
    root.mkdir(parents=True)
    (root / "executor.py").write_text(code, encoding="utf-8")
    (root / "capability.json").write_text(json.dumps(spec.as_dict()), encoding="utf-8")
    (root / "README.md").write_text("# candidate\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests/test_capability.py").write_text("def test_placeholder(): assert True\n", encoding="utf-8")
    return root


def _revision(tmp_path: Path, spec: CapabilitySpec | None = None, code: str = "def execute(value):\n    return 'ok'\n"):
    spec = spec or _spec()
    store = CandidateRevisionStore(tmp_path / "artifacts")
    spec_hash = canonical_hash(spec.as_dict())
    store.initialize_run(spec.ref, "run-1", spec_hash=spec_hash, route_snapshot_hash="sha256:route")
    store.transition(spec.ref, "run-1", BuildLifecycleState.ROUTE_FROZEN, reason="test")
    revision = store.create_revision(
        _source(tmp_path / "source", spec, code), capability_ref=spec.ref, build_run_id="run-1",
        spec_hash=spec_hash, route_snapshot_hash="sha256:route", provider_id="fake",
        provider_operation="GENERATION", creation_reason="TEST",
    )
    store.transition(spec.ref, "run-1", BuildLifecycleState.CANDIDATE_CREATED, reason="test", current_revision_id=revision.revision_id)
    return store, revision, spec


def test_revision_round_trip_and_frozen_contract(tmp_path: Path):
    store, revision, _ = _revision(tmp_path)
    loaded = store.load_revision(revision.revision_id)
    assert loaded == revision
    with pytest.raises(Exception):
        loaded.source_hash = "changed"  # type: ignore[misc]


def test_revision_source_manifest_hash_is_stable(tmp_path: Path):
    store, revision, _ = _revision(tmp_path)
    assert store.load_revision(revision.revision_id).source_hash == revision.source_hash


def test_revision_tamper_is_detected(tmp_path: Path):
    store, revision, _ = _revision(tmp_path)
    (store.source_path(revision.revision_id) / "executor.py").write_text("def execute(value): return 'tampered'\n")
    with pytest.raises(ValueError, match="IMMUTABILITY"):
        store.load_revision(revision.revision_id)


def test_duplicate_revision_is_rejected(tmp_path: Path):
    store, revision, spec = _revision(tmp_path)
    with pytest.raises(FileExistsError):
        store.create_revision(
            tmp_path / "source", capability_ref=spec.ref, build_run_id="run-1",
            spec_hash=revision.spec_hash, route_snapshot_hash=revision.route_snapshot_hash,
            provider_id="fake", provider_operation="GENERATION", creation_reason="DUPLICATE",
        )


def test_repair_revision_has_parent_and_distinct_hash(tmp_path: Path):
    store, first, spec = _revision(tmp_path)
    second_source = _source(tmp_path / "source-2", spec, "def execute(value):\n    return 'fixed'\n")
    second = store.create_revision(
        second_source, capability_ref=spec.ref, build_run_id="run-1", spec_hash=first.spec_hash,
        route_snapshot_hash=first.route_snapshot_hash, provider_id="fake", provider_operation="REPAIR",
        creation_reason="REPAIR", parent_revision_id=first.revision_id,
    )
    assert second.parent_revision_id == first.revision_id and second.source_hash != first.source_hash
    assert store.load_revision(first.revision_id).source_hash == first.source_hash


def test_partial_staging_is_not_published(tmp_path: Path, monkeypatch):
    spec = _spec()
    store = CandidateRevisionStore(tmp_path / "artifacts")
    store.initialize_run(spec.ref, "run-1", spec_hash=canonical_hash(spec.as_dict()), route_snapshot_hash="sha256:route")
    monkeypatch.setattr(store, "_durable_json", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        store.create_revision(
            _source(tmp_path / "source", spec), capability_ref=spec.ref, build_run_id="run-1",
            spec_hash=canonical_hash(spec.as_dict()), route_snapshot_hash="sha256:route",
            provider_id="fake", provider_operation="GENERATION", creation_reason="TEST",
        )
    revisions = store.run_dir(spec.ref, "run-1") / "revisions"
    assert not (revisions / "r0001").exists() and not list(revisions.glob(".r0001.*"))


def test_valid_transition_appends_event_history(tmp_path: Path):
    store, _, spec = _revision(tmp_path)
    events = store.events(spec.ref, "run-1")
    assert [event.event_type for event in events].count("LIFECYCLE_TRANSITION") == 2


def test_illegal_transition_is_rejected(tmp_path: Path):
    spec = _spec()
    store = CandidateRevisionStore(tmp_path / "artifacts")
    store.initialize_run(spec.ref, "run-1", spec_hash="sha256:spec", route_snapshot_hash="sha256:route")
    with pytest.raises(ValueError, match="ILLEGAL_LIFECYCLE_TRANSITION"):
        store.transition(spec.ref, "run-1", BuildLifecycleState.ADMITTED, reason="skip validation")


def test_validation_receipt_hash_is_semantically_stable(tmp_path: Path):
    store, revision, spec = _revision(tmp_path)
    context = ValidationContext(revision, store.source_path(revision.revision_id), spec, canonical_hash([]))
    suite = ValidationSuite(validators=(RuntimeExampleValidator(),), version="stable")
    assert suite.validate_one(suite.validators[0], context).receipt_hash == suite.validate_one(suite.validators[0], context).receipt_hash


def test_provider_receipt_schema_carries_no_credentials():
    receipt = ProviderAttemptReceipt("a", "GENERATION", "grok", "grok-4.7", "r", "s", "h", "start", "end", "PASS", "", False, {"input": 1}, {"output": 1}, 0.1, True)
    assert receipt.as_dict()["contains_credentials"] is False
    assert not ({"token", "api_key", "credential"} & set(receipt.as_dict()))


@pytest.mark.parametrize(
    ("domain", "exists", "budget", "operation", "action"),
    [
        (FailureDomain.CANDIDATE_DEFECT, True, 1, "GENERATION", RecommendedAction.REPAIR_CANDIDATE),
        (FailureDomain.FRAMEWORK_HARNESS_DEFECT, True, 1, "GENERATION", RecommendedAction.REVALIDATE_EXISTING),
        (FailureDomain.FRAMEWORK_VALIDATOR_DEFECT, True, 1, "GENERATION", RecommendedAction.REVALIDATE_EXISTING),
        (FailureDomain.PROVIDER_TRANSPORT_FAILURE, False, 0, "GENERATION", RecommendedAction.RETRY_GENERATION),
        (FailureDomain.PROVIDER_TRANSPORT_FAILURE, True, 0, "REPAIR", RecommendedAction.RETRY_TRANSPORT),
        (FailureDomain.EXTERNAL_DEPENDENCY_FAILURE, True, 1, "GENERATION", RecommendedAction.WAIT_EXTERNAL),
        (FailureDomain.ENVIRONMENT_BLOCKED, True, 1, "GENERATION", RecommendedAction.BLOCK_ENVIRONMENT),
        (FailureDomain.DEPENDENCY_DRIFT, True, 1, "GENERATION", RecommendedAction.REVALIDATE_DEPENDENCY),
        (FailureDomain.UNKNOWN_FAILURE, True, 1, "GENERATION", RecommendedAction.ESCALATE_REVIEW),
        (FailureDomain.CANDIDATE_POLICY_DEFECT, True, 1, "GENERATION", RecommendedAction.REJECT_CANDIDATE),
    ],
)
def test_action_policy(domain, exists, budget, operation, action):
    assert CapabilityBuildActionPolicy().decide(domain, candidate_exists=exists, repair_budget=budget, provider_operation=operation).action is action


def test_syntax_failure_is_owned_by_candidate(tmp_path: Path):
    store, revision, spec = _revision(tmp_path, code="def broken(:\n")
    receipt = ValidationSuite().validate_one(ValidationSuite().validators[0], ValidationContext(revision, store.source_path(revision.revision_id), spec, canonical_hash([])))
    assert receipt.failure_domain is FailureDomain.CANDIDATE_DEFECT and receipt.failure_owner is FailureOwner.CANDIDATE


def test_runtime_fixture_failure_is_owned_by_harness(tmp_path: Path):
    spec = _spec(output="ok", dependencies=("missing@1",))
    code = "def execute(value, ctx):\n    ctx.capabilities.invoke('other@1', value)\n    return 'ok'\n"
    store, revision, _ = _revision(tmp_path, spec, code)
    receipt = ValidationSuite(validators=(RuntimeExampleValidator(),)).validate_one(RuntimeExampleValidator(), ValidationContext(revision, store.source_path(revision.revision_id), spec, canonical_hash([])))
    assert receipt.failure_domain is FailureDomain.FRAMEWORK_HARNESS_DEFECT and receipt.failure_owner is FailureOwner.HARNESS


def test_validator_exception_is_owned_by_validator(tmp_path: Path):
    class BrokenValidator:
        phase, version = ValidationPhase.SYNTAX, "x"
        def validate(self, context):
            raise RuntimeError("framework bug")
    store, revision, spec = _revision(tmp_path)
    validator = BrokenValidator()
    receipt = ValidationSuite(validators=(validator,)).validate_one(validator, ValidationContext(revision, store.source_path(revision.revision_id), spec, canonical_hash([])))
    assert receipt.failure_domain is FailureDomain.FRAMEWORK_VALIDATOR_DEFECT and receipt.failure_owner is FailureOwner.VALIDATOR


def test_dependency_hash_mismatch_is_owned_by_dependency(tmp_path: Path):
    spec = _spec(dependencies=("base.echo@1",))
    code = "def execute(value, ctx):\n    ctx.capabilities.invoke('base.echo@1', value)\n    return 'ok'\n"
    store, revision, _ = _revision(tmp_path, spec, code)
    fake_store = SimpleNamespace(resolve_dependency_manifest=lambda value: [{"capability_ref": "base.echo@1", "package_hash": "new"}])
    context = ValidationContext(revision, store.source_path(revision.revision_id), spec, "sha256:old", fake_store)
    observation = DependencyValidator().validate(context)
    assert observation.failure_domain is FailureDomain.DEPENDENCY_DRIFT and observation.failure_owner is FailureOwner.DEPENDENCY


def test_external_rate_limit_never_recommends_repair(tmp_path: Path):
    store, revision, spec = _revision(tmp_path)
    observation = ExternalSmokeValidator().validate(ValidationContext(revision, store.source_path(revision.revision_id), spec, canonical_hash([]), external_status="GITHUB_RATE_LIMITED", external_required=True))
    assert observation.failure_domain is FailureDomain.EXTERNAL_DEPENDENCY_FAILURE
    assert observation.recommended_action is RecommendedAction.WAIT_EXTERNAL


class _NoProviderAdapter:
    provider_id, mode = "grok", "SINGLE_PROVIDER_MODE"
    config = SimpleNamespace(model="grok")
    calls = 0


class _BuggyEmptyListValidator:
    phase, version = ValidationPhase.RUNTIME_EXAMPLE, "1"
    def validate(self, context):
        return ValidationObservation("FAIL", FailureDomain.FRAMEWORK_HARNESS_DEFECT, "EMPTY_LIST_SEQUENCE_AMBIGUITY", FailureOwner.HARNESS, [], "IndexError", (), RecommendedAction.REVALIDATE_EXISTING)


class _FixedEmptyListValidator:
    phase, version = ValidationPhase.RUNTIME_EXAMPLE, "2"
    def validate(self, context):
        return ValidationObservation("PASS", expected=[], observed=[])


def test_framework_fix_revalidates_same_revision_without_provider(tmp_path: Path):
    spec = _spec(output=[])
    source = _source(tmp_path / "historical", spec, "def execute(value):\n    return []\n")
    adapter = _NoProviderAdapter()
    lifecycle = CapabilityBuildLifecycleService(adapter, CapabilityStore(tmp_path / "capabilities"))
    revision = lifecycle.recover_candidate(tmp_path / "artifacts", source, spec, build_run_id="iter-023", provider_id="grok", provider_request_id="request-023", route_snapshot_hash="sha256:route")
    before = revision.source_hash
    first_receipts, first_action = lifecycle.revalidate_candidate(revision.revision_id, ValidationSuite(validators=(_BuggyEmptyListValidator(),), version="v1"), spec=spec, dependency_manifest_hash=canonical_hash([]))
    assert first_receipts[0].failure_domain is FailureDomain.FRAMEWORK_HARNESS_DEFECT
    assert first_action.action is RecommendedAction.REVALIDATE_EXISTING
    second_receipts, second_action = lifecycle.revalidate_candidate(revision.revision_id, ValidationSuite(validators=(_FixedEmptyListValidator(),), version="v2"), spec=spec, dependency_manifest_hash=canonical_hash([]))
    assert second_receipts[0].status == "PASS" and second_action.action is RecommendedAction.ADMIT_CANDIDATE
    assert lifecycle.revision_store.load_revision(revision.revision_id).source_hash == before
    assert adapter.calls == 0
    assert any(event.event_type == "VALIDATION_RECEIPT_STALE" for event in lifecycle.revision_store.events(spec.ref, "iter-023"))


@pytest.mark.parametrize(
    "target",
    [
        BuildLifecycleState.CANDIDATE_CREATED,
        BuildLifecycleState.VALIDATION_PENDING,
        BuildLifecycleState.VALIDATION_FAILED,
        BuildLifecycleState.REVALIDATION_REQUIRED,
        BuildLifecycleState.ADMISSION_PENDING,
        BuildLifecycleState.PROVIDER_BLOCKED,
    ],
)
def test_resume_states_do_not_repeat_provider_calls(tmp_path: Path, target: BuildLifecycleState):
    spec = _spec()
    adapter = _NoProviderAdapter()
    lifecycle = CapabilityBuildLifecycleService(adapter, CapabilityStore(tmp_path / "capabilities"))
    revision = lifecycle.recover_candidate(
        tmp_path / "artifacts", _source(tmp_path / "candidate", spec), spec,
        build_run_id="resume-run", provider_id="grok", provider_request_id="historical",
        route_snapshot_hash="sha256:route",
    )
    store = lifecycle.revision_store
    if target is not BuildLifecycleState.CANDIDATE_CREATED:
        store.transition(spec.ref, "resume-run", BuildLifecycleState.VALIDATION_PENDING, reason="test", current_revision_id=revision.revision_id)
    if target in {BuildLifecycleState.VALIDATION_FAILED, BuildLifecycleState.REVALIDATION_REQUIRED, BuildLifecycleState.PROVIDER_BLOCKED, BuildLifecycleState.ADMISSION_PENDING}:
        store.transition(spec.ref, "resume-run", BuildLifecycleState.VALIDATING, reason="test", current_revision_id=revision.revision_id)
    if target in {BuildLifecycleState.VALIDATION_FAILED, BuildLifecycleState.REVALIDATION_REQUIRED}:
        store.transition(spec.ref, "resume-run", BuildLifecycleState.VALIDATION_FAILED, reason="test", current_revision_id=revision.revision_id)
    if target is BuildLifecycleState.REVALIDATION_REQUIRED:
        store.transition(spec.ref, "resume-run", BuildLifecycleState.REVALIDATION_REQUIRED, reason="test", current_revision_id=revision.revision_id)
    if target is BuildLifecycleState.PROVIDER_BLOCKED:
        store.transition(spec.ref, "resume-run", BuildLifecycleState.REPAIR_REQUIRED, reason="test", current_revision_id=revision.revision_id)
        store.transition(spec.ref, "resume-run", BuildLifecycleState.REPAIR_REQUESTED, reason="test", current_revision_id=revision.revision_id)
        store.transition(spec.ref, "resume-run", BuildLifecycleState.PROVIDER_BLOCKED, reason="test", current_revision_id=revision.revision_id)
    if target is BuildLifecycleState.ADMISSION_PENDING:
        store.transition(spec.ref, "resume-run", BuildLifecycleState.ADMISSION_PENDING, reason="test", current_revision_id=revision.revision_id)
    receipts, decision = lifecycle.resume(revision.revision_id, ValidationSuite(validators=(_FixedEmptyListValidator(),), version=f"resume-{target.value}"))
    assert adapter.calls == 0
    assert decision.action is RecommendedAction.ADMIT_CANDIDATE
    assert store.load_revision(revision.revision_id).source_hash == revision.source_hash


class _SequenceClient:
    def __init__(self, codes, fail_at=None):
        self.codes, self.fail_at, self.calls = list(codes), fail_at, 0

    def complete(self, **kwargs):
        self.calls += 1
        if self.fail_at == self.calls:
            raise OSError("transport unavailable")
        prompt = json.loads(kwargs["user"])
        before = prompt["current_sources"]["executor.py"]
        action = {"action": "patch_file", "path": "executor.py", "find": before, "replace": self.codes[self.calls - 1]}
        envelope = {"schema_version": "1.0", "node_id": prompt["node_id"], "summary": "candidate", "actions": [action], "expected_outputs": ["tests pass"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
        return ProviderCompletion(json.dumps(envelope), "grok-4.7", f"request-{self.calls}", {"total_tokens": 1})


def _builder(tmp_path: Path, client):
    return CapabilityBuilderService(client, ModelRoleConfig("worker", "grok", 30, 1000, 0, "low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=CapabilityStore(tmp_path / "store"))


def test_candidate_repair_creates_child_and_preserves_parent(tmp_path: Path):
    client = _SequenceClient(["def execute(value):\n    return 'wrong'\n", "def execute(value):\n    return 'ok'\n"])
    receipt = _builder(tmp_path, client).build(tmp_path / "artifacts", _spec())
    assert receipt.status == "PASS" and receipt.repair_rounds == 1 and client.calls == 2
    index = json.loads((tmp_path / "artifacts/candidate_runs/candidate_revision_index.json").read_text())["revisions"]
    store = CandidateRevisionStore(tmp_path / "artifacts")
    revisions = sorted((store.load_revision(revision_id) for revision_id in index), key=lambda row: row.revision_number)
    assert len(revisions) == 2 and revisions[1].parent_revision_id == revisions[0].revision_id
    assert revisions[0].source_hash != revisions[1].source_hash
    admission = json.loads((tmp_path / "store/example-echo-1/admission.json").read_text())
    assert admission["candidate_revision_id"] == revisions[1].revision_id


def test_provider_repair_failure_preserves_parent_without_child(tmp_path: Path):
    client = _SequenceClient(["def execute(value):\n    return 'wrong'\n"], fail_at=2)
    receipt = _builder(tmp_path, client).build(tmp_path / "artifacts", _spec())
    assert receipt.status == "FAIL" and client.calls == 2
    index = json.loads((tmp_path / "artifacts/candidate_runs/candidate_revision_index.json").read_text())["revisions"]
    assert len(index) == 1
    store = CandidateRevisionStore(tmp_path / "artifacts")
    parent = store.load_revision(next(iter(index)))
    state = store.load_state(parent.capability_ref, parent.build_run_id)
    assert state["state"] == BuildLifecycleState.PROVIDER_BLOCKED.value
    assert store.load_revision(parent.revision_id).source_hash == parent.source_hash


def test_provider_failure_without_candidate_never_enters_repair(tmp_path: Path):
    client = _SequenceClient([], fail_at=1)
    receipt = _builder(tmp_path, client).build(tmp_path / "artifacts", _spec())
    assert receipt.provider_calls == 1 and receipt.repair_rounds == 0 and receipt.status == "FAIL"
    index_path = tmp_path / "artifacts/candidate_runs/candidate_revision_index.json"
    assert not index_path.exists()


def test_repair_adapter_rejects_non_policy_authority(tmp_path: Path):
    client = _SequenceClient([])
    builder = _builder(tmp_path, client)
    source = _source(tmp_path / "source", _spec())
    decision = ActionDecision(RecommendedAction.ESCALATE_REVIEW, BuildLifecycleState.NEEDS_REVIEW, "unknown")
    with pytest.raises(PermissionError, match="ACTION_POLICY"):
        builder.repair_candidate(source, tmp_path / "repair", _spec(), route_snapshot_hash="sha256:route", failure_evidence={}, decision=decision)


def test_lifecycle_uses_canonical_tree_and_dag():
    tree = CapabilityBuildLifecycleService.lifecycle_tree()
    dag = CapabilityBuildLifecycleService.lifecycle_dag()
    assert tree.nodes[0].id == "spec.validate" and tree.nodes[-1].id == "original.resume"
    assert dag.topological_order()[-1] == "original.resume"


def test_architecture_guards_validator_and_admission_provider_independence():
    roots = [
        Path("cgkn/application/capability_builder/validators.py"),
        Path("cgkn/application/capability_builder/lifecycle.py"),
    ]
    forbidden = {"CompletionClient", "ConnectorCompletionClient", "ProviderConnector", "ModelRoleConfig"}
    for path in roots:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[-1] for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
        assert not (imported & forbidden), (path, imported & forbidden)


def test_compatibility_builder_has_no_inline_repair_loop():
    path = Path("cgkn/application/capability_builder/service.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CapabilityBuilderService")
    build = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "build")
    assert not any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(build))
