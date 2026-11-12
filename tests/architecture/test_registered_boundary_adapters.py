"""Finite public import and access-delegation controls; no qualification claims."""
import importlib
from types import SimpleNamespace
import pytest

@pytest.mark.boundary
@pytest.mark.parametrize('module', ['cgkn.adapters', 'cgkn.adapters.veriarbor', 'cgkn.agent', 'cgkn.artifacts', 'cgkn.capabilities', 'cgkn.compiler', 'cgkn.component', 'cgkn.execution', 'cgkn.executors', 'cgkn.governance', 'cgkn.growth', 'cgkn.orchestration', 'cgkn.protocol', 'cgkn.providers', 'cgkn.runtime', 'cgkn.state', 'cgkn.telemetry'])
def test_public_package_exports_resolve(module):
    package=importlib.import_module(module)
    for name in getattr(package,'__all__',()):
        assert getattr(package,name) is not None

@pytest.mark.boundary
@pytest.mark.negative
def test_archive_reader_preserves_access_denial():
    from cgkn.adapters.veriarbor.corpus_adapter import CorpusArchive
    calls=[]
    def reader(ref):
        calls.append(ref)
        if ref!='public':raise PermissionError('outside declared scope')
        return b'public data'
    archive=CorpusArchive(reader)
    assert archive.read('public')==b'public data'
    with pytest.raises(PermissionError):archive.read('private')
    assert calls==['public','private']

@pytest.mark.boundary
def test_metadata_adapters_preserve_unknown_cost_and_existing_event():
    from cgkn.adapters.veriarbor.accounting_adapter import call_context
    from cgkn.adapters.veriarbor.event_adapter import event_payload
    from cgkn.adapters.veriarbor.allocation_adapter import allocate_slots
    result=call_context(node_id='n',obligation='R',strategy='s',expected_delta=1,actual_delta=None,reason='inspect')
    assert result['actual_frontier_delta'] is None and 'cost' not in result
    event={'kind':'UNKNOWN','receipt':None}
    assert event_payload(SimpleNamespace(as_dict=lambda:dict(event)))==event
    assert allocate_slots({'b':{},'a':{}})==[{'id':'a','allocated':1},{'id':'b','allocated':1}]

@pytest.mark.negative
@pytest.mark.boundary
def test_impact_adapter_requires_bound_original_node():
    from cgkn.adapters.veriarbor.impact_adapter import plan_acceptance_changes
    from cgkn.orchestration.capability_tree import CapabilityTree
    from cgkn.orchestration.execution_dag import compile_tree
    state={'plans':[{'goals':[]}],'subjects':{},'checks':[]}
    with pytest.raises(ValueError,match='unknown changed node'):
        plan_acceptance_changes(compile_tree(CapabilityTree('root',())),state,['invented'])
