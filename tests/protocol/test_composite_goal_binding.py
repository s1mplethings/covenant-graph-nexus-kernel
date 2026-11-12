"""Explicit composite goal binding; no global acceptance fallback."""
from dataclasses import replace
from types import SimpleNamespace
import pytest
from cgkn.agent.composer import AgentDecisionContext
from cgkn.orchestration import CapabilityTree, CapabilityNode
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.orchestration.execution_dag import _thaw
from cgkn.protocol.declaration import compile_declaration
from cgkn.protocol.compiler import TableSnapshot, compile_planner
from cgkn.protocol.tables import planner_snapshot
from cgkn.protocol.normalization import ContractError
from cgkn.state.task_feedback import digest
from cgkn.protocol.repair import planner_schema_v2
from cgkn.execution.deliverables import parent_projection

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def setup_snapshot():
    artifacts=[{'path':p,'purpose':'neutral bounded file','interfaces':{'public_exports':[]}} for p in ['a.txt','b.txt']]
    declaration={'artifacts':artifacts,'public_interface':{
        'interface':'two neutral files','fields':{'value':{'type':'str','required':True,'consumers':['caller']}},
        'types':{'value':'str'},'exceptions':'none','idempotency':'identical bytes','persistence':'files',
        'ordering':'independent','concurrency':'separate paths','edge_behavior':'missing fails'},
        'test_command':['python','check.py'],'reason_summary':'neutral structural qualification'}
    _,registry,_=compile_declaration(declaration,source_ref='raw:declaration',acceptance_bindings=[{
        'acceptance_id':'accepted-goal','contract_id':'contract','checker_ref':'check@1','object_ref':'bundle','version':1}])
    catalog={'code':{'executor_ref':'worker','checker_ref':'files','acceptance':['literal'],
        'effect_domains':['local'],'semantic_task_kinds':[2]}}
    context=AgentDecisionContext('p','r','neutral goal',1,CapabilityTree('neutral goal',()),('code',),catalog,{}, {},
        goal_acceptance={'checker_bindings':{'checked':'check@1'},'goals':[{'id':'accepted-goal',
          'acceptance':'both files satisfy the independent contract','checker':'checked','subject_refs':['bundle'],
          'requirement_refs':['R'],'verdict':'MISSING'}]})
    snapshot=planner_snapshot(context,artifacts,action_version=2,public_contract_registry=registry)
    child=lambda node,scope:{'action':1,'task_kind':2,'target':node,'goal':'materialize neutral file',
        'scope':[scope],'expected':['literal bytes'],'accept':['literal predicate'],'deps':[]}
    packet={'action':2,'target':0,'goal_ref':0,'children':[child(1,0),child(2,1)]}
    return context,snapshot,packet

def compile_tree_packet(context,snapshot,packet):
    out=compile_planner(packet,snapshot,bound_hash=snapshot.hash,tree=context.tree,context_identity='decision')
    return apply_tree_edits(context.tree,out['edits'],known_capabilities={'code'})

def test_composite_goal_table_is_derived_from_registered_checker_and_contract():
    _,snapshot,_=setup_snapshot()
    row=snapshot.document['goals'][0]
    assert row['goal_id']=='accepted-goal'
    assert {'a.txt','b.txt'}<=set(row['covered_artifact_paths'])
    assert snapshot.public_document['goals'][0]['id']==0
    assert 'goal_id' not in snapshot.public_document['goals'][0]
    assert planner_schema_v2()['properties']['goal_ref']['type']=='integer'

@pytest.mark.parametrize('value',[None,True,9,'accepted-goal'])
def test_missing_or_invalid_composite_goal_is_not_inferred(value):
    context,snapshot,packet=setup_snapshot()
    if value is None:packet.pop('goal_ref')
    else:packet['goal_ref']=value
    with pytest.raises(ContractError):compile_tree_packet(context,snapshot,packet)
    assert not context.tree.nodes

def test_goal_binding_does_not_cover_foreign_scopes_or_checker():
    context,snapshot,packet=setup_snapshot()
    doc=snapshot.document
    doc['goals'][0]['covered_artifact_paths']=['a.txt']
    with pytest.raises(ContractError,match='COMPOSITE_GOAL_SCOPE_MISMATCH'):
        compile_tree_packet(context,TableSnapshot(doc),packet)
    wrong=replace(context,goal_acceptance={**dict(context.goal_acceptance),'checker_bindings':{'checked':'wrong-checker'}})
    artifacts=[{'path':p,'purpose':'neutral','interfaces':{}} for p in ['a.txt','b.txt']]
    snap=planner_snapshot(wrong,artifacts,action_version=2,public_contract_registry=snapshot.document['public_contract_registry'])
    assert not snap.document['goals'][0]['covered_artifact_paths']
    with pytest.raises(ContractError,match='COMPOSITE_GOAL_SCOPE_MISMATCH'):
        compile_tree_packet(wrong,snap,packet)

def test_bound_parent_still_requires_current_goal_and_all_children():
    context,snapshot,packet=setup_snapshot()
    tree=compile_tree_packet(context,snapshot,packet)
    parent=tree.by_id['sem-node-0000']
    assert parent.config['acceptance_goal_id']=='accepted-goal'
    results={node.id:SimpleNamespace(metadata={'deliverable_verdict':'VERIFIED',
        'leaf_contract_hash':digest(_thaw(node.config['leaf_contract']))}) for node in tree.nodes if node.executable}
    assert parent_projection(tree,results,{'accepted-goal':'VERIFIED'})[parent.id]['verdict']=='VERIFIED'
    for verdict in ['MISSING','FAILED','INSUFFICIENT_EVIDENCE']:
        assert parent_projection(tree,results,{'accepted-goal':verdict})[parent.id]['verdict']=='BLOCKED'
    assert parent_projection(tree,results,{parent.id:'VERIFIED'})[parent.id]['verdict']=='BLOCKED'
    assert parent_projection(tree,{}, {'accepted-goal':'VERIFIED'})[parent.id]['verdict']=='BLOCKED'
    results['sem-node-0001'].metadata['leaf_contract_hash']='tampered'
    assert parent_projection(tree,results,{'accepted-goal':'VERIFIED'})[parent.id]['verdict']=='BLOCKED'

def test_composite_cannot_change_its_bound_goal():
    context,snapshot,packet=setup_snapshot()
    tree=compile_tree_packet(context,snapshot,packet)
    doc=snapshot.document
    doc['goals'].append({**doc['goals'][0],'goal_id':'another-goal'})
    packet['goal_ref']=1
    with pytest.raises(ContractError,match='COMPOSITE_GOAL_BINDING_CHANGED'):
        compile_tree_packet(replace(context,tree=tree),TableSnapshot(doc),packet)
