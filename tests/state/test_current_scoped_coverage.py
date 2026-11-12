from dataclasses import replace
import pytest
from tests.state.test_checker_revision import fixture,measure
from cgkn.state.provenance import put_evidence, ProvenanceGate
from cgkn.state.checker_revision import bind_checker_revision
from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.adapters.veriarbor.verification_adapter import goal_verification_keys

@pytest.mark.parametrize('value,old_verdict,new_required_verdict',[(7,'VERIFIED','INSUFFICIENT_EVIDENCE'),(6,'FAILED','FAILED')])
def test_scoped_observer_needs_current_measurement_preserving_history(tmp_path,value,old_verdict,new_required_verdict):
    old,request,a,workspace,original,decision,proof=fixture(tmp_path,value)
    result=measure(old,request);a.store.save_result(result);a.record('g',result,executor_ref='project.acceptance@1')
    receipt=a.root/'attempts/check/a1.json';frozen=receipt.read_bytes()
    assert a.view()['goals'][0]['verdict']==old_verdict
    proof['requirement_scope']=['R'];decision['qualification_ref']=put_evidence(a.store,'p','r',proof)
    revision=bind_checker_revision(a.store,'p','r','independent',original,decision)
    view=a.view()
    assert view['goals'][0]['verdict']==new_required_verdict
    assert view['required_checker_versions']=={'g':'qualified-revision-1'}
    assert not goal_verification_keys(view)
    assert ProvenanceGate(a.store,'p','r').verify_check(result,view['goals'][0],view['subject_identities'])['status']=='TRUSTED'
    current=measure(ExternalAcceptanceExecutor(workspace,tmp_path,session_acceptance=a,consumer=original,qualified_revision=revision),replace(request,attempt_id='a2'))
    a.store.save_result(current);a.record('g',current,executor_ref='project.acceptance@1')
    assert a.view()['goals'][0]['verdict']==old_verdict
    assert receipt.read_bytes()==frozen

def test_unrelated_scoped_revision_preserves_existing_pass(tmp_path,monkeypatch):
    from tests.application.software_project import test_milestone_consumer as fixtures
    original_acceptance=fixtures.GoalAcceptance
    monkeypatch.setattr(fixtures,'GoalAcceptance',lambda store,p,r,requirements,checkers:
        original_acceptance(store,p,r,{**requirements,'S':{'must':True}},checkers))
    old,request,a,workspace,original,decision,proof=fixture(tmp_path)
    result=measure(old,request);a.store.save_result(result);a.record('g',result,executor_ref='project.acceptance@1')
    proof['requirement_scope']=['S'];decision['qualification_ref']=put_evidence(a.store,'p','r',proof)
    bind_checker_revision(a.store,'p','r','independent',original,decision)
    assert a.view()['goals'][0]['verdict']=='VERIFIED'
    assert 'g' not in a.view().get('required_checker_versions',{})
