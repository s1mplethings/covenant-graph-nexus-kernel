"""Metadata refresh cannot confer acceptance and must reload canonical bindings."""
import json
import pytest
from cgkn.agent.project_loop import ProjectSession
from cgkn.state import RunState,NodeExecutionRecord
from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
from cgkn.state.provenance import file_hash
from tests.fixtures.provenance import setup,check

def metadata_view_guard(original):
    def guarded(*args,**kwargs):
        import inspect
        # Persisting a changed subject or newly recorded witness renders the
        # real authenticated view. Only unused pre-read views are redundant.
        assert inspect.currentframe().f_back.f_code.co_name=='render', 'metadata read must not rebuild all historical verdicts'
        return original(*args,**kwargs)
    return guarded

def test_subject_refresh_reloads_disk_metadata_and_invalidates_changed_object(tmp_path,monkeypatch):
    f=setup(tmp_path,production=True);a=f['acceptance'];check(f)
    assert a.view()['complete']
    stale=GoalAcceptance(f['store'],'p','r',a.requirements,a.checkers)
    a.bind_subjects({**a.data['subjects'],'other':'retained'})
    f['artifact'].write_text('{"value":8}',encoding='utf-8')
    current_hash=file_hash(f['artifact'])
    loop=ProjectSession.__new__(ProjectSession);loop.acceptance=stale
    loop.subject_snapshot=lambda paths:{'object':current_hash}
    plan={'goals':[{'subject_refs':['object'],'milestone_contract':{'design':{'artifacts':[{'path':'object'}]}}}]}
    with monkeypatch.context() as m:
        m.setattr(stale,'view',metadata_view_guard(stale.view))
        loop._refresh_milestone_subjects(plan)
    assert stale.data['subjects']=={'object':current_hash,'other':'retained'}
    assert not stale.view()['complete']

@pytest.mark.parametrize('tamper',[False,True])
def test_recovery_still_authenticates_committed_receipt_without_global_view(tmp_path,monkeypatch,tamper):
    f=setup(tmp_path,production=True);a=f['acceptance'];original=a.record
    def interrupted(*args,**kwargs):raise KeyboardInterrupt()
    a.record=interrupted
    with pytest.raises(KeyboardInterrupt):check(f)
    a.record=original;store=f['store'];result=store.load_result('p','r','checker')
    store.save_run(RunState('p','r',nodes={'checker':NodeExecutionRecord('checker','SUCCEEDED',['attempt-0001'])}))
    if tamper:
        witness=json.loads((store.root/result.outputs['goal_check']['provenance_ref']['path']).read_text())
        (store.root/witness['observation_ref']['path']).write_text('{}')
    loop=ProjectSession.__new__(ProjectSession);loop.store=store;loop.acceptance=a
    with monkeypatch.context() as m:
        m.setattr(a,'view',metadata_view_guard(a.view))
        loop._reconcile_completed_checks('p','r')
    assert a.view()['complete'] is (not tamper)
    assert len(a.data['checks'])==1

def test_metadata_reload_still_rejects_modified_frozen_requirements(tmp_path):
    f=setup(tmp_path,production=True);a=f['acceptance']
    path=f['store'].run_dir('p','r')/'goal_acceptance.json'
    data=json.loads(path.read_text());data['requirements']['R']['must']=False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='immutable acceptance bindings changed'):a._reload()
