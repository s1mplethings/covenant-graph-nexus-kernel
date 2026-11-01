import json
import random
import pytest
from cgkn.protocol.admission import InvalidDecisionTracker, invalid_decision_fingerprint
from cgkn.protocol.compiler import TableSnapshot, compile_planner, compile_worker
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.exchange import exchange, SchemaRepairFailed
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.providers import ModelRoleConfig, ProviderCompletion

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def snapshot():
    return TableSnapshot({'nodes':[{'node_id':'n'}],
        'scopes':[{'path':'a.py','allowed_capabilities':['code']},{'path':'project','allowed_capabilities':['accept']}],
        'capabilities':[{'capability_ref':ref,'task_kinds':kinds,'executor_ref':'executor','checker_ref':'checker',
            'acceptance_refs':['public'],'effect_domains':['local']} for ref,kinds in [('code',[2,3]),('accept',[4,5])]]})

def packet():return {'action':1,'task_kind':4,'target':0,'scope':[1],'deps':[],
    'goal':'Run independent acceptance','expected':['Current candidate checked'],'accept':['All public requirements pass']}

def compile(p,s=None):
    s=s or snapshot()
    return compile_planner(p,s,bound_hash=s.hash,tree=CapabilityTree('goal',()),context_identity='one')

def test_scope_rejection_exact_and_never_auto_drops_scope():
    p={**packet(),'scope':[0,1]};before=json.dumps(p)
    with pytest.raises(ContractError) as e:compile(p)
    d=e.value.as_dict()
    assert d['fields']==['scope'] and d['allowed_scope_ids']==[1] and d['invalid_scope_ids']==[0]
    assert d['current_value']==[0,1] and d['repair_class']=='R5'
    assert json.dumps(p)==before

@pytest.mark.parametrize('seed',range(200))
def test_deterministic_pair_property(seed):
    rng=random.Random(seed);d=snapshot().document
    for row in d['scopes']:
        row['allowed_capabilities']=[c['capability_ref'] for c in d['capabilities'] if rng.choice([True,False])]
    s=TableSnapshot(d);cap=rng.randrange(2);scope=rng.sample([0,1],rng.randint(1,2))
    p={**packet(),'task_kind':d['capabilities'][cap]['task_kinds'][0],'scope':scope,'capability':cap}
    graph={r['capability_id']:r['allowed_scope_ids'] for r in s.public_document['compatibility']}
    valid=all(x in graph[cap] for x in scope)
    if valid:assert compile(p,s)['admission_status']=='ADMISSIBLE'
    else:
        with pytest.raises(ContractError) as e:compile(p,s)
        assert e.value.code=='SCOPE_CAPABILITY_DENIED'
        assert e.value.as_dict()['allowed_values']==graph[cap]

def test_inference_uses_scope_as_well_as_kind():
    d=snapshot().document;d['capabilities'][0]['task_kinds']=[4]
    s=TableSnapshot(d)
    assert compile(packet(),s)['edits'][0].payload['capability_ref']=='accept'
    d['scopes'][1]['allowed_capabilities']=['code','accept'];s=TableSnapshot(d)
    with pytest.raises(ContractError,match='CAPABILITY_SELECTION_REQUIRED'):compile(packet(),s)

@pytest.mark.parametrize('field,value',[('capability_ref',1),('capability_ref','accept'),('executor_ref','executor'),('checker_ref','checker'),('schema_version','1.0')])
def test_proven_binding_strip(field,value):
    result=compile({**packet(),field:value});ordinary=compile(packet())
    assert result['edits']==ordinary['edits']
    assert result['mechanical_receipts'][0]['semantics_changed'] is False

@pytest.mark.parametrize('field,value',[('capability_ref','code'),('executor_ref','publish'),('checker_ref','fake'),('provenance',{'verified':True}),('unknown',0)])
def test_no_unsafe_strip(field,value):
    with pytest.raises(ContractError) as e:compile({**packet(),field:value})
    assert e.value.as_dict()['safe_strip_allowed'] is False

def test_repeated_fingerprint_and_changed_scope():
    tracker=InvalidDecisionTracker();p={**packet(),'scope':[0,1]}
    for count in range(1,4):
        with pytest.raises(ContractError) as exc:compile(p)
        e=exc.value;assert tracker.observe(p,e)==count
        assert e.as_dict()['correction_path_terminated']==(count==3)
    assert invalid_decision_fingerprint(p,e)!=invalid_decision_fingerprint({**p,'scope':[0]},e)

class Client:
    def __init__(self,packets):self.packets=iter(packets);self.calls=[]
    def complete(self,**kwargs):
        self.calls.append(kwargs)
        return ProviderCompletion(json.dumps(next(self.packets)),'fake','req'+str(len(self.calls)),{'input_tokens':3,'output_tokens':5})

def invoke(packets):
    client=Client(packets);s=snapshot();events=[]
    result=exchange(client,ModelRoleConfig('agent','fixture'),system='bounded',context={},snapshot=s,semantic_attempt_id='one',
        compiler=lambda p,h:compile(p,s),normalization={},trace=events.append)
    return result,client,events

def test_admission_correction_separate_budget():
    result,client,events=invoke([{**packet(),'scope':[0,1]},packet()])
    stats=result[2]
    assert stats['semantic_decision_attempts']==1 and stats['schema_repair_attempts']==0
    assert stats['admission_correction_attempts']==1 and len(stats['calls'])==2
    assert json.loads(client.calls[1]['user'])['exact_error']['allowed_scope_ids']==[1]

@pytest.mark.parametrize('retain_mechanical',[False,True])
def test_scope_correction_does_not_require_retaining_stripped_field(retain_mechanical):
    corrected={**packet(),**({'capability_ref':1} if retain_mechanical else {})}
    result,client,events=invoke([{**packet(),'scope':[0,1],'capability_ref':1},corrected])
    assert result[2]['admission_correction_attempts']==1 and len(client.calls)==2
    assert 'capability_ref' not in json.loads(client.calls[1]['user'])['immutable_fields']
    assert events[0]['error']['mechanical_receipts'][0]['semantics_changed'] is False

def test_third_repeat_terminates_without_fourth_call():
    with pytest.raises(SchemaRepairFailed) as e:invoke([{**packet(),'scope':[0,1]}]*3)
    assert len(e.value.semantic_calls)==3 and e.value.details['correction_path_terminated'] is True

def test_worker_permission_feedback():
    s=TableSnapshot({'paths':[{'path':'dependency.py','readable':True,'writable':False},{'path':'own.py','readable':True,'writable':True}]})
    with pytest.raises(ContractError) as e:compile_worker({'op':2,'path':0,'payload':'x'},s,bound_hash=s.hash,node_id='n')
    assert e.value.as_dict()['allowed_values']==[1] and e.value.as_dict()['allowed_op_ids']==[0,1]

def test_worker_escalation_cannot_smuggle_action():
    s=TableSnapshot({'paths':[]})
    result=compile_worker({'escalation':True,'expected_local_effect':'Need unavailable dependency'},s,bound_hash=s.hash,node_id='n')
    assert result['needs_escalation'] and not result['actions']
    with pytest.raises(ContractError,match='ESCALATION_CONTRADICTION'):
        compile_worker({'escalation':True,'expected_local_effect':'publish','op':2,'path':0,'payload':'x'},s,bound_hash=s.hash,node_id='n')

def test_approval_policy_visible_and_denied():
    d=snapshot().document;d['capabilities'][1]['external_effect']=True
    s=TableSnapshot(d)
    assert s.public_document['capabilities'][1]['requires_approval'] is True
    assert s.public_document['capabilities'][1]['approved'] is False
    with pytest.raises(ContractError) as e:compile(packet(),s)
    assert e.value.as_dict()['admission_status']=='POLICY_DENIED'
    assert e.value.as_dict()['allowed_values']==[0]

def test_worker_exhausted_admission_keeps_separate_cost_counters(tmp_path):
    from cgkn.executors.llm import LLMExecutor
    from cgkn.execution import BlockExecutionRequest,TaskContext,BlockStatus
    from cgkn.orchestration.leaf_contract import build_leaf_contract
    contract=build_leaf_contract(goal='write own file',kind='IMPLEMENTATION',scope=['own.py'],acceptance=['public'],
        checker='checker',output_identity='own',effect_domains=['local'],executor='llm.cheap@1',expected_delta='own.py')
    contract['read_scope']=['dependency.py']
    request=BlockExecutionRequest(project_id='p',run_id='r',attempt_id='a',node_id='n',component_ref='code',executor_ref='llm.cheap@1',task_context=TaskContext('own file',{'leaf_contract':contract}))
    client=Client([{'op':2,'path':0,'payload':'not allowed'}]*3)
    result=LLMExecutor(tmp_path,client,ModelRoleConfig('worker','fixture'),semantic_protocol=True,protocol_trace=lambda e:None).execute(request)
    assert result.status is BlockStatus.FAILED
    assert result.usage['schema_repair_attempts']==0 and result.usage['admission_correction_attempts']==2
    assert result.usage['input_tokens']==9 and len(result.usage['semantic_calls'])==3
    assert not list(tmp_path.iterdir())

def test_target_version_detects_tree_change_even_with_same_local_id():
    from cgkn.orchestration.tree_edits import apply_tree_edits
    from cgkn.protocol.tables import planner_snapshot
    from cgkn.agent.composer import AgentDecisionContext
    initial=compile(packet())
    tree=apply_tree_edits(CapabilityTree('goal',()),initial['edits'],known_capabilities={'code','accept'})
    catalog={'accept':{'executor_ref':'executor','checker_ref':'checker','acceptance':['public'],'effect_domains':['local'],'semantic_task_kinds':[4]}}
    context=AgentDecisionContext('p','r','goal',2,tree,tuple(catalog),catalog,{}, {})
    s=planner_snapshot(context,[{'path':'project','purpose':'acceptance'}])
    altered=tree.as_dict();altered['nodes'][0]['config']['semantic_expected']=['changed target intent']
    changed=CapabilityTree.from_dict(altered)
    with pytest.raises(ContractError,match='STALE_TARGET') as e:
        compile_planner({'action':3,'target':0},s,bound_hash=s.hash,tree=changed,context_identity='same-id')
    assert e.value.as_dict()['expected_hash']!=e.value.as_dict()['actual_hash']

def test_noncorrectable_repetition_stops_across_project_decisions(tmp_path):
    from cgkn.agent.composer import AgentComposer
    from cgkn.agent.project_loop import AgentProjectLoop
    from cgkn.executors import ExecutorRegistry
    from cgkn.runtime import DAGRunner
    from cgkn.state import FileRunStore
    client=Client([{**packet(),'unknown_intent':'publish'}]*3);events=[]
    composer=AgentComposer(client,ModelRoleConfig('agent','fixture'),semantic_tables=lambda ctx:snapshot(),protocol_trace=events.append)
    store=FileRunStore(tmp_path)
    loop=AgentProjectLoop(composer,DAGRunner(ExecutorRegistry(),store),store,known_capabilities={'code','accept'},worker_model='fixture',max_decisions=10)
    result=loop.run(project_id='p',run_id='r',goal='goal')
    assert result.status=='BLOCKED' and result.decision_count==3 and len(client.calls)==3
    assert events[-1]['error']['correction_path_terminated'] is True
    assert events[1]['error']['repetition_status']=='REPEATED_INVALID_DECISION'
    assert len(result.tree.nodes)==0

@pytest.mark.parametrize('late_failure',[False,True])
def test_worker_rounds_do_not_erase_prior_call_cost_or_corrections(tmp_path,late_failure):
    from cgkn.executors.llm import LLMExecutor
    from cgkn.execution import BlockExecutionRequest,TaskContext,BlockStatus
    from cgkn.orchestration.leaf_contract import build_leaf_contract
    contract=build_leaf_contract(goal='write own file',kind='IMPLEMENTATION',scope=['own.py'],acceptance=['public'],
        checker='checker',output_identity='own',effect_domains=['local'],executor='llm.cheap@1',expected_delta='own.py')
    contract['read_scope']=['dependency.py']
    request=BlockExecutionRequest(project_id='p',run_id='r',attempt_id='a',node_id='n',component_ref='code',executor_ref='llm.cheap@1',task_context=TaskContext('own file',{'leaf_contract':contract}))
    (tmp_path/'own.py').write_text('old=1');(tmp_path/'dependency.py').write_text('dependency=1')
    packets=([{'op':0,'path':1}]+[{'op':2,'path':0,'payload':'forbidden'}]*3) if late_failure else [
        {'op':0,'path':99},{'op':0,'path':1},{'op':2,'path':1,'payload':'new=2'}]
    client=Client(packets)
    result=LLMExecutor(tmp_path,client,ModelRoleConfig('worker','fixture'),max_rounds=3,semantic_protocol=True,protocol_trace=lambda e:None).execute(request)
    assert result.status is (BlockStatus.FAILED if late_failure else BlockStatus.SUCCEEDED)
    assert result.usage['input_tokens']==3*len(packets) and result.usage['output_tokens']==5*len(packets)
    assert len(result.usage['semantic_calls'])==len(packets) and result.usage['provider_attempts']==len(packets)
    assert result.usage['semantic_decision_attempts']==2
    assert result.usage['schema_repair_attempts']==(0 if late_failure else 1)
    assert result.usage['admission_correction_attempts']==(2 if late_failure else 0)
    assert (tmp_path/'dependency.py').read_text()=='dependency=1'
