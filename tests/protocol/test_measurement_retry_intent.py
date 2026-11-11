import pytest
from cgkn.protocol.compiler import TableSnapshot,compile_planner
from cgkn.protocol.normalization import ContractError
from tests.protocol.test_repair_target_feedback import fixture

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def failed_table():
    t,tree=fixture();d=t.document
    d['repair_context']={'failures':[{'acceptance_id':'A','failure_domain':'business','target_leaf_refs':['n'],
        'artifact_paths':['module.py'],'object_identity':'hash','evidence_refs':['current-check.json'],'actual':'wrong value','expected':'public value'}]}
    return TableSnapshot(d),tree

def test_failed_business_measurement_retry_preserves_checker_and_predicate():
    t,tree=failed_table();before=tree.as_dict()
    out=compile_planner({'action':3,'target':1},t,bound_hash=t.hash,tree=tree,context_identity='refresh')
    assert [(e.operation,e.node_id) for e in out['edits']]==[('retry_node','sibling')]
    assert tree.as_dict()==before
    assert not any(e.operation=='update_config' for e in out['edits'])

def test_same_business_failure_on_writer_still_requires_implementation_repair():
    t,tree=failed_table()
    with pytest.raises(ContractError,match='ACTION_MISMATCH_REPAIR_REQUIRED'):
        compile_planner({'action':3,'target':0},t,bound_hash=t.hash,tree=tree,context_identity='writer')

def test_measurement_retry_cannot_change_semantics():
    t,tree=failed_table()
    with pytest.raises(ContractError,match='RETRY_CHANGES_SEMANTICS'):
        compile_planner({'action':3,'target':1,'goal':'weaken checker'},t,bound_hash=t.hash,tree=tree,context_identity='changed')

def test_unknown_measurement_still_requires_reconciliation():
    t,tree=failed_table();d=t.document;d['repair_context']['failures'].append({'acceptance_id':'unknown','failure_domain':'outcome_unknown','target_leaf_refs':['sibling'],'artifact_paths':['module.py']});t=TableSnapshot(d)
    with pytest.raises(ContractError,match='OUTCOME_UNKNOWN_REQUIRES_RECONCILE'):
        compile_planner({'action':3,'target':1},t,bound_hash=t.hash,tree=tree,context_identity='unknown')
