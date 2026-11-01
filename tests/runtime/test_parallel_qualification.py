import json,sys,time,threading,sqlite3,hashlib,subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest
from cgkn.execution import BlockExecutionResult,BlockStatus,ExecutionError,ExecutionErrorCode
from cgkn.executors import ExecutorRegistry,ExecutorDescriptor,CommandExecutor
from cgkn.orchestration.capability_tree import CapabilityNode,CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.runtime.dag_runner import GraphEditRejected
from cgkn.state import FileRunStore,EventRecord
from cgkn.state.task_feedback import digest
from cgkn.state.provenance import put_evidence
from tests.qualification_support import probe_node, probe_runner
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.execution.deliverables import FileDeliverableChecker


def tree_of(rows,ref='witness@1',shared=False):
    nodes=[]
    for n,deps in rows:
        cfg={'executor_ref':ref,'parallel_safe':True,'resources':{'shared' if shared else n:'write'}}
        if ref=='local.command@1':
            writing=n in {'A','B'}
            cfg['leaf_contract']=build_leaf_contract(goal='Persist independent artifact '+n if writing else 'Measure local dependency results '+n,
                kind='IMPLEMENTATION' if writing else 'TEST',scope=([n+'.txt'] if writing else [])+[n+'.timing.json'],
                acceptance=['local-results'],checker='local',output_identity=n,effect_domains=[n],executor=ref,
                dependencies=deps,probe_id=n,**({'expected_delta':'new artifact bytes and process timing'} if writing else
                {'subject':'input.sqlite and branch artifacts','expected_observation':'read-only DB=42 and current branch results',
                 'pass_fail_rule':'independent local object checks'}))
            nodes.append(CapabilityNode(n,capability_ref='work@1',depends_on=deps,config=cfg))
        else:nodes.append(probe_node(n,capability_ref='work@1',depends_on=deps,config=cfg))
    return CapabilityTree('parallel qualification',tuple(nodes))


class Timed:
    descriptor=ExecutorDescriptor('witness@1','deterministic',('*',))
    def __init__(self,barrier=None):self.barrier=barrier;self.times=[];self.fail=set()
    def execute(self,r):
        start=time.monotonic()
        if self.barrier and r.node_id in {'A','B'}:self.barrier.wait(4)
        time.sleep(2 if r.node_id in {'A','B'} else .03)
        end=time.monotonic();self.times.append({'node':r.node_id,'attempt':r.attempt_id,'start':start,'end':end})
        failed=r.node_id in self.fail
        return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,node_id=r.node_id,attempt_id=r.attempt_id,
            executor_ref=r.executor_ref,status=BlockStatus.FAILED if failed else BlockStatus.SUCCEEDED,
            error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,'controlled business failure') if failed else None,
            outputs={'start':start,'end':end})


def run_setup(tmp,tree,executor,**kw):
    store=FileRunStore(tmp/'state');reg=ExecutorRegistry();reg.register(executor)
    if isinstance(executor,CommandExecutor):
        def local(root,c):
            n=c['probe_id'];timing=json.loads((root/(n+'.timing.json')).read_text())
            passed=timing['end']>=timing['start']
            if n in {'A','B'}:passed=passed and (root/(n+'.txt')).read_text()==n
            else:
                with sqlite3.connect(f'file:{(root/"input.sqlite").as_posix()}?mode=ro',uri=True) as db:
                    passed=passed and db.execute('select value from source').fetchone()[0]==42
                if n=='join':passed=passed and all((root/(x+'.txt')).read_text()==x for x in ('A','B'))
            return {'passed':bool(passed),'observed':{'node':n,'timing':timing}}
        reg.register(FileDeliverableChecker(tmp,{'local-results':local}))
        return store,DAGRunner(reg,store,deliverable_checkers={'local':'deliverable.files@1'},**kw)
    return store,probe_runner(reg,store,**kw)


def test_two_node_barrier_total_wall_below_serial_executor_sum(tmp_path):
    tree=tree_of([('A',()),('B',())]);ex=Timed(threading.Barrier(2))
    store,runner=run_setup(tmp_path,tree,ex,max_parallel=2)
    start=time.monotonic();r=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree));wall=time.monotonic()-start
    assert r.status=='SUCCEEDED'
    a,b=[next(x for x in ex.times if x['node']==n) for n in ('A','B')]
    overlap=min(a['end'],b['end'])-max(a['start'],b['start'])
    assert overlap>1 and wall<(a['end']-a['start']+b['end']-b['start'])*.85
    (tmp_path/'parallel-timing.json').write_text(json.dumps({'nodes':ex.times,'overlap_ms':overlap*1000,'wall_seconds':wall}))


def test_barrier_failure_isolation_retry_and_join(tmp_path):
    tree=tree_of([('A',()),('B',()),('C',('A',)),('D',('A','B')),('E',('B',))])
    ex=Timed(threading.Barrier(2));ex.fail={'A'};store,runner=run_setup(tmp_path,tree,ex,max_parallel=3)
    start=time.monotonic();r=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree));wall=time.monotonic()-start
    assert r.failed_nodes==('A',) and set(r.blocked_nodes)=={'C','D'}
    assert store.load_result('p','r','E').status==BlockStatus.SUCCEEDED
    a,b=[next(x for x in ex.times if x['node']==n) for n in ('A','B')]
    overlap=min(a['end'],b['end'])-max(a['start'],b['start'])
    assert overlap>1
    (tmp_path/'parallel-timing.json').write_text(json.dumps({'nodes':ex.times,'overlap_ms':overlap*1000,'wall_seconds':wall}))
    ex.barrier=None;ex.fail.clear()
    recovered=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),retry_node='A')
    assert recovered.status=='SUCCEEDED' and set(recovered.actual_executions)=={'A','C','D'}
    assert sum(x['node']=='B' for x in ex.times)==1 and sum(x['node']=='E' for x in ex.times)==1


LOCAL=r'''
import pathlib,sys,time,json,sqlite3
n=sys.argv[1];start=time.monotonic();root=pathlib.Path('.')
if n in ('A','B'):
 (root/(n+'.txt')).write_text(n)
elif n=='C':
 db=sqlite3.connect('file:input.sqlite?mode=ro',uri=True)
 assert db.execute('select value from source').fetchone()[0]==42;db.close()
else:
 assert (root/'A.txt').read_text()=='A' and (root/'B.txt').read_text()=='B'
 for key in ('A','B','C'):assert (root/(key+'.timing.json')).exists()
time.sleep(2 if n!='join' else 0)
(root/(n+'.timing.json')).write_text(json.dumps(dict(start=start,end=time.monotonic())))
print(n)
'''


@pytest.mark.parametrize('conflict',[False,True])
def test_real_local_process_file_sqlite_and_conflict(tmp_path,conflict):
    db=sqlite3.connect(tmp_path/'input.sqlite');db.execute('create table source(value integer)');db.execute('insert into source values(42)');db.commit();db.close()
    tree=tree_of([('A',()),('B',()),('C',()),('join',('A','B','C'))],ref='local.command@1',shared=conflict)
    tree=CapabilityTree(tree.goal,tuple(replace(n,config={**n.config,'command':[sys.executable,'-c',LOCAL,n.id]}) for n in tree.nodes))
    store,runner=run_setup(tmp_path,tree,CommandExecutor(tmp_path),max_parallel=3)
    assert runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree)).status=='SUCCEEDED'
    times={n:json.loads((tmp_path/(n+'.timing.json')).read_text()) for n in ('A','B','C','join')}
    overlap=min(times['A']['end'],times['B']['end'])-max(times['A']['start'],times['B']['start'])
    assert overlap<=0 if conflict else overlap>1
    assert times['join']['start']>=max(times[n]['end'] for n in ('A','B','C'))
    before={p.name:p.read_bytes() for p in tmp_path.glob('*.txt')}
    assert not runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True).actual_executions
    assert before=={p.name:p.read_bytes() for p in tmp_path.glob('*.txt')}
    (tmp_path/'local-timing.json').write_text(json.dumps({'nodes':times,'overlap_ms':max(0,overlap)*1000,'conflict':conflict}))


def test_resource_capacity_and_event_appends(tmp_path):
    tree=tree_of([('A',()),('B',())]);tree=CapabilityTree(tree.goal,tuple(replace(n,config={**n.config,'capacity_claims':{'provider:P':1}}) for n in tree.nodes))
    ex=Timed();store,runner=run_setup(tmp_path,tree,ex,max_parallel=3,resource_limits={'provider:P':1})
    assert runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree)).status=='SUCCEEDED'
    assert ex.times[1]['start']>=ex.times[0]['end']
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i:store.append_event(EventRecord('event-'+str(i),'p','r','CONCURRENT',data={'i':i})),range(80)))
    assert {e.data['i'] for e in store.load_events('p','r') if e.event_type=='CONCURRENT'}==set(range(80))


def test_unknown_effect_checked_before_reconciliation_not_replayed(tmp_path):
    tree=tree_of([('A',())]);ex=Timed();store,runner=run_setup(tmp_path,tree,ex,max_parallel=2,reconciliation_executors=('verify.effect@1',))
    c=build_leaf_contract(goal='Inspect reconciled durable effect',kind='INSPECTION',scope=['effect.txt'],
        acceptance=['committed'],checker='effect',output_identity='effect',effect_domains=['effect'],executor='witness@1',
        subject='effect.txt',expected_observation='committed bytes',pass_fail_rule='independent disk read')
    tree=CapabilityTree(tree.goal,(replace(tree.nodes[0],config={**tree.nodes[0].config,'leaf_contract':c}),))
    runner.registry.register(FileDeliverableChecker(tmp_path,{'committed':lambda root,c:
        {'passed':(root/'effect.txt').read_text()=='committed','observed':{'bytes':(root/'effect.txt').read_text()}}}))
    runner.deliverable_checkers['effect']='deliverable.files@1'
    state=runner._new_state('p','r',compile_tree(tree));state.nodes['A'].status='RUNNING';store.save_run(state)
    # Simulated controller interruption after a real local effect, before receipt.
    subprocess.run([sys.executable,'-c',"from pathlib import Path;Path('effect.txt').write_text('committed')"],cwd=tmp_path,check=True)
    assert runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True).blocked_nodes==('A',)
    old=store.load_result('p','r','A');assert old.error.details['outcome_unknown']
    with pytest.raises(GraphEditRejected,match='UNRESOLVED'):runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),retry_node='A')
    read=subprocess.run([sys.executable,'-c',"from pathlib import Path;assert Path('effect.txt').read_text()=='committed';print('committed')"],cwd=tmp_path,capture_output=True,check=True)
    ref=put_evidence(store,'p','r',{'kind':'EffectObservation','stdout':read.stdout.decode(),'returncode':read.returncode,'effect_sha256':hashlib.sha256((tmp_path/'effect.txt').read_bytes()).hexdigest()})
    checker=BlockExecutionResult(project_id='p',run_id='r',node_id='verify',attempt_id='attempt-0001',executor_ref='verify.effect@1',status=BlockStatus.SUCCEEDED,
        outputs={'effect_reconciliation':{'source_receipt_hash':digest(old.as_dict()),'disposition':'COMPLETED','evidence_refs':[ref],'recovered_outputs':{'effect':'committed'}}})
    store.save_result(checker);runner.reconcile_effects('p','r','A',checker)
    assert runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True).status=='SUCCEEDED'
    assert not ex.times and json.loads((store.run_dir('p','r')/'attempts/A/attempt-0001.json').read_text())==old.as_dict()


def test_evaluation_overlaps_unrelated_business_and_route_waits(tmp_path):
    from cgkn.executors.task_evaluation import TaskEvaluationExecutor
    from cgkn.providers import ModelRoleConfig
    from tests.agent.test_capability_routing_qualification import Evaluator
    store=FileRunStore(tmp_path/'state');started=threading.Event();routed=threading.Event();times={}
    class Work:
        descriptor=ExecutorDescriptor('work@1','deterministic',('*',))
        def execute(self,r):
            times[r.node_id+'_start']=time.monotonic()
            if r.node_id=='B':started.set();assert routed.wait(10)
            if r.node_id=='route':
                assert list((store.run_dir('p','r')/'evaluations').glob('*/*.json'));routed.set()
            times[r.node_id+'_end']=time.monotonic()
            return BlockExecutionResult(project_id='p',run_id='r',node_id=r.node_id,attempt_id=r.attempt_id,executor_ref=r.executor_ref,status=BlockStatus.SUCCEEDED,outputs={'node':r.node_id})
    class Client(Evaluator):
        def complete(self,**kw):
            assert started.wait(5);times['evaluation_start']=time.monotonic();out=super().complete(**kw);times['evaluation_end']=time.monotonic();return out
    reg=ExecutorRegistry();reg.register(Work());reg.register(TaskEvaluationExecutor(store,Client(),ModelRoleConfig('worker','fake')))
    tree=tree_of([('A',()),('B',()),('evaluate',('A',)),('route',('evaluate',))],ref='work@1')
    tree=CapabilityTree(tree.goal,tuple(probe_node(n.id,capability_ref='task.evaluate@1',depends_on=n.depends_on,config={**n.config,'executor_ref':'task.evaluate@1','meta_operation':True,'inputs':{'feedback_identity':digest(['p','r','A','attempt-0001']),'evaluation_contract':'2'}}) if n.id=='evaluate' else n for n in tree.nodes))
    assert probe_runner(reg,store,max_parallel=3).run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree)).status=='SUCCEEDED'
    assert times['B_start']<=times['evaluation_start']<=times['evaluation_end']<=times['B_end']
    assert times['route_start']>=times['evaluation_end']
    (tmp_path/'evaluation-overlap.json').write_text(json.dumps(times))


def test_real_controller_process_loss_preserves_completed_sibling(tmp_path):
    code=r'''
import os,sys,time,pathlib
from cgkn.execution import BlockExecutionResult,BlockStatus
from cgkn.executors import ExecutorRegistry,ExecutorDescriptor
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.orchestration.execution_dag import compile_tree
from tests.runtime.test_parallel_qualification import tree_of
from tests.qualification_support import probe_runner
root=pathlib.Path(sys.argv[1]);store=FileRunStore(root/'state')
class Child:
 descriptor=ExecutorDescriptor('witness@1','deterministic',('*',))
 def execute(self,r):
  if r.node_id=='A':
   end=time.monotonic()+10
   while store.load_run('p','r').nodes['B'].status!='SUCCEEDED':
    if time.monotonic()>end:raise RuntimeError('B not committed')
    time.sleep(.01)
   (root/'A-effect').write_text('committed before crash');os._exit(73)
  (root/'B-effect').write_text('completed')
  return BlockExecutionResult(project_id='p',run_id='r',node_id=r.node_id,attempt_id=r.attempt_id,executor_ref=r.executor_ref,status=BlockStatus.SUCCEEDED,outputs={'node':r.node_id})
reg=ExecutorRegistry();reg.register(Child());tree=tree_of([('A',()),('B',())])
probe_runner(reg,store,max_parallel=2).run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
'''
    proc=subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,timeout=20)
    assert proc.returncode==73,proc.stderr.decode()
    tree=tree_of([('A',()),('B',())]);ex=Timed();store,runner=run_setup(tmp_path,tree,ex,max_parallel=2)
    result=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
    assert result.reused_nodes==('B',) and result.blocked_nodes==('A',) and not ex.times
    with pytest.raises(GraphEditRejected):runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),retry_node='A')
