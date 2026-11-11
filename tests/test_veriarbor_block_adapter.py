from types import SimpleNamespace
from veriarbor.compatibility import PortCompatibility as C
from cgkn.adapters.veriarbor.block_adapter import leaf_block, local_scope, verification_key, component_port
from cgkn.component.ports import PortSpec


def graph():
    nodes = [SimpleNamespace(id=k, depends_on=deps) for k, deps in
             [('a', ()), ('b', ('a',)), ('c', ('b',)), ('d', ('c',))]]
    return SimpleNamespace(nodes=nodes, by_id={n.id: n for n in nodes},
                           topological_order=lambda: ('a', 'b', 'c', 'd'))


def test_initial_unqualified_boundary_inspects_only_direct_neighbors():
    affected, bubbles = local_scope(graph(), ['b'])
    assert affected == ('a', 'b', 'c')
    assert 'd' not in affected
    assert bubbles[0].expand


def test_identical_boundary_has_no_transitive_rechecks():
    affected, bubbles = local_scope(graph(), ['b'], boundary_relations={'b': C.IDENTICAL})
    assert affected == ('b',)
    assert bubbles[0].verification == ('block',)


def test_real_host_port_and_leaf_mapping():
    spec = PortSpec('input', 'artifact.request@2')
    p = component_port(spec, direction='input', schema={'type': 'object'}, semantic='request')
    assert p.version == '2'
    node = SimpleNamespace(id='leaf', capability_ref='cap@1')
    boundary = {'input_ports': [{'port_id': 'input', 'version': '2', 'schema': {'type': 'object'}, 'semantic': 'request'}],
                'output_ports': [], 'effects': {'reads': ['store'], 'persistence': 'read only'}}
    b = leaf_block(node, artifacts={'api.py': 'hash'}, boundary=boundary)
    assert b.input_ports[0] == p
    assert verification_key(b, 'accept', 'checker').artifact_hashes == (('api.py', 'hash'),)


def test_missing_boundaries_never_infer_certificate():
    import pytest
    with pytest.raises(ValueError, match='BLOCK_BOUNDARY_UNQUALIFIED'):
        leaf_block(SimpleNamespace(id='leaf', capability_ref='cap'), artifacts={'api': 'hash'}, boundary={})


def test_verification_projection_dedups_current_trusted_fail_only():
    import pytest
    from cgkn.adapters.veriarbor.verification_adapter import goal_verification_keys, reject_duplicate_measurement
    from cgkn.protocol.normalization import ContractError
    view = {'evidence_mode': 'production_provenance', 'subject_identities': {'api': 'a'}, 'goals': [
        {'id': 'g', 'acceptance': 'actual check', 'subject_refs': ['api'], 'milestone_contract': {'registry': {'v': 1}},
         'verdict': 'FAILED', 'evidence': {'node_id': 'n', 'receipt_hash': 'r', 'subjects': {'api': 'a'},
            'provenance': {'status': 'TRUSTED', 'chain': {'checker': {'hash': 'h'}}}}}]}
    rows = goal_verification_keys(view)
    assert rows[0]['disposition'] == 'NO_NOVEL_DELTA'
    with pytest.raises(ContractError, match='NO_NOVEL_DELTA'):
        reject_duplicate_measurement({'verification_dedup': rows}, goal_id='g')
    with pytest.raises(ContractError, match='NO_NOVEL_DELTA'):
        reject_duplicate_measurement({'verification_dedup': rows}, node_id='n')
    view['subject_identities']['api'] = 'changed'
    assert goal_verification_keys(view) == []
