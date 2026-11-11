from tests.calibration_admission import run_calibration
from contextvars import ContextVar
from threading import Barrier

from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.state import FileRunStore
from tests.qualification_support import probe_node, probe_runner


def test_parallel_dispatch_inherits_context_and_isolates_mutation(tmp_path):
    scope = ContextVar('request_scope', default='missing')
    token = scope.set('parent-audit')
    barrier = Barrier(2, timeout=10)
    observations = {}

    class Worker:
        descriptor = ExecutorDescriptor('ctx@1', 'local', ('ctx@1',))
        def execute(self, request):
            inherited = scope.get()
            scope.set(request.node_id)
            barrier.wait()
            observations[request.node_id] = (inherited, scope.get())
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
                node_id=request.node_id, attempt_id=request.attempt_id,
                executor_ref=request.executor_ref, status=BlockStatus.SUCCEEDED,
                outputs={'node':request.node_id})

    registry = ExecutorRegistry()
    registry.register(Worker())
    tree = CapabilityTree('context propagation', tuple(probe_node(n, capability_ref='ctx@1',
        config={'executor_ref':'ctx@1', 'parallel_safe':True, 'resources':{n:'write'}}) for n in ('a','b')))
    try:
        result = run_calibration(governed_probe_runner(registry, FileRunStore(tmp_path), max_parallel=2),
            project_id='p', run_id='r', tree=tree, dag=compile_tree(tree))
        assert result.status == 'SUCCEEDED'
        assert observations == {'a':('parent-audit','a'), 'b':('parent-audit','b')}
        assert scope.get() == 'parent-audit'
    finally:
        scope.reset(token)


def governed_probe_runner(*args, **kwargs):
    return probe_runner(*args, execution_mode="GOVERNED", **kwargs)
