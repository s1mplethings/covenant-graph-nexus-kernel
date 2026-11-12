from dataclasses import replace
import pytest
from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.executors import ExecutorRegistry, ExecutorDescriptor
from cgkn.execution.deliverables import SubjectDeliverableChecker
from cgkn.orchestration import CapabilityTree, compile_tree
from cgkn.runtime import DAGRunner
from cgkn.runtime.dag_runner import GraphEditRejected
from cgkn.state import FileRunStore
from tests.qualification_support import probe_node, check_probe

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def fixture(tmp_path, dependent=False, unrelated=False):
    calls=[];version={'v':'first'}
    class Probe:
        descriptor=ExecutorDescriptor('probe@1','deterministic',('probe@1',),())
        def execute(self,r):
            calls.append(r.node_id)
            return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,node_id=r.node_id,attempt_id=r.attempt_id,executor_ref=r.executor_ref,status=BlockStatus.SUCCEEDED,outputs={'node':r.node_id,'version':version['v']})
    reg=ExecutorRegistry();reg.register(Probe())
    reg.register(SubjectDeliverableChecker(lambda c:{s:version['v'] for s in c['target_scope']},{'probe_observation':check_probe}))
    store=FileRunStore(tmp_path/'state');runner=DAGRunner(reg,store,deliverable_checkers={'fixture.probe':'deliverable.subjects@1'})
    nodes=[]
    for name in ['a','b']+(['child'] if dependent else []):
        n=probe_node(name,capability_ref='probe@1',depends_on=('b',) if name=='child' else (),config={'executor_ref':'probe@1'})
        c=dict(n.config['leaf_contract']);c.update(target_scope=['different' if unrelated and name=='b' else 'shared'],subject='shared')
        nodes.append(replace(n,config={**n.config,'leaf_contract':c}))
    tree=CapabilityTree('same subject measurements',tuple(nodes));dag=compile_tree(tree)
    def run(**kw):return runner.run(project_id='p',run_id='r',tree=tree,dag=dag,**kw)
    assert run().status=='SUCCEEDED';version['v']='second'
    return calls,store,run

def test_explicit_retry_blocks_stale_peer_without_replay_and_retains_receipt(tmp_path):
    calls,store,run=fixture(tmp_path);folder=store.run_dir('p','r');before=(folder/'node_results/b.json').read_bytes()
    with pytest.raises(GraphEditRejected,match='OBJECT_VERSION_MISMATCH'):run(resume=True)
    result=run(resume=True,retry_node='a')
    assert result.actual_executions==('a',) and 'b' not in result.reused_nodes
    assert calls==['a','b','a']
    assert store.load_run('p','r').nodes['b'].status=='BLOCKED'
    assert (folder/'node_results/b.json').read_bytes()==before
    assert store.load_result('p','r','a').outputs['version']=='second'
    result=run(resume=True,retry_node='b')
    assert result.status=='SUCCEEDED' and result.actual_executions==('b',)
    assert calls==['a','b','a','b']
    assert len([e for e in store.load_events('p','r') if e.event_type=='STALE_MEASUREMENT_INVALIDATED'])==1

@pytest.mark.parametrize('option',['dependent','unrelated'])
def test_unrelated_or_nonleaf_stale_peer_remains_fail_closed(tmp_path,option):
    calls,store,run=fixture(tmp_path,**{option:True});before=store.load_run('p','r').as_dict()
    with pytest.raises(GraphEditRejected,match='OBJECT_VERSION_MISMATCH'):run(resume=True,retry_node='a')
    assert store.load_run('p','r').as_dict()==before
    assert calls==(['a','b','child'] if option=='dependent' else ['a','b'])

def test_unknown_requested_measurement_never_replayed(tmp_path):
    calls,store,run=fixture(tmp_path)
    r=store.load_result('p','r','a');store.save_result(replace(r,attempt_id="attempt-0002",status=BlockStatus.FAILED,error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'unknown',details={'outcome_unknown':True})))
    with pytest.raises(GraphEditRejected,match='UNRESOLVED_OUTCOME'):run(resume=True,retry_node='a')
    assert calls==['a','b']
