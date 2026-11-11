"""A failed integration can repair its bound owner, without opening siblings."""
import copy
import pytest
from cgkn.agent.composer import AgentComposer
from cgkn.protocol.compiler import compile_planner
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.repair import plain
from tests.agent.test_dependency_ready_admission import chain

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def failed_integration():
    ctx=chain('VERIFIED')
    view=ctx.goal_acceptance
    view['evidence_mode']='production_provenance'
    upstream,current=view['goals']
    path=upstream['milestone_contract']['design']['artifacts'][0]['path']
    current['verdict']='FAILED'
    current['evidence']={'node_id':'check','attempt_id':'attempt-0001','receipt_hash':'a'*64,
        'subjects':{p:view['subject_identities'][p] for p in current['subject_refs']},
        'provenance':{'status':'TRUSTED'},'reason':'Integration rejects the required behavior'}
    return ctx,path

def test_bound_owner_source_is_available_for_explicit_repair_only():
    ctx,path=failed_integration();before=copy.deepcopy(ctx.as_dict())
    table=AgentComposer._milestone_snapshot(ctx);doc=table.document
    index=next(i for i,s in enumerate(doc['scopes']) if s['path']==path)
    packet=dict(action=1,task_kind=3,target=0,scope=[index],deps=[],goal='Repair bound dependency behavior',expected=['Integration behavior restored'],accept=['Source valid'])
    result=compile_planner(packet,table,bound_hash=table.hash,tree=ctx.tree,context_identity='repair-owner')
    config=plain(result['edits'][0].payload['config'])
    assert config['leaf_contract']['target_scope']==[path]
    assert config['imported_artifact_repair_evidence'][0]['acceptance_id']=='current'
    owner=ctx.goal_acceptance['goals'][0]['milestone_contract']['registry']['entries']
    assert all(e in doc['public_contract_registry']['entries'] for e in owner)
    assert {g['goal_id'] for g in doc['goals']}=={'current'}
    assert ctx.as_dict()==before
    with pytest.raises(ContractError,match='MATERIALIZED_SCOPE_REQUIRES_EXPLICIT_CHANGE'):
        compile_planner({**packet,'task_kind':2},table,bound_hash=table.hash,tree=ctx.tree,context_identity='not-repair')

@pytest.mark.parametrize('mode',['not_failed','untrusted','not_production','stale_subject','missing_subject','not_dependency','not_declared','no_receipt'])
def test_unqualified_dependency_never_becomes_a_write_scope(mode):
    ctx,path=failed_integration();view=ctx.goal_acceptance;g=view['goals'][1]
    if mode=='not_failed':g['verdict']='INSUFFICIENT_EVIDENCE'
    elif mode=='untrusted':g['evidence']['provenance']['status']='UNTRUSTED'
    elif mode=='not_production':view['evidence_mode']='diagnostic'
    elif mode=='stale_subject':g['evidence']['subjects'][path]='b'*64
    elif mode=='missing_subject':g['evidence']['subjects'].pop(path)
    elif mode=='not_dependency':g['milestone_contract']['dependency_goal_ids']=[]
    elif mode=='not_declared':g['milestone_contract']['dependency_artifacts']=[]
    elif mode=='no_receipt':g['evidence']['receipt_hash']=''
    doc=AgentComposer._milestone_snapshot(ctx).document
    assert path not in {s['path'] for s in doc['scopes']}

def test_owner_tests_and_unrelated_paths_stay_outside_failed_subject_scope():
    ctx,path=failed_integration();owner=ctx.goal_acceptance['goals'][0]
    test_path=owner['milestone_contract']['design']['artifacts'][1]['path']
    ctx.goal_acceptance['subject_identities']['unrelated.py']='f'*64
    scopes={s['path'] for s in AgentComposer._milestone_snapshot(ctx).document['scopes']}
    assert path in scopes
    assert test_path not in scopes and 'unrelated.py' not in scopes
