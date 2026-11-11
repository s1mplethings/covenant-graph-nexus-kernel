import pytest

from cgkn.orchestration import CapabilityTree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.protocol.compiler import TableSnapshot, compile_planner
from cgkn.protocol.context_pack import failure_context
from cgkn.protocol.normalization import ContractError
from tests.protocol.test_repair_path import packet
from tests.protocol.test_repair_target_feedback import fixture

pytestmark = [pytest.mark.boundary, pytest.mark.negative]


def setup_measurement(source_status='SUCCEEDED'):
    snapshot, tree = fixture()
    document = tree.as_dict()
    document['nodes'][1]['config']['goal_id'] = 'public'
    tree = CapabilityTree.from_dict(document)
    table = snapshot.document
    for i, row in enumerate(table['nodes']):
        row['execution_state'] = source_status if i == 0 else 'SUCCEEDED'
    return TableSnapshot(table), tree


def rejected_repair(snapshot, tree):
    with pytest.raises(ContractError) as caught:
        compile_planner({**packet(), 'action': 4, 'task_kind': 3}, snapshot,
                        bound_hash=snapshot.hash, tree=tree, context_identity='missing')
    assert caught.value.code == 'REPAIR_REQUIRES_OBSERVED_FAILURE'
    return caught.value


def test_missing_evidence_exposes_existing_measurement_without_authorizing_repair():
    snapshot, tree = setup_measurement()
    before = tree.as_dict()
    error = rejected_repair(snapshot, tree)
    assert error.details['allowed_values'] == []
    assert 3 in error.details['allowed_action_ids']
    choices = error.details['existing_measurements']
    assert [choice['target'] for choice in choices] == [1]
    assert choices[0]['dependency_targets'] == [0]
    assert choices[0]['dependencies_ready'] is True
    result = compile_planner({'action': 3, 'target': 1}, snapshot,
                             bound_hash=snapshot.hash, tree=tree, context_identity='measure')
    assert [edit.operation for edit in result['edits']] == ['retry_node']
    assert apply_tree_edits(tree, result['edits'], known_capabilities={'code', 'measure'}).as_dict() == before
    assert tree.as_dict() == before


def test_blocked_measurement_does_not_hide_failed_prerequisite():
    snapshot, tree = setup_measurement('FAILED')
    error = rejected_repair(snapshot, tree)
    choice = error.details['existing_measurements'][0]
    assert choice['dependency_states'] == ['FAILED']
    assert choice['dependencies_ready'] is False
    assert 'prerequisites' in error.details['instruction']


def test_only_admitted_goal_measurements_are_suggested():
    snapshot, tree = fixture()  # A TEST leaf without a goal binding is not enough.
    error = rejected_repair(snapshot, tree)
    assert error.details['existing_measurements'] == []


def test_measurement_hint_never_bypasses_unknown_reconciliation():
    snapshot, tree = setup_measurement()
    document = snapshot.document
    document['repair_context'] = {'failures': [{
        'failure_domain': 'outcome_unknown', 'target_leaf_refs': ['sibling'],
        'artifact_paths': ['module.py'], 'acceptance_id': 'public'}]}
    snapshot = TableSnapshot(document)
    with pytest.raises(ContractError, match='OUTCOME_UNKNOWN_REQUIRES_RECONCILE'):
        compile_planner({'action': 3, 'target': 1}, snapshot,
                        bound_hash=snapshot.hash, tree=tree, context_identity='unknown')


def test_recovery_choices_survive_bounded_public_context():
    snapshot, tree = setup_measurement()
    error = rejected_repair(snapshot, tree)
    pack = failure_context({'goal': 'public goal', 'failure_details': {
        'decision_validation': {'protocol_error': error.as_dict()}}}, evidence_ref='raw.json')
    assert pack['previous_rejection']['existing_measurements'] == error.details['existing_measurements']
    assert pack['failures'] == []


@pytest.mark.parametrize('action', [7, 8])
def test_self_dependency_reports_graph_safe_ids_without_mutating_graph(action):
    snapshot, tree = setup_measurement()
    before = tree.as_dict()
    proposal = {'action': 7, 'target': 0, 'deps': [0]} if action == 7 else {
        **packet(), 'action': 8, 'deps': [0]}
    with pytest.raises(ContractError) as caught:
        compile_planner(proposal, snapshot, bound_hash=snapshot.hash,
                        tree=tree, context_identity='self')
    error = caught.value
    assert error.code == 'SELF_DEPENDENCY'
    assert error.fields == ('deps',)
    assert error.details['current_value'] == [0]
    assert error.details['allowed_values'] == [2]  # Excludes self and dependent checker.
    assert error.details['existing_dependency_targets'] == []
    assert error.details['auto_generate_semantics'] is False
    assert tree.as_dict() == before


def test_new_task_cannot_self_depend_and_legal_prerequisites_remain_admissible():
    snapshot, tree = setup_measurement()
    document = snapshot.document
    document['nodes'].append({'node_id': 'new', 'execution_state': 'PENDING'})
    snapshot = TableSnapshot(document)
    proposal = {**packet(), 'target': 3, 'deps': [3]}
    with pytest.raises(ContractError, match='SELF_DEPENDENCY') as caught:
        compile_planner(proposal, snapshot, bound_hash=snapshot.hash,
                        tree=tree, context_identity='new-self')
    assert caught.value.details['allowed_values'] == [0, 1, 2]
    result = compile_planner({**proposal, 'deps': [0]}, snapshot,
                             bound_hash=snapshot.hash, tree=tree, context_identity='legal')
    changed = apply_tree_edits(tree, result['edits'], known_capabilities={'code', 'measure'})
    assert changed.by_id['new'].depends_on == ('n',)


@pytest.mark.parametrize('action', [7, 8])
def test_downstream_dependency_reports_cycle_choices_without_rewriting_proposal(action):
    snapshot, tree = setup_measurement()
    before = tree.as_dict()
    proposal = {'action': 7, 'target': 0, 'deps': [2, 1]} if action == 7 else {
        **packet(), 'action': 8, 'deps': [2, 1]}
    with pytest.raises(ContractError) as caught:
        compile_planner(proposal, snapshot, bound_hash=snapshot.hash,
                        tree=tree, context_identity='downstream-cycle')
    error = caught.value
    assert error.code == 'DEPENDENCY_CYCLE'
    assert error.fields == ('deps',)
    assert error.details['current_value'] == [2, 1]
    assert error.details['allowed_values'] == [2]
    assert proposal['deps'] == [2, 1] and tree.as_dict() == before
    # A separate explicit corrected proposal is required; no automatic deletion.
    corrected = {**proposal, 'deps': [2]}
    result = compile_planner(corrected, snapshot, bound_hash=snapshot.hash,
                             tree=tree, context_identity='explicit-legal-dependency')
    after = apply_tree_edits(tree, result['edits'], known_capabilities={'code', 'measure'})
    assert after.by_id['n'].depends_on == ('inspect',)


def test_existing_prerequisites_are_reported_without_changing_rejected_proposal():
    snapshot, tree = setup_measurement()
    before = tree.as_dict()
    proposal = {'action': 7, 'target': 1, 'deps': [1]}
    with pytest.raises(ContractError) as caught:
        compile_planner(proposal, snapshot, bound_hash=snapshot.hash,
                        tree=tree, context_identity='preserve-prerequisites')
    assert caught.value.details['existing_dependency_targets'] == [0]
    assert proposal['deps'] == [1]
    assert tree.as_dict() == before


def test_exact_admission_choices_and_instruction_survive_large_public_feedback():
    # High numeric IDs must remain selectable; truncating the first 24 values
    # silently changes the legal choice set of a large production DAG.
    instruction = 'Preserve existing dependencies or explicitly choose new prerequisites. ' * 12
    error = {'code': 'DEPENDENCY_CYCLE', 'field': 'deps',
             'current_value': [91], 'allowed_values': list(range(89)) + [99],
             'existing_dependency_targets': [87, 88], 'instruction': instruction,
             'private_checker_implementation': 'DO_NOT_EXPOSE',
             'raw_response': 'DO_NOT_EXPOSE'}
    pack = failure_context({'goal': 'public goal', 'failure_details': {
        'decision_validation': {'protocol_error': error}}}, evidence_ref='raw.json')
    feedback = pack['previous_rejection']
    assert feedback['allowed_values'] == error['allowed_values']
    assert feedback['instruction'] == instruction
    assert feedback['existing_dependency_targets'] == [87, 88]
    assert 'private_checker_implementation' not in feedback
    assert 'raw_response' not in feedback
