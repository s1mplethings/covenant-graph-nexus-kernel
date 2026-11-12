from types import SimpleNamespace
import copy
import pytest

from cgkn.agent.catalog_composer import CatalogAgentComposer
from cgkn.orchestration import CapabilityTree,CapabilityNode
from cgkn.providers import ModelRoleConfig


def fixture():
    contract={'dependencies':[],'leaf_goal':'preserve original behavior'}
    cfg={'executor_ref':'fixture@1','leaf_contract':contract,'value':'original'}
    context=SimpleNamespace(capability_catalog={'fixture@1':{'executor_ref':'fixture@1','config':cfg}},
        tree=CapabilityTree('original goal',(CapabilityNode('n',capability_ref='fixture@1',config=cfg),)))
    return CatalogAgentComposer(None,ModelRoleConfig('agent','fixture')),context


@pytest.mark.happy_path
@pytest.mark.boundary
def test_catalog_binds_registered_executor_without_mutating_canonical_input():
    composer,context=fixture();before=copy.deepcopy(context.capability_catalog)
    raw={'edits':[{'operation':'add_node','payload':{'capability_ref':'fixture@1','parent_id':'',
        'depends_on':['dependency'],'config':{'value':'candidate'}}}]}
    result=composer._normalize_decision(raw,context)
    config=result['edits'][0]['payload']['config']
    assert config['executor_ref']=='fixture@1'
    assert config['leaf_contract']['dependencies']==['dependency']
    assert config['leaf_contract']['leaf_goal']=='preserve original behavior'
    assert config['value']=='candidate' and context.capability_catalog==before
    assert raw['edits'][0]['payload']['config']=={'value':'candidate'}


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize('field',['executor_ref','leaf_contract'])
def test_catalog_update_cannot_replace_execution_authority(field):
    composer,context=fixture()
    with pytest.raises(ValueError,match='cannot replace'):
        composer._normalize_decision({'edits':[{'operation':'update_config',
            'payload':{'node_id':'n','config':{field:'untrusted'}}}]},context)


@pytest.mark.negative
@pytest.mark.boundary
def test_catalog_unknown_capability_does_not_acquire_an_executor():
    composer,context=fixture()
    with pytest.raises(ValueError,match='not registered'):
        composer._normalize_decision({'edits':[{'operation':'add_node',
            'payload':{'capability_ref':'unregistered@1','config':{}}}]},context)
