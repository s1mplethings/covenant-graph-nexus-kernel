from dataclasses import replace
import json
import pytest
from cgkn.agent.action_composer import ActionComposer
from cgkn.agent.project_loop import AgentProjectLoop
from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.executors import ExecutorRegistry, ExecutorDescriptor
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.state.acceptance import GoalAcceptance, identity
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.execution.deliverables import SubjectDeliverableChecker, FileDeliverableChecker
from cgkn.state.task_feedback import digest

PLAN={'phases':[{'id':'usable','outcome':'current object works','depends_on':[]}], 'goals':[{'id':'current','phase_id':'usable','requirement_refs':['R1'],'acceptance':'persisted object is current input','subject_refs':['input'],'checker':'measure','task_refs':[]}]}
class Client:
    def __init__(self, actions): self.actions=list(actions);self.contexts=[]
    def complete(self, **kw):
        self.contexts.append(json.loads(kw['user']))
        return ProviderCompletion(json.dumps(self.actions.pop(0)), 'actual-agent', 'request', {}, 1)
def action(op, config=None, capability=''):
    cfg=dict(config or {})
    if op=='execute':
        if capability=='check@1':
            cfg['leaf_contract']=build_leaf_contract(goal='Measure the current public goal',kind='TEST',
                scope=['input'],acceptance=['measurement-envelope'],checker='measurement',
                output_identity='current-measurement',effect_domains=['measurement'],executor='check@1',
                subject='input',expected_observation='valid measured verdict and observed facts',
                pass_fail_rule='valid measurement envelope; GoalAcceptance independently interprets its verdict')
        elif capability=='produce@1':
            cfg['leaf_contract']=build_leaf_contract(goal='Persist requested fixture value',kind='IMPLEMENTATION',
                scope=['object.txt'],acceptance=['persisted-value'],checker='persisted',
                output_identity='object',effect_domains=['object'],executor='produce@1',
                expected_delta='new requested persisted value',fixture_value=cfg['value'])
    return dict(summary='fixture action',operation=op,config=cfg,capability=capability,node_id='',depends_on=[])
class Check:
    descriptor=ExecutorDescriptor('check@1','deterministic',('*',))
    def __init__(self, wrong=False):self.wrong=wrong
    def execute(self,r):
        return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,node_id=r.node_id,attempt_id=r.attempt_id,executor_ref=r.executor_ref,status=BlockStatus.SUCCEEDED,outputs={'goal_check':{'goal_id':'current','condition_hash':identity(PLAN['goals'][0]['acceptance']),'subjects':{'input':'v1'},'execution':'VALID','evidence_refs':['measured/database'],'observed': 'old' if self.wrong else 'current','verdict':'FAILED' if self.wrong else 'VERIFIED'}})
def setup(tmp_path, actions, wrong=False, continuous=False):
    store=FileRunStore(tmp_path);accept=GoalAcceptance(store,'p','r',{'R1':{'must':True}}, {'measure':'check@1'})
    accept.bind_subjects({'input':'v1'})
    client=Client(actions);composer=ActionComposer(client,ModelRoleConfig('agent','agent'))
    registry=ExecutorRegistry();registry.register(Check(wrong))
    def measurement(request,contract):
        out=request.as_dict()['input_values']['execution_receipt']['outputs'].get('goal_check',{})
        valid=(out.get('goal_id')=='current' and out.get('condition_hash')==identity(PLAN['goals'][0]['acceptance'])
            and out.get('subjects')=={'input':'v1'} and out.get('execution')=='VALID'
            and out.get('verdict') in {'VERIFIED','FAILED'} and bool(out.get('observed')) and bool(out.get('evidence_refs')))
        return {'passed':valid,'observed':out,'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}
    registry.register(SubjectDeliverableChecker(lambda c:{'input':'v1'},{'measurement-envelope':measurement}))
    runner=DAGRunner(registry,store,deliverable_checkers={'measurement':'deliverable.subjects@1'})
    loop=AgentProjectLoop(composer,runner,store,known_capabilities={'check@1'},worker_model='worker',capability_catalog={'check@1':{'executor_ref':'check@1'}},max_decisions=len(actions),acceptance=accept,continuous=continuous)
    return loop,accept,client

def test_actual_planning_dag_receipt_gap_and_view(tmp_path):
    loop,a,c=setup(tmp_path,[action('plan',PLAN),action('execute',{},'check@1'),action('finish')],True)
    result=loop.run(project_id='p',run_id='r',goal='verify current object')
    assert result.status=='BLOCKED'
    assert c.contexts[-1]['goal_acceptance']['goals'][0]['verdict']=='FAILED'
    assert a.view()['complete'] is False
    assert 'FAILED' in a.render().read_text()
    assert a.store.load_run('p','r').nodes['n0002'].status=='SUCCEEDED'
    assert len(a.data['checks'])==1

def test_verified_check_and_auto_checkpoint_no_replay(tmp_path):
    loop,a,c=setup(tmp_path,[action('plan',PLAN),action('execute',{},'check@1'),action('finish')],continuous=True)
    loop.max_decisions=1
    result=loop.run(project_id='p',run_id='r',goal='verify current object')
    assert result.status=='GOALS_VERIFIED' and a.view()['complete']
    assert len(a.store.load_run('p','r').nodes['n0002'].attempts)==1
    assert any(e.event_type=='AGENT_CHECKPOINT_CONTINUED' for e in a.store.load_events('p','r'))

def test_uncovered_must_stale_subject_and_no_requirement_weakening(tmp_path):
    loop,a,c=setup(tmp_path,[action('plan',PLAN),action('execute',{},'check@1'),action('finish')])
    loop.run(project_id='p',run_id='r',goal='g')
    a.bind_subjects({'input':'v2'})
    assert not a.view()['complete']
    changed=json.loads(json.dumps(PLAN));changed['goals'][0]['acceptance']='exit 0'
    with pytest.raises(ValueError,match='weakened'):a.propose(changed,CapabilityTree('g',()))
    changed=json.loads(json.dumps(PLAN));changed['phases'][0]['depends_on']=['usable']
    with pytest.raises(ValueError,match='cycle'):a.propose(changed,CapabilityTree('g',()))
    with pytest.raises(ValueError,match='another run'):
        a.record('current',replace(a.store.load_result('p','r','n0002'),run_id='other'),executor_ref='check@1')
    with pytest.raises(ValueError,match='producer'):
        a.record('current',a.store.load_result('p','r','n0002'),executor_ref='producer@1')
    restored=GoalAcceptance(a.store,'p','r',{'R1':{'must':True}},{'measure':'check@1'})
    assert restored.view()==a.view()


def test_rejected_large_plan_returns_actual_registry_error(tmp_path):
    bad=json.loads(json.dumps(PLAN));bad['goals'][0]['checker']='incorrect';bad['goals'][0]['acceptance']='large '*1000
    loop,a,c=setup(tmp_path,[action('plan',bad),action('plan',PLAN),action('execute',{},'check@1'),action('finish')])
    result=loop.run(project_id='p',run_id='r',goal='g')
    feedback=c.contexts[1]['failure_details']['decision_validation']
    assert feedback['error']=='unregistered checker; allowed keys: measure'
    assert 'decision_ref' in feedback
    assert result.status=='GOALS_VERIFIED'


def test_process_loss_keeps_unknown_effect_and_rejects_unreconciled_retry(tmp_path):
    loop,a,c=setup(tmp_path,[action('plan',PLAN),action('execute',{},'check@1')],continuous=True)
    checker=loop.runner.registry.resolve('check@1','check@1')
    def interrupted(request):raise KeyboardInterrupt('controlled process loss after dispatch')
    checker.execute=interrupted
    with pytest.raises(KeyboardInterrupt):loop.run(project_id='p',run_id='r',goal='g')
    retry=action('retry');retry['node_id']='n0002'
    restored,a2,c2=setup(tmp_path,[retry,action('finish')],continuous=True)
    # Recovery may inspect the checkpoint, but an Agent retry alone is not
    # evidence that an interrupted external effect is safe to repeat.
    restored.continuous=False
    restored._recover_interrupted('p','r',CapabilityTree('g',()),None)
    result=restored.run(project_id='p',run_id='r',goal='g',resume=True)
    assert result.status=='BLOCKED'
    assert 'INTERRUPTED_UNKNOWN' in json.dumps(c2.contexts[0]['failure_details'])
    assert restored.store.load_run('p','r').nodes['n0002'].attempts==['attempt-0001']
    assert len(a2.data['checks'])==0
    assert 'UNRESOLVED_OUTCOME' in json.dumps(c2.contexts[-1]['failure_details'])


def test_roll_forward_replan_keeps_failed_evidence_and_repairs_actual_object(tmp_path):
    new_plan=json.loads(json.dumps(PLAN));new_plan['phases'].append({'id':'repair','outcome':'correct current persisted object','depends_on':['usable']});new_plan['goals'][0]['phase_id']='repair'
    actions=[action('plan',PLAN),action('execute',{'value':'old'},'produce@1'),action('execute',{},'check@1'),action('plan',new_plan),action('execute',{'value':'current'},'produce@1'),action('execute',{},'check@1'),action('finish')]
    # Replacing the same object is an explicit affected-node retry, not a new
    # sibling that silently leaves an old successful version marked current.
    actions[4].update(operation='retry',node_id='n0002')
    loop,a,c=setup(tmp_path/'store',actions,continuous=True)
    loop.max_decisions=2
    file=tmp_path/'object.txt'
    class Produce:
        descriptor=ExecutorDescriptor('produce@1','fixture',('*',))
        def execute(self,r):
            file.write_text(r.task_context.node_config['value'])
            return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,node_id=r.node_id,attempt_id=r.attempt_id,executor_ref=r.executor_ref,status=BlockStatus.SUCCEEDED,outputs={'path':str(file)})
    loop.runner.registry.register(Produce());loop.known_capabilities=frozenset({'produce@1','check@1'});loop.capability_catalog['produce@1']={'executor_ref':'produce@1'}
    loop.runner.registry.register(FileDeliverableChecker(tmp_path,{'persisted-value':lambda root,c:
        {'passed':(root/'object.txt').read_text()==c['fixture_value'],'observed':{'value':(root/'object.txt').read_text()}}}))
    loop.runner.deliverable_checkers['persisted']='deliverable.files@1'
    checker=loop.runner.registry.resolve('check@1','check@1');original=checker.execute
    def measure(request):
        result=original(request);outputs=result.as_dict()['outputs'];outputs['goal_check']['observed']=file.read_text();outputs['goal_check']['verdict']='VERIFIED' if file.read_text()=='current' else 'FAILED'
        outputs['goal_check']['supersedes_receipts']=[row['receipt_hash'] for row in a.data['checks'] if row['goal_id']=='current']
        return replace(result,outputs=outputs)
    checker.execute=measure
    result=loop.run(project_id='p',run_id='r',goal='current persisted object')
    assert result.status=='GOALS_VERIFIED' and file.read_text()=='current'
    assert [r['verdict'] for r in a.data['checks']]==['FAILED','VERIFIED']
    assert len(a.data['plans'])==2 and c.contexts[3]['goal_acceptance']['goals'][0]['verdict']=='FAILED'
    assert a.view()['goals'][0]['phase_id']=='repair'


def test_unchanged_goal_frontier_changes_main_route_without_quota_stop():
    from cgkn.agent.composer import AgentDecisionContext
    c=Client([action('plan',PLAN)]*10)
    composer=ActionComposer(c,ModelRoleConfig('agent','first'))
    composer.set_runtime_context(lambda:{'raw_state':{'stdout':'{"artifact_hash":"same"}'},'public_feedback':'historical frozen failure'},['first','second'])
    context=AgentDecisionContext('p','r','g',1,CapabilityTree('g',()),(),{}, {},{},goal_acceptance={'goals':[{'id':'g','verdict':'INSUFFICIENT_EVIDENCE','evidence':None}]})
    for i in range(10):
        current_goals={'goals':[{'id':'g','verdict':'INSUFFICIENT_EVIDENCE','evidence':{'node_id':str(i)}}]}
        decision=composer.decide(replace(context,decision_number=i+1,goal_acceptance=current_goals))
        assert not decision.needs_escalation and not decision.finish
    assert composer.config.model=='second'
    assert c.contexts[-1]['progress_observation']['unchanged_frontier_rounds']==10
    assert 'historical' in c.contexts[-1]['feedback_scope_rule']
    assert composer._frontier_models==['first','second']
