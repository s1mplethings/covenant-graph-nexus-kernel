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
    assert len(client.calls)==2 and not (Path(config['inputs_and_workspace']['workspace'])/'answer.txt').exists()
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
                    'actions':[] if any(o.get('action')=='write_file' for o in context.get('observations',[])) else [{'action':'write_file','path':'answer.txt','content':'hello'}],
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
                    'decision_audit':{'requirement_refs':['R1'],'alternatives_considered':['wait for input','implement uncovered requirement'],'expected_outcome':'independent checker sees required bytes'}}
            return ProviderCompletion(json.dumps(value),kw['config'].model_id,'offline-'+str(len(self.calls)),{},1)
        return perform_scoped_effect('PROVIDER_CALL',response,resource_usage={'calls':1})

def test_new_project_capability_is_admitted_and_consumed(tmp_path):
    config=configuration(tmp_path);client=Fake();session,planning=build_session(config,tmp_path/'run',client)
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=planning,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED',result.as_dict()
    assert (Path(config['inputs_and_workspace']['workspace'])/'answer.txt').read_text()=='hello'
    assert 'project.greeting@1' in session.known_capabilities
    assert [x['role'] for x in client.calls]==['agent','worker','worker','agent']
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
    import os
    # The CLI normally has its own process; restore its per-process variables
    # when exercising main in-process so later negative controls stay isolated.
    for suffix in ('MAX_API_CALLS','MAX_INPUT_TOKENS','MAX_OUTPUT_TOKENS','MAX_ESTIMATED_COST',
                   'INPUT_COST_PER_MILLION','OUTPUT_COST_PER_MILLION','BUDGET_LEDGER'):
        key='CGKN_PROVIDER_'+suffix
        if key in os.environ:monkeypatch.setenv(key,os.environ[key])
        else:monkeypatch.delenv(key,raising=False)
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
    import scripts.run_goal_driven as cli
    from cgkn.state import FileRunStore
    rd=FileRunStore(Path(config['run_root'])/'store').run_dir(config['project_id'],config['run_id'])
    deadline=json.loads((rd/'execution-window.json').read_text())['deadline']
    monkeypatch.setattr(cli.time,'time',lambda:deadline+1)
    with pytest.raises(ValueError,match='original execution deadline'):
        main(['resume','--config',str(p)])
    assert len(client.calls)==before

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


@pytest.mark.parametrize('resume_at', [110, 170])
def test_execution_window_survives_restart_without_new_allowance(tmp_path, resume_at):
    from scripts.run_goal_driven import execution_deadline
    from cgkn.state import FileRunStore
    store=FileRunStore(tmp_path/'store');rd=store.run_dir('project','run')
    assert execution_deadline(store,rd,60,resume=False,now=100)==160
    original=(rd/'execution-window.json').read_bytes()
    assert execution_deadline(store,rd,60,resume=True,now=resume_at)==160
    assert (rd/'execution-window.json').read_bytes()==original
    with pytest.raises(ValueError,match='INVALID'):
        execution_deadline(store,rd,600,resume=True,now=resume_at)
    with pytest.raises(ValueError,match='CLOCK_REGRESSION'):
        execution_deadline(store,rd,60,resume=True,now=99)


def test_resume_missing_execution_window_cannot_mint_budget(tmp_path):
    from scripts.run_goal_driven import execution_deadline
    from cgkn.state import FileRunStore
    store=FileRunStore(tmp_path/'store');rd=store.run_dir('project','run')
    with pytest.raises(ValueError,match='EXECUTION_WINDOW_MISSING'):
        execution_deadline(store,rd,60,resume=True,now=100)
    assert not (rd/'execution-window.json').exists()


def test_failed_batch_compilation_leaves_no_partial_capability(tmp_path):
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    from copy import deepcopy
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    ctx=AgentDecisionContext('goal-test','one',config['root_goal'],1,CapabilityTree('g',()),(),{}, {},{})
    policy=session.admission_policy;known=session.known_capabilities;catalog=deepcopy(session.capability_catalog)
    value={'edits':[{'node_id':'read','operation':'add_node','payload':{'capability_ref':'project.read@1','config':{'executor_ref':'local.file@1','goal':'inspect','action':'list_files','path':'.'}}},
                    {'node_id':'bad','operation':'add_node','payload':{'capability_ref':'project.bad@1','config':{'executor_ref':'unapproved','goal':'inspect'}}}],
           'decision_audit':{'requirement_refs':['R1']}}
    original=deepcopy(value)
    with pytest.raises(ValueError,match='allowed='):
        session.composer._normalize_decision(value,ctx)
    assert session.admission_policy==policy and session.known_capabilities==known
    assert session.capability_catalog==catalog and value==original


def test_executor_interface_fields_share_compiler_definition(tmp_path):
    from cgkn.application.goal_driven import EXECUTOR_INTERFACES
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    interfaces=session.composer.executor_interfaces()
    assert interfaces==EXECUTOR_INTERFACES
    assert set(interfaces)=={'llm.cheap@1','local.file@1','local.python-test@1','goal.acceptance@1'}
    assert session.admission_policy.max_new_nodes==2


@pytest.mark.parametrize('refs,gap',[([{}],None),(['R1'],{})])
def test_malformed_references_retain_actionable_validation(tmp_path,refs,gap):
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    ctx=AgentDecisionContext('goal-test','one',config['root_goal'],1,CapabilityTree('g',()),(),{}, {},{})
    with pytest.raises(ValueError,match='requirement_refs|target_gap_id'):
        session.composer._normalize_decision({'decision_audit':{'requirement_refs':refs,'capability_claim':{'target_gap_id':gap}}},ctx)


def test_atomic_local_batch_admitted_before_both_executions(tmp_path):
    from dataclasses import replace
    config=configuration(tmp_path);config['resource_and_effect_limits']['max_planning_decisions']=1
    class Batch(Fake):
        def complete(self,**kw):
            response=super().complete(**kw)
            value=json.loads(response.text)
            value['edits']=[{'edit_id':'e-'+n,'node_id':n,'operation':'add_node','payload':{
                'capability_ref':'project.'+n+'@1','parent_id':'','depends_on':[],
                'config':{'executor_ref':'local.file@1','goal':'inspect current inputs','action':'list_files','path':'.'}},'provenance':{}} for n in ('inspect1','inspect2')]
            return replace(response,text=json.dumps(value))
    session,planning=build_session(config,tmp_path/'run',Batch())
    session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=planning)
    for n in ('inspect1','inspect2'):
        result=session.store.load_result(config['project_id'],config['run_id'],n)
        assert result.succeeded and result.metadata['node_commit_receipt_id']


def test_authorized_requirement_extension_preserves_run_and_budget(tmp_path):
    from copy import deepcopy
    from scripts.run_goal_driven import bind_goal_config
    from cgkn.state.acceptance import identity
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    store=session.store;rd=store.run_dir(config['project_id'],config['run_id'])
    frozen={'config':config,'sources':{'fixture':'source-v1'},'checker':'checker-v1'}
    bind_goal_config(store,rd,frozen,'start')
    new=deepcopy(frozen);new['config']['requirements']['R2']='Support the additional declared input format'
    new['config']['requirement_extension']={'parent_config_identity':identity(frozen),'authority_reference':'OFFLINE_EXPLICIT_USER_REQUIREMENT_REVISION'}
    checks=deepcopy(session.acceptance.data['checks'])
    bind_goal_config(store,rd,new,'extend')
    bind_goal_config(store,rd,new,'extend')
    bind_goal_config(store,rd,new,'resume')
    events=[e for e in store.load_events(config['project_id'],config['run_id']) if e.event_type=='GOAL_CONFIG_EXTENDED']
    assert len(events)==1
    resumed,_=build_session(new['config'],tmp_path/'run',Fake())
    assert resumed.acceptance.data['checks']==checks
    assert set(resumed.acceptance.requirements)=={'R1','R2'}
    assert len(resumed.acceptance.data['plans'][-1]['goals'])==2
    assert resumed.acceptance.data['plans'][0]['goals'][0]['requirement_refs']==['R1']
    assert not resumed.acceptance.view()['complete']


@pytest.mark.parametrize('mutation',['budget','original_requirement','source'])
def test_requirement_extension_cannot_refresh_authority(tmp_path,mutation):
    from copy import deepcopy
    from scripts.run_goal_driven import bind_goal_config
    from cgkn.state.acceptance import identity
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    store=session.store;rd=store.run_dir(config['project_id'],config['run_id'])
    frozen={'config':config,'sources':{'fixture':'source-v1'},'checker':'checker-v1'}
    bind_goal_config(store,rd,frozen,'start')
    new=deepcopy(frozen);new['config']['requirements']['R2']='additional format'
    new['config']['requirement_extension']={'parent_config_identity':identity(frozen),'authority_reference':'OFFLINE_TEST'}
    if mutation=='budget':new['config']['resource_and_effect_limits']['max_calls_per_leaf']=100
    elif mutation=='original_requirement':new['config']['requirements']['R1']='weakened'
    else:new['sources']['fixture']='source-v2'
    original=(rd/'goal_acceptance.json').read_bytes()
    with pytest.raises(ValueError,match='cannot|source identity'):
        bind_goal_config(store,rd,new,'extend')
    assert (rd/'goal_acceptance.json').read_bytes()==original


def test_second_project_inherits_original_campaign_deadline(tmp_path):
    from scripts.run_goal_driven import execution_deadline,hash_file
    from cgkn.state import FileRunStore
    store=FileRunStore(tmp_path/'store')
    first=store.run_dir('first','one');second=store.run_dir('second','one')
    assert execution_deadline(store,first,60,resume=False,now=100)==160
    path=first/'execution-window.json'
    reference={'path':str(path),'sha256':hash_file(path)}
    assert execution_deadline(store,second,60,resume=False,now=150,inherited_window=reference)==160
    assert execution_deadline(store,second,60,resume=True,now=170)==160
    reference['sha256']='0'*64
    with pytest.raises(ValueError,match='IDENTITY_MISMATCH'):
        execution_deadline(store,store.run_dir('third','one'),60,resume=False,now=150,inherited_window=reference)


def test_goal_schema_omits_mechanical_ids_and_checks_executor_fields(tmp_path):
    import jsonschema
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    context=AgentDecisionContext('goal-test','one',config['root_goal'],1,CapabilityTree('g',()),(),{},{},{})
    session.composer.prepare_context(context)
    schema=session.composer.decision_schema
    raw={'schema_version':'1.0','summary':'inspect','reason':'R1 missing','request_run':True,'finish':False,'needs_escalation':False,'escalation_reason':'',
        'edits':[{'operation':'add_node','node_id':'inspect','payload':{'capability_ref':'project.inspect@1','parent_id':'','depends_on':[],
            'config':{'executor_ref':'local.file@1','goal':'inspect inputs','action':'list_files','path':'.'}}}]}
    jsonschema.validate(raw,schema)
    raw['decision_audit']={'requirement_refs':['R1'],'expected_outcome':'inspect available inputs'}
    compiled=session.composer._normalize_decision(raw,context)
    assert compiled['decision_id'].startswith('host-decision-')
    assert compiled['edits'][0]['edit_id'].startswith('host-edit-')
    assert compiled['edits'][0]['provenance']['run_id']=='one'
    raw.pop('decision_audit');raw['edits'][0]['payload']['config']['unapproved']='no'
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw,schema)


def test_authorized_input_fetch_needs_no_tree_node(tmp_path):
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    from cgkn.protocol.adaptive_context import public_context_view
    from cgkn.protocol.normalization import ContractError
    config=configuration(tmp_path);inputs=Path(config['inputs_and_workspace']['workspace'])/'inputs';inputs.mkdir()
    source=inputs/'sample.jsonl';source.write_text('{"run_id":"public-fixture"}',encoding='utf-8')
    config['inputs_and_workspace']['inputs']=[{'name':source.name,'path':str(source),'sha256':digest_file(source)}]
    session,_=build_session(config,tmp_path/'run',Fake())
    ctx=AgentDecisionContext('goal-test','one',config['root_goal'],1,CapabilityTree('g',()),(),{},{},{})
    prepared=session.composer.prepare_context(ctx)
    view,resolver=public_context_view(prepared.as_dict())
    assert 'public-fixture' not in json.dumps(view)
    item=next(row for row in resolver.catalog() if row['kind']=='artifact')
    fetched=resolver.resolve({'context_operation':'fetch_artifact','ref':item['ref'],'reason':'inspect authorized schema'})
    assert fetched['value']['content']==source.read_text(encoding='utf-8')
    assert prepared.tree.nodes==()
    with pytest.raises(ContractError):
        resolver.resolve({'context_operation':'fetch_artifact','ref':'../../private','reason':'invalid'})
    source.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='identity changed'):session.composer.prepare_context(ctx)


def test_host_context_projection_is_not_a_product_version_change(tmp_path):
    from cgkn.application.goal_driven import workspace_identity
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    config=configuration(tmp_path);session,_=build_session(config,tmp_path/'run',Fake())
    workspace=Path(config['inputs_and_workspace']['workspace'])
    before=workspace_identity(workspace)
    ctx=AgentDecisionContext('goal-test','one',config['root_goal'],1,CapabilityTree('g',()),(),{},{},{},
        execution_results={'inspect':{'status':'SUCCEEDED','outputs':{'content':'informational observation','path':'source.txt'}}})
    session.composer.prepare_context(ctx)
    assert workspace_identity(workspace)==before
    (workspace/'inputs'/'business.json').write_text('{"changed":true}',encoding='utf-8')
    assert workspace_identity(workspace)!=before


def test_authorized_extension_can_update_successful_implementation_without_fake_failure(tmp_path):
    from cgkn.agent.composer import AgentDecisionContext
    config=configuration(tmp_path);session,planning=build_session(config,tmp_path/'run',Fake())
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=planning,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED'
    session.acceptance.extend_requirements({'R2':{'must':True,'description':'support another input format'}},authority_reference='OFFLINE_USER_EXTENSION')
    config['requirements']['R2']='support another input format'
    revised,_=build_session(config,tmp_path/'run',Fake())
    ctx=AgentDecisionContext('goal-test','one',config['root_goal'],3,result.tree,(),{},{},{},goal_acceptance=revised.acceptance.view())
    value={'decision_audit':{'requirement_refs':['R2'],'expected_outcome':'new format works and R1 remains valid'},
        'edits':[{'node_id':'make-greeting','operation':'update_config','payload':{'config':{
            'goal':'Implement newly authorized format','verified_artifact_change_reason':'explicit user requirement R2'}}},
                 {'node_id':'make-greeting','operation':'retry_node','payload':{}}]}
    compiled=revised.composer._normalize_decision(value,ctx)
    assert compiled['edits'][0]['payload']['config']['goal']=='Implement newly authorized format'
    assert not ctx.failure_details
    assert revised.acceptance.data['checks']==session.acceptance.data['checks']


@pytest.mark.parametrize('fetches',[1,3])
def test_planning_context_exchange_uses_authorized_multicall_permit(tmp_path,fetches):
    from cgkn.protocol.adaptive_context import ContextPacker
    config=configuration(tmp_path)
    inputs=Path(config['inputs_and_workspace']['workspace'])/'inputs';inputs.mkdir()
    for index in range(fetches):
        p=inputs/f'spec{index}.json';p.write_text(json.dumps({'public_rule':str(index)}))
        config['inputs_and_workspace']['inputs'].append({'name':p.name,'path':str(p),'sha256':digest_file(p)})
    class FetchThenBuild(Fake):
        def __init__(self):super().__init__();self.fetches=0;self.permits=[]
        def complete(self,**kw):
            authority,pid=require_provider_context();self.permits.append((kw['config'].role,authority.permit(pid).budget_scope))
            if kw['config'].role=='agent' and self.fetches<fetches:
                context=ContextPacker.restore(json.loads(kw['user']))
                catalog=context['available_context']
                rows=catalog.values() if isinstance(catalog,dict) else catalog
                rows=[row for row in rows if row.get('kind')=='artifact']
                row=rows[self.fetches];self.fetches+=1
                value={'context_operation':'fetch_artifact','ref':row['ref'],'reason':'Inspect authorized public rule'}
                return perform_scoped_effect('PROVIDER_CALL',lambda:ProviderCompletion(json.dumps(value),'offline','fetch-'+str(self.fetches),{'input_tokens':1,'output_tokens':1},1),resource_usage={'calls':1})
            return super().complete(**kw)
    client=FetchThenBuild();session,scope=build_session(config,tmp_path/'run',client)
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED',result.as_dict()
    assert client.fetches==fetches
    assert all(p['calls']==4 for role,p in client.permits if role=='agent')
    assert all(p['calls']==2 for role,p in client.permits if role=='worker')
    authority=session.runner._authority(config['project_id'],config['run_id'])
    planning=[e for e in authority.events() if e['event_type']=='NODE_PERMIT_ISSUED' and e['node_id']==scope.root_id]
    assert all(authority.permit(e['data']['permit_id']).status=='CONSUMED' for e in planning)


@pytest.mark.parametrize('interrupted_revoke',[False,True])
def test_completed_bad_context_reference_closes_permit_and_returns_feedback(tmp_path,monkeypatch,interrupted_revoke):
    config=configuration(tmp_path)
    inputs=Path(config['inputs_and_workspace']['workspace'])/'inputs';inputs.mkdir()
    spec=inputs/'spec.json';spec.write_text('{"public":"rule"}')
    config['inputs_and_workspace']['inputs']=[{'name':spec.name,'path':str(spec),'sha256':digest_file(spec)}]
    class WrongKindThenBuild(Fake):
        rejected=False
        def complete(self,**kw):
            if kw['config'].role=='agent' and not self.rejected:
                from cgkn.protocol.adaptive_context import ContextPacker
                prompt=ContextPacker.restore(json.loads(kw['user']))
                ref=next(x['ref'] for x in prompt['available_context'] if x['kind']=='artifact')
                self.rejected=True
                return perform_scoped_effect('PROVIDER_CALL',lambda:ProviderCompletion(json.dumps({'context_operation':'fetch_evidence','ref':ref,'reason':'wrong kind control'}),'offline'),resource_usage={'calls':1})
            return super().complete(**kw)
    client=WrongKindThenBuild();session,scope=build_session(config,tmp_path/'run',client)
    # Simulate the already-observed old source leaving a settled rejected response active.
    from cgkn.runtime.node_authority import ExecutionAuthority
    original=ExecutionAuthority.revoke_permit
    if interrupted_revoke:
        # The protocol event is saved by the loop after its exception handler;
        # suppress revocation once, then let normal recovery consume that event.
        monkeypatch.setattr(ExecutionAuthority,'revoke_permit',lambda self,pid,reason:None if reason=='PLANNER_RESPONSE_REJECTED' else original(self,pid,reason))
    result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],planning=scope,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED',result.as_dict()
    a=session.runner._authority(config['project_id'],config['run_id'])
    issued=[e for e in a.events() if e['event_type']=='NODE_PERMIT_ISSUED' and e['node_id']==scope.root_id]
    assert a.permit(issued[0]['data']['permit_id']).status=='REVOKED'
    assert all(a.permit(e['data']['permit_id']).status=='CONSUMED' for e in issued[1:])
    raw=json.loads((session.store.run_dir(config['project_id'],config['run_id'])/'agent/decision-01.json').read_text())
    assert raw['rejected'] and raw['error']=='CONTEXT_REF_KIND_MISMATCH'


def test_public_repair_schema_excludes_host_fields_and_permission_changes(tmp_path):
    from jsonschema import Draft202012Validator
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    c=configuration(tmp_path);session,_=build_session(c,tmp_path/'run',Fake())
    context=AgentDecisionContext('goal-test','one',c['root_goal'],1,CapabilityTree('g',()),(),{}, {},{})
    prepared=session.composer.prepare_context(context)
    schema=session.composer.decision_schema['properties']['edits']['items']
    validator=Draft202012Validator(schema)
    edit={'operation':'update_config','node_id':'n','payload':{'config':{'goal':'Repair exact authorized output'}}}
    assert validator.is_valid(edit)
    for key in ('leaf_contract','input_paths','target_paths','executor_ref'):
        assert not validator.is_valid({**edit,'payload':{'config':{key:'untrusted'}}})
    assert prepared.task_feedback['repair_interface']['config_fields']==['goal','read_paths','verified_artifact_change_reason']


def test_worker_public_write_schema_matches_target_scope():
    from jsonschema import Draft202012Validator
    from cgkn.execution.file_actions import scoped_worker_schema,WORKER_SCHEMA
    schema=scoped_worker_schema({'target_scope':['runlens.py']},'n')
    validator=Draft202012Validator(schema['properties']['actions']['items'])
    assert validator.is_valid({'action':'write_file','path':'runlens.py','content':'candidate'})
    assert not validator.is_valid({'action':'write_file','path':'test_runlens.py','content':'outside'})
    assert not validator.is_valid({'action':'patch_file','path':'../runlens.py','find':'a','replace':'b'})
    assert 'enum' not in WORKER_SCHEMA['properties']['actions']['items']['oneOf'][2]['properties']['path']


def test_portable_component_uses_governed_candidate_publication(tmp_path):
    """Source-only regression: run later with the authorized engineering suite."""
    import hashlib
    from veriarbor.block import Block
    from veriarbor.port import Port
    from veriarbor.contract import Contract
    from veriarbor.effects import EffectContract
    from veriarbor.variant import Variant
    from veriarbor.component_package import pack
    from cgkn.adapters.veriarbor.component_package import ComponentPackages,PortableComponentExecutor
    from cgkn.state import FileRunStore
    from cgkn.executors import ExecutorRegistry
    from cgkn.execution.deliverables import FileDeliverableChecker
    from cgkn.orchestration import CapabilityTree,CapabilityNode,compile_tree
    from cgkn.runtime import DAGRunner
    from tests.governed_measurement_support import admit_fixture_tree
    work=tmp_path/'work';work.mkdir();store=FileRunStore(tmp_path/'state')
    code=b'import json,sys\nx=json.load(sys.stdin)["inputs"]["value"]\nprint(json.dumps({"doubled":x*2}))\n'
    integer=Contract.create({'type':'integer'},'An exact integer')
    block=Block('double','project.double@1',(Port('value','1','input',integer),),
        (Port('doubled','1','output',integer),),EffectContract(external_effects=('local_process',)),
        (Variant('one',(('main.py',hashlib.sha256(code).hexdigest()),)),),'one')
    options=dict(entrypoint='main.py',dependencies={},applicability={})
    packet=pack(block,{'main.py':code},**options,invocation={'protocol':'python-json-stdio@1',
        'input_semantics':'Double the value input','error_semantics':'Nonzero exit rejects candidate'})
    packages=ComponentPackages(store,'p','r')
    imported=packages.import_candidate(packet,context={},dependencies={})
    assert imported['qualification']=='NEEDS_REVALIDATION'
    packages.materialize_inputs(work,{})
    executor=PortableComponentExecutor(work,packages,{})
    config,leaf=executor.compile({'executor_ref':'local.component@1','goal':'Double an integer',
        'package_identity':packet['identity'],'inputs':{'value':3},'output_paths':{'doubled':'answer.json'}},'double',[],work)
    config['leaf_contract']=leaf
    def independent(root,contract):
        passed=json.loads((root/'answer.json').read_text())==6
        return {'passed':passed,'observed':{'exact_double':passed},'artifacts':['answer.json'] if passed else []}
    registry=ExecutorRegistry();registry.register(executor)
    registry.register(FileDeliverableChecker(work,{'local-artifacts':independent}))
    runner=DAGRunner(registry,store,deliverable_checkers={'files':'deliverable.files@1'})
    tree=admit_fixture_tree(store,CapabilityTree('Double an integer',(
        CapabilityNode('double',capability_ref='project.double@1',config=config),)))
    result=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    assert result.status=='SUCCEEDED' and json.loads((work/'answer.json').read_text())==6
    execution=store.load_result('p','r','double')
    assert execution.outputs['ports']['doubled']==6
    assert execution.metadata['node_commit_receipt_id']
    assert execution.metadata['deliverable_verdict']=='VERIFIED'
    # Merely importing source must never enable the typed subprocess adapter.
    source_packet=pack(block,{'main.py':code},**options)
    packages.import_candidate(source_packet,context={},dependencies={});packages.materialize_inputs(work,{})
    with pytest.raises(ValueError,match='no declared executable adapter'):
        executor.compile({**config,'package_identity':source_packet['identity']},'source',[],work)
    from jsonschema.exceptions import ValidationError
    with pytest.raises(ValidationError):
        executor.compile({**config,'inputs':{'value':'not an integer'}},'bad',[],work)
    source=work/'inputs'/'components'/packet['identity']/'main.py'
    source.write_text('changed')
    with pytest.raises(ValueError,match='missing or changed'):
        executor.compile(config,'changed',[],work)
