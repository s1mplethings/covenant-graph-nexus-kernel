import hashlib
from dataclasses import replace
import pytest
from cgkn.state.provenance import put_evidence, freeze_goal_bindings, ProvenanceGate, ProvenanceError
from cgkn.state.checker_revision import bind_checker_revision
from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from tests.application.software_project.test_milestone_consumer import setup, CONSUMER
from tests.governed_measurement_support import execute_external_measurement as measure


def fixture(tmp_path, value=7):
    executor, request, acceptance, workspace = setup(tmp_path, CONSUMER, value=value)
    store=acceptance.store;root=store.run_dir('p','r');goal=acceptance.view()['goals'][0]
    original=dict(executor.consumer)
    store.immutable_json(root/'provenance_contract.json', {
        'kind':'ProvenanceContract','logical_task_id':'p/r','requirements':acceptance.requirements,
        'input_ref':put_evidence(store,'p','r',{'kind':'PublicInput','requirements':acceptance.requirements}),
        'environment_ref':put_evidence(store,'p','r',{'kind':'ToolEnvironment','fixture':True}),
        'workspace_root':str(workspace),'goals':{},'incremental_checker_bindings':{'independent':{
            'checker_ref':'project.acceptance@1','checker_hash':original['sha256'],
            'checker_version':'1','predicate':{'operator':'equal','expected':True}}}})
    freeze_goal_bindings(store,'p','r',{'goals':[goal]})
    source=tmp_path/'revised.py';source.write_text(CONSUMER+'\n# qualified identical public predicate\n')
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    raw=put_evidence(store,'p','r',{'kind':'QualificationObservation','positive':True,'negative':False,'mutation':False})
    proof={'kind':'CheckerRevisionQualification','status':'QUALIFIED','previous_checker_hash':original['sha256'],
           'checker_hash':sha,'requirement_policy':'UNCHANGED','historical_evidence_policy':'RETAIN_ORIGINAL_VERDICTS',
           'controls':[{'kind':kind,'passed':True,'evidence_ref':raw} for kind in ('positive','negative','mutation')]}
    decision={'checker_key':'independent','previous_checker_hash':original['sha256'],'source_path':str(source),
              'source_sha256':sha,'qualification_ref':put_evidence(store,'p','r',proof),'reason':'Qualified observer correction'}
    return executor,request,acceptance,workspace,original,decision,proof


@pytest.mark.parametrize('value,verdict',[(7,'VERIFIED'),(6,'FAILED')])
@pytest.mark.boundary
@pytest.mark.happy_path
def test_revised_consumer_uses_same_goal_and_preserves_original_receipt(tmp_path,value,verdict):
    old,request,a,workspace,original,decision,proof=fixture(tmp_path,value)
    store=a.store;root=store.run_dir('p','r')
    result=measure(old,request);store.save_result(result);a.record('g',result,executor_ref='project.acceptance@1')
    frozen={p:p.read_bytes() for p in [root/'provenance_contract.json',root/'independent_consumer.json',root/'attempts/check/a1.json']}
    assert a.view()['goals'][0]['verdict']==verdict
    revision=bind_checker_revision(store,'p','r','independent',original,decision)
    assert bind_checker_revision(store,'p','r','independent',original,decision)==revision
    assert bind_checker_revision(store,'p','r','independent',original)==revision
    assert a.view()['goals'][0]['verdict']==verdict  # revision alone grants nothing
    new=ExternalAcceptanceExecutor(workspace,tmp_path,session_acceptance=a,consumer=original,qualified_revision=revision)
    current=measure(new,replace(request,attempt_id='a2'));store.save_result(current)
    assert current.outputs['goal_check']['checker_version']=='qualified-revision-1'
    a.record('g',current,executor_ref='project.acceptance@1')
    assert a.view()['goals'][0]['verdict']==verdict
    assert all(p.read_bytes()==raw for p,raw in frozen.items())
    gate=ProvenanceGate(store,'p','r');goal=a.view()['goals'][0];subjects=a.view()['subject_identities']
    assert gate.verify_check(result,goal,subjects)['status']=='TRUSTED'
    assert gate.verify_check(current,goal,subjects)['status']=='TRUSTED'
    (store.root/revision['source_ref']['path']).write_text('tampered')
    with pytest.raises(ProvenanceError):gate.binding()


@pytest.mark.parametrize('defect',['missing_negative','failed_mutation','changed_requirements','missing_evidence','stale_source','changed_predicate'])
@pytest.mark.boundary
@pytest.mark.negative
def test_unqualified_or_stale_revision_cannot_activate(tmp_path,defect):
    old,request,a,workspace,original,decision,proof=fixture(tmp_path)
    if defect=='missing_negative':proof['controls']=[c for c in proof['controls'] if c['kind']!='negative']
    elif defect=='failed_mutation':proof['controls'][-1]['passed']=False
    elif defect=='changed_requirements':proof['requirement_policy']='RELAXED'
    elif defect=='missing_evidence':proof['controls'][0]['evidence_ref']={'path':'p/r/missing.json','sha256':'0'*64}
    elif defect=='stale_source':decision['previous_checker_hash']='0'*64
    else:decision['predicate']={'operator':'equal','expected':False}
    decision['qualification_ref']=put_evidence(a.store,'p','r',proof)
    with pytest.raises((ValueError,ProvenanceError)):
        bind_checker_revision(a.store,'p','r','independent',original,decision)
    assert not list((a.store.run_dir('p','r')/'checker_revisions').glob('*.json'))
