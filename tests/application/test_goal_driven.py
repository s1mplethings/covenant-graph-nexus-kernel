import json
import pytest
from pathlib import Path
from cgkn.application.goal_driven import build_session,digest_file
from cgkn.providers import ProviderCompletion
from cgkn.execution.node_effects import perform_scoped_effect,require_provider_context

def test_goal_links_survive_normalization_and_invalid_references_fail(tmp_path):
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    from dataclasses import replace
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    gap={'gap_id':'g1','goal_id':'root','metric_id':'file-present','target':1,'current':0,'capability_ids':['project.x@1']}
    session.admission_policy=replace(session.admission_policy,goal_gaps={'g1':gap})
    context=AgentDecisionContext('goal-test','one',config['root_goal'],1,CapabilityTree('g',()),(),{}, {},{})
    value={'reason':'specific observed missing file','edits':[{'node_id':'x','operation':'add_node','payload':{'capability_ref':'project.x@1','config':{'executor_ref':'local.file@1','goal':'inspect missing output','action':'list_files','path':'.'}}}],
        'decision_audit':{'requirement_refs':['R1'],'facts':['file absent'],'expected_improvement':'inspect actual files','capability_claim':{'target_gap_id':'g1','target_capability_id':'project.x@1','strategy_capabilities':['project.x@1']}}}
    normalized=session.composer._normalize_decision(value,context)
    assert normalized['decision_audit']==value['decision_audit']
    value['decision_audit']['capability_claim']['target_gap_id']='foreign'
    with pytest.raises(ValueError,match='cross-project'):session.composer._normalize_decision(value,context)
    value['decision_audit']['capability_claim']['target_gap_id']='g1';value['decision_audit']['requirement_refs']=['missing']
    with pytest.raises(ValueError,match='requirement_refs'):session.composer._normalize_decision(value,context)

def test_gap_view_keeps_goal_and_separates_available_audio(tmp_path):
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    config=configuration(tmp_path);config['feedback']=[{'source':'user','text':'disliked previous result'}]
    config['evidence_catalog']=[{'type':'audio','status':'AVAILABLE_NOT_MODEL_HEARD'}]
    session,_=build_session(config,tmp_path/'run',Fake())
    context=AgentDecisionContext('goal-test','one',config['root_goal'],1,CapabilityTree('g',()),(),{}, {},{})
    prepared=session.composer.prepare_context(context)
    assert prepared.goal==context.goal
    assert prepared.task_feedback['user_feedback']==config['feedback']
    assert prepared.task_feedback['goal_gap_view'][0]['user_feedback_ref']=='task_feedback.user_feedback'
    assert prepared.task_feedback['evidence_catalog'][0]['status']=='AVAILABLE_NOT_MODEL_HEARD'
    from dataclasses import replace
    read=replace(context,execution_results={'read':{'outputs':{'path':'evidence.json','content':'actual signal evidence'}}})
    assert session.composer.prepare_context(read).execution_results['read']['outputs']['content']=='actual signal evidence'

def configuration(tmp_path):
    workspace=tmp_path/'product';workspace.mkdir()
    checker=tmp_path/'checker.py'
    checker.write_text("import argparse,json,pathlib\np=argparse.ArgumentParser();p.add_argument('--workspace');a=p.parse_args();f=pathlib.Path(a.workspace)/'answer.txt';print(json.dumps({'requirements':{'R1':f.is_file() and f.read_text()=='hello'},'observation':'exact independent bytes'}))",encoding='utf-8')
    return {'project_id':'goal-test','run_id':'one','root_goal':'Deliver a reusable hello text file',
        'requirements':{'R1':'answer.txt contains exactly hello'},'inputs_and_workspace':{'workspace':str(workspace),'inputs':[]},
        'completion':{'checker_path':str(checker),'checker_sha256':digest_file(checker)},
        'resource_and_effect_limits':{'models':{'planner':{'model':'qwen','model_id':'offline-planner'},'worker':{'model':'qwen','model_id':'offline-worker'}},'max_calls_per_leaf':2,'max_planning_decisions':8}}

@pytest.mark.parametrize('reference',['requirement_field','requirement_alias','registered_gap'])
def test_host_compiles_exact_requirement_gap_without_false_failure(tmp_path,reference):
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    before=session.acceptance.view()
    bindings=session.composer.requirement_gap_bindings();gid=bindings['R1']['gap_id']
    audit={'requirement_refs':['R1'],'capability_claim':{}}
    if reference!='requirement_field':audit['capability_claim']['target_gap_id']='R1' if reference=='requirement_alias' else gid
    value={'edits':[{'node_id':'read','operation':'add_node','payload':{'capability_ref':'project.read@1','config':{'executor_ref':'local.file@1','goal':'inspect actual files','action':'list_files','path':'.'}}}], 'decision_audit':audit}
    context=AgentDecisionContext('goal-test','one',config['root_goal'],1,CapabilityTree('g',()),(),{}, {},{})
    result=session.composer._normalize_decision(value,context)
    assert result['decision_audit']['capability_claim']['target_gap_id']==gid
    assert result['edits'][0]['provenance']['goal_binding']['compiled_gap_id']==gid
    assert session.admission_policy.goal_gaps[gid]['current']==0
    assert session.acceptance.view()==before  # missing evidence does not manufacture FAILED
    assert 'project.read@1' in session.admission_policy.goal_gaps[gid]['capability_ids']

def test_gap_is_derived_when_missing_and_illegal_repeated_proposals_stop(tmp_path):
    config=configuration(tmp_path)
    class Invalid(Fake):
        def complete(self,**kw):
            response=super().complete(**kw)
            if kw['config'].role=='agent':
                value=json.loads(response.text);value['decision_audit']['capability_claim']={'target_gap_id':'foreign-R1'}
                return ProviderCompletion(json.dumps(value),response.model,response.request_id,response.usage,response.attempts)
            return response
    client=Invalid();session,scope=build_session(config,tmp_path/'run',client)
    assert not session.admission_policy.goal_gaps
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope)
    assert result.status=='BLOCKED' and 'NO_PROGRESS' in result.escalation_reason
    assert len(client.calls)==3 and not (Path(config['inputs_and_workspace']['workspace'])/'answer.txt').exists()
    assert session.admission_policy.goal_gaps and all(g['current']==0 for g in session.admission_policy.goal_gaps.values())

def test_real_admission_executes_requirement_linked_fixture(tmp_path):
    config=configuration(tmp_path)
    class Linked(Fake):
        def complete(self,**kw):
            response=super().complete(**kw)
            if kw['config'].role=='agent':
                value=json.loads(response.text);value['decision_audit']['requirement_refs']=['R1']
                return ProviderCompletion(json.dumps(value),response.model,response.request_id,response.usage,response.attempts)
            return response
    session,scope=build_session(config,tmp_path/'run',Linked())
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED',result.as_dict()
    assert session.store.load_result(config['project_id'],config['run_id'],'make-greeting').metadata['node_commit_receipt_id']

class Fake:
    def __init__(self):self.calls=[]
    def complete(self,**kw):
        authority,pid=require_provider_context();permit=authority.permit(pid)
        self.calls.append({'role':kw['config'].role,'node':permit.node_id,'permit':pid,'call_identity':kw.get('call_identity')})
        def response():
            context=json.loads(kw['user'])
            if kw['config'].role=='worker':
                value={'schema_version':'1.0','node_id':context['node_id'],'summary':'offline fixture only',
                    'actions':[{'action':'write_file','path':'answer.txt','content':'hello'}],
                    'expected_outputs':['answer.txt'],'confidence':1,'needs_escalation':False,'escalation_reason':''}
            else:
                produced=any(n.get('capability_ref')=='project.greeting@1' for n in context['tree']['nodes'])
                node='observe-result' if produced else 'make-greeting'
                executor='goal.acceptance@1' if produced else 'llm.cheap@1'
                cfg={'executor_ref':executor,'goal':'Check promised hello file' if produced else 'Create promised hello file'}
                if not produced:cfg.update(target_paths=['answer.txt'],read_paths=[])
                value={'schema_version':'1.0','decision_id':'d-'+node,'summary':'fixture context decision','reason':'unmet root requirement',
                    'edits':[{'edit_id':'e-'+node,'operation':'add_node','node_id':node,'payload':{'capability_ref':'project.rootcheck@1' if produced else 'project.greeting@1','parent_id':'','depends_on':['make-greeting'] if produced else [],'config':cfg},'provenance':{'offline_fixture':True}}],
                    'request_run':True,'finish':False,'needs_escalation':False,'escalation_reason':'',
                    'decision_audit':{'alternatives_considered':['wait for input','implement uncovered requirement'],'expected_outcome':'independent checker sees required bytes'}}
            return ProviderCompletion(json.dumps(value),kw['config'].model_id,'offline-'+str(len(self.calls)),{},1)
        return perform_scoped_effect('PROVIDER_CALL',response,resource_usage={'calls':1})

def test_new_project_capability_is_admitted_and_consumed(tmp_path):
    config=configuration(tmp_path);client=Fake();session,planning=build_session(config,tmp_path/'run',client)
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=planning,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED',result.as_dict()
    assert (Path(config['inputs_and_workspace']['workspace'])/'answer.txt').read_text()=='hello'
    assert 'project.greeting@1' in session.known_capabilities
    assert [x['role'] for x in client.calls]==['agent','worker','agent']
    assert client.calls[0]['node']=='__host_planning_root__' and client.calls[1]['node']=='make-greeting'
    assert session.store.load_result(config['project_id'],config['run_id'],'observe-result').metadata['node_commit_receipt_id']
    resumed,scope=build_session(config,tmp_path/'run',client)
    before=len(client.calls)
    result=resumed.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope,resume=True,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED' and len(client.calls)==before

def test_unknown_planner_is_not_replayed(tmp_path):
    import pytest
    config=configuration(tmp_path)
    class Lost:
        def complete(self,**kw):raise RuntimeError('simulated transport outcome unknown')
    session,planning=build_session(config,tmp_path/'run',Lost())
    with pytest.raises(RuntimeError,match='outcome unknown'):
        session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=planning)
    authority=session.runner._authority(config['project_id'],config['run_id'])
    assert any(e['event_type']=='NODE_PERMIT_ISSUED' and authority.permit(e['data']['permit_id']).status=='ACTIVE' for e in authority.events())

def test_read_only_tool_cannot_be_promoted_to_writer(tmp_path):
    import pytest
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    context=AgentDecisionContext('p','r','g',1,CapabilityTree('g',()),(),{}, {},{})
    value={'edits':[{'node_id':'x','operation':'add_node','payload':{'capability_ref':'project.x@1','config':{'executor_ref':'local.file@1','goal':'escape','action':'write_file','path':'inputs/source.json','content':'overwrite'}}}]}
    with pytest.raises(ValueError,match='configuration fields|read-only'):
        session.composer._normalize_decision(value,context)

def test_model_transport_is_supporting_grant_not_general_multi_domain_escape():
    import pytest
    from cgkn.orchestration.leaf_contract import build_leaf_contract
    common=dict(goal='bounded file',kind='IMPLEMENTATION',scope=['a.py'],acceptance=['local'],checker='files',
        output_identity='a',effect_domains=['filesystem','external_network'],expected_delta='file')
    assert build_leaf_contract(executor='llm.cheap@1',**common)['effect_domains']==['filesystem','external_network']
    with pytest.raises(ValueError,match='NEEDS_DECOMPOSITION'):
        build_leaf_contract(executor='local.file@1',**common)

def test_real_checker_feedback_drives_fixture_local_repair(tmp_path):
    class FeedbackFake(Fake):
        feedback_seen=False
        def complete(self,**kw):
            result=super().complete(**kw);value=json.loads(result.text);context=json.loads(kw['user'])
            if kw['config'].role=='worker':
                if not context['config'].get('goal','').startswith('Repair'):
                    value['actions'][0]['content']='wrong'
            elif any(n['id']=='observe-result' for n in context['tree']['nodes']):
                self.feedback_seen=context['goal_acceptance']['goals'][0]['verdict']=='FAILED'
                assert self.feedback_seen
                value.update(decision_id='repair-greeting',summary='fixture reacts to actual failed user-path observation',
                    reason='independent checker rejected current bytes',edits=[
                    {'edit_id':'repair-config','operation':'update_config','node_id':'make-greeting','payload':{'config':{'goal':'Repair hello file using failed exact-byte observation','verified_artifact_change_reason':'Root exact-byte checker FAILED; locally nonempty text was wrong'}},'provenance':{'offline_fixture':True}},
                    {'edit_id':'repair-retry','operation':'retry_node','node_id':'make-greeting','payload':{},'provenance':{'offline_fixture':True}}])
            from dataclasses import replace
            return replace(result,text=json.dumps(value))
    config=configuration(tmp_path);client=FeedbackFake();session,planning=build_session(config,tmp_path/'run',client)
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=planning,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED' and client.feedback_seen,result.as_dict()
    assert len(session.acceptance.data['checks'])==2
    assert [c['verdict'] for c in session.acceptance.data['checks']]==['FAILED','VERIFIED']
    attempts=session.store.run_dir(config['project_id'],config['run_id'])/'attempts/make-greeting'
    assert len(list(attempts.glob('*.json')))==2

def test_cli_denies_missing_authorization_without_creating_workspace(tmp_path):
    from scripts.run_goal_driven import main
    config=configuration(tmp_path);Path(config['inputs_and_workspace']['workspace']).rmdir()
    config['run_root']=str(tmp_path/'run');p=tmp_path/'goal.json';p.write_text(json.dumps(config))
    assert main(['start','--config',str(p)])==2
    assert not Path(config['run_root']).exists() and not Path(config['inputs_and_workspace']['workspace']).exists()

def test_cli_complete_and_resume_with_explicit_fake_transport(tmp_path,monkeypatch):
    from scripts.run_goal_driven import main
    import cgkn.providers
    from cgkn.providers import GatewayCompletionClient
    config=configuration(tmp_path);Path(config['inputs_and_workspace']['workspace']).rmdir()
    config['run_root']=str(tmp_path/'run');config['completion']['description']='exact hello byte observation'
    config['resource_and_effect_limits'].update(authorization_reference='OFFLINE_TEST_NOT_USER_APPROVAL',
        billing_mode='api_estimated_with_frozen_upper_rates',currency='TEST',pricing_reference='OFFLINE_FIXTURE',
        max_api_calls=8,max_input_tokens=10000,max_output_tokens=10000,max_estimated_cost=1,
        input_cost_per_million=1,output_cost_per_million=1,max_seconds=60,allowed_egress=['OFFLINE_NONE'])
    p=tmp_path/'goal.json';p.write_text(json.dumps(config))
    client=Fake()
    monkeypatch.setattr(GatewayCompletionClient,'complete',lambda self,**kw:client.complete(**kw))
    monkeypatch.setattr(cgkn.providers,'completion_client_from_environment',lambda:GatewayCompletionClient('http://127.0.0.1:1','offline-not-a-credential'))
    assert main(['start','--config',str(p)])==0
    assert all(x['call_identity'] for x in client.calls)
    before=len(client.calls)
    assert main(['resume','--config',str(p)])==0 and len(client.calls)==before

def test_child_environment_does_not_inherit_provider_secret(monkeypatch):
    from cgkn.application.goal_driven import child_environment
    monkeypatch.setenv('PROVIDER_API_KEY','SYNTHETIC_CANARY')
    assert 'PROVIDER_API_KEY' not in child_environment()

def test_resume_planning_only_rejection_does_not_require_fabricated_run_state(tmp_path):
    config=configuration(tmp_path)
    class Invalid(Fake):
        def complete(self,**kw):
            response=super().complete(**kw)
            from dataclasses import replace
            return replace(response,text='{}')
    session,scope=build_session(config,tmp_path/'run',Invalid())
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope)
    assert result.status=='BLOCKED'
    assert not (session.store.run_dir(config['project_id'],config['run_id'])/'run_state.json').exists()
    resumed,scope=build_session(config,tmp_path/'run',Fake())
    result=resumed.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope,resume=True)
    # Persistent no-progress remains authoritative; no invented successful DAG.
    assert result.status=='BLOCKED' and 'NO_PROGRESS' in result.escalation_reason

def test_exact_known_not_sent_planning_record_can_reconcile_on_explicit_redecision(tmp_path):
    import pytest,hashlib
    from cgkn.providers.gateway_client import GatewayCompletionError
    config=configuration(tmp_path)
    class NotSent:
        def complete(self,**kw):raise GatewayCompletionError('provider_request_rejected_before_send','fixture before transport',outcome_unknown=False)
    session,scope=build_session(config,tmp_path/'run',NotSent())
    with pytest.raises(GatewayCompletionError):
        session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope)
    root=session.store.run_dir(config['project_id'],config['run_id'])
    error=next(root.glob('provider_calls/*/error.json'))
    resumed,scope=build_session(config,tmp_path/'run',Fake())
    result=resumed.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope,
        resume=True,finish_when_verified=True,continuation_feedback={'redecision':{'strategy_revision':hashlib.sha256(b'fixed-input').hexdigest(),
        'reason':'correct input after explicit known not submitted failure','evidence_refs':[str(error)]}})
    assert result.status=='GOALS_VERIFIED',result.as_dict()

def test_repair_can_bind_new_local_observation_but_not_external_file(tmp_path):
    import pytest
    from cgkn.agent.composer import AgentDecisionContext
    config=configuration(tmp_path);session,scope=build_session(config,tmp_path/'run',Fake())
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope,finish_when_verified=True)
    inputs=tmp_path/'product/inputs';inputs.mkdir(exist_ok=True);(inputs/'review.json').write_text('{"failed":true}')
    context=AgentDecisionContext('goal-test','one',config['root_goal'],3,result.tree,(),{}, {},{'external_review':'failed'})
    def proposal(path):return {'edits':[{'node_id':'make-greeting','operation':'update_config','payload':{'config':{
        'goal':'Repair required bytes','read_paths':[path],'verified_artifact_change_reason':'external review failed'}}}]}
    normalized=session.composer._normalize_decision(proposal('inputs/review.json'),context)
    cfg=normalized['edits'][0]['payload']['config']
    assert cfg['leaf_contract']['read_subjects']['inputs/review.json']==digest_file(inputs/'review.json')
    assert cfg['leaf_contract']['target_scope']==['answer.txt']
    with pytest.raises(ValueError,match='workspace inputs'):
        session.composer._normalize_decision(proposal('../checker.py'),context)

def test_resume_cannot_use_unadmitted_changed_tree_even_with_redecision(tmp_path):
    import pytest,hashlib
    config=configuration(tmp_path);session,scope=build_session(config,tmp_path/'run',Fake())
    session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope,finish_when_verified=True)
    p=session.store.run_dir(config['project_id'],config['run_id'])/'capability_tree.json'
    tree=json.loads(p.read_text(encoding='utf-8'))
    next(n for n in tree['nodes'] if n['id']=='make-greeting')['config']['goal']='unadmitted change'
    p.write_text(json.dumps(tree),encoding='utf-8')
    resumed,scope=build_session(config,tmp_path/'run',Fake())
    with pytest.raises(ValueError,match='resume graph mismatch'):
        resumed.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope,resume=True,
            continuation_feedback={'redecision':{'strategy_revision':hashlib.sha256(b'test').hexdigest(),'reason':'test','evidence_refs':[str(p)]}})


def test_result_projection_is_bounded_and_readable(tmp_path):
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    results={str(i):{'status':'FAILED' if i==0 else 'SUCCEEDED','outputs':{'content':'x'*6000,'path':'source.txt'},'error':'UNKNOWN' if i==0 else None} for i in range(8)}
    context=AgentDecisionContext('goal-test','one',config['root_goal'],1,CapabilityTree('g',()),(),{},{},{},execution_results=results)
    projected=session.composer.prepare_context(context)
    assert sum('content' in row['outputs'] for row in projected.execution_results.values())==2
    for node,row in projected.execution_results.items():
        saved=Path(config['inputs_and_workspace']['workspace'])/row['readable_result_ref']['path']
        assert json.loads(saved.read_text(encoding='utf-8'))==results[node]
    assert projected.execution_results['0']['error']=='UNKNOWN'
