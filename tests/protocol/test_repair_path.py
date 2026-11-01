import json
import pytest
from cgkn.protocol.compiler import TableSnapshot,compile_planner
from cgkn.protocol.repair import (PublicContractRegistry,RepairIntentClassifier,contract_diff,
    repair_progress,ACTIONS_V2,plain)
from cgkn.protocol.context_pack import failure_context,worker_contract_pack,token_bound
from cgkn.protocol.normalization import ContractError,digest
from cgkn.protocol.exchange import exchange
from cgkn.orchestration import CapabilityTree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.providers import ProviderCompletion,ModelRoleConfig

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def registry():
    return {'kind':'PublicContractRegistry','entries':[{'contract_id':'public-api','feature':'value',
        'source_decision':'declaration-1','version':1,'status':'DECLARED','evidence_refs':['declaration.json'],
        'change_policy':'immutable','artifact_paths':['module.py','tests.py','project'],
        'integrity_version':2,'must_acceptance_ids':['public'],
        'artifact_declarations':[{'path':'module.py','interfaces':{'public_exports':[{'name':'read','kind':'function'}]}}],
        'definition':{'interface':'read(key)','fields':{'value':'int'},'return_shape':{'value':'int'},
            'types':{'value':'int'},'exports':[{'name':'read','kind':'function','owner':'module.py'}],
            'field_contracts':[{'name':'value','type':'int','owner':'$contract','required':True,'consumers':['public']}],
            'return_shapes':{'$contract':['value']},'exception_bindings':[],
            'acceptance_bindings':[{'acceptance_id':'public','contract_id':'public-api','checker_ref':'checker','object_ref':'module.py','version':1}],
            'exceptions':{'invalid':'ValueError'},'idempotency':'same request same value',
            'persistence':'survives restart','ordering':'FIFO','concurrency':'single logical result','edge_behavior':'unknown raises'}}]}

def snapshot():
    return TableSnapshot({'action_version':2,'nodes':[{'node_id':'n'},{'node_id':'sibling'},{'node_id':'inspect'}],
        'scopes':[{'path':'module.py'},{'path':'tests.py'},{'path':'project'}],
        'capabilities':[{'capability_ref':'code','task_kinds':[2,3,4,5], 'executor_ref':'executor','checker_ref':'checker',
            'acceptance_refs':['public'],'effect_domains':['local']}], 'sources':[],
        'public_contract_registry':registry(),'context_raw_ref':'context.json','repair_context':{}})

def packet():return {'action':1,'task_kind':2,'target':0,'scope':[0],'deps':[],
    'goal':'implement declared function','expected':['module exists'],'accept':['original public behavior holds']}

def run(packet,s,tree):return compile_planner(packet,s,bound_hash=s.hash,tree=tree,context_identity='test')

def initial():
    s=snapshot();tree=CapabilityTree('original user goal',())
    tree=apply_tree_edits(tree,run(packet(),s,tree)['edits'],known_capabilities={'code'})
    return s,tree

def failed_snapshot(s):
    d=s.document;d['repair_context']={'failures':[{'acceptance_id':'A-field','failure_domain':'business',
        'artifact_paths':['module.py'],'target_leaf_refs':['n'],'expected':'value:int','actual':'value:str',
        'object_identity':'sha256:candidate','evidence_refs':['checker.json'],'failure_code':'FIELD_MISMATCH'}],
        'goal_state':{'verified':['unrelated'],'failed':['A-field'],'missing':['A-other']}}
    return TableSnapshot(d)

def repair_packet():return {**packet(),'action':4,'task_kind':3,'goal':'repair implementation to original contract',
    'expected':['field uses declared type'],'accept':['field check passes']}

def test_v2_action_table_unambiguous_and_legacy_retained():
    from cgkn.protocol.compiler import ACTIONS
    assert len(ACTIONS_V2)==11 and len(set(ACTIONS_V2.values()))==11
    assert ACTIONS[7]=='FINISH' and ACTIONS_V2[7]=='ADD_DEPENDENCY'

def test_generated_v2_snapshot_survives_json_roundtrip_with_action_ten():
    from cgkn.protocol.tables import planner_snapshot
    from cgkn.agent.composer import AgentDecisionContext
    cat={'code':{'executor_ref':'executor','checker_ref':'checker','acceptance':['public'],
        'effect_domains':['local'],'semantic_task_kinds':[2,3]}}
    ctx=AgentDecisionContext('p','r','goal',1,CapabilityTree('goal',()),('code',),cat,{}, {})
    snap=planner_snapshot(ctx,[{'path':'module.py','purpose':'module','interfaces':{}}],action_version=2,
        public_contract_registry=registry(),context_raw_ref='context.json')
    snap.bind(snap.hash)
    assert TableSnapshot(json.loads(json.dumps(snap.document))).hash==snap.hash
    assert snap.public_document['action_table']['10']=='ESCALATE'

def test_legal_retry_keeps_original_tree():
    s,t=initial();out=run({'action':3,'target':0},s,t)
    assert [e.operation for e in out['edits']]==['retry_node']
    assert apply_tree_edits(t,out['edits'],known_capabilities={'code'})==t

@pytest.mark.parametrize('key,value',[('goal','new'),('expected',['new']),('accept',['easier']),('deps',[1]),('scope',[1])])
def test_retry_semantic_drift_rejected(key,value):
    s,t=initial()
    with pytest.raises(ContractError,match='RETRY_CHANGES_SEMANTICS') as e:run({'action':3,'target':0,key:value},s,t)
    assert e.value.details['allowed_action_ids']==[4,5,8]
    assert key in e.value.details['changed_fields']

def test_business_failure_retry_is_repair_specific():
    s,t=initial();s=failed_snapshot(s)
    with pytest.raises(ContractError,match='ACTION_MISMATCH_REPAIR_REQUIRED') as e:run({**repair_packet(),'action':3},s,t)
    assert e.value.details['failed_acceptance_ids']==['A-field']
    assert e.value.details['immutable_goal']==t.goal

def test_repair_admitted_original_acceptance_and_registry_preserved():
    s,t=initial();s=failed_snapshot(s);out=run(repair_packet(),s,t)
    after=apply_tree_edits(t,out['edits'],known_capabilities={'code'});config=plain(after.by_id['n'].config)
    assert after.goal==t.goal
    assert set(t.by_id['n'].config['semantic_acceptance'])<=set(config['semantic_acceptance'])
    assert config['repair_contract']['state']=='REPAIR_ADMITTED'
    assert config['repair_contract']['immutable_contract_refs']['registry_hash']==PublicContractRegistry(registry()).hash
    assert config['repair_contract']['evidence_refs']==['checker.json']

def test_repair_cannot_silently_change_public_contract():
    s,t=initial();d=failed_snapshot(s).document
    d['public_contract_registry']['entries'][0]['definition']['fields']['value']='str'
    with pytest.raises(ContractError,match='PUBLIC_CONTRACT_CHANGE'):run(repair_packet(),TableSnapshot(d),t)

def test_repair_cannot_manufacture_failed_requirement():
    s,t=initial()
    with pytest.raises(ContractError,match='REPAIR_REQUIRES_OBSERVED_FAILURE'):run(repair_packet(),s,t)
    with pytest.raises(ContractError,match='REPAIR_REQUIRES_OBSERVED_FAILURE'):
        run({**repair_packet(),'failed_acceptance_ids':['invented']},failed_snapshot(s),t)

@pytest.mark.parametrize('action',[5,8])
def test_strategy_and_replan_preserve_user_goal(action):
    s,t=initial();s=failed_snapshot(s);out=run({**repair_packet(),'action':action},s,t)
    after=apply_tree_edits(t,out['edits'],known_capabilities={'code'})
    assert after.goal==t.goal and 'original public behavior holds' in after.by_id['n'].config['semantic_acceptance']
    if action==8:assert after.by_id['n'].config['replan_carry_forward']['verified']==('unrelated',)

@pytest.mark.parametrize('domain,expected,operation',[
    ('business','IMPLEMENTATION_REPAIR','REPAIR_IMPLEMENTATION'),('field_mismatch','IMPLEMENTATION_REPAIR','REPAIR_IMPLEMENTATION'),
    ('exception','IMPLEMENTATION_REPAIR','REPAIR_IMPLEMENTATION'),('idempotency','IMPLEMENTATION_REPAIR','REPAIR_IMPLEMENTATION'),
    ('persistence','IMPLEMENTATION_REPAIR','REPAIR_IMPLEMENTATION'),('transport','SAME_EXECUTION_RETRY','RETRY_EXECUTION'),
    ('outcome_unknown','UNKNOWN','RECONCILE'),('schema','UNKNOWN','SCHEMA_CORRECTION'),('decomposition','TREE_REPLAN','REPLAN')])
def test_failure_domain_classifier(domain,expected,operation):
    got=RepairIntentClassifier.classify(3,[{'failure_domain':domain}],{'goal':'changed'})
    assert (got['intent'],got['next_operation'])==(expected,operation)

class Fake:
    def __init__(self,packets):self.packets=iter(packets);self.requests=[]
    def complete(self,**kw):
        self.requests.append(kw)
        return ProviderCompletion(json.dumps(next(self.packets)),'fake-model',str(len(self.requests)),{'input_tokens':1,'output_tokens':1})

def test_action_correction_second_call_admits_without_full_context():
    s,t=initial();s=failed_snapshot(s);client=Fake([{**repair_packet(),'action':3},repair_packet()]);events=[]
    out,_,stats=exchange(client,ModelRoleConfig('agent','fake'),system='Choose intent',context={},snapshot=s,
        semantic_attempt_id='one',compiler=lambda p,h:run(p,s,t),normalization={},trace=events.append)
    assert len(client.requests)==2 and stats['repair_action_corrections']==1 and stats['semantic_decision_attempts']==1
    corrected=json.loads(client.requests[1]['user'])
    assert 'context' not in corrected and 'tables' not in corrected
    assert corrected['invalid_fields']==['action'] and events[1]['semantic_diff']['changed_fields']==['action']
    assert any(e.operation=='retry_node' for e in out['edits'])

def test_repair_correction_cannot_weaken_packet_acceptance():
    s,t=initial();s=failed_snapshot(s);client=Fake([{**repair_packet(),'action':3},{**repair_packet(),'accept':['nothing required']}])
    with pytest.raises(ContractError,match='IMMUTABLE'):
        exchange(client,ModelRoleConfig('agent','fake'),system='intent',context={},snapshot=s,semantic_attempt_id='one',
            compiler=lambda p,h:run(p,s,t),normalization={},trace=lambda e:None)
    assert len(client.requests)==2

def test_repeated_action_mismatch_has_bounded_paid_calls():
    s,t=initial();s=failed_snapshot(s);client=Fake([{**repair_packet(),'action':3}]*4)
    with pytest.raises(ContractError) as e:
        exchange(client,ModelRoleConfig('agent','fake'),system='intent',context={},snapshot=s,semantic_attempt_id='one',
            compiler=lambda p,h:run(p,s,t),normalization={},trace=lambda e:None)
    assert len(client.requests)==3 and e.value.details['correction_path_terminated']

def test_public_registry_local_retrieval_and_diff():
    r=PublicContractRegistry(registry());assert r.select(['unrelated.py'])['entries']==[]
    assert r.select(['module.py'])['entries'][0]['definition']['exceptions']=={'invalid':'ValueError'}
    changed=registry();del changed['entries'][0]['definition']['idempotency']
    assert contract_diff(registry(),changed)['drift_count'] and contract_diff(registry(),changed)['possible_weakening']

def test_registry_is_immutable_and_persisted_ref_binds_actual_bytes(tmp_path):
    import hashlib
    from pathlib import Path
    from cgkn.state import FileRunStore
    r=PublicContractRegistry(registry());copy=r.document;copy['entries'][0]['definition']['fields']['value']='str'
    assert r.document['entries'][0]['definition']['fields']['value']=='int'
    ref=r.persist(FileRunStore(tmp_path),'p','r')
    assert ref['registry_hash']==r.hash and ref['sha256']==hashlib.sha256(Path(ref['ref']).read_bytes()).hexdigest()

@pytest.mark.parametrize('section',['fields','return_shape','exceptions','idempotency','persistence','ordering','concurrency'])
def test_required_contract_section_cannot_disappear(section):
    doc=registry();doc['entries'][0]['required_sections']=[section];del doc['entries'][0]['definition'][section]
    with pytest.raises(ContractError,match='INCOMPLETE_PUBLIC_CONTRACT'):PublicContractRegistry(doc)
    s,t=initial();config=plain(t.by_id['n'].config);config['public_contracts']['entries']=doc['entries']
    with pytest.raises(ContractError,match='WORKER_REQUIRED_CONTRACT_MISSING'):
        worker_contract_pack({'goal':'task','config':config})

def test_worker_receives_complete_contract_and_read_only_permissions():
    s,t=initial();s=failed_snapshot(s);after=apply_tree_edits(t,run(repair_packet(),s,t)['edits'],known_capabilities={'code'})
    raw={'goal':'repair','config':plain(after.by_id['n'].config),'observations':[]}
    pack=worker_contract_pack(raw);definition=pack['public_contracts']['entries'][0]['definition']
    assert set(definition)>={'fields','return_shape','exceptions','idempotency','persistence','ordering','concurrency','edge_behavior'}
    assert pack['failed_acceptance_ids']==['A-field'] and pack['allowed_write_paths']==['module.py']
    assert token_bound(pack)<10000
    del raw['config']['public_contracts']
    with pytest.raises(ContractError,match='WORKER_REQUIRED_CONTRACT_MISSING'):worker_contract_pack(raw)

def test_failure_pack_references_raw_without_losing_failed_acceptance():
    raw={'goal':'original','failure_details':{'stdout':'large log\n'*50000},'goal_acceptance':{'obligations':{'A':{'verdict':'FAILED'}}}}
    failures=failed_snapshot(snapshot()).document['repair_context']['failures']
    pack=failure_context(raw,evidence_ref='immutable/context.json',failures=failures)
    assert pack['failures']==failures and pack['goal_state']['failed']==['A']
    assert pack['raw_evidence_refs']==['immutable/context.json'] and pack['raw_evidence_bytes_inlined']==0
    assert token_bound(pack)<8000 and 'large log' not in json.dumps(pack)

def test_context_hard_cap_never_silently_drops_contract():
    # ITER-130 explicitly replaces the old arbitrary local cap. The complete
    # original contract must now survive; sourced physical limits are separate.
    contract={'huge_contract':'x'*20000}
    assert failure_context({'goal':'goal'},evidence_ref='raw',contracts=contract)['public_contracts']==contract

def test_two_repairs_without_improvement_require_strategy_change():
    first=repair_progress(['a'],['a'],'same');second=repair_progress(['a'],['a'],'same',[first])
    assert second['code']=='REPEATED_REPAIR_NO_PROGRESS'
    assert repair_progress(['a'],[],'same',[first])['status']=='REPAIR_PROGRESS'
    assert repair_progress(['a'],['a','b'],'different',[first])['status']=='REPAIR_REGRESSION'

def test_compile_stops_repeated_no_progress_and_preserves_terminal_flag():
    from cgkn.protocol.admission import InvalidDecisionTracker
    s,t=initial();s=failed_snapshot(s);p=repair_packet()
    fingerprint=digest({k:p.get(k) for k in ('target','goal','expected','scope','deps')})
    d=s.document;d['repair_context']['previous_repair_attempts']=[{'strategy_fingerprint':fingerprint,'status':'REPAIR_NO_PROGRESS'}]*2
    with pytest.raises(ContractError,match='REPEATED_REPAIR_NO_PROGRESS') as e:run(p,TableSnapshot(d),t)
    InvalidDecisionTracker().observe(p,e.value)
    assert e.value.details['correction_path_terminated'] and e.value.details['allowed_action_ids']==[5,6,8]

def test_stale_v2_snapshot_fails_before_edits():
    s,t=initial()
    with pytest.raises(ContractError,match='STALE_TABLE'):
        compile_planner(repair_packet(),s,bound_hash='wrong',tree=t,context_identity='one')

def test_split_uses_one_composite_and_existing_canonical_children():
    s=snapshot();t=CapabilityTree('original user goal',())
    out=run({'action':2,'target':2,'children':[packet(),{**packet(),'target':1,'scope':[1]}]},s,t)
    after=apply_tree_edits(t,out['edits'],known_capabilities={'code'})
    assert not after.by_id['inspect'].executable and len(after.children('inspect'))==2
    assert after.goal==t.goal

def test_split_never_demotes_existing_executable_identity():
    s,t=initial()
    with pytest.raises(ContractError,match='ADDITIVE_REPLAN'):
        run({'action':2,'target':0,'children':[{**packet(),'target':1},{**packet(),'target':2}]},s,t)

def test_targeted_retest_runs_real_process_before_final_acceptance(tmp_path):
    import subprocess,sys
    from cgkn.state.repair import TargetedRepairVerification
    order=[]
    def targeted(ids):
        process=subprocess.run([sys.executable,'-c','assert 2 + 2 == 4'],capture_output=True)
        order.append('target')
        return {'checks':{k:process.returncode==0 for k in ids},'evidence_refs':['target-process.json']}
    def final():
        order.append('final');return {'checks':{'a':True,'b':True},'passed':True,'evidence_refs':['full.json']}
    phases=[];result=TargetedRepairVerification(targeted,final).execute(['a'],record=lambda p,d:phases.append(p))
    assert result['passed'] and order==['target','final']
    assert phases==['TARGETED_RETEST','ACCEPTANCE_RECHECK','REPAIR_VERIFIED']

def test_failed_targeted_retest_never_calls_final_acceptance():
    from cgkn.state.repair import TargetedRepairVerification
    def final():raise AssertionError('must not execute final acceptance')
    result=TargetedRepairVerification(lambda ids:{'checks':{'a':False}},final).execute(['a'],record=lambda *a:None)
    assert not result['passed'] and result['final'] is None

def test_targeted_retest_cannot_omit_failed_predicate():
    from cgkn.state.repair import TargetedRepairVerification
    with pytest.raises(ValueError,match='omitted'):
        TargetedRepairVerification(lambda ids:{'checks':{}},lambda:None).execute(['a'],record=lambda *a:None)
