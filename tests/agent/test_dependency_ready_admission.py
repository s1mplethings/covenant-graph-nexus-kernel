import copy
from dataclasses import replace
import pytest
from tests.agent.test_milestone_dependency_reads import context
from tests.protocol.test_milestone_declaration import semantic
from cgkn.agent.composer import AgentComposer
from cgkn.protocol.declaration import MilestoneContractCompiler
from cgkn.protocol.context_pack import failure_context,dependency_ready_goals

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def chain(status):
    ctx,old_dep,hash_value=context(status)
    design,registry,receipt=MilestoneContractCompiler().compile(semantic(),source_ref='prior-agent-declaration',requirement_refs=['prior'],namespace='prior',checker_ref='consumer',artifact_subject=True)
    upstream=ctx.goal_acceptance['goals'][0];upstream.update(checker='measure',requirement_refs=['prior'],milestone_contract=dict(design=design,registry=registry,compilation=receipt,dependency_artifacts=[],dependency_goal_ids=[]))
    dep=design['artifacts'][0]['path'];upstream['subject_refs']=[dep]
    current=ctx.goal_acceptance['goals'][1];current['requirement_refs']=['next'];current['subject_refs']=[current['subject_refs'][0],dep];current['milestone_contract']['dependency_artifacts']=[dep]
    for g in ctx.goal_acceptance['goals']:
        for a in g['milestone_contract']['design']['artifacts']:ctx.goal_acceptance['subject_identities'][a['path']]=hash_value
    catalog={**ctx.capability_catalog,'measurement':{'executor_ref':'consumer','semantic_task_kinds':[4],'checker_ref':'independent-measurement','acceptance':['measurement'],'effect_domains':['measurement']}}
    return replace(ctx,capability_catalog=catalog,known_capabilities=tuple(catalog))

@pytest.mark.parametrize('status',['FAILED','INSUFFICIENT_EVIDENCE','UNKNOWN','STALE'])
def test_materialized_downstream_not_advertised_before_upstream_verified(status):
    ctx=chain(status);before=copy.deepcopy(ctx.as_dict());doc=AgentComposer._milestone_snapshot(ctx).document
    assert {g['goal_id'] for g in doc['goals']}=={'upstream-goal'}
    assert {c['config']['goal_id'] for c in doc['capabilities'] if c.get('config',{}).get('goal_id')}=={'upstream-goal'}
    blocked={a['path'] for a in ctx.goal_acceptance['goals'][1]['milestone_contract']['design']['artifacts']}
    assert not blocked.intersection(x['path'] for x in doc['scopes'])
    assert failure_context(ctx,evidence_ref='raw.json')['current_milestone_requirements']==['prior']
    assert ctx.as_dict()==before

def test_verified_upstream_unlocks_existing_downstream_without_new_plan():
    ctx=chain('VERIFIED');doc=AgentComposer._milestone_snapshot(ctx).document
    assert {g['goal_id'] for g in doc['goals']}=={'current'}
    assert {c['config']['goal_id'] for c in doc['capabilities'] if c.get('config',{}).get('goal_id')}=={'current'}
    assert failure_context(ctx,evidence_ref='raw.json')['current_milestone_requirements']==['next']

def test_missing_dependency_does_not_unlock_and_independent_goals_remain_ready():
    goals=[{'id':'a','verdict':'FAILED','milestone_contract':{}}, {'id':'b','verdict':'INSUFFICIENT_EVIDENCE','milestone_contract':{}}, {'id':'c','verdict':'INSUFFICIENT_EVIDENCE','milestone_contract':{'dependency_goal_ids':['missing']}}]
    assert [g['id'] for g in dependency_ready_goals(goals)]==['a','b']
