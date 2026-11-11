"""Distribution controls for the real compile -> runner -> checker -> feedback path."""
import json
import threading
import time
from dataclasses import replace
import pytest
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.orchestration.leaf_contract import LeafContractError
from cgkn.executors import ExecutorRegistry
from cgkn.executors.llm import LLMExecutor
from cgkn.providers import ProviderCompletion, ModelRoleConfig
from cgkn.execution.deliverables import FileDeliverableChecker, parent_projection
from cgkn.runtime import DAGRunner
from cgkn.runtime.dag_runner import GraphEditRejected
from cgkn.state import FileRunStore
from cgkn.state.task_feedback import TaskFeedback
from tests.governed_measurement_support import admit_fixture_tree
from cgkn.runtime.node_authority import ExecutionAuthority


def node(name='n',files=('f.py',),kind='IMPLEMENTATION',deps=(),**changes):
    contract=dict(schema_version='1.0',leaf_goal='bounded function',task_kind=kind,
        target_scope=list(files),acceptance=['works'],checker_ref='check',output_identity=name,
        effect_domains=['filesystem','external_network'],executor_ref='llm.cheap@1',dependencies=list(deps),expected_delta='new function')
    if kind in {'RESEARCH','READ_ONLY_ANALYSIS'}:contract.update(source_refs=['public:source'],completion_criterion='evidence recorded')
    if kind in {'TEST','INSPECTION'}:contract.update(subject='f.py',expected_observation='works',pass_fail_rule='independent predicate')
    contract.update(changes)
    return CapabilityNode(name,capability_ref='code@1',depends_on=deps,
        config={'executor_ref':'llm.cheap@1','leaf_contract':contract,'parallel_safe':True})


class Client:
    def __init__(self,actions,barrier=None):self.actions=actions;self.calls=[];self.barrier=barrier;self.times=[]
    def complete(self,**kw):
        p=json.loads(kw['user']);n=p['node_id'];start=time.monotonic();self.calls.append(n)
        if self.barrier and n in {'a','b'}:self.barrier.wait(3);time.sleep(.3)
        actions=self.actions[n] if isinstance(self.actions,dict) else self.actions
        if p.get('observations') and actions and all(a['action'] in {'read_file','list_files'} for a in actions):
            actions=[]  # Fixture acknowledges the read observation and finishes.
        value=dict(schema_version='1.0',node_id=n,summary='candidate',actions=actions,
            expected_outputs=['function'],confidence=.8,needs_escalation=False,escalation_reason='')
        self.times.append((n,start,time.monotonic()))
        return ProviderCompletion(json.dumps(value),'fake-model',usage={'input_tokens':1,'output_tokens':1})


def write(name='f.py',content='def f(x): return x + 1\n'):
    return {'action':'write_file','path':name,'content':content}


def works(root,c):
    results={}
    for name in c['target_scope']:
        try:
            ns={};exec((root/name).read_text(),ns);results[name]=ns['f'](3)==4 and ns['f'](-1)==0
        except Exception:results[name]=False
    return {'passed':all(results.values()),'observed':results,'artifact_verdicts':results}


def setup(tmp,client,check=works):
    root=tmp/'project';root.mkdir();store=FileRunStore(tmp/'state');reg=ExecutorRegistry()
    reg.register(LLMExecutor(root,client,ModelRoleConfig('worker','fake')))
    reg.register(FileDeliverableChecker(root,{'works':check}))
    runner=DAGRunner(reg,store,max_parallel=3,deliverable_checkers={'check':'deliverable.files@1'})
    return root,store,runner


def run(runner,nodes,**kw):
    tree=CapabilityTree('goal',tuple(nodes))
    if not ExecutionAuthority(runner.store,'p','r').committed_tree():
        tree=admit_fixture_tree(runner.store,tree)
    elif kw.get('retry_node'):
        tree=admit_fixture_tree(runner.store,tree,operations=({'operation':'retry_node','node_id':kw['retry_node']},))
    return runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),**kw)


@pytest.mark.parametrize('change,verdict',[
    ({'acceptance':[]},'INVALID_CONTRACT'),({'target_scope':['**']},'INVALID_CONTRACT'),
    ({'expected_delta':''},'INVALID_CONTRACT'),({'effect_domains':['db','api','gui']},'NEEDS_DECOMPOSITION'),
    ({'target_scope':[str(i) for i in range(9)]},'NEEDS_DECOMPOSITION'),
    ({'dependencies':['unknown']},'INVALID_CONTRACT')])
def test_invalid_leaf_cannot_compile(change,verdict):
    with pytest.raises(LeafContractError,match=verdict):compile_tree(CapabilityTree('goal',(node(**change),)))


def test_composite_rejected_and_split_children_compile():
    parent=node('parent');child=replace(node('child'),parent_id='parent')
    with pytest.raises(LeafContractError,match='NEEDS_DECOMPOSITION'):compile_tree(CapabilityTree('g',(parent,child)))
    parent=CapabilityNode('parent')
    assert len(compile_tree(CapabilityTree('g',(parent,child))).nodes)==1


def test_pure_function_checked_and_version_reuse_guard(tmp_path):
    root,store,runner=setup(tmp_path,Client([write()]))
    assert run(runner,[node()]).status=='SUCCEEDED'
    receipt=store.load_result('p','r','n');assert receipt.metadata['execution_status']=='EXECUTION_SUCCESS'
    assert receipt.metadata['deliverable_verdict']=='VERIFIED'
    (root/'f.py').write_text('changed')
    with pytest.raises(GraphEditRejected,match='OBJECT_VERSION_MISMATCH'):run(runner,[node()],resume=True)


@pytest.mark.boundary
@pytest.mark.happy_path
def test_partial_two_files_retained_and_continued_without_rewrite(tmp_path):
    client=Client([write('a.py')]);root,store,runner=setup(tmp_path,client)
    n=node(files=('a.py','b.py'))
    assert run(runner,[n]).status=='FAILED'
    assert not (root/'a.py').exists()
    receipt=store.load_result('p','r','n');proof=receipt.as_dict()['metadata']['deliverable_check']
    assert set(proof['verified_artifacts'])=={'a.py'}
    client.actions=[write('b.py')]
    assert run(runner,[n],retry_node='n').status=='SUCCEEDED'
    assert (root/'a.py').exists() and (root/'b.py').exists()


@pytest.mark.boundary
@pytest.mark.negative
def test_no_delta_is_failed_deliverable_and_next_decision_feedback(tmp_path):
    root,store,runner=setup(tmp_path,Client([]));(root/'f.py').write_text('def f(x): return x + 1\n')
    assert run(runner,[node()]).status=='FAILED'
    r=store.load_result('p','r','n')
    assert r.metadata['execution_status']=='EXECUTION_SUCCESS'
    assert r.error.message=='EXECUTION_SUCCEEDED_DELIVERABLE_FAILED'
    assert run(runner,[node()],retry_node='n').status=='FAILED'
    feedback=TaskFeedback(store,'p','r').context()
    assert feedback['items'][0]['implementation_progress']['verdict']=='NO_IMPLEMENTATION_PROGRESS'
    assert feedback['progress_signals'][0]['signal']=='REPEATED_NO_PROGRESS_STRATEGY'


def test_readonly_evidence_not_false_no_progress(tmp_path):
    root,store,runner=setup(tmp_path,Client([{'action':'read_file','path':'f.py'}]));(root/'f.py').write_text('def f(x): return x + 1\n')
    assert run(runner,[node(kind='RESEARCH')]).status=='SUCCEEDED'
    assert store.load_result('p','r','n').metadata['implementation_progress']['verdict']=='NOT_APPLICABLE'


def test_parallel_join_failure_isolation_targeted_repair(tmp_path):
    client=Client({'a':[write('a.py','bad')],'b':[write('b.py')],'join':[write('join.py')]},threading.Barrier(2))
    root,store,runner=setup(tmp_path,client)
    nodes=[node('a',('a.py',)),node('b',('b.py',)),node('join',('join.py',),deps=('a','b'))]
    result=run(runner,nodes);assert result.failed_nodes==('a',) and result.blocked_nodes==('join',)
    a,b=sorted(client.times);overlap=min(a[2],b[2])-max(a[1],b[1]);assert overlap>.25
    client.barrier=None;client.actions['a']=[write('a.py')]
    assert run(runner,nodes,retry_node='a').status=='SUCCEEDED'
    assert client.calls.count('b')==1
    (tmp_path/'overlap.json').write_text(json.dumps({'intervals':client.times,'overlap_ms':overlap*1000}))


def test_three_independent_branches_join_current_versions_and_no_sibling_replay(tmp_path):
    barrier=threading.Barrier(3)
    intervals=[]
    class Three(Client):
        synchronize=True
        def complete(self,**kw):
            n=json.loads(kw['user'])['node_id'];start=time.monotonic()
            if self.synchronize and n in {'a','b','c'}:
                barrier.wait(4);time.sleep(.4)
            value=super().complete(**kw);intervals.append({'node':n,'start':start,'end':time.monotonic()})
            return value
    client=Three({n:[write(n+'.py','bad' if n=='a' else 'def f(x): return x + 1\n')] for n in ('a','b','c','join')})
    _,store,runner=setup(tmp_path,client)
    nodes=[node(n,(n+'.py',)) for n in ('a','b','c')]+[node('join',('join.py',),deps=('a','b','c'))]
    first=run(runner,nodes)
    assert first.failed_nodes==('a',) and first.blocked_nodes==('join',)
    overlap=min(x['end'] for x in intervals)-max(x['start'] for x in intervals)
    assert overlap>.35
    client.synchronize=False;client.actions['a']=[write('a.py')]
    repaired=run(runner,nodes,retry_node='a')
    assert repaired.status=='SUCCEEDED' and set(repaired.actual_executions)=={'a','join'}
    assert client.calls.count('b')==client.calls.count('c')==1
    assert store.load_result('p','r','join').metadata['deliverable_verdict']=='VERIFIED'
    (tmp_path/'three-branch-overlap.json').write_text(json.dumps({'intervals':intervals,'overlap_ms':overlap*1000,'sibling_reruns':0}))


def test_parent_requires_children_and_own_acceptance(tmp_path):
    _,store,runner=setup(tmp_path,Client([write()]))
    n=replace(node(),parent_id='parent');tree=CapabilityTree('goal',(CapabilityNode('parent'),n))
    assert run(runner,tree.nodes).status=='SUCCEEDED'
    receipts={'n':store.load_result('p','r','n')}
    assert parent_projection(tree,receipts,{})['parent']['verdict']=='BLOCKED'
    assert parent_projection(tree,{}, {'parent':'VERIFIED'})['parent']['verdict']=='BLOCKED'
    assert parent_projection(tree,receipts,{'parent':'VERIFIED'})['parent']['verdict']=='VERIFIED'


def test_out_of_scope_write_is_rejected_before_any_write(tmp_path):
    root,store,runner=setup(tmp_path,Client([write(),write('other.py')]))
    assert run(runner,[node()]).status=='FAILED'
    assert not (root/'f.py').exists() and not (root/'other.py').exists()


def test_old_graph_load_is_readonly_not_requalified():
    tree=CapabilityTree('g',(CapabilityNode('old',capability_ref='code@1',config={'executor_ref':'llm.cheap@1'}),))
    loaded=CapabilityTree.from_dict(tree.as_dict())
    assert compile_tree(loaded,historical_read_only=True).nodes
    with pytest.raises(LeafContractError):compile_tree(loaded)


def test_contract_executor_projects_legacy_alias_without_changing_identity():
    original=node();c=dict(original.config);c.pop('executor_ref')
    normalized=replace(original,config=c)
    assert normalized.config['executor_ref']=='llm.cheap@1'
    compile_tree(CapabilityTree('g',(normalized,)))
    with pytest.raises(LeafContractError,match='identity mismatch'):
        compile_tree(CapabilityTree('g',(replace(normalized,config={**c,'executor_ref':'other@1'}),)))


def test_worker_receives_current_contract_goal_not_stale_legacy_alias(tmp_path):
    client=Client([write()]);seen=[];complete=client.complete
    def observe(**kw):seen.append(json.loads(kw['user'])['goal']);return complete(**kw)
    client.complete=observe
    _,store,runner=setup(tmp_path,client);n=node(leaf_goal='current repair decision')
    n=replace(n,config={**dict(n.config),'goal':'stale read-only instruction'})
    assert run(runner,[n]).status=='SUCCEEDED'
    assert seen==['current repair decision']
    assert TaskFeedback(store,'p','r').context()['items'][0]['goal']=='current repair decision'


def test_check_task_requires_observable_subject_and_rule(tmp_path):
    root,store,runner=setup(tmp_path,Client([]));(root/'f.py').write_text('def f(x): return x + 1\n')
    assert run(runner,[node(kind='TEST')]).status=='SUCCEEDED'
    with pytest.raises(LeafContractError):compile_tree(CapabilityTree('g',(node(kind='TEST',subject=''),)))


def test_output_limit_preserves_partial_text_and_unknown_without_replay():
    from cgkn.providers.streaming_sse import SSEEvent,collect_chat_completions,StreamError
    # Events from a real-shaped SSE decoder, including its explicit done fence.
    from cgkn.providers.streaming_sse import sse_events,StreamLimits
    raw='data: '+json.dumps({'model':'m','choices':[{'index':0,'delta':{'content':'partial'},'finish_reason':'length'}]})+'\n\ndata: [DONE]\n\n'
    with pytest.raises(StreamError) as error:collect_chat_completions(sse_events(raw.encode().splitlines(keepends=True),limits=StreamLimits()))
    assert error.value.finish_reason=='OUTPUT_TOKEN_LIMIT'
    assert error.value.response['partial_text']=='partial' and error.value.outcome_unknown


def test_checker_failure_preserves_worker_usage_and_classifies_harness(tmp_path):
    def broken(*args): raise RuntimeError('controlled checker failure')
    root,store,runner=setup(tmp_path,Client([write()]),broken)
    assert run(runner,[node()]).status=='FAILED'
    r=store.load_result('p','r','n')
    assert r.error.details['failure_domain']=='HARNESS' and r.usage['input_tokens']==1
    assert not (root/'f.py').exists()


def test_unregistered_checker_rejected_before_worker(tmp_path):
    client=Client([write()]);_,_,runner=setup(tmp_path,client)
    with pytest.raises(GraphEditRejected):run(runner,[node(checker_ref='self-attest')])
    assert client.calls==[]


def test_legacy_ledger_scope_cannot_promote_unrelated_route(tmp_path):
    from cgkn.state.capability_ledger import CapabilityLedger
    from cgkn.state.task_feedback import digest
    from dataclasses import asdict
    ledger=CapabilityLedger(FileRunStore(tmp_path/'state'),'p')
    cfg=ModelRoleConfig('worker','qwen',model_id='model')
    ledger.view=lambda:{'snapshot_hash':'snapshot','records':[dict(task_class='fullstack',provider_id='qwen',actual_model='model',
        config_hash=digest(asdict(cfg)),routing_support=10,contradictions=[],accepted=10,qualified_attempts=10,
        operation='registry',capability_scope={'artifact_domain':'registry','environment':'python','tool_identity':'files'},
        last_updated='2026-10-30T00:00:00+00:00',evidence_refs=['raw'])]}
    r=ledger.route('fullstack',{'prior':cfg,'chosen':cfg},'chosen',operation='fullstack',
        capability_scope={'artifact_domain':'web','environment':'browser','tool_identity':'files'})
    assert r['selected_config']=='chosen' and r['scope_match']=='INSUFFICIENT_EVIDENCE'


def test_real_sqlite_process_acceptance_positive_negative(tmp_path):
    import subprocess,sys
    def check(root,c):
        code="import sqlite3,tempfile; from adapter import store; p=tempfile.mktemp(); store(p,'v'); c=sqlite3.connect(p); assert c.execute('select value from items').fetchall()==[('v',)]; print('sqlite round trip verified')"
        r=subprocess.run([sys.executable,'-c',code],cwd=root,capture_output=True,text=True,timeout=10)
        return {'passed':r.returncode==0 and 'sqlite round trip verified' in r.stdout,
                'observed':{'stdout':r.stdout,'stderr':r.stderr,'returncode':r.returncode}}
    client=Client([write('adapter.py','def store(p,v): pass\n')]);root,store,runner=setup(tmp_path,client,check)
    n=node(files=('adapter.py',))
    assert run(runner,[n]).status=='FAILED'
    client.actions=[write('adapter.py',"import sqlite3\ndef store(p,v):\n c=sqlite3.connect(p); c.execute('create table items(value text)'); c.execute('insert into items values(?)',(v,)); c.commit(); c.close()\n")]
    assert run(runner,[n],retry_node='n').status=='SUCCEEDED'


def test_progress_is_received_by_next_canonical_planner_decision(tmp_path):
    from cgkn.agent.composer import AgentComposer
    from cgkn.agent.project_loop import AgentProjectLoop
    from cgkn.agent.project_agent import AdmissionPolicy
    from veriarbor.capability import CapabilityContract
    from dataclasses import asdict
    n=node();contexts=[]
    class Planner:
        def complete(self,**kw):
            context=json.loads(kw['user']);contexts.append(context)
            first=len(contexts)==1
            edits=[dict(edit_id='add',operation='add_node',node_id='n',payload={k:v for k,v in CapabilityTree('g',(n,)).as_dict()['nodes'][0].items() if k!='id'},provenance={'actor':'fixture'})] if first else []
            value=dict(schema_version='1.0',decision_id=str(len(contexts)),summary='fixture',reason='public facts',edits=edits,request_run=first,finish=False,needs_escalation=not first,escalation_reason='' if first else 'change strategy')
            value['decision_audit']={'alternatives_considered':['inspect current candidate','change strategy'],
                'expected_outcome':'Independent checker reports no implementation progress',
                'capability_claim':{'target_capability_id':'code@1','strategy_capabilities':['code@1'],
                'exploration_reason':'Measure no-progress feedback','exploration_budget':1,'exploration_measure':'Independent file predicate'}}
            return ProviderCompletion(json.dumps(value),'fake-planner')
    root,store,runner=setup(tmp_path,Client([]))
    policy=AdmissionPolicy(project_id='p',capability_contracts={'code@1':asdict(CapabilityContract('code@1','bounded function',critical=False,
        positive_controls=('independent file predicate',)))},allow_remote_effects=True,execution_budget={'calls':4})
    loop=AgentProjectLoop(AgentComposer(Planner(),ModelRoleConfig('agent','fake')),runner,store,known_capabilities={'code@1'},worker_model='fake',max_decisions=2,admission_policy=policy)
    loop.run(project_id='p',run_id='r',goal='g')
    assert len(contexts)==2
    assert contexts[1]['task_feedback']['items'][0]['implementation_progress']['verdict']=='NO_IMPLEMENTATION_PROGRESS'


def test_partial_output_limit_retains_verified_artifact_and_blocks_blind_retry(tmp_path):
    from cgkn.providers.streaming_sse import StreamError
    client=Client([write('a.py')]);_,store,runner=setup(tmp_path,client);n=node(files=('a.py','b.py'))
    run(runner,[n])
    def interrupted(**kw):raise StreamError('stream_output_token_limit',response={'partial_text':'incomplete b.py'})
    client.complete=interrupted
    run(runner,[n],retry_node='n')
    r=store.load_result('p','r','n')
    assert r.status.value=='BLOCKED'
    assert r.metadata['finish_reason']=='OUTPUT_TOKEN_LIMIT'
    assert 'a.py' in r.metadata['deliverable_check']['verified_artifacts']
    with pytest.raises(GraphEditRejected,match='UNRESOLVED_OUTCOME'):run(runner,[n],retry_node='n')
