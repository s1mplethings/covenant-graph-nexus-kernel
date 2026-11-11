import hashlib
from types import SimpleNamespace
import pytest
from cgkn.agent.composer import AgentComposer,AgentDecisionContext
from cgkn.orchestration import CapabilityTree
from cgkn.protocol.declaration import MilestoneContractCompiler
from cgkn.protocol.compiler import compile_planner
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.repair import plain
from cgkn.execution.materialization import stage_file_worker
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.executors.llm import BoundedFileActions
from tests.protocol.test_milestone_declaration import semantic

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def context(status='VERIFIED'):
    design,registry,receipt=MilestoneContractCompiler().compile(semantic(),source_ref='public-decision',requirement_refs=['next'],namespace='next',checker_ref='consumer',artifact_subject=True)
    dep='upstream.py';digest=hashlib.sha256(b'value = 7\n').hexdigest()
    contract=dict(design=design,registry=registry,compilation=receipt,dependency_artifacts=[dep],dependency_goal_ids=['upstream-goal'])
    view={'goals':[{'id':'upstream-goal','verdict':status,'acceptance':'prior independent behavior','subject_refs':[dep]},
        {'id':'current','verdict':'INSUFFICIENT_EVIDENCE','acceptance':'current behavior','subject_refs':[design['artifacts'][0]['path'],dep],'checker':'measure','milestone_contract':contract}],
        'checker_bindings':{'measure':'consumer'},'subject_identities':{dep:digest}}
    catalog={'code':{'executor_ref':'llm.cheap@1','checker_ref':'source','acceptance':['source'],'effect_domains':['source'],'semantic_task_kinds':[2,3]}}
    return AgentDecisionContext('p','r','implement next',1,CapabilityTree('implement next',()),tuple(catalog),catalog,{}, {},goal_acceptance=view),dep,digest

def compile_context(ctx):
    t=AgentComposer._milestone_snapshot(ctx)
    p=dict(action=1,task_kind=2,target=0,scope=[0],deps=[],goal='Implement public next module',expected=['public source'],accept=['public source'])
    return plain(compile_planner(p,t,bound_hash=t.hash,tree=ctx.tree,context_identity='decision')['edits'][0].payload['config']['leaf_contract']),t

def test_declared_verified_dependency_reaches_real_staged_worker_read_only(tmp_path):
    ctx,dep,digest=context();contract,t=compile_context(ctx)
    assert contract['read_scope']==[dep] and contract['read_subjects']=={dep:digest}
    assert dep not in contract['target_scope']
    root=tmp_path/'live';root.mkdir();(root/dep).write_bytes(b'value = 7\n')
    worker,checker,_=stage_file_worker(SimpleNamespace(actions=BoundedFileActions(root)),FileDeliverableChecker(root,{}),contract,tmp_path/'staged')
    assert worker.actions.root.joinpath(dep).read_bytes()==b'value = 7\n'
    from cgkn.protocol.context_pack import worker_contract_pack
    # Existing Worker derives its numeric readable/writable table from this leaf.
    assert contract['target_scope']==[t.document['scopes'][0]['path']]
    assert (root/dep).read_bytes()==b'value = 7\n'

@pytest.mark.parametrize('status',['FAILED','INSUFFICIENT_EVIDENCE'])
def test_unverified_dependency_cannot_grant_reads(status):
    ctx,_,_=context(status)
    with pytest.raises(ContractError,match='MILESTONE_DEPENDENCY_NOT_READY'):compile_context(ctx)

@pytest.mark.parametrize('mode',['missing','tampered'])
def test_dependency_identity_checked_before_worker(tmp_path,mode):
    ctx,dep,_=context();contract,_=compile_context(ctx);root=tmp_path/'live';root.mkdir()
    if mode=='tampered':(root/dep).write_bytes(b'value = 99\n')
    with pytest.raises(ValueError,match='verified dependency input changed'):
        stage_file_worker(SimpleNamespace(actions=BoundedFileActions(root)),FileDeliverableChecker(root,{}),contract,tmp_path/'staged')

def test_unrelated_subject_is_not_injected():
    ctx,dep,_=context();ctx.goal_acceptance['subject_identities']['unrelated.py']='f'*64
    contract,_=compile_context(ctx)
    assert contract['read_scope']==[dep]



def test_real_worker_protocol_exposes_dependency_as_readable_not_writable():
    import json
    from cgkn.protocol.adapters import SemanticWorkerClient
    from cgkn.providers import ModelRoleConfig,ProviderCompletion
    ctx,dep,_=context();table=AgentComposer._milestone_snapshot(ctx)
    packet=dict(action=1,task_kind=2,target=0,scope=[0],deps=[],goal='Implement next module',expected=['public source'],accept=['public source'])
    config=plain(compile_planner(packet,table,bound_hash=table.hash,tree=ctx.tree,context_identity='wire')['edits'][0].payload['config'])
    seen=[]
    class Client:
        def complete(self,**kw):
            request=json.loads(kw['user']);seen.append(request)
            row=next(r for r in request['tables']['paths'] if r['path']==dep)
            assert row['readable'] and not row['writable']
            return ProviderCompletion(json.dumps({'op':0,'path':row['id']}),'fake','fake',{})
    raw={'config':config,'node_id':'n','goal':config['leaf_contract']['leaf_goal'],'observations':[]}
    response=SemanticWorkerClient(Client(),lambda e:None).complete(user=json.dumps(raw),config=ModelRoleConfig('worker','fake'))
    assert seen and dep in response.text
