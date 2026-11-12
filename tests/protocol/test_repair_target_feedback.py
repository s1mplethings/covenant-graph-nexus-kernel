import pytest
from cgkn.protocol.compiler import TableSnapshot,compile_planner
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.repair import plain
from cgkn.protocol.tables import planner_snapshot
from cgkn.agent.composer import AgentDecisionContext
from cgkn.orchestration import CapabilityTree
from cgkn.orchestration.tree_edits import apply_tree_edits
from tests.protocol.test_repair_path import snapshot,packet

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def fixture():
    doc=snapshot().document
    doc['capabilities'][0]['task_kinds']=[2,3]
    doc['capabilities'].append(dict(capability_ref='measure',task_kinds=[4],executor_ref='checker',checker_ref='checker',acceptance_refs=['public'],effect_domains=['read']))
    t=TableSnapshot(doc);tree=CapabilityTree('original user goal',())
    for p in [packet(),{**packet(),'target':1,'task_kind':4,'deps':[0]},{**packet(),'target':2,'scope':[2]}]:
        result=compile_planner(p,t,bound_hash=t.hash,tree=tree,context_identity='fixture')
        tree=apply_tree_edits(tree,result['edits'],known_capabilities={'code','measure'})
    return t,tree


def test_measurement_target_rejected_with_scope_compatible_writer_ids_not_capability_ids():
    t,tree=fixture();before=tree.as_dict()
    with pytest.raises(ContractError) as caught:
        compile_planner({**packet(),'action':4,'task_kind':3,'target':1},t,bound_hash=t.hash,tree=tree,context_identity='repair')
    e=caught.value
    assert e.code=='STRATEGY_REQUIRES_REPLAN' and e.fields==('target',)
    assert e.details['allowed_values']==[0] # other code node has an unrelated scope
    assert e.details['current_value']==1 and 'measurement/checker' in e.details['instruction']
    assert tree.as_dict()==before
    # Selecting a writer is not sufficient: observed failure remains required.
    with pytest.raises(ContractError,match='REPAIR_REQUIRES_OBSERVED_FAILURE'):
        compile_planner({**packet(),'action':4,'task_kind':3},t,bound_hash=t.hash,tree=tree,context_identity='repair2')


def test_public_target_table_identifies_kind_and_numeric_dependencies():
    t,tree=fixture()
    catalog={r['capability_ref']:{'executor_ref':r['executor_ref'],'checker_ref':r['checker_ref'],'acceptance':r['acceptance_refs'],'effect_domains':r['effect_domains'],'semantic_task_kinds':r['task_kinds']} for r in t.document['capabilities']}
    ctx=AgentDecisionContext('p','r',tree.goal,1,tree,tuple(catalog),catalog,{}, {})
    table=planner_snapshot(ctx,[{'path':'module.py','purpose':'declared public source'}])
    public=table.public_document
    assert public['nodes'][0]['task_kind']=='IMPLEMENTATION'
    assert public['nodes'][1]['task_kind']=='TEST'
    assert public['nodes'][1]['dependency_ids']==[0]
    assert 'node_id' not in public['nodes'][1]


