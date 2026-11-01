"""A measured business FAIL remains distinct from checker failure after DAG qualification."""
import json
from dataclasses import replace
import pytest
from tests.fixtures.provenance import setup
from cgkn.execution import BlockStatus
from cgkn.execution.deliverables import SubjectDeliverableChecker
from cgkn.executors import ExecutorRegistry
from cgkn.executors.measurement import EvidenceBoundExecutor,FileMeasurementExecutor
from cgkn.orchestration import CapabilityNode,CapabilityTree,compile_tree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.runtime import DAGRunner
from cgkn.state.provenance import ProvenanceGate,file_hash,reference

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def measured(tmp_path,value=8):
    f=setup(tmp_path,value=value);h=file_hash(f['artifact'])
    contracts={'c':{'goal_id':'g','version':'1','path':'candidate.json','field':'value','subject':'object',
                    'artifact_sha256':h,'predicate':{'operator':'equal','expected':7}}}
    executor=EvidenceBoundExecutor(FileMeasurementExecutor(f['root'],contracts),f['store'],f['source'],{'object':f['artifact']},'candidate','v1')
    registry=ExecutorRegistry();registry.register(executor)
    # Force a negative deliverable in both controls; a positive business claim
    # must never be promoted from a failed final execution.
    registry.register(SubjectDeliverableChecker(lambda _: {'object':h},{'business':lambda r,c:{
        'passed':False,'observed':r.as_dict()['input_values']['execution_receipt']['outputs'],
        'evidence_refs':[dict(r.input_values['execution_receipt_ref'])]}}))
    leaf=build_leaf_contract(goal='independently measure public predicate',kind='TEST',scope=['object'],
        acceptance=['business'],checker='business-check',output_identity='object',effect_domains=['measurement'],
        executor='measure.file@1',subject='object',expected_observation='actual stored integer',pass_fail_rule='value equals 7')
    tree=CapabilityTree('value must equal 7',(CapabilityNode('checker',capability_ref='measure.file@1',
        config={'executor_ref':'measure.file@1','inputs':{'contract_id':'c'},'leaf_contract':leaf}),))
    summary=DAGRunner(registry,f['store'],deliverable_checkers={'business-check':'deliverable.subjects@1'}).run(
        project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    assert summary.status=='FAILED'
    result=f['store'].load_result('p','r','checker');assert result.status is BlockStatus.FAILED
    return f,result

def test_negative_business_measurement_survives_dag_deliverable_rejection(tmp_path):
    f,result=measured(tmp_path)
    gate=ProvenanceGate(f['store'],'p','r');report=gate.verify_check(result,f['goal'],f['acceptance'].data['subjects'])
    assert report['status']=='TRUSTED',report
    assert report['chain']['verdict']=='FAILED'
    f['acceptance'].record('g',result,executor_ref='measure.file@1')
    view=f['acceptance'].view()
    assert view['hard_verdict']=='FAILED' and view['evidence_coverage']==1 and not view['complete']

@pytest.mark.parametrize('attack',['missing','hash_tamper','checker_failed','wrong_path','metadata_only'])
def test_negative_business_shortcut_requires_exact_successful_raw_receipt(tmp_path,attack):
    f,result=measured(tmp_path);metadata=result.as_dict()['metadata'];ref=metadata['raw_execution_receipt_ref']
    path=f['store'].root/ref['path']
    if attack=='missing':path.unlink()
    elif attack=='hash_tamper':path.write_text(path.read_text()+' ')
    elif attack=='metadata_only':metadata.pop('raw_execution_receipt_ref')
    else:
        raw=json.loads(path.read_text())
        if attack=='checker_failed':raw['status']='FAILED';path.write_text(json.dumps(raw))
        else:
            path=path.with_name('unbound.json');path.write_text(json.dumps(raw))
        metadata['raw_execution_receipt_ref']=reference(f['store'].root,path)
    changed=replace(result,metadata=metadata)
    # Disposable tamper control updates the enclosing attempt so the new check
    # must reject the raw execution proof, not merely a changed envelope hash.
    run=f['store'].run_dir('p','r');f['store'].atomic_json(run/'attempts/checker/attempt-0001.json',changed.as_dict())
    assert ProvenanceGate(f['store'],'p','r').verify_check(changed,f['goal'],f['acceptance'].data['subjects'])['status']!='TRUSTED'

def test_failed_final_execution_cannot_promote_positive_business_claim(tmp_path):
    f,result=measured(tmp_path,value=7)
    assert result.outputs['goal_check']['verdict']=='VERIFIED'
    assert ProvenanceGate(f['store'],'p','r').verify_check(result,f['goal'],f['acceptance'].data['subjects'])['status']!='TRUSTED'
    f['acceptance'].record('g',result,executor_ref='measure.file@1')
    assert not f['acceptance'].view()['complete']
