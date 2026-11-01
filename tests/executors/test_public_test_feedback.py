"""Actual product-test diagnostics must survive the existing repair context."""
import json
import pytest
from cgkn.executors import PythonTestExecutor
from tests.executors.test_test_observation import request
from tests.protocol.test_repair_path import initial,repair_packet,run,plain
from cgkn.protocol.compiler import TableSnapshot
from cgkn.orchestration.tree_edits import apply_tree_edits

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def test_actual_product_failure_reaches_repair_contract_without_private_oracle(tmp_path):
    test=tmp_path/'test_public.py'
    test.write_text("def test_public_operation():\n raise RuntimeError('PUBLIC_OPERATION_FAILURE_481')\n",encoding='utf8')
    execution=PythonTestExecutor(tmp_path).execute(request())
    observed=execution.outputs['test_observation']
    assert observed['status']=='FAIL'
    # Failure before this repair: only aggregate counts and raw XML existed.
    assert observed.get('failure_details'), 'Actual failure diagnostic is missing from structured observation'
    from cgkn.execution.test_results import public_test_feedback
    actual=public_test_feedback(observed)
    assert actual['failure_details'][0]['test_id'].endswith('::test_public_operation')
    assert 'PUBLIC_OPERATION_FAILURE_481' in json.dumps(actual)
    assert actual['failure_details'][0]['test_file']=='test_public.py'
    assert actual['failure_details'][0]['source_sha256']==observed['files'][0]['sha256']
    assert 'raw_report' not in actual and 'raw_report_ref' in actual
    snap,tree=initial();doc=snap.document
    doc['repair_context']={'failures':[{'acceptance_id':'product_tests','failure_domain':'business',
       'artifact_paths':['module.py'],'target_leaf_refs':['n'],'expected':'Actual product tests pass',
       'actual':actual,'object_identity':'candidate-hash','evidence_refs':['public-product-test-receipt.json'],
       'failure_code':'PRODUCT_TEST_FAILED'}]}
    repaired=apply_tree_edits(tree,run(repair_packet(),TableSnapshot(doc),tree)['edits'],known_capabilities={'code'})
    contract=plain(repaired.by_id['n'].config['repair_contract'])
    assert contract['observed_actual'][0]['actual']==actual
    assert contract['evidence_refs']==['public-product-test-receipt.json']
    from cgkn.protocol.context_pack import worker_contract_pack
    pack=worker_contract_pack({'goal':'repair public operation','config':plain(repaired.by_id['n'].config)})
    assert pack['actual_behavior'][0]['actual']==actual
    assert 'PUBLIC_OPERATION_FAILURE_481' in json.dumps(pack)
    assert pack['allowed_write_paths']==['module.py']

def test_large_product_diagnostic_is_explicitly_truncated_with_raw_hash(tmp_path):
    (tmp_path/'test_public.py').write_text("def test_long():\n raise RuntimeError('public-' * 2000)\n",encoding='utf8')
    observed=PythonTestExecutor(tmp_path).execute(request()).outputs['test_observation']
    assert observed.get('failure_details'), 'Missing public diagnostic projection'
    from cgkn.execution.test_results import public_test_feedback
    actual=public_test_feedback(observed)
    assert actual['failure_details'][0]['diagnostic_truncated']
    assert actual['raw_report_ref']['sha256']==observed['report_sha256']
    assert len(actual['failure_details'][0]['diagnostic'])<=4096

def test_invalid_or_unbound_test_observation_never_becomes_public_facts():
    from cgkn.execution.test_results import public_test_feedback
    for value in [{},{'kind':'PytestExecutionObservation','status':'INVALID'},
                  {'kind':'PytestExecutionObservation','status':'FAIL','report_sha256':None}]:
        with pytest.raises(ValueError,match='evidence required'):
            public_test_feedback(value)
