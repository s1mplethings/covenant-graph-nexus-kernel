"""Unrelated registry entries cannot change an immutable scoped contract."""
import copy
import pytest
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.repair import PublicContractRegistry,contract_diff
from cgkn.protocol.normalization import ContractError
from tests.protocol.test_repair_path import initial,failed_snapshot,repair_packet,run

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def expanded_registry():
    original,tree=initial()
    document=failed_snapshot(original).document
    extra=copy.deepcopy(document['public_contract_registry']['entries'][0])
    extra['contract_id']='unrelated-owner';extra['artifact_paths']=['unrelated.py']
    document['public_contract_registry']['entries'].append(extra)
    return original,TableSnapshot(document),tree

def test_unchanged_selected_contract_survives_unrelated_registry_growth():
    old,new,tree=expanded_registry()
    before=PublicContractRegistry(old.document['public_contract_registry']).select(['module.py'])
    after=PublicContractRegistry(new.document['public_contract_registry']).select(['module.py'])
    assert before['registry_hash']!=after['registry_hash'] and before['entries']==after['entries']
    result=contract_diff(before,after)
    assert result['drift_count']==0
    assert result['registry_context_change']=={'before':before['registry_hash'],'after':after['registry_hash']}
    compiled=run(repair_packet(),new,tree)
    assert any(e.operation=='retry_node' and e.node_id=='n' for e in compiled['edits'])

@pytest.mark.parametrize('change',['definition','version','evidence','nested_registry_hash'])
def test_real_scoped_contract_drift_still_requires_explicit_review(change):
    old,new,tree=expanded_registry();doc=new.document
    entry=doc['public_contract_registry']['entries'][0]
    if change=='definition':entry['definition']['fields']['value']='str'
    elif change=='version':entry['version']=2
    elif change=='evidence':entry['evidence_refs']=['different-declaration.json']
    else:entry['definition']['registry_hash']='changed public field'
    with pytest.raises(ContractError,match='PUBLIC_CONTRACT_CHANGE_REQUIRES_EXPLICIT_VERSION_REVIEW'):
        run(repair_packet(),TableSnapshot(doc),tree)
