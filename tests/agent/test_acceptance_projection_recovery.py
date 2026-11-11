import json
import pytest
from cgkn.agent.project_loop import ProjectSession
from cgkn.state import RunState,NodeExecutionRecord
from tests.agent.test_goal_acceptance_integration import setup,action,PLAN

@pytest.mark.parametrize('wrong',[False,True])
def test_resume_projects_committed_check_before_next_planning_without_execution(tmp_path,wrong):
    loop,a,client=setup(tmp_path,[action('plan',PLAN),action('execute',{},'check@1')],wrong=wrong,continuous=True)
    original=a.record
    def interrupted(*args,**kwargs):raise KeyboardInterrupt('after immutable checker commit before acceptance projection')
    a.record=interrupted
    with pytest.raises(KeyboardInterrupt):loop.run(project_id='p',run_id='r',goal='g')
    root=a.store.run_dir('p','r');before={str(p):p.read_bytes() for p in (root/'attempts').rglob('*.json')}
    assert not a.data['checks']
    restored,a2,client2=setup(tmp_path,[action('finish')],continuous=True)
    seen=[]
    class Stop(Exception):pass
    def observe(context):seen.append(context.goal_acceptance);raise Stop()
    restored.composer.decide=observe
    with pytest.raises(Stop):restored.run(project_id='p',run_id='r',goal='g',resume=True)
    assert seen[0]['goals'][0]['verdict']==('FAILED' if wrong else 'VERIFIED')
    assert a2.view()['complete'] is (not wrong)
    assert not client2.contexts
    assert all(__import__('pathlib').Path(p).read_bytes()==raw for p,raw in before.items())
    assert len(a2.data['checks'])==1
    restored._reconcile_completed_checks('p','r')
    assert len(a2.data['checks'])==1
    events=[e for e in a2.store.load_events('p','r') if e.event_type=='ACCEPTANCE_CHECK_RECOVERED']
    assert len(events)==1 and events[0].data['executor_replayed'] is False

@pytest.mark.parametrize('attack',['none','changed_candidate','changed_observation','missing_observation','unknown','model_claim','state_receipt_mismatch'])
def test_recovery_uses_existing_provenance_and_never_upgrades_invalid_evidence(tmp_path,attack):
    from tests.fixtures.provenance import setup as fixture,check
    from cgkn.state.provenance import file_hash
    from cgkn.state import StateStoreError
    f=fixture(tmp_path,production=True);a=f['acceptance'];original=a.record
    def interrupted(*args,**kwargs):raise KeyboardInterrupt()
    a.record=interrupted
    with pytest.raises(KeyboardInterrupt):check(f)
    a.record=original;store=f['store'];root=store.run_dir('p','r');result=store.load_result('p','r','checker')
    store.save_run(RunState('p','r',nodes={'checker':NodeExecutionRecord('checker','SUCCEEDED',['attempt-0001'])}))
    if attack=='changed_candidate':
        f['artifact'].write_text('{"value":8}');a.bind_subjects({'object':file_hash(f['artifact'])})
    if attack in {'changed_observation','missing_observation'}:
        witness=json.loads((store.root/result.outputs['goal_check']['provenance_ref']['path']).read_text())
        raw=store.root/witness['observation_ref']['path']
        if attack=='missing_observation':raw.unlink()
        else:raw.write_text('{}')
    if attack=='unknown':
        state=store.load_run('p','r');state.nodes['checker'].status='BLOCKED';store.save_run(state)
    if attack=='model_claim':
        path=root/'node_results/checker.json';row=json.loads(path.read_text());row['executor_ref']='llm.cheap@1';path.write_text(json.dumps(row))
    if attack=='state_receipt_mismatch':
        state=store.load_run('p','r');state.nodes['checker'].attempts.append('attempt-0002');store.save_run(state)
    loop=ProjectSession.__new__(ProjectSession);loop.store=store;loop.acceptance=a
    if attack=='state_receipt_mismatch':
        with pytest.raises(StateStoreError,match='RECEIPT_STATE_MISMATCH'):loop._reconcile_completed_checks('p','r')
    else:loop._reconcile_completed_checks('p','r')
    assert a.view()['complete'] is (attack=='none')

