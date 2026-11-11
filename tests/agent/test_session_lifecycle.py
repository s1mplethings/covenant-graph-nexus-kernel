"""Governed lifecycle wiring; offline clients, no real model qualification."""
import threading
import pytest
from tests.agent.test_goal_acceptance_integration import setup, action, PLAN
from cgkn.state import StateStoreError

def test_session_lock_rejects_another_planner_before_call(tmp_path):
    loop,a,client=setup(tmp_path,[action('plan',PLAN)],continuous=True)
    with a.store.exclusive_file(a.store.run_dir('p','r')/'session.lock'):
        with pytest.raises(StateStoreError,match='active coordinator'):
            loop.run(project_id='p',run_id='r',goal='g')
    assert not client.contexts

def test_stop_before_planner_then_resume(tmp_path):
    loop,a,client=setup(tmp_path,[action('plan',PLAN),action('execute',{},'check@1')],continuous=True)
    cancel=threading.Event();cancel.set()
    result=loop.run(project_id='p',run_id='r',goal='g',cancel=cancel,finish_when_verified=True)
    assert result.status=='STOPPED' and not client.contexts
    cancel.clear()
    result=loop.run(project_id='p',run_id='r',goal='g',resume=True,cancel=cancel,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED' and result.agent_calls==2
    before={str(p):p.read_bytes() for p in a.store.run_dir('p','r').rglob('attempt-*.json')}
    result=loop.run(project_id='p',run_id='r',goal='g',resume=True,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED' and result.agent_calls==0
    assert result.run_summary.execution_mode=='GOVERNED'
    assert before=={str(p):p.read_bytes() for p in a.store.run_dir('p','r').rglob('attempt-*.json')}

def test_stop_is_forwarded_to_existing_dag(tmp_path):
    loop,a,client=setup(tmp_path,[action('plan',PLAN),action('execute',{},'check@1')],continuous=True)
    stop=threading.Event();original=loop.runner.run;seen=[]
    def run(**kwargs):
        seen.append(kwargs['cancel']);stop.set();return original(**kwargs)
    loop.runner.run=run
    result=loop.run(project_id='p',run_id='r',goal='g',cancel=stop)
    assert seen==[stop] and not a.data['checks']
    assert result.status in {'STOPPED','BLOCKED'}

def test_failed_independent_outcome_cannot_shortcut_finish(tmp_path):
    loop,a,client=setup(tmp_path,[action('plan',PLAN),action('execute',{},'check@1'),action('finish')],wrong=True)
    result=loop.run(project_id='p',run_id='r',goal='g',finish_when_verified=True)
    assert result.status=='BLOCKED' and not a.view()['complete']
    assert a.store.load_run('p','r').nodes['n0002'].status=='SUCCEEDED'
