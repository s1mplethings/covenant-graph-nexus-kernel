import pytest
from cgkn.protocol.review_policy import review_kind, evaluator_disposition, qualify_evaluator, review_needed
from cgkn.protocol.repair import RepairIntentClassifier
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.normalization import ContractError
from test_repair_path import initial, failed_snapshot, repair_packet, run


def test_actual_model_identity_not_role_determines_review_kind():
    assert review_kind('Qwen-Flash',' qwen-flash ')=='SELF_CRITIQUE'
    assert review_kind('qwen-flash','deepseek-flash')=='CROSS_MODEL_REVIEW'
    assert review_kind('UNKNOWN','deepseek-flash')=='UNQUALIFIED_REVIEW'
    assert not review_needed('json_syntax') and review_needed('repair_strategy_switch')


@pytest.mark.parametrize('signal',['checker_failed','empty_test_collection','object_version_mismatch',
    'contract_contradiction','positive_control_failed','negative_control_passed','mutation_control_passed'])
def test_evaluator_suspicion_blocks_real_repair_compiler(signal):
    s,t=initial();doc=failed_snapshot(s).document
    doc['repair_context']['failures'][0]['evaluator_evidence']={signal:True}
    with pytest.raises(ContractError,match='EVALUATOR_SUSPECTED'):
        run(repair_packet(),TableSnapshot(doc),t)


def test_qualification_requires_positive_negative_and_binding_controls():
    r={key:'ref' for key in ('contract_ref','object_hash','checker_hash','positive_control_ref','negative_control_ref')}
    r.update(test_ids=['test_one'],positive_control_passed=True,negative_control_rejected=True,
             object_version_verified=True,contract_derived=True)
    assert qualify_evaluator(r)=='QUALIFIED'
    for key in ('test_ids','object_hash','negative_control_rejected','positive_control_passed'):
        assert qualify_evaluator({**r,key:False})=='INVALID_EVALUATOR'
    assert qualify_evaluator({**r,'mutation_applicable':True})=='INVALID_EVALUATOR'
    assert RepairIntentClassifier.classify(4,[{'failure_domain':'HARNESS'}])['next_operation']=='EVALUATOR_QUALIFICATION'
