"""Offline milestone lifecycle qualification; no product implementation."""
import copy
import json
from dataclasses import asdict
from cgkn.agent.project_agent import AdmissionPolicy
from veriarbor.capability import CapabilityContract,GoalGap

import pytest

from cgkn.agent import AgentComposer, ProjectSession
from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.execution.deliverables import SubjectDeliverableChecker
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.state.acceptance import GoalAcceptance, identity
from tests.protocol.test_milestone_declaration import semantic


INTENT={'overall_goal':'measure two fixture records','user_visible_outcomes':['both records verified'],
        'constraints':['offline fixture only'],'forbidden_operations':['network'],
        'delivery_expectations':['qualified fixture receipts'],
        'major_acceptance_categories':['first record','second record']}


class PlannerClient:
    def __init__(self):
        self.requests=[]
        self.declarations=0
        self.executions=0
    def complete(self, **kw):
        self.requests.append(kw)
        context=json.loads(kw['user'])
        if kw['schema_name']=='cgkn_next_milestone':
            value={'requirement_refs':[next(iter(context['uncovered_requirements']))],
                   'checker':'measure',
                   'reason_summary':'Verify one registered record before planning the next'}
        elif kw['schema_name']=='cgkn_semantic_v1' and context['tables'].get('mode')=='MILESTONE_MODE':
            value=semantic()
            value['acceptance_intent']=['registered fixture record is usable']
            self.declarations+=1
        elif kw['schema_name']=='cgkn_semantic_v1':
            if self.executions < self.declarations:
                target=next(n['id'] for n in context['tables']['nodes'] if n['state']=='available')
                value={'action':1,'task_kind':4,'target':target,'scope':[0],'deps':[],
                       'goal':'Measure current fixture record','expected':['independent current measurement'],
                       'accept':['valid independent acceptance envelope']}
                self.executions+=1
            else:
                value={'action':9}
        else:
            view=context['goal_acceptance']
            pending=[g for g in view['goals'] if g['verdict']!='VERIFIED']
            value={'schema_version':'1.0','decision_id':'d'+str(len(self.requests)),
                   'summary':'Measure current record' if pending else 'Finish verified fixture',
                   'reason':'Use registered independent checker', 'edits':[],
                   'request_run':bool(pending),'finish':not pending,'needs_escalation':False,'escalation_reason':''}
            value['decision_audit']={'alternatives_considered':['measure','finish'],
                'expected_outcome':'Independent current record measurement',
                'capability_claim':{'target_capability_id':'measure@1','target_gap_id':'records','strategy_capabilities':['measure@1']}}
            if pending:
                goal=pending[0]
                leaf=build_leaf_contract(goal='Measure fixture record',kind='TEST',scope=['fixture'],
                    acceptance=['envelope'],checker='measurement',output_identity=goal['id'],
                    effect_domains=['measurement'],executor='measure@1',subject='fixture',
                    expected_observation='current fixture record measurement',
                    pass_fail_rule='valid envelope; independent goal verdict decides acceptance')
                value['edits']=[{'edit_id':'e'+str(len(self.requests)),'operation':'add_node',
                    'node_id':'measure'+str(len(self.requests)), 'provenance':{'source':'offline-planner-fixture'},
                    'payload':{'capability_ref':'measure@1','parent_id':'','depends_on':[],
                               'config':{'executor_ref':'measure@1','goal_id':goal['id'],'leaf_contract':leaf}}}]
        return ProviderCompletion(json.dumps(value),'offline-planner','request-'+str(len(self.requests)),
                                  {'input_tokens':20,'output_tokens':20}, raw_finish_reason='stop')


def setup_session(tmp_path, bad_record=False, dependencies=False):
    store=FileRunStore(tmp_path/'state')
    a=GoalAcceptance(store,'p','r',{'one':{'must':True,'checker_keys':['measure']},
                                  'two':{'must':True,'checker_keys':['measure'],'depends_on':['one'] if dependencies else []}}, {'measure':'measure@1'})
    fixture=tmp_path/'records.json'
    fixture.write_text(json.dumps({'one':False if bad_record else True,'two':True}))
    subject={'fixture':identity(fixture.read_text())}
    a.bind_subjects(subject)
    class Measure:
        descriptor=ExecutorDescriptor('measure@1','deterministic',('*',))
        def execute(self, request):
            g=next(g for g in a.view()['goals'] if g['id']==request.task_context.node_config['goal_id'])
            data=json.loads(fixture.read_text())
            passed=all(data[r] is True for r in g['requirement_refs'])
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,
                node_id=request.node_id,attempt_id=request.attempt_id,executor_ref='measure@1',
                status=BlockStatus.SUCCEEDED,outputs={'goal_check':{'goal_id':g['id'],
                    'condition_hash':identity(g['acceptance']),'subjects':{p:subject['fixture'] for p in g['subject_refs']},
                    'execution':'VALID','evidence_refs':[str(fixture)],'observed':{'records':data},
                    'verdict':'VERIFIED' if passed else 'FAILED'}})
    def envelope(request,contract):
        result=request.as_dict()['input_values']['execution_receipt']['outputs'].get('goal_check',{})
        return {'passed':bool(result.get('evidence_refs')) and all(v==subject['fixture'] for v in result.get('subjects',{}).values()),
                'observed':result,'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}
    def fixture_snapshot(contract):
        # Read-only state fixture: semantic scope keys resolve to this frozen
        # input record. This qualifies binding/lifecycle, not Python delivery.
        allowed={artifact['path'] for g in a.view()['goals']
                 for artifact in g['milestone_contract']['design']['artifacts']}
        assert set(contract['target_scope']) <= allowed
        return {scope:identity(fixture.read_text()) for scope in contract['target_scope']}
    registry=ExecutorRegistry();registry.register(Measure())
    registry.register(SubjectDeliverableChecker(fixture_snapshot,{'envelope':envelope}))
    client=PlannerClient();events=[]
    composer=AgentComposer(client,ModelRoleConfig('agent','offline-flash'),
                           planner_mode='MILESTONE_MODE',protocol_trace=events.append)
    runner=DAGRunner(registry,store,deliverable_checkers={'measurement':'deliverable.subjects@1'})
    session=ProjectSession(composer,runner,store,known_capabilities={'measure@1'},worker_model='offline',
        admission_policy=AdmissionPolicy(project_id='p',execution_budget={'calls':0},
            capability_contracts={'measure@1':asdict(CapabilityContract('measure@1','Measure both fixture records',
                critical=False,positive_controls=('registered fixture observation',)))},
            goal_gaps={'records':asdict(GoalGap('records',INTENT['overall_goal'],'all-records-verified',1,0,capability_ids=('measure@1',)))}),
        capability_catalog={'measure@1':{'executor_ref':'measure@1','semantic_task_kinds':[4],
            'checker_ref':'measurement','acceptance':['envelope'],'effect_domains':['measurement'],
            'description':'Read-only independent fixture measurement'}},acceptance=a,max_decisions=5,
        subject_snapshot=lambda paths:{p:identity(fixture.read_text()) for p in paths})
    return session,a,client,events


def test_existing_session_declares_checks_and_appends_next_milestone(tmp_path):
    session,a,client,events=setup_session(tmp_path)
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    assert result.status=='GOALS_VERIFIED'
    assert a.view()['complete']
    assert len(a.data['plans'])==2 and len(a.data['checks'])==2
    assert [len(p['goals']) for p in a.data['plans']]==[1,2]
    assert a.data['plans'][0]['goals'][0]==a.data['plans'][1]['goals'][0]
    decision=json.loads((session.store.run_dir('p','r')/'agent/decision-02.json').read_text())
    claim=decision['decision_audit']['capability_claim']
    assert claim=={'target_capability_id':'measure@1','target_gap_id':'records','strategy_capabilities':['measure@1']}
    selections=[r for r in client.requests if r['schema_name']=='cgkn_next_milestone']
    assert len(selections)==2
    assert json.loads(selections[0]['user'])['verified_milestones']==[]
    assert len(json.loads(selections[1]['user'])['verified_milestones'])==1
    assert len(result.run_summary.actual_executions)==1
    assert len(result.run_summary.reused_nodes)==1
    assert not any(r['schema_name']=='cgkn_agent_decision' for r in client.requests)
    assert all(n.id.startswith('sem-node-') for n in result.tree.nodes)
    assert all(n.config.get('public_contracts',{}).get('entries') for n in result.tree.nodes)
    assert len([e for e in events if e.get('kind')=='MILESTONE_SELECTION'])==2
    for g in a.data['plans'][-1]['goals']:
        assert g['milestone_contract']['compilation']['business_implementation_generated'] is False
    changed=copy.deepcopy(a.data['plans'][-1])
    changed['goals'][0]['milestone_contract']['design']['reason_summary']='replace public contract'
    with pytest.raises(ValueError,match='weakened'): a.propose(changed,result.tree)


def test_repeated_admission_rejection_is_bounded_across_decisions_and_resume(tmp_path):
    from cgkn.protocol.normalization import ContractError
    session,a,client,events=setup_session(tmp_path)
    session.continuous=True
    calls=[]
    def reject(context):
        calls.append(context)
        if len(calls)>1:
            original=context.failure_details['decision_validation']['protocol_error']['original_error']
            assert original['fields']==['failure_semantics']
        raise ContractError('MILESTONE_REDECISION_REQUIRED',details={'original_error':{
            'code':'FAILURE_SEMANTICS_REQUIRED','fields':['failure_semantics']}})
    session.composer.decide=reject
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    assert result.status=='BLOCKED' and 'ADMISSION_NO_PROGRESS' in result.escalation_reason
    assert len(calls)==3 and not a.data['checks']
    again=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT,resume=True)
    assert again.status=='BLOCKED' and len(calls)==3


def test_independent_acceptance_is_unavailable_until_all_declared_artifacts_exist(tmp_path):
    from types import SimpleNamespace
    from cgkn.orchestration.capability_tree import CapabilityTree
    session,a,client,events=setup_session(tmp_path)
    session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    raw=json.loads((session.store.run_dir('p','r')/'agent/context-02.json').read_text())
    raw['tree']=CapabilityTree.from_dict(raw['tree'])
    ready=session.composer._milestone_snapshot(SimpleNamespace(**raw)).document
    assert ready['capabilities'] and all(row['ready'] for row in ready['acceptance_readiness'])
    test_path=next(row['path'] for row in ready['artifact_readiness'] if row['path'].startswith('tests/'))
    raw['goal_acceptance']['subject_identities'][test_path]=None
    missing=session.composer._milestone_snapshot(SimpleNamespace(**raw)).document
    assert not missing['capabilities']
    assert all(test_path in row['missing_artifacts'] for row in missing['acceptance_readiness'])
    assert not next(row for row in missing['artifact_readiness'] if row['path']==test_path)['materialized']
    assert all(g['verdict']=='INSUFFICIENT_EVIDENCE' for g in raw['goal_acceptance']['goals'])


def test_unverified_finish_loop_is_bounded_and_resume_does_not_repeat_calls(tmp_path):
    from cgkn.agent.composer import AgentDecision
    session,a,client,events=setup_session(tmp_path)
    session.continuous=True
    calls=[]
    def finish(context):
        calls.append(context)
        return AgentDecision('finish-'+str(len(calls)),'Finish','model self report',(),False,True,False,'',{},'offline',0)
    session.composer.decide=finish
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    assert result.status=='BLOCKED' and 'FINISH_NO_PROGRESS' in result.escalation_reason
    assert len(calls)==3 and not a.view()['complete']
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT,resume=True)
    assert result.status=='BLOCKED' and len(calls)==3
    from cgkn.protocol.context_pack import failure_context
    visible=failure_context(calls[1],evidence_ref='agent/context-02.json')
    assert visible['finish_rejection']['finish_allowed'] is False
    assert visible['finish_rejection']['goal_error']=='MUST goals lack current valid evidence'
    feedback={'redecision':{'strategy_revision':'a'*64,'reason':'Explicit revised planning strategy',
                           'evidence_refs':['audit/revised-strategy.json']}}
    resumed=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT,
                        resume=True,continuation_feedback=feedback)
    assert resumed.status=='BLOCKED' and len(calls)==6
    assert calls[3].failure_details['continuation_requirements']==feedback
    with pytest.raises(ValueError,match='already consumed'):
        session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT,
                    resume=True,continuation_feedback=feedback)
    assert len(calls)==6


def test_failed_independent_measurement_does_not_admit_next_milestone(tmp_path):
    session,a,client,events=setup_session(tmp_path,bad_record=True)
    session.max_decisions=3
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    assert result.status=='BLOCKED' and not a.view()['complete']
    assert len(a.data['plans'])==1
    assert a.view()['uncovered_must']==['two']
    assert a.view()['goals'][0]['verdict']=='FAILED'
    assert a.data['checks']
    assert len([r for r in client.requests if r['schema_name']=='cgkn_next_milestone'])==1
    raw=json.loads((session.store.run_dir('p','r')/'agent/context-03.json').read_text())
    from types import SimpleNamespace
    from cgkn.orchestration.capability_tree import CapabilityTree
    raw['tree']=CapabilityTree.from_dict(raw['tree'])
    snapshot=session.composer._milestone_snapshot(SimpleNamespace(**raw))
    failure=snapshot.document['repair_context']['failures'][0]
    assert failure['failure_domain']=='business'
    assert failure['actual']=={'verdict':'FAILED','root_cause':'UNRESOLVED'}
    assert failure['object_identity'] and failure['evidence_refs'][0]['receipt_hash']
    assert (session.store.run_dir('p','r')/failure['evidence_refs'][0]['path']).is_file()
    raw['goal_acceptance']['goals'][0]['evidence']['reason']='Observed value 6; public requirement expects 7'
    contextual=session.composer._milestone_snapshot(SimpleNamespace(**raw))
    actual=contextual.document['repair_context']['failures'][0]['actual']
    assert actual['public_reason']=='Observed value 6; public requirement expects 7'
    assert actual['root_cause']=='UNRESOLVED'


def test_dependent_milestone_receives_public_contract_and_binds_upstream_identity(tmp_path):
    session,a,client,events=setup_session(tmp_path,dependencies=True)
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    assert result.status=='GOALS_VERIFIED'
    selections=[json.loads(r['user']) for r in client.requests if r['schema_name']=='cgkn_next_milestone']
    assert list(selections[0]['uncovered_requirements'])==['one']
    assert list(selections[1]['uncovered_requirements'])==['two']
    first,second=a.view()['goals']
    assert set(first['subject_refs'])<set(second['subject_refs'])
    assert second['milestone_contract']['dependency_goal_ids']==[first['id']]
    dependencies=session.composer._milestone_dependencies(a.view(),['two'])
    assert dependencies[0]['public_contract']==first['milestone_contract']['registry']
    assert session.composer._milestone_dependencies(a.view(),['one'])==[]
    current=dict(a.view()['subject_identities'])
    current[first['subject_refs'][0]]='changed-upstream-object'
    a.bind_subjects(current)
    assert all(g['verdict']=='INSUFFICIENT_EVIDENCE' for g in a.view()['goals'])


@pytest.mark.parametrize('dependencies',[['missing'],['r'],['other','other']])
def test_invalid_requirement_dependency_graph_fails_before_planning(tmp_path,dependencies):
    with pytest.raises(ValueError,match='requirement dependenc'):
        GoalAcceptance(FileRunStore(tmp_path/'state'),'p','r',
            {'r':{'must':True,'depends_on':dependencies},'other':{'must':True}},{'measure':'measure@1'})


def test_incomplete_declaration_is_checkpointed_and_not_automatically_replayed(tmp_path):
    from dataclasses import replace
    session,a,client,events=setup_session(tmp_path)
    original=client.complete
    def incomplete(**kw):
        response=original(**kw)
        return replace(response,raw_finish_reason=None) if kw['schema_name']=='cgkn_semantic_v1' else response
    client.complete=incomplete
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    assert result.status=='BLOCKED'
    assert 'DECLARATION_COMPLETION_INCOMPLETE' in result.escalation_reason
    assert len(client.requests)==2 and not a.data['plans']
    rejected=[e for e in session.store.load_events('p','r') if e.event_type=='AGENT_DECISION_REJECTED']
    assert rejected[-1].data['protocol_error']['outcome_unknown'] is True
    assert events[-1]['raw_text'] and events[-1]['request_id']
    event_path=session.store.run_dir('p','r')/'events.jsonl'
    before=event_path.read_bytes()
    again=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'])
    assert again.status=='BLOCKED' and 'PLANNER_OUTCOME_UNKNOWN' in again.escalation_reason
    assert len(client.requests)==2 and event_path.read_bytes()==before
    explicit={'redecision':{'strategy_revision':'b'*64,'reason':'Cannot authorize unknown replay',
                            'evidence_refs':['audit/unknown.json']}}
    again=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],resume=True,continuation_feedback=explicit)
    assert 'PLANNER_OUTCOME_UNKNOWN' in again.escalation_reason
    assert len(client.requests)==2 and event_path.read_bytes()==before


@pytest.mark.parametrize('continuous', [False, True])
def test_worker_unknown_stops_planning_and_explicit_redecision_cannot_replay(tmp_path, continuous):
    from cgkn.execution import ExecutionError, ExecutionErrorCode
    session, acceptance, client, events = setup_session(tmp_path)
    session.continuous = continuous
    executor = session.runner.registry.resolve('measure@1', 'measure@1')
    def unknown(request):
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
            node_id=request.node_id, attempt_id=request.attempt_id, executor_ref='measure@1',
            status=BlockStatus.BLOCKED,
            error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, 'stream interrupted',
                {'outcome_unknown': True, 'failure_domain': 'TRANSPORT'}))
    executor.execute = unknown
    result = session.run(project_id='p', run_id='r', goal=INTENT['overall_goal'], project_intent=INTENT)
    assert result.status == 'BLOCKED'
    assert 'EXECUTION_OUTCOME_UNKNOWN' in result.escalation_reason
    assert not acceptance.view()['complete']
    calls = len(client.requests)
    assert calls == 3  # selection, declaration, executable decision; no futile follow-up
    root = session.store.run_dir('p', 'r')
    before = {str(p.relative_to(root)): p.read_bytes() for p in (root/'attempts').rglob('*.json')}
    feedback = {'redecision': {'strategy_revision': 'c'*64, 'reason': 'Cannot override unknown',
                              'evidence_refs': ['audit/raw.json']}}
    again = session.run(project_id='p', run_id='r', goal=INTENT['overall_goal'],
                        resume=True, continuation_feedback=feedback)
    assert 'EXECUTION_OUTCOME_UNKNOWN' in again.escalation_reason
    assert len(client.requests) == calls
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in (root/'attempts').rglob('*.json')}

    # Independent read-only reconciliation releases execution uncertainty only;
    # it never turns the original UNKNOWN receipt into success.
    from cgkn.state.task_feedback import digest
    from cgkn.state.provenance import put_evidence
    node_id = result.run_summary.actual_executions[0]
    prior = session.store.load_result('p', 'r', node_id)
    ref = put_evidence(session.store, 'p', 'r', {'kind': 'ReadOnlyEffectCheck', 'applied': False})
    proof = BlockExecutionResult(project_id='p', run_id='r', node_id='verify',
        attempt_id='attempt-0001', executor_ref='verify.effect@1', status=BlockStatus.SUCCEEDED,
        outputs={'effect_reconciliation': {'source_receipt_hash': digest(prior.as_dict()),
            'disposition': 'NOT_APPLIED', 'evidence_refs': [ref]}})
    session.store.save_result(proof)
    session.runner.reconciliation_executors = frozenset({'verify.effect@1'})
    session.runner.reconcile_effects('p', 'r', node_id, proof)
    assert session._unresolved_execution_nodes('p', 'r') == []
    assert json.loads((root/'attempts'/node_id/'attempt-0001.json').read_text()) == prior.as_dict()
    assert not acceptance.view()['complete']



def test_interrupted_context_is_immutable_and_requires_explicit_new_decision(tmp_path):
    session, acceptance, client, events = setup_session(tmp_path)
    session.continuous = True
    original = session.composer.decide
    def stop(context):
        raise KeyboardInterrupt('controller lost before decision persisted')
    session.composer.decide = stop
    with pytest.raises(KeyboardInterrupt):
        session.run(project_id='p', run_id='r', goal=INTENT['overall_goal'], project_intent=INTENT)
    root = session.store.run_dir('p', 'r')
    first = (root/'agent/context-01.json').read_bytes()
    session.composer.decide = original
    blocked = session.run(project_id='p', run_id='r', goal=INTENT['overall_goal'], resume=True)
    assert blocked.status == 'BLOCKED' and 'PLANNER_CONTEXT_INTERRUPTED' in blocked.escalation_reason
    assert not client.requests
    feedback = {'redecision': {'strategy_revision': 'd'*64, 'reason': 'Read-only interrupted planning reconciled',
                              'evidence_refs': ['audit/interrupted-request.json']}}
    result = session.run(project_id='p', run_id='r', goal=INTENT['overall_goal'], resume=True,
                         continuation_feedback=feedback)
    assert result.status == 'GOALS_VERIFIED'
    assert (root/'agent/context-01.json').read_bytes() == first
    assert not (root/'agent/decision-01.json').exists()
    assert (root/'agent/decision-02.json').exists()
    retained = [e for e in session.store.load_events('p', 'r') if e.event_type == 'AGENT_INTERRUPTED_CONTEXT_RETAINED']
    assert len(retained) == 1 and retained[0].data['decision_number'] == 1


def test_repeated_blocked_runs_without_execution_are_bounded_and_preserved(tmp_path):
    from cgkn.agent.composer import AgentDecision
    from cgkn.execution import ExecutionError, ExecutionErrorCode
    session, acceptance, client, events = setup_session(tmp_path)
    session.continuous=True
    executor=session.runner.registry.resolve('measure@1','measure@1')
    def blocked(request):
        return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,
            node_id=request.node_id,attempt_id=request.attempt_id,executor_ref='measure@1',
            status=BlockStatus.BLOCKED,error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED,'known blocked prerequisite'))
    executor.execute=blocked
    original=session.composer.decide;seen=[]
    def decide(context):
        seen.append(context.decision_number)
        if context.run_summary:
            return AgentDecision('keep-'+str(context.decision_number),'keep','fixture',(),True,False,False,'',{},'',0)
        return original(context)
    session.composer.decide=decide
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    assert result.status=='BLOCKED' and 'DAG_NO_EXECUTABLE_PROGRESS' in result.escalation_reason
    records=[e for e in session.store.load_events('p','r') if e.event_type=='PROJECT_EXECUTION_CHECKPOINT']
    assert [e.data['consecutive_empty_blocked_runs'] for e in records]==[0,1,2,3]
    assert len(records[0].data['actual_executions'])==1
    assert all(not e.data['actual_executions'] for e in records[1:])
    count=len(seen)
    again=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],resume=True)
    assert 'DAG_NO_EXECUTABLE_PROGRESS' in again.escalation_reason and len(seen)==count
    assert not acceptance.view()['complete']


def test_graph_rejection_reaches_actual_wire_context_and_stops_identical_repetition(tmp_path):
    from cgkn.runtime.dag_runner import GraphEditRejected
    from cgkn.protocol.adaptive_context import ContextPacker
    session, acceptance, client, events = setup_session(tmp_path)
    session.continuous=True
    original=session.composer.decide
    def decide(context):
        client.executions=0
        return original(context)
    session.composer.decide=decide
    def reject(**kwargs):raise GraphEditRejected('OBJECT_VERSION_MISMATCH: explicit affected-subgraph retry required sem-node-0000')
    session.runner.validate_graph_transition=reject
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    assert result.status=='BLOCKED' and 'ADMISSION_NO_PROGRESS' in result.escalation_reason
    rejected=[e for e in session.store.load_events('p','r') if e.event_type=='AGENT_DECISION_REJECTED']
    assert len(rejected)==3 and not list(session.store.run_dir('p','r').glob('node_results/*.json'))
    requests=[ContextPacker.restore(json.loads(x['user'])) for x in client.requests]
    feedback=[x['context']['decision_rejection'] for x in requests if x.get('context',{}).get('decision_rejection')]
    assert len(feedback)==2 and all('OBJECT_VERSION_MISMATCH' in x['error'] for x in feedback)
    assert all(x['failure_domain']=='GRAPH_ADMISSION_NOT_BUSINESS_FAILURE' for x in feedback)
    count=len(client.requests)
    again=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],resume=True)
    assert again.status=='BLOCKED' and len(client.requests)==count


@pytest.mark.parametrize('binding',['missing','ambiguous'])
def test_semantic_capability_binding_never_invents_exploration_or_selects_goal(tmp_path,binding):
    from dataclasses import replace
    session,a,client,events=setup_session(tmp_path)
    gaps={} if binding=='missing' else {**session.admission_policy.goal_gaps,
        'other':asdict(GoalGap('other','another explicit goal','records',1,0,capability_ids=('measure@1',)))}
    session.admission_policy=replace(session.admission_policy,goal_gaps=gaps)
    result=session.run(project_id='p',run_id='r',goal=INTENT['overall_goal'],project_intent=INTENT)
    assert result.status=='BLOCKED' and 'CAPABILITY_GOAL_BINDING_REQUIRED' in result.escalation_reason
    assert not list(session.store.run_dir('p','r').glob('node_results/*.json'))
    authority=session.runner._authority('p','r')
    assert not any(e['event_type']=='NODE_PERMIT_ISSUED' for e in authority.events())
