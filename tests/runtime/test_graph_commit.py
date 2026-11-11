from tests.calibration_admission import run_calibration
"""Bounded graph evolution through the canonical runner and persistent store."""
from dataclasses import replace
import pytest
from tests.qualification_support import probe_node, probe_runner
from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.executors import ExecutorRegistry, ExecutorDescriptor
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.state import FileRunStore
from cgkn.runtime import DAGRunner

class Recorder:
    descriptor=ExecutorDescriptor('record@1','deterministic',('*',))
    def __init__(self):self.calls=[]
    def execute(self,r):
        self.calls.append((r.run_id,r.node_id))
        return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,attempt_id=r.attempt_id,node_id=r.node_id,executor_ref=r.executor_ref,status=BlockStatus.SUCCEEDED,outputs={'original':dict(r.task_context.node_config)})

def setup(tmp_path):
    e=Recorder();reg=ExecutorRegistry();reg.register(e)
    return e,governed_probe_runner(reg,FileRunStore(tmp_path))
def tree(*ids):return CapabilityTree('goal',tuple(probe_node(i,capability_ref='c@1',config={'executor_ref':'record@1'}) for i in ids))
def run(r,t,identity='r',**kw):return run_calibration(r,project_id='p',run_id=identity,tree=t,dag=compile_tree(t),**kw)

def test_R1_save_reload_executes_once(tmp_path):
    e,r=setup(tmp_path);t=tree('a');run(r,t)
    run(governed_probe_runner(r.registry,FileRunStore(tmp_path)),t,resume=True)
    assert e.calls==[('r','a')]

def test_R2_missing_executor_correction_and_append(tmp_path):
    e,r=setup(tmp_path);t=CapabilityTree('goal',(probe_node('a',capability_ref='c@1'),))
    assert run(r,t).failed_nodes==('a',);assert e.calls==[]
    assert run(r,tree('a','b'),resume=True,accept_edits=True).status=='SUCCEEDED'
    assert e.calls==[('r','a'),('r','b')]
    assert len(r.store.load_run('p','r').nodes['a'].attempts)==2

def test_R3_append_reuses_completed_and_initializes_dependencies(tmp_path):
    e,r=setup(tmp_path);t=tree('a');run(r,t)
    t=CapabilityTree('goal',t.nodes+(probe_node('b',capability_ref='c@1',depends_on=('a',),config={'executor_ref':'record@1'}),))
    result=run(r,t,resume=True,accept_edits=True)
    assert result.reused_nodes==('a',) and result.actual_executions==('b',)
    assert e.calls==[('r','a'),('r','b')]

def test_R4_committed_graph_reload_and_atomic_write_failure(tmp_path,monkeypatch):
    e,r=setup(tmp_path);run(r,tree('a'));state=r.store.load_run('p','r')
    before=(tmp_path/'p/r/run_state.json').read_bytes()
    original=r.store.save_run
    monkeypatch.setattr(r.store,'save_run',lambda state: (_ for _ in ()).throw(OSError('controlled precommit failure')))
    with pytest.raises(OSError):r._bind_graph(state,compile_tree(tree('a','b')),accept_edits=True,retry_node=None)
    assert (tmp_path/'p/r/run_state.json').read_bytes()==before
    monkeypatch.setattr(r.store,'save_run',original)
    r._bind_graph(r.store.load_run('p','r'),compile_tree(tree('a','b')),accept_edits=True,retry_node=None)
    # Definition mirror still old: committed state is authoritative on restart.
    restored=governed_probe_runner(r.registry,FileRunStore(tmp_path))
    assert run(restored,tree('a','b'),resume=True,accept_edits=True).actual_executions==('b',)
    assert e.calls==[('r','a'),('r','b')]

def test_R5_real_mismatch_and_success_edit_rejected_without_state_change(tmp_path):
    e,r=setup(tmp_path);t=tree('a');run(r,t)
    before=(tmp_path/'p/r/run_state.json').read_bytes()
    with pytest.raises(ValueError,match='explicit edit'):run(r,tree('a','b'),resume=True)
    changed=CapabilityTree('goal',(probe_node('a',capability_ref='c@1',config={'executor_ref':'record@1','value':2}),))
    with pytest.raises(ValueError,match='succeeded'):run(r,changed,resume=True,accept_edits=True)
    with pytest.raises(ValueError,match='goal/removal'):run(r,tree('b'),resume=True,accept_edits=True)
    assert (tmp_path/'p/r/run_state.json').read_bytes()==before and e.calls==[('r','a')]

def test_R6_same_node_ids_separate_run_states(tmp_path):
    e,r=setup(tmp_path);run(r,tree('a'),'one');run(r,tree('a'),'two')
    run(r,tree('a','b'),'one',resume=True,accept_edits=True)
    run(r,tree('a'),'two',resume=True)
    assert e.calls==[('one','a'),('two','a'),('one','b')]
    assert set(r.store.load_run('p','two').nodes)=={'a'}


def test_explicit_independent_tasks_actually_overlap(tmp_path):
    import threading
    from cgkn.runtime import DAGRunner
    barrier=threading.Barrier(2)
    class Concurrent(Recorder):
        def execute(self,r):
            barrier.wait(timeout=3)
            return super().execute(r)
    e=Concurrent();reg=ExecutorRegistry();reg.register(e)
    runner=governed_probe_runner(reg,FileRunStore(tmp_path),max_parallel=2)
    t=CapabilityTree('parallel',tuple(probe_node(n,capability_ref='c@1',config={'executor_ref':'record@1','parallel_safe':True}) for n in ('a','b')))
    assert run(runner,t).status=='SUCCEEDED'
    assert sorted(e.calls)==[('r','a'),('r','b')]


def test_unknown_receipt_retry_is_rejected_before_graph_mutation(tmp_path):
    from cgkn.execution import ExecutionError, ExecutionErrorCode
    from cgkn.runtime import DAGRunner
    class Unknown(Recorder):
        def execute(self, request):
            return replace(super().execute(request), status=BlockStatus.FAILED,
                error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "unknown", {"outcome_unknown":True}))
    e=Unknown();reg=ExecutorRegistry();reg.register(e);r=governed_probe_runner(reg,FileRunStore(tmp_path))
    t=tree('a');run(r,t)
    before=(tmp_path/'p/r/run_state.json').read_bytes()
    with pytest.raises(ValueError,match='UNRESOLVED_OUTCOME'):
        run(r,t,resume=True,retry_node='a')
    assert e.calls==[('r','a')]
    assert (tmp_path/'p/r/run_state.json').read_bytes()==before


@pytest.mark.parametrize('operation',[None,'business-op'])
def test_unknown_operation_cannot_escape_by_adding_new_node_name(tmp_path,operation):
    from cgkn.execution import ExecutionError, ExecutionErrorCode
    from cgkn.runtime import DAGRunner
    class Unknown(Recorder):
        def execute(self, request):
            return replace(super().execute(request),status=BlockStatus.FAILED,error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'unknown',{'outcome_unknown':True}))
    e=Unknown();reg=ExecutorRegistry();reg.register(e);r=governed_probe_runner(reg,FileRunStore(tmp_path))
    first=probe_node('a',capability_ref='c@1',config={'executor_ref':'record@1',**({'operation_id':operation} if operation else {})})
    t=CapabilityTree('goal',(first,));run(r,t)
    renamed=CapabilityTree('goal',(first,replace(first,id='new-name')))
    before_tree=(tmp_path/'p/r/capability_tree.json').read_bytes()
    with pytest.raises(ValueError,match='UNRESOLVED_OPERATION'):run(r,renamed,resume=True,accept_edits=True)
    assert e.calls==[('r','a')]
    assert (tmp_path/'p/r/capability_tree.json').read_bytes()==before_tree
    independent=CapabilityTree('goal',(first,probe_node('independent',capability_ref='other@1',config={'executor_ref':'record@1'})))
    run(r,independent,resume=True,accept_edits=True)
    assert 'independent' in r.store.load_run('p','r').nodes


def governed_probe_runner(*args, **kwargs):
    return probe_runner(*args, execution_mode="GOVERNED", **kwargs)
