"""Artifact compatibility views must not own scheduling or replay decisions."""
import json

import pytest

from cgkn.runtime import ArtifactModuleRunner, ModuleExecutionError
from cgkn.state import FileRunStore
from tests.test_component_runtime_integration import _runner, ROOT, FLOW
from tests.artifact_authority_support import artifact_runner as ArtifactModuleRunner


def state_store(runner):
    return FileRunStore(runner.run_dir / 'execution')


def test_artifact_execution_and_repeat_use_canonical_state(tmp_path, monkeypatch):
    runner, inputs = _runner(tmp_path)
    runner.run(inputs)
    store = state_store(runner)
    state = store.load_run('artifact-flow', 'session')
    assert set(state.nodes) == set(runner.graph.node_outputs)
    assert all(n.status == 'SUCCEEDED' for n in state.nodes.values())
    from cgkn.runtime.node_authority import ExecutionAuthority
    authority=ExecutionAuthority(store,'artifact-flow','session')
    for artifact in runner.store.list_artifacts():
        if artifact.producer.node_id=='flow_input':continue
        saved=store.load_result('artifact-flow','session',artifact.producer.node_id)
        receipt=authority.validate_execution_result(saved)
        path=str(runner.store._path(artifact.id))
        assert path in receipt.output_hashes
        assert runner.store.resolve_governed(artifact.ref,authority=authority,receipt_id=receipt.receipt_id).ref==artifact.ref
    receipts = list((runner.run_dir / 'component_receipts').glob('*.json'))
    before = {p: p.read_bytes() for p in receipts}
    second = ArtifactModuleRunner(ROOT, runner.run_dir, FLOW)
    monkeypatch.setattr(second, '_run_node', lambda *a: pytest.fail('successful module replayed'))
    result = second.run(inputs)
    assert result['outputs']
    assert all(row['reuse_authority'] == 'DAGRunner' for row in result['feedForwardReport']['nodes'])
    assert all(p.read_bytes() == data for p, data in before.items())


def test_failed_branch_does_not_erase_independent_success(tmp_path):
    runner, inputs = _runner(tmp_path)
    runner.local_functions['cgkn.runtime.reference_modules:interpret_requirement'] = (
        lambda *a: (_ for _ in ()).throw(RuntimeError('controlled local failure')))
    with pytest.raises(ModuleExecutionError, match='controlled local failure'):
        runner.run(inputs)
    state = state_store(runner).load_run('artifact-flow', 'session')
    assert state.nodes['n_requirement_interpretation'].status == 'FAILED'
    assert state.nodes['n_project_snapshot'].status == 'SUCCEEDED'
    assert state.nodes['n_problem_analysis'].status == 'BLOCKED'


def test_unknown_is_not_replayed_by_new_adapter_instance(tmp_path, monkeypatch):
    runner, inputs = _runner(tmp_path)
    class UnknownTransport(RuntimeError):
        outcome_unknown = True
    runner.local_functions['cgkn.runtime.reference_modules:interpret_requirement'] = (
        lambda *a: (_ for _ in ()).throw(UnknownTransport('response lost')))
    with pytest.raises(ModuleExecutionError):
        runner.run(inputs)
    result = state_store(runner).load_result('artifact-flow', 'session', 'n_requirement_interpretation')
    assert result.error.details['outcome_unknown'] is True
    second = ArtifactModuleRunner(ROOT, runner.run_dir, FLOW)
    monkeypatch.setattr(second, '_run_node', lambda *a: pytest.fail('unknown operation replayed'))
    with pytest.raises(ModuleExecutionError):
        second.run(inputs)
    with pytest.raises(ModuleExecutionError, match='UNRESOLVED_OUTCOME'):
        second.run(inputs, retry_node='n_requirement_interpretation')


def test_tampered_artifact_cannot_be_reused(tmp_path, monkeypatch):
    runner, inputs = _runner(tmp_path)
    result = runner.run(inputs)
    ref = result['outputs']['project_snapshot']
    path = runner.store.artifacts_dir / (ref.artifact_instance_id + '.json')
    document = json.loads(path.read_text(encoding='utf-8'))
    document['content'] = {'tampered': True}
    path.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises((ModuleExecutionError, ValueError)):
        second = ArtifactModuleRunner(ROOT, runner.run_dir, FLOW)
        monkeypatch.setattr(second, '_run_node', lambda *a: pytest.fail('tamper triggered automatic replay'))
        second.run(inputs)


def test_changed_loaded_implementation_requires_explicit_redecision(tmp_path):
    runner, inputs = _runner(tmp_path)
    runner.run(inputs)
    second = ArtifactModuleRunner(ROOT, runner.run_dir, FLOW)
    second.local_functions['cgkn.runtime.reference_modules:interpret_requirement'] = lambda *a: {}
    with pytest.raises(ModuleExecutionError, match='explicit edit commit required'):
        second.run(inputs)


def test_changed_input_identity_is_not_silently_rebound(tmp_path):
    from cgkn.artifacts import ArtifactInstance, Producer, Provenance
    runner, inputs = _runner(tmp_path)
    runner.run(inputs)
    old = runner.store.resolve_artifact_ref(inputs['raw_requirement'])
    new = runner.store.write_artifact(ArtifactInstance(runner.store.allocate_id(old.artifact_type),
        old.artifact_type, runner.run_dir.name, Producer('flow_input','module.test@1','raw_requirement'),
        old.content, Provenance()),execution_mode='IMPORTED_UNMANAGED')
    second = ArtifactModuleRunner(ROOT, runner.run_dir, FLOW)
    with pytest.raises(ModuleExecutionError, match='explicit edit commit required'):
        second.run({**inputs,'raw_requirement':new})
