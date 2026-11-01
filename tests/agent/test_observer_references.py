from experiments.product_dev_113.observer import valid_history_reference

def test_scalar_and_multiple_actual_measurements_but_not_feedback_or_invalid_tools():
    history=[{'result':{'status':'COMPLETED','exit_code':0}}, {'framework_feedback':'not a tool'}, {'result':{'status':'INVALID_TOOL_ARGUMENTS'}}, {'result':{'status':'FAILED','exit_code':1}}]
    assert valid_history_reference(0,history)
    assert valid_history_reference([0,3],history)
    for value in ([],True,[0,1],[0,2],[9],'0'):
        assert not valid_history_reference(value,history)


def test_observer_source_changes_cannot_attest_original_candidate(tmp_path):
    from experiments.product_dev_113.observer import source_identity,altered_sources
    (tmp_path/'app.py').write_text('print("original")')
    before=source_identity(tmp_path)
    (tmp_path/'check.py').write_text('assert True')
    (tmp_path/'data.sqlite').write_bytes(b'runtime state')
    assert altered_sources(before,tmp_path)==[]
    (tmp_path/'app.py').write_text('print("repaired by checker")')
    assert altered_sources(before,tmp_path)==['app.py']
