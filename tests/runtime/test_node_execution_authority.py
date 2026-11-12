"""Offline historical counterexamples through real Admission and authority."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import pytest

from cgkn.state import FileRunStore
from cgkn.agent.project_agent import AdmissionPolicy, ProjectProposal
from cgkn.orchestration.capability_tree import CapabilityTree, CapabilityNode
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.runtime.node_authority import ExecutionAuthority, file_hash
from cgkn.adapters.veriarbor import capability_adapter as adapter
from veriarbor.capability import CapabilityContract, Observation
from veriarbor.model import Evidence
from veriarbor.execution_authority import (CriticalCheckSpec, CriticalCheckRegistry,
    DecisionRecord, NodeExecutionResult)


def setup_authority(tmp_path, *, status=None, missing=False, unknown_policy='BLOCK', commit=True, quote="I'm playing this game", domain='filesystem', budget_state='OK'):
    store=FileRunStore(tmp_path/'runs')
    registry=CriticalCheckRegistry()
    def check(decisions,context):
        if status:return status
        # This deliberately small fixture checker reads bound evidence, not a
        # worker's assertion that the citation exists or its claimed verdict.
        for d in decisions:
            for ref in d.input_refs:
                if ref not in context['permit']['input_hashes']:return 'UNKNOWN'
                quote=Path(ref).read_text(encoding='utf-8')
                if "play this person's music" in quote:return 'FAIL'
                if "I'm playing this game" not in quote:return 'UNKNOWN'
        return 'PASS'
    if not missing:registry.register('fixture.gameplay',check)
    authority=ExecutionAuthority(store,'p','r',registry=registry)
    contract=CapabilityContract('habit@1','Ground habit classifications',evidence_requirements={'allow_imported_unmanaged':True},critical_checks=(
        CriticalCheckSpec('gameplay','transcript→habit','fixture.gameplay',unknown_policy=unknown_policy),))
    leaf=build_leaf_contract(goal='Inspect fixture',kind='INSPECTION',scope=['probe/child'],
        acceptance=['probe_observation'],checker='fixture.probe',output_identity='probe/child',
        effect_domains=[domain],executor='fake@1',dependencies=[],
        subject='probe/child',expected_observation='node identity',pass_fail_rule='independent observation')
    source=tmp_path/'quote.txt';source.write_text(quote,encoding='utf-8')
    catalog={'habit@1':{'executor_ref':'fake@1','config':{'leaf_contract':leaf,'input_paths':[str(source)]}}}
    proposal=ProjectProposal('p1','p',1,'root',(),({'operation':'add_node','node_id':'child',
        'parent_id':'root','capability_ref':'habit@1'},),reason_summary='bounded test',
        target_capability_id='habit@1',strategy_capabilities=('habit@1',),
        exploration_reason='historical fixture',exploration_budget=1,exploration_measure='check outcome')
    policy=AdmissionPolicy(project_id='p',capability_contracts={'habit@1':asdict(contract)},allow_remote_effects=(domain=='external_network'),
                           execution_budget={'calls':1},budget_state=budget_state)
    tree=CapabilityTree('root',(CapabilityNode('root'),))
    aid,admitted=authority.admit(tree,1,proposal,known_capabilities={'habit@1'},catalog=catalog,policy=policy)
    if budget_state=='BLOCKED':
        assert not admitted.valid and admitted.code=='BUDGET_BLOCKED'
        return authority,contract,tree,aid
    assert admitted.valid,admitted.code
    if commit:tree=authority.commit_tree(aid)
    return authority,contract,tree,aid


def execute(a,c,tmp_path,quote="I'm playing this game",**permit_options):
    source=tmp_path/'quote.txt';source.write_text(quote,encoding='utf-8')
    p=a.issue_permit(node_id='child',contract=c,input_hashes={str(source):file_hash(source)},**permit_options)
    a.begin_node_execution(p.permit_id)
    out=a.staging_dir(p.permit_id)/'habit.json';out.write_text('{"category":"CONTENT_GAMEPLAY"}',encoding='utf-8')
    d=DecisionRecord('decision1','transcript→habit','fixture',input_refs=(str(source),),
                     output_value='CONTENT_GAMEPLAY',output_claim='recurring gaming behavior',
                     evidence_refs=(str(source),),check_id='gameplay',metadata={'worker_says_checks_passed':True})
    a.submit_node_result(NodeExecutionResult(p.permit_id,{str(out):file_hash(out)},('filesystem',),
        (d,), (str(source),),{},dict(p.input_hashes)))
    return p,out


def test_rejected_and_uncommitted_admission(tmp_path):
    a,c,tree,aid=setup_authority(tmp_path,commit=False)
    with pytest.raises(ValueError,match='TREE_COMMIT_REQUIRED'):a.issue_permit(node_id='child',contract=c)
    with pytest.raises(ValueError,match='ADMISSION_REQUIRED'):a.commit_tree('rejected-or-forged')
    tree=a.commit_tree(aid)
    assert a.issue_permit(node_id='child',contract=c).status=='ACTIVE'


@pytest.mark.parametrize('key,value',[('node_id','wrong'),('capability_id','wrong'),('tree_version',99),
    ('contract_hash','wrong'),('input_hashes',{'wrong':'hash'}),('run_id','other'),('project_id','other')])
def test_permit_mismatch(tmp_path,key,value):
    a,c,_,_=setup_authority(tmp_path);p=a.issue_permit(node_id='child',contract=c)
    with pytest.raises(ValueError,match='BINDING_REJECT'):a.validate_permit(p.permit_id,**{key:value})


def test_scope_budget_effect_no_transport(tmp_path):
    a,c,_,_=setup_authority(tmp_path)
    with pytest.raises(ValueError,match='BUDGET'):a.issue_permit(node_id='child',contract=c,budget_scope={'calls':2})
    with pytest.raises(ValueError,match='UNAUTHORIZED_EFFECT'):a.issue_permit(node_id='child',contract=c,allowed_effects=('external_network',))
    p=a.issue_permit(node_id='child',contract=c,allowed_effects=('filesystem',));a.begin_node_execution(p.permit_id)
    calls=[]
    with pytest.raises(ValueError,match='UNAUTHORIZED_EFFECT'):
        a.perform_effect(p.permit_id,'PROVIDER_CALL',lambda:calls.append('transport'))
    assert calls==[]
    with pytest.raises(ValueError,match='REVOKED'):a.begin_node_execution(p.permit_id)


def test_positive_receipt_parent_acceptance_and_projection(tmp_path):
    a,c,_,_=setup_authority(tmp_path);p,out=execute(a,c,tmp_path)
    r=a.commit_node_execution(p.permit_id)
    assert a._permit(p.permit_id).status=='CONSUMED'
    with pytest.raises(ValueError,match='CONSUMED'):a.begin_node_execution(p.permit_id)
    assert a.validate_receipt(r.receipt_id,output_path=str(out),output_hash=file_hash(out))==r
    v=a.node_view('child')
    assert v['state']=='COMMITTED' and v['decision_records'] and v['critical_check_results'][0]['status']=='PASS'
    assert v['gate_status']['utility_status']==v['gate_status']['generalization_status']=='NOT_TESTED'
    e=Evidence('VERIFIED',{}, {}, (),scope={'PROJECT':'p'})
    adapter.bind_inputs(a.store,'p','r','parent',[dict(artifact_path=str(out),commit_receipt_id=r.receipt_id,
        requirements={'consumer':'parent'},evidence=asdict(e))])
    assert adapter.validate_inputs(a.store,'p','r','parent')=='VALID'
    def obs():
        return Observation(True,Evidence('VERIFIED',{'x':'1'},{'c':'1'},('fixture',),qualified=True,
            scope={'PROJECT':'p','CAPABILITY':c.capability_id},context={'contract_hash':c.fingerprint}))
    gates=adapter.record_acceptance(a.store,'p','r','child',c,{'implemented':obs(),'executed':obs()},
        object_versions={'x':'1'},checker_versions={'c':'1'},strategy_capabilities=('habit@1',),commit_receipt_id=r.receipt_id)
    assert gates.semantic_status=='PASS'
    assert gates.utility_status==gates.generalization_status=='NOT_TESTED'
    out.write_text('tampered',encoding='utf-8')
    assert 'OUTPUT_BINDING_REJECT' in adapter.validate_inputs(a.store,'p','r','parent')


@pytest.mark.parametrize('status,missing,quote',[('FAIL',False,"I'm playing this game"),
    ('UNKNOWN',False,"I'm playing this game"),(None,True,"I'm playing this game"),
    (None,False,"I want to play this person's music")])
def test_semantic_block_and_quarantine(tmp_path,status,missing,quote):
    a,c,_,_=setup_authority(tmp_path,status=status,missing=missing)
    p,out=execute(a,c,tmp_path,quote)
    with pytest.raises(ValueError,match='CRITICAL_CHECK_BLOCKED'):a.commit_node_execution(p.permit_id)
    v=a.node_view('child')
    assert out.exists() and v['state']=='BLOCKED' and v['output_state']=='QUARANTINED'
    assert v['decision_records'] and v['evidence_refs'] and v['violations']
    assert not v['commit_receipt_id'] and v['gate_status']['semantic_status']!='PASS'
    assert not [e for e in a.events() if e['event_type']=='NODE_COMMITTED']


def test_unknown_warning_and_required_missing_checker(tmp_path):
    a,c,_,_=setup_authority(tmp_path,status='UNKNOWN',unknown_policy='ALLOW_WITH_WARNING')
    p,_=execute(a,c,tmp_path);r=a.commit_node_execution(p.permit_id)
    assert r.gate_snapshot['semantic_status']=='UNKNOWN'
    assert a.node_view('child')['warnings']
    assert a.validate_receipt(r.receipt_id)


def test_physical_bypass_fake_receipt_and_acceptance(tmp_path):
    a,c,_,_=setup_authority(tmp_path)
    out=tmp_path/'fake.txt';out.write_text('already existed')
    adapter.bind_inputs(a.store,'p','r','parent',[dict(artifact_path=str(out),commit_receipt_id='fake',
        requirements={'consumer':'parent'},evidence=asdict(Evidence('VERIFIED',{}, {}, (),scope={'PROJECT':'p'})))])
    assert adapter.validate_inputs(a.store,'p','r','parent')=='COMMIT_RECEIPT_REQUIRED'
    with pytest.raises(ValueError,match='RECEIPT_ID_REQUIRED'):a.validate_receipt({'receipt_id':'fake'})
    with pytest.raises(ValueError,match='RECEIPT_ID_REQUIRED'):
        adapter.record_acceptance(a.store,'p','r','child',c,{},object_versions={},checker_versions={},strategy_capabilities=())
    a.import_unmanaged('old',{str(out):file_hash(out)})
    assert a.node_view('old')['governed_execution'] is False
    assert a.node_view('old')['commit_receipt_id'] is None


def test_posthoc_output_cannot_be_adopted(tmp_path):
    a,c,_,_=setup_authority(tmp_path,status='PASS')
    out=tmp_path/'old.txt';out.write_text('old output')
    p=a.issue_permit(node_id='child',contract=c,output_paths=(str(out),));a.begin_node_execution(p.permit_id)
    d=DecisionRecord('d','transcript→habit','test',check_id='gameplay')
    a.submit_node_result(NodeExecutionResult(p.permit_id,{str(out):file_hash(out)},decision_records=(d,)))
    with pytest.raises(ValueError,match='POST_HOC_OUTPUT_REJECT'):a.commit_node_execution(p.permit_id)


def test_retry_epoch_revocation_and_tree_tamper(tmp_path):
    a,c,tree,_=setup_authority(tmp_path)
    p=a.issue_permit(node_id='child',contract=c);a.revoke_permit(p.permit_id)
    p2=a.issue_permit(node_id='child',contract=c)
    assert p2.execution_epoch==2 and p2.permit_id!=p.permit_id
    path=a.store.run_dir('p','r')/'capability_tree.json'
    path.write_text('{}')
    with pytest.raises(ValueError,match='UNMANAGED_TREE_MUTATION'):a.validate_tree(tree)


def test_expired_permit(tmp_path):
    a,c,_,_=setup_authority(tmp_path)
    p=a.issue_permit(node_id='child',contract=c,expires_at='2000-01-01T00:00:00+00:00')
    with pytest.raises(ValueError,match='EXPIRED'):a.begin_node_execution(p.permit_id)


def test_events_are_truth_projection_is_rebuildable(tmp_path):
    a,c,_,_=setup_authority(tmp_path);p,_=execute(a,c,tmp_path);a.commit_node_execution(p.permit_id)
    (a.root/'nodes'/'child.json').write_text('{}')
    assert a.node_view('child')['state']=='COMMITTED'
    reloaded=ExecutionAuthority(a.store,'p','r')
    assert reloaded.node_view('child')==a.node_view('child')


def test_missing_checker_blocks_even_allow_warning(tmp_path):
    a,c,_,_=setup_authority(tmp_path,missing=True,unknown_policy='ALLOW_WITH_WARNING')
    p,_=execute(a,c,tmp_path)
    with pytest.raises(ValueError,match='CRITICAL_CHECK_BLOCKED'):a.commit_node_execution(p.permit_id)


def make_runner(a):
    from cgkn.executors import ExecutorRegistry, ExecutorDescriptor
    from cgkn.execution import BlockExecutionResult, BlockStatus
    from cgkn.execution.deliverables import SubjectDeliverableChecker
    from cgkn.runtime import DAGRunner
    from cgkn.state.task_feedback import digest
    class Fake:
        descriptor=ExecutorDescriptor('fake@1','deterministic',('habit@1',))
        calls=0
        def execute(self,request):
            self.calls+=1
            p=request.metadata['node_execution_permit']
            d=DecisionRecord('d','transcript→habit','fixture',input_refs=tuple(p['input_hashes']),
                output_value='CONTENT_GAMEPLAY',evidence_refs=tuple(p['input_hashes']),check_id='gameplay')
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,
                attempt_id=request.attempt_id,node_id=request.node_id,executor_ref=request.executor_ref,
                status=BlockStatus.SUCCEEDED,outputs={'node':request.node_id},metadata={'decision_records':[d.as_dict()]})
    fake=Fake();registry=ExecutorRegistry();registry.register(fake)
    def checked(request,c):
        out=request.input_values['execution_receipt']['outputs']
        return {'passed':out.get('node')==request.node_id,'observed':dict(out),
                'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}
    registry.register(SubjectDeliverableChecker(lambda c:{s:digest(s) for s in c['target_scope']},
                                               {'probe_observation':checked}))
    return DAGRunner(registry,a.store,deliverable_checkers={'fixture.probe':'deliverable.subjects@1'},
                     critical_check_registry=a.registry),fake


@pytest.mark.parametrize('quote,success',[("I'm playing this game",True),("I want to play this person's music",False)])
def test_governed_dag_integration_and_cache(tmp_path,quote,success):
    from cgkn.orchestration.execution_dag import compile_tree
    a,c,tree,_=setup_authority(tmp_path,quote=quote);runner,fake=make_runner(a)
    summary=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    assert (summary.status=='SUCCEEDED')==success, a.store.load_result('p','r','child').as_dict()
    assert fake.calls==1

    v=a.node_view('child')
    assert bool(v['commit_receipt_id'])==success
    types=[e['event_type'] for e in a.events()]
    assert types.index('TREE_COMMITTED')<types.index('NODE_PERMIT_ISSUED')<types.index('NODE_EXECUTION_STARTED')
    if success:
        cached=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
        assert cached.reused_nodes==('child',) and fake.calls==1
        receipt=a.validate_receipt(v['commit_receipt_id'])
        Path(next(iter(receipt.output_hashes))).write_text('tampered')
        with pytest.raises(ValueError,match='OUTPUT_BINDING_REJECT'):
            runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
    else:
        assert v['state']=='BLOCKED' and v['output_state']=='QUARANTINED'


def test_subprocess_serialized_permit_host_commit(tmp_path):
    import sys
    a,c,_,_=setup_authority(tmp_path,status='PASS',domain='local_process')
    p=a.issue_permit(node_id='child',contract=c)
    program="""
import json,os,pathlib,hashlib
p=json.loads(pathlib.Path(os.environ['NODE_EXECUTION_PERMIT']).read_text())
result=pathlib.Path(os.environ['NODE_EXECUTION_RESULT'])
out=result.parent/'out.txt';out.write_text('child output')
result.write_text(json.dumps(dict(permit_id=p['permit_id'],input_hashes=p['input_hashes'],
 output_hashes={str(out):hashlib.sha256(out.read_bytes()).hexdigest()},effects_used=['local_process'],
 decision_records=[dict(decision_id='child-d',semantic_transform='transcript→habit',strategy_id='fixture',check_id='gameplay')],
 evidence_refs=[str(out)],resource_usage={})))
"""
    a.run_subprocess(p.permit_id,[sys.executable,'-c',program])
    assert not a.node_view('child')['commit_receipt_id']
    receipt=a.commit_node_execution(p.permit_id)
    assert a.validate_receipt(receipt.receipt_id)


def test_standard_effect_guard_checks_before_fake_transport(tmp_path):
    from cgkn.execution.node_effects import guard_effect, execution_scope
    from cgkn.execution import BlockExecutionRequest,TaskContext
    a,c,_,_=setup_authority(tmp_path,domain='external_network',status='PASS')
    p=a.issue_permit(node_id='child',contract=c);a.begin_node_execution(p.permit_id)
    request=BlockExecutionRequest(project_id='p',run_id='r',node_id='child',attempt_id='a',
        component_ref='habit@1',executor_ref='fake@1',task_context=TaskContext('fixture',{}),
        metadata={'execution_mode':'GOVERNED','node_execution_permit':p.as_dict()})
    calls=[]
    def fake_transport():
        guard_effect(request,'PROVIDER_CALL',resource_usage={'calls':1})
        calls.append('fake')
    with pytest.raises(ValueError,match='AUTHORITY_REQUIRED'):fake_transport()
    with execution_scope(a,p.permit_id):
        fake_transport()
        with pytest.raises(ValueError,match='BUDGET_SCOPE_REJECT'):fake_transport()
    assert calls==['fake']


def test_standard_file_executor_cannot_write_without_authority(tmp_path):
    from cgkn.executors import FileExecutor
    from cgkn.execution import BlockExecutionRequest,TaskContext
    request=BlockExecutionRequest(project_id='p',run_id='r',node_id='n',attempt_id='a',
        component_ref='file@1',executor_ref='local.file@1',
        task_context=TaskContext('write',{'action':'write_file','path':'forbidden','content':'x'}))
    result=FileExecutor(tmp_path).execute(request)
    assert not result.succeeded and not (tmp_path/'forbidden').exists()
    assert 'AUTHORITY_REQUIRED' in result.error.message


def test_actual_rejected_admission_cannot_commit_or_issue(tmp_path):
    a,c,t,_=setup_authority(tmp_path)
    proposal=ProjectProposal('bad','p',2,'root',(),({'operation':'add_node','node_id':'bad',
        'capability_ref':'not.registered'},),reason_summary='reject fixture')
    aid,result=a.admit(t,2,proposal,known_capabilities={'habit@1'},catalog={},policy=AdmissionPolicy())
    assert not result.valid
    with pytest.raises(ValueError,match='ADMISSION_REQUIRED'):a.commit_tree(aid)
    with pytest.raises(ValueError,match='NODE_NOT_ADMITTED'):a.issue_permit(node_id='bad',contract=c)


@pytest.mark.parametrize('target',['input','output'])
def test_tamper_before_commit_quarantines(tmp_path,target):
    a,c,_,_=setup_authority(tmp_path);p,out=execute(a,c,tmp_path)
    (tmp_path/'quote.txt' if target=='input' else out).write_text('changed')
    with pytest.raises(ValueError,match='BINDING_REJECT'):a.commit_node_execution(p.permit_id)
    assert a.node_view('child')['output_state']=='QUARANTINED'


def test_existing_citation_is_not_semantic_support(tmp_path):
    a,c,_,_=setup_authority(tmp_path);p,_=execute(a,c,tmp_path,"I want to play this person's music")
    assert (tmp_path/'quote.txt').exists()
    with pytest.raises(ValueError,match='CRITICAL_CHECK_BLOCKED'):a.commit_node_execution(p.permit_id)
    v=a.node_view('child')
    assert v['decision_records'][0]['output_claim']=='recurring gaming behavior'
    assert v['critical_check_results'][0]['status']=='FAIL'


def test_missing_decision_and_new_epoch_invalidate_old_receipt(tmp_path):
    a,c,_,_=setup_authority(tmp_path)
    p,_=execute(a,c,tmp_path);r=a.commit_node_execution(p.permit_id)
    p2=a.issue_permit(node_id='child',contract=c);a.begin_node_execution(p2.permit_id)
    with pytest.raises(ValueError,match='STALE_EXECUTION_EPOCH'):a.validate_receipt(r.receipt_id)
    a.submit_node_result(NodeExecutionResult(p2.permit_id,{}))
    with pytest.raises(ValueError,match='CRITICAL_CHECK_BLOCKED'):a.commit_node_execution(p2.permit_id)


def test_imported_input_scope_stays_unmanaged(tmp_path):
    a,c,_,_=setup_authority(tmp_path)
    raw=tmp_path/'old.txt';raw.write_text('historical')
    e=Evidence('VERIFIED',{}, {}, (),scope={'PROJECT':'p'})
    binding=dict(artifact_path=str(raw),execution_mode='IMPORTED_UNMANAGED',requirements={'consumer':'inspect'},evidence=asdict(e))
    adapter.bind_inputs(a.store,'p','r','parent',[binding])
    assert adapter.validate_inputs(a.store,'p','r','parent')=='IMPORTED_INPUT_NOT_ALLOWED'
    adapter.bind_inputs(a.store,'p','r','parent',[binding],contract=c)
    assert adapter.validate_inputs(a.store,'p','r','parent')=='VALID'
    assert adapter.load(a.store,'p','r')['nodes']['parent']['input_bindings'][0]['execution_mode']=='IMPORTED_UNMANAGED'


def test_receipt_cannot_be_attached_to_changed_worker_output(tmp_path):
    from cgkn.orchestration.execution_dag import compile_tree
    a,c,tree,_=setup_authority(tmp_path);runner,_=make_runner(a)
    runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    saved=a.store.load_result('p','r','child')
    forged=replace(saved,outputs={'goal_check':{'verdict':'VERIFIED'}})
    with pytest.raises(ValueError,match='OUTPUT_BINDING_REJECT'):a.validate_execution_result(forged)


def test_goal_acceptance_rejects_receiptless_and_legacy_reopen(tmp_path):
    from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
    from cgkn.state.acceptance import identity
    from cgkn.execution import BlockExecutionResult,BlockStatus
    a,c,tree,_=setup_authority(tmp_path)
    requirements={'R':{'must':True}};checkers={'check':'fake@1'}
    legacy=GoalAcceptance(a.store,'p','r',requirements,checkers,execution_mode='LEGACY')
    legacy.bind_subjects({'quote':'v1'})
    plan={'phases':[{'id':'phase','outcome':'checked','depends_on':[]}],
          'goals':[{'id':'g','phase_id':'phase','requirement_refs':['R'],'acceptance':'supported',
                    'subject_refs':['quote'],'checker':'check','task_refs':['child']}]}
    legacy.commit(legacy.propose(plan,tree))
    result=BlockExecutionResult(project_id='p',run_id='r',node_id='child',attempt_id='a',
        executor_ref='fake@1',status=BlockStatus.SUCCEEDED,outputs={'goal_check':{
            'goal_id':'g','condition_hash':identity('supported'),'subjects':{'quote':'v1'},
            'execution':'VALID','evidence_refs':['old'],'observed':'legacy fixture','verdict':'VERIFIED'}})
    a.store.save_result(result)
    legacy.record('g',result,executor_ref='fake@1')
    governed=GoalAcceptance(a.store,'p','r',requirements,checkers)
    with pytest.raises(ValueError,match='RECEIPT_ID_REQUIRED'):governed.record('g',result,executor_ref='fake@1')
    assert governed.view()['goals'][0]['verdict']!='VERIFIED'
    assert legacy.data['checks']  # retained, never rewritten as governed


def test_blocked_budget_cannot_issue_resource_allowance(tmp_path):
    a,c,_,aid=setup_authority(tmp_path,budget_state='BLOCKED',domain='external_network')
    with pytest.raises(ValueError,match='ADMISSION_REQUIRED'):a.commit_tree(aid)
    with pytest.raises(ValueError,match='TREE_COMMIT_REQUIRED'):
        a.issue_permit(node_id='child',contract=c,budget_scope={'calls':1})


def test_update_config_cannot_expand_remote_effects(tmp_path):
    a,c,tree,_=setup_authority(tmp_path)
    cfg=tree.by_id['child'].as_dict()['config'];cfg['leaf_contract']['effect_domains']=['external_network']
    proposal=ProjectProposal('update','p',2,'root',(),({'operation':'update_config','node_id':'child','config':cfg},),
                             reason_summary='try forbidden remote effect')
    aid,result=a.admit(tree,2,proposal,known_capabilities={'habit@1'},catalog={},
        policy=AdmissionPolicy(allowed_effect_domains=frozenset({'external_network'}),allow_remote_effects=False))
    assert not result.valid and result.code=='UNAUTHORIZED_EFFECT'
    with pytest.raises(ValueError,match='ADMISSION_REQUIRED'):a.commit_tree(aid)


@pytest.mark.parametrize('progress_enabled',[False,True])
def test_default_session_issues_permit_through_same_authority(tmp_path,progress_enabled):
    from cgkn.agent.project_loop import ProjectSession
    from cgkn.agent.composer import AgentDecision
    from cgkn.orchestration.tree_edits import TreeEdit
    a,c,tree,_=setup_authority(tmp_path)
    # A separate run starts empty; do not reclassify the fixture run.
    cfg=tree.by_id['child'].as_dict()['config']
    catalog={'habit@1':{'executor_ref':'fake@1','config':cfg}}
    policy=AdmissionPolicy(project_id='p',capability_contracts={'habit@1':asdict(c)})
    claim=dict(target_capability_id='habit@1',strategy_capabilities=('habit@1',),
        exploration_reason='bounded test',exploration_budget=1,exploration_measure='semantic outcome')
    class Composer:
        def decide(self,context):
            return AgentDecision('decision','inspect','bounded fixture',
                (TreeEdit('edit','add_node','child',{'capability_ref':'habit@1','config':cfg},provenance={'source':'fixture'}),),
                True,False,False,'',{},'fixture',0,decision_audit={'capability_claim':claim})
    runner,fake=make_runner(a)
    from cgkn.agent.progress import ExecutionProgressController
    session=ProjectSession(Composer(),runner,a.store,known_capabilities={'habit@1'},worker_model='fake',
                           capability_catalog=catalog,admission_policy=policy,max_decisions=1,
                           progress_controller=ExecutionProgressController() if progress_enabled else None)
    session.run(project_id='p',run_id='session',goal='root')
    b=ExecutionAuthority(a.store,'p','session')
    assert b.node_view('child')['state']=='COMMITTED',b.events()
    assert fake.calls==1
    observations=[e for e in a.store.load_events('p','session') if e.event_type=='PROGRESS_OBSERVATION']
    assert bool(observations)==progress_enabled
