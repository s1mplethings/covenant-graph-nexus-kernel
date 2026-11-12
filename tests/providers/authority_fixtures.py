"""Real Host admission for isolated loopback transport tests."""
from dataclasses import asdict
from contextlib import contextmanager
from cgkn.state import FileRunStore
from cgkn.agent.project_agent import AdmissionPolicy, ProjectProposal
from cgkn.orchestration.capability_tree import CapabilityTree, CapabilityNode
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.runtime.node_authority import ExecutionAuthority
from cgkn.execution.node_effects import execution_scope
from veriarbor.capability import CapabilityContract, AcceptanceMetric


@contextmanager
def authorized_transport(root, calls=8):
    authority = ExecutionAuthority(FileRunStore(root), 'transport-test', 'offline')
    contract = CapabilityContract('transport@1', 'Inspect isolated loopback transport',
        acceptance_metrics=(AcceptanceMetric('wire_matches', '==', True),),
        positive_controls=('valid loopback response',), negative_controls=('schema violation',))
    leaf = build_leaf_contract(goal=contract.semantic_goal, kind='INSPECTION',
        scope=['response'], acceptance=['observation'], checker='fixture.transport',
        output_identity='response', effect_domains=['external_network'],
        executor='fixture.transport@1', dependencies=[], subject='response',
        expected_observation='Exact loopback request and response',
        pass_fail_rule='Test assertions inspect serialized request and usage')
    catalog = {'transport@1': {'executor_ref': 'fixture.transport@1', 'config': {'leaf_contract': leaf}}}
    proposal = ProjectProposal('admit', 'transport-test', 1, 'transport', (),
        ({'operation': 'add_node', 'node_id': 'call', 'parent_id': 'root', 'capability_ref': 'transport@1'},),
        reason_summary='Offline transport fixture', target_capability_id='transport@1',
        strategy_capabilities=('transport@1',), exploration_reason='Loopback only',
        exploration_budget=1, exploration_measure='Wire assertions')
    aid, admitted = authority.admit(CapabilityTree('transport', (CapabilityNode('root'),)), 1,
        proposal, known_capabilities={'transport@1'}, catalog=catalog,
        policy=AdmissionPolicy(project_id='transport-test', capability_contracts={'transport@1': asdict(contract)},
            allow_remote_effects=True, execution_budget={'calls': calls}))
    assert admitted.valid, admitted.code
    authority.commit_tree(aid)
    permit = authority.issue_permit(node_id='call', contract=contract)
    authority.begin_node_execution(permit.permit_id)
    with execution_scope(authority, permit.permit_id):
        yield authority, permit
