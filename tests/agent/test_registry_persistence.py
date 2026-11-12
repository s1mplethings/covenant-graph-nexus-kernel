import json

import pytest

from cgkn.agent.capability_registry import SharedCapabilityRegistry
from cgkn.execution.node_effects import execution_scope
from tools.core_governance_e2e import setup, session


@pytest.mark.negative
@pytest.mark.boundary
def test_registry_save_without_permit_does_not_create_parent(tmp_path):
    target = tmp_path / 'outside' / 'registry.json'
    with pytest.raises(ValueError, match='PERMIT_REQUIRED'):
        SharedCapabilityRegistry().save(target)
    assert not target.parent.exists()


@pytest.mark.happy_path
@pytest.mark.boundary
def test_registry_save_stages_through_host_library_effect(tmp_path):
    authority, contract, source = setup(tmp_path)
    node = session(authority, contract, 'registry', source)
    authority.begin_node_execution(node.permit_id)
    registry = SharedCapabilityRegistry()
    with execution_scope(authority, node.permit_id):
        path = registry.save('registry.json')
    assert path == authority.staging_dir(node.permit_id) / 'registry.json'
    assert json.loads(path.read_text(encoding='utf-8')) == registry.as_dict()
    assert 'PERSISTENT_LIBRARY_WRITE' in [
        event['data'].get('operation') for event in authority.events()]
    assert not authority.node_view('registry')['commit_receipt_id']


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize('relative', [True, False])
def test_registry_save_cannot_escape_permit_staging(tmp_path, relative):
    authority, contract, source = setup(tmp_path)
    node = session(authority, contract, 'registry', source)
    authority.begin_node_execution(node.permit_id)
    target = '../escape.json' if relative else tmp_path / 'outside' / 'escape.json'
    with execution_scope(authority, node.permit_id):
        with pytest.raises(ValueError, match='OUTPUT_BINDING_REJECT'):
            SharedCapabilityRegistry().save(target)
    assert not list(tmp_path.rglob('escape.json'))
