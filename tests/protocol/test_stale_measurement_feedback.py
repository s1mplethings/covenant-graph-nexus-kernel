import pytest
from cgkn.protocol.context_pack import failure_context

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

@pytest.mark.parametrize('kind,expected',[('TEST',[{'action':3,'target':1}]),('INSPECTION',[{'action':3,'target':1}]),('IMPLEMENTATION',None),('REPAIR',None)])
def test_stale_measurement_has_explicit_read_only_retry_option(kind,expected):
    source={'goal':'unchanged goal','tree':{'nodes':[{'id':'n1'},{'id':'n10','config':{'leaf_contract':{'task_kind':kind}}}]},
        'failure_details':{'decision_validation':{'error_type':'GraphEditRejected','error':'OBJECT_VERSION_MISMATCH: explicit affected-subgraph retry required n10'}}}
    pack=failure_context(source,evidence_ref='raw-context.json')
    assert pack['decision_rejection'].get('recovery_options')==expected
    assert pack['decision_rejection']['failure_domain']=='GRAPH_ADMISSION_NOT_BUSINESS_FAILURE'
    assert not pack['failures']
    assert source['goal']=='unchanged goal'

def test_arbitrary_rejection_does_not_grant_retry():
    source={'goal':'g','tree':{'nodes':[{'id':'m','config':{'leaf_contract':{'task_kind':'TEST'}}}]},
        'failure_details':{'decision_validation':{'error':'m has unknown external effects','error_type':'GraphEditRejected'}}}
    pack=failure_context(source,evidence_ref='raw')
    assert 'recovery_options' not in pack['decision_rejection']
