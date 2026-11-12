import pytest
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.progress import check_strategy_constraints
from cgkn.protocol.compiler import TableSnapshot, _feedback

RULE={'scope_paths':['unit.py'],'required_dimensions':['full_file_write'],
      'dimension_types':{'full_file_write':'boolean'},
      'forbidden_patterns':[{'full_file_write':False}],'evidence_refs':['failure.json']}

@pytest.mark.parametrize('strategy,code',[
    ({'problem':'repair','boundary':'all callers'},'STRATEGY_DIMENSIONS_REQUIRED'),
    ({'full_file_write':'true'},'STRATEGY_DIMENSION_TYPE')])
def test_missing_or_mistyped_declared_dimension_has_exact_bounded_correction(strategy,code):
    with pytest.raises(ContractError) as caught:
        check_strategy_constraints(strategy,['unit.py'],[RULE])
    error=_feedback(caught.value,{'strategy':strategy},TableSnapshot({'action_version':2}))
    assert error.code==code
    assert error.repair_class=='R5'
    assert error.details['admission_status']=='REPAIRABLE_SEMANTIC'
    assert error.details['allowed_values']['dimension_types']=={'full_file_write':'boolean'}
    assert error.details['semantic_patch_policy']['allowed_paths']==[['strategy']]
    assert ['scope'] in error.details['semantic_patch_policy']['immutable_paths']
    assert 'full_file_write' in str(error.details['allowed_values'])
    assert 'field not allowed' not in str(error.details['allowed_values'])

def test_false_strategy_still_rejected_and_unrelated_scope_untouched():
    with pytest.raises(ContractError,match='FALSIFIED_STRATEGY_FAMILY') as caught:
        check_strategy_constraints({'full_file_write':False},['unit.py'],[RULE])
    assert caught.value.repair_class=='R6'
    check_strategy_constraints({'full_file_write':True},['unit.py'],[RULE])
    check_strategy_constraints({},['elsewhere.py'],[RULE])
