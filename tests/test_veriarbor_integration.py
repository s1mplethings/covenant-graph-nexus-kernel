"""Host conversions and safety boundaries, with no Provider calls."""
from copy import deepcopy
import pytest
from cgkn.adapters.veriarbor.certificate_adapter import certificates
from cgkn.adapters.veriarbor.dag_adapter import select_batch
from cgkn.adapters.veriarbor.tree_adapter import dependency_ready_goals


def test_no_certificate_from_self_report_or_stale_subject():
    view = {'evidence_mode': 'production_provenance', 'subject_identities': {'a.py': 'v1'},
            'goals': [{'id': 'g', 'verdict': 'VERIFIED', 'acceptance': 'contract',
                       'evidence': {'subjects': {'a.py': 'v1'}, 'receipt_hash': 'receipt', 'condition_hash': 'contract',
                                    'provenance': {'status': 'TRUSTED', 'chain': {'checker': {'hash': 'c1', 'ref': 'checker'}}}}}]}
    assert certificates(view)['g'].artifact_versions == {'a.py': 'v1'}
    for delta in ('untrusted', 'stale', 'legacy'):
        changed = deepcopy(view)
        if delta == 'untrusted': changed['goals'][0]['evidence']['provenance']['status'] = 'UNTRUSTED'
        if delta == 'stale': changed['subject_identities']['a.py'] = 'v2'
        if delta == 'legacy': changed['evidence_mode'] = 'legacy_unverified_provenance'
        assert certificates(changed) == {}


def test_same_gui_file_and_running_writer_serialize():
    configs = {'gui-a': {'parallel_safe': True, 'resources': {'gui.py': 'write'}},
               'gui-b': {'parallel_safe': True, 'resources': {'gui.py': 'write'}},
               'api': {'parallel_safe': True, 'resources': {'api.py': 'read'}}}
    assert select_batch(configs, slots=3) == ('api', 'gui-a')
    assert select_batch({'gui-b': configs['gui-b']}, slots=2, running=[('gui-a', configs['gui-a'])]) == ()


def test_unknown_effect_blocks_transitive_dependency():
    goals = [{'id': 'a', 'verdict': 'VERIFIED', 'subject_refs': ['a.py']},
             {'id': 'b', 'verdict': 'VERIFIED', 'milestone_contract': {'dependency_goal_ids': ['a']}},
             {'id': 'c', 'verdict': 'FAILED', 'milestone_contract': {'dependency_goal_ids': ['b']}}]
    assert dependency_ready_goals(goals, ['a.py']) == []


def test_backjump_uses_earliest_matching_checkpoint_and_preserves_siblings():
    from types import SimpleNamespace
    from cgkn.adapters.veriarbor.backtracking_adapter import recommendation
    def node(key, strategy, scope):
        return SimpleNamespace(id=key, config={'repair_contract': {
            'strategy_fingerprint': strategy, 'decision_checkpoint': {'reversible': True, 'restore_scope': [scope]}}})
    tree = SimpleNamespace(nodes=[node('first', 's', 'a.py'), node('sibling', 'other', 'b.py'), node('last', 's', 'a.py')])
    result = recommendation(tree, 's')
    assert result['id'] == 'first'
    assert result['affected_nodes'] == ('a.py',)
    assert recommendation(tree, 'unknown') is None


def test_low_sample_slot_policy_remains_bounded_and_respects_conflicts():
    configs = {'a': {'parallel_safe': True, 'strategy_statistics': {'samples': 20, 'reward': 15}},
               'b': {'parallel_safe': True, 'strategy_statistics': {'samples': 0, 'reward': 0}}}
    assert select_batch(configs, slots=1) == ('b',)
