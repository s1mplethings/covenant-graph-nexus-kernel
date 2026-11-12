import pytest
from cgkn.protocol.compiler import compile_planner
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.tables import planner_snapshot
from cgkn.agent.composer import AgentDecisionContext
from tests.protocol.test_repair_target_feedback import fixture
from tests.protocol.test_repair_path import packet

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def test_unrelated_writer_repair_fails_early_with_correct_target_ids():
    t,tree=fixture();before=tree.as_dict()
    with pytest.raises(ContractError) as caught:
        compile_planner({**packet(),'action':4,'task_kind':3,'target':2},t,bound_hash=t.hash,tree=tree,context_identity='repair')
    assert caught.value.code=='REPAIR_TARGET_SCOPE_MISMATCH'
    assert caught.value.fields==('target',) and caught.value.details['allowed_values']==[0]
    assert 'contract_diff' not in caught.value.details
    assert tree.as_dict()==before


def test_public_scope_maps_only_existing_writers_for_that_scope():
    t,tree=fixture()
    catalog={r['capability_ref']:{'executor_ref':r['executor_ref'],'checker_ref':r['checker_ref'],'acceptance':r['acceptance_refs'],'effect_domains':r['effect_domains'],'semantic_task_kinds':r['task_kinds']} for r in t.document['capabilities']}
    ctx=AgentDecisionContext('p','r',tree.goal,1,tree,tuple(catalog),catalog,{}, {})
    table=planner_snapshot(ctx,[{'path':x,'purpose':'public scope'} for x in ['module.py','project','new.py']]).public_document
    assert [s['writer_target_ids'] for s in table['scopes']]==[[0],[2],[]]
    assert all(isinstance(i,int) for s in table['scopes'] for i in s['writer_target_ids'])
