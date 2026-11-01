"""Production DAG tests: real executor overlap, joins, conflicts and recovery."""
import threading
import pytest
from tests.qualification_support import probe_node, probe_runner

from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore


class Witness:
    descriptor = ExecutorDescriptor('witness@1', 'deterministic', ('*',))

    def __init__(self):
        self.b_started = threading.Event()
        self.c_started = threading.Event()
        self.trace = []

    def execute(self, request):
        node = request.node_id
        self.trace.append((node, 'start'))
        if node == 'a':
            assert self.b_started.wait(3), 'independent B never overlapped A'
        elif node == 'b':
            self.b_started.set()
            assert self.c_started.wait(3), 'C was held behind unrelated B'
        elif node == 'c':
            self.c_started.set()
        self.trace.append((node, 'end'))
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
            node_id=node, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
            status=BlockStatus.SUCCEEDED, outputs={'node': node})


def test_event_frontier_and_no_side_effect_replay(tmp_path):
    executor = Witness()
    registry = ExecutorRegistry()
    registry.register(executor)
    tree = CapabilityTree('event frontier', tuple(probe_node(n, capability_ref='work@1',
        depends_on=deps, config={'executor_ref': 'witness@1', 'parallel_safe': True,
                                'resources': {n: 'write'}})
        for n, deps in [('a', ()), ('b', ()), ('c', ('a',)), ('join', ('b', 'c'))]))
    store = FileRunStore(tmp_path)
    runner = probe_runner(registry, store, max_parallel=2)
    result = runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree))
    assert result.status == 'SUCCEEDED'
    assert executor.trace.index(('c', 'start')) < executor.trace.index(('b', 'end'))
    before = list(executor.trace)
    assert not runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree), resume=True).actual_executions
    assert executor.trace == before
    events = store.load_events('p', 'r')
    assert len([e for e in events if e.event_type == 'NODE_DISPATCHED']) == 4


def test_shared_resource_claims():
    def claim(mode):
        return {'parallel_safe': True, 'resources': {'database': mode}}
    assert DAGRunner._compatible(claim('read'), claim('read'))
    assert not DAGRunner._compatible(claim('write'), claim('read'))
    assert not DAGRunner._compatible(claim('write'), claim('write'))
    assert not DAGRunner._compatible({}, claim('read'))


def test_unknown_dispatch_is_not_replayed(tmp_path):
    tree = CapabilityTree('unknown', (probe_node('a', capability_ref='work@1',
        config={'executor_ref': 'witness@1'}),))
    store = FileRunStore(tmp_path)
    registry = ExecutorRegistry()
    witness = Witness()
    registry.register(witness)
    runner = probe_runner(registry, store)
    state = runner._new_state('p', 'r', compile_tree(tree))
    state.nodes['a'].status = 'RUNNING'
    store.save_run(state)
    result = runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree), resume=True)
    assert result.blocked_nodes == ('a',)
    assert not witness.trace


def test_receipt_committed_before_state_failure_is_recovered_without_replay(tmp_path, monkeypatch):
    tree = CapabilityTree('recover receipt', (probe_node('c', capability_ref='work@1',
        config={'executor_ref': 'witness@1'}),))
    store = FileRunStore(tmp_path)
    registry = ExecutorRegistry()
    witness = Witness()
    registry.register(witness)
    runner = probe_runner(registry, store)
    original = store.atomic_json

    def fail_latest(path, value):
        if path.parent.name == 'node_results':
            raise OSError('injected durable latest receipt write failure')
        return original(path, value)

    monkeypatch.setattr(store, 'atomic_json', fail_latest)
    with pytest.raises(OSError, match='injected'):
        runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree))
    assert store.load_run('p', 'r').nodes['c'].status == 'RUNNING'
    assert (store.run_dir('p', 'r') / 'attempts/c/attempt-0001.json').exists()
    monkeypatch.setattr(store, 'atomic_json', original)
    result = runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree), resume=True)
    assert result.status == 'SUCCEEDED'
    assert witness.trace == [('c', 'start'), ('c', 'end')]


def test_pre_dispatch_cancel_and_coordinator_lock(tmp_path):
    tree = CapabilityTree('cancel', (probe_node('c', capability_ref='work@1',
        config={'executor_ref': 'witness@1'}),))
    store = FileRunStore(tmp_path)
    registry = ExecutorRegistry()
    witness = Witness()
    registry.register(witness)
    runner = probe_runner(registry, store)
    with store.exclusive_run('p', 'r'):
        with pytest.raises(RuntimeError, match='active coordinator'):
            runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree))
    cancel = threading.Event()
    cancel.set()
    result = runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree), cancel=cancel)
    assert result.blocked_nodes == ('c',) and not witness.trace


def test_inflight_cancel_preserves_observed_result_without_success(tmp_path):
    cancel = threading.Event()

    class Cancelling(Witness):
        def execute(self, request):
            result = super().execute(request)
            cancel.set()
            return result

    tree = CapabilityTree('late cancel', (probe_node('c', capability_ref='work@1',
        config={'executor_ref': 'witness@1'}),))
    store = FileRunStore(tmp_path)
    registry = ExecutorRegistry()
    registry.register(Cancelling())
    result = probe_runner(registry, store).run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree), cancel=cancel)
    assert result.status == 'FAILED'
    receipt = store.load_result('p', 'r', 'c')
    assert receipt.status == BlockStatus.BLOCKED
    assert receipt.metadata['observed_execution_status'] == 'SUCCEEDED'
    assert receipt.outputs['node'] == 'c'
