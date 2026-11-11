"""Bounded offline tests of the actual Host admission, runner and run store."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

from cgkn.agent.project_agent import AdmissionPolicy, ProjectProposal, admit_proposal
from cgkn.agent.composer import AgentDecisionContext
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.state import FileRunStore
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry
from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.adapters.veriarbor import capability_adapter as adapter
from tests.qualification_support import probe_node, probe_runner
from tests.project_agent.test_project_agent import catalog, proposal, add_operation
from veriarbor.capability import AcceptanceMetric, CapabilityContract, CapabilityGateState, GoalGap, Observation
from veriarbor.model import Evidence
from veriarbor.skills import SkillManifest, SkillRegistry, SkillMatcher, SkillValidation


def contract():
    return CapabilityContract('quality', 'Improve parent outcome',
        forbidden_substitutes=('vocabulary.correction',), semantic_invariants=('influence',),
        acceptance_metrics=(AcceptanceMetric('quality_delta', '>=', 0.0),))


def policy():
    c = contract()
    gap = GoalGap('gap', 'root', 'quality_delta', 1.0, 0.5, capability_ids=('quality',))
    return AdmissionPolicy(project_id='demo', require_capability_contract=True,
        capability_contracts={'quality': asdict(c)}, goal_gaps={'gap': asdict(gap)})


class Witness:
    descriptor = ExecutorDescriptor('witness@1', 'deterministic', ('*',))
    def __init__(self):
        self.calls = 0
    def execute(self, request):
        self.calls += 1
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
            node_id=request.node_id, attempt_id=request.attempt_id,
            executor_ref=request.executor_ref, status=BlockStatus.SUCCEEDED, outputs={'node': request.node_id})


class HostCapabilityTests(unittest.TestCase):
    def test_dynamic_composer_claim_schema_and_parser(self):
        from types import SimpleNamespace
        from cgkn.agent.composer import parse_agent_decision
        completion = SimpleNamespace(model='fixture', routing={}, request_id='offline', usage={}, attempts=1)
        packet = dict(schema_version='1.0', decision_id='d', summary='bounded plan', reason='quality gap',
                      edits=[], request_run=False, finish=True, needs_escalation=False, escalation_reason='',
                      decision_audit={'alternatives_considered': ['inspect'], 'expected_outcome': 'quality improves',
                                      'capability_claim': {'target_capability_id': 'quality', 'target_gap_id': 'gap'}})
        decision = parse_agent_decision(packet, completion, '{}')
        self.assertEqual(decision.decision_audit['capability_claim']['target_gap_id'], 'gap')
        packet['decision_audit']['capability_claim']['fake_acceptance'] = 'PASS'
        with self.assertRaisesRegex(ValueError, 'invalid capability claim'):
            parse_agent_decision(packet, completion, '{}')

    def test_admission_enforces_input_policy_and_project_scope(self):
        p = replace(proposal([add_operation()]), target_capability_id='quality', target_gap_id='gap')
        e = Evidence('VERIFIED', {}, {}, (), scope={'PROJECT': 'demo'}, forbidden_for=('profile',))
        governed = replace(policy(), evidence_inputs={'demo.write': [
            {'requirements': {'consumer': 'profile'}, 'evidence': asdict(e)}]})
        kwargs = dict(known_capabilities=set(catalog()), catalog=catalog(), policy=governed)
        self.assertEqual(admit_proposal(CapabilityTree('goal', ()), 1, p, **kwargs).code,
                         'PORT_EVIDENCE_SCOPE_REJECT')
        self.assertEqual(admit_proposal(CapabilityTree('goal', ()), 1, replace(p, project_id='other'), **kwargs).code,
                         'PROJECT_SCOPE_REJECT')

    def test_session_reuses_skill_without_planner_and_runs_normal_runner(self):
        from cgkn.agent.project_loop import ProjectSession
        class NeverPlan:
            def decide(self, context):
                raise AssertionError('compatible skill should avoid planning')
        with tempfile.TemporaryDirectory() as folder:
            store = FileRunStore(Path(folder) / 'runs')
            witness = Witness()
            executors = ExecutorRegistry()
            executors.register(witness)
            node = probe_node('work', capability_ref='work@1', config={'executor_ref': 'witness@1'})
            cat = {'work@1': {'executor_ref': 'witness@1', 'config': node.as_dict()['config']}}
            m = SkillManifest('probe', '1', 'inspection', 'Observe bounded execution', 'demo',
                strategy_steps=({'operation': 'add_node', 'node_id': 'work',
                                 'payload': {'capability_ref': 'work@1', 'config': node.as_dict()['config']}},),
                block_refs=('work@1',), port_contract_refs=('probe',), capability_contract_refs=('quality',),
                acceptance_refs=('quality',), dependency_versions={'work@1': '1'},
                dependency_contract_hashes={'probe': 'A', 'quality': 'A'}, created_from_tree_branch='work')
            proofs = [SkillValidation(str(i), 'demo', str(i), m.strategy_hash,
                CapabilityGateState('PASS', 'PASS', 'PASS', 'PASS'), (str(i),), True, True) for i in range(2)]
            registry = SkillRegistry(Path(folder) / 'skills', execution_mode='LEGACY')
            registry.register(replace(m, status='VERIFIED'), proofs)
            task = dict(task_family='inspection', capability_id='quality', inputs=(), outputs=(),
                        dependency_versions=m.dependency_versions, dependency_contract_hashes=m.dependency_contract_hashes,
                        capability_claim={'target_capability_id': 'quality', 'target_gap_id': 'gap'})
            session = ProjectSession(NeverPlan(), probe_runner(executors, store), store,
                known_capabilities={'work@1'}, worker_model='unused', capability_catalog=cat, max_decisions=1,
                admission_policy=replace(policy(), allowed_effect_domains=frozenset({'probe/work'})),
                skill_matcher=SkillMatcher(registry), skill_task=task, execution_mode='LEGACY')
            result = session.run(project_id='demo', run_id='r', goal='goal')
            self.assertEqual(witness.calls, 1)
            self.assertEqual(result.agent_calls, 0)
            self.assertEqual(result.run_summary.status, 'SUCCEEDED')
            self.assertEqual(adapter.load(store, 'demo', 'r')['nodes']['work']['gates']['utility_status'], 'NOT_TESTED')
            context = json.loads((store.run_dir('demo', 'r') / 'agent/context-01.json').read_text())
            self.assertEqual(len(context['retrieved_knowledge']['skill_index']), 1)
            self.assertNotIn('strategy_steps', context['retrieved_knowledge']['skill_index'][0])

    def test_admission_resolves_catalog_implementation_and_roundtrip(self):
        p = replace(proposal([add_operation()]), target_capability_id='quality', target_gap_id='gap')
        self.assertEqual(ProjectProposal.from_dict(p.as_dict()).as_dict(), p.as_dict())
        cat = catalog()
        cat['demo.write@1']['implements_capabilities'] = ['vocabulary.correction']
        result = admit_proposal(CapabilityTree('goal', ()), 1, p,
                                known_capabilities=set(cat), catalog=cat, policy=policy())
        self.assertEqual(result.code, 'ANTI_SUBSTITUTION_REJECT')
        cat['demo.write@1']['implements_capabilities'] = ['ranking.improvement']
        result = admit_proposal(CapabilityTree('goal', ()), 1, p,
                                known_capabilities=set(cat), catalog=cat, policy=policy())
        self.assertTrue(result.valid)
        result = admit_proposal(CapabilityTree('goal', ()), 1, replace(p, target_gap_id='gui'),
                                known_capabilities=set(cat), catalog=cat, policy=policy())
        self.assertEqual(result.code, 'REJECT_NO_GOAL_LINK')

    def test_runtime_blocks_scope_and_frozen_hash_before_executor(self):
        for requirements, expected in (
            ({'consumer': 'stable_profile'}, 'PORT_EVIDENCE_SCOPE_REJECT'),
            ({'consumer': 'search', 'required_context_hash': 'A'}, 'CONTEXT_BINDING_REJECT')):
            with tempfile.TemporaryDirectory() as folder:
                store = FileRunStore(folder)
                witness = Witness()
                registry = ExecutorRegistry()
                registry.register(witness)
                node = probe_node('work', capability_ref='work@1', config={'executor_ref': 'witness@1'})
                tree = CapabilityTree('goal', (node,))
                evidence = Evidence('VERIFIED', {}, {}, (), scope={'PROJECT': 'p'},
                                    forbidden_for=('stable_profile',), context={'artifact_hash': 'B'})
                adapter.bind_inputs(store, 'p', 'r', 'work', [{'requirements': requirements, 'evidence': asdict(evidence)}])
                result = probe_runner(registry, store).run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree))
                self.assertEqual(witness.calls, 0)
                self.assertEqual(result.blocked_nodes, ('work',))
                self.assertEqual(store.load_result('p', 'r', 'work').error.message, expected)

    def test_execution_does_not_grant_quality_and_new_execution_invalidates(self):
        with tempfile.TemporaryDirectory() as folder:
            store = FileRunStore(folder)
            witness = Witness()
            registry = ExecutorRegistry()
            registry.register(witness)
            tree = CapabilityTree('goal', (probe_node('work', capability_ref='work@1', config={'executor_ref': 'witness@1'}),))
            runner = probe_runner(registry, store)
            result = runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree))
            self.assertEqual(result.status, 'SUCCEEDED')
            row = adapter.load(store, 'p', 'r')['nodes']['work']
            self.assertEqual(row['runtime_state'], 'EXECUTED')
            self.assertEqual(row['gates']['utility_status'], 'NOT_TESTED')
            self.assertFalse(adapter.completion_ready(store, 'p', 'r', {'quality': asdict(contract())}))
            evidence = Evidence('VERIFIED', {}, {}, (), scope={'PROJECT': 'p'}, context={'artifact_hash': 'B'})
            adapter.bind_inputs(store, 'p', 'r', 'work', [{'requirements': {
                'consumer': 'work', 'required_context_hash': 'A'}, 'evidence': asdict(evidence)}])
            with self.assertRaisesRegex(ValueError, 'CONTEXT_BINDING_REJECT'):
                runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree), resume=True)
            self.assertEqual(witness.calls, 1)

    def test_acceptance_persists_resource_repair_closure_and_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = FileRunStore(folder)
            c = contract()
            adapter.record_feedback(store, 'p', 'r', resource_decision={
                'id': 'resource-1', 'capability_id': 'quality', 'acceptance_result': 'PENDING'},
                repair_trace={'id': 'repair-1', 'capability_id': 'quality', 'final_result': 'pending'})
            e = Evidence('VERIFIED', {'a': '1'}, {'checker': '1'}, ('offline:1',), True,
                         scope={'PROJECT': 'p', 'CAPABILITY': 'quality'}, context={'contract_hash': c.fingerprint})
            obs = {k: Observation(v, e) for k, v in {'implemented': True, 'executed': True,
                    'influence': True, 'quality_delta': -0.2}.items()}
            adapter.record_acceptance(store, 'p', 'r', 'work', c, obs, object_versions={'a': '1'},
                checker_versions={'checker': '1'}, strategy_capabilities=('ranking',),
                artifact_after='after', acceptance_delta={'quality_delta': -0.2}, execution_mode='LEGACY')
            state = adapter.load(store, 'p', 'r')
            self.assertEqual(state['resource_decisions'][0]['acceptance_result'], 'FAILED')
            self.assertEqual(state['resource_decisions'][0]['utility_result'], 'FAIL')
            self.assertEqual(state['failure_repair_traces'][0]['final_result'], 'FAILED')
            self.assertFalse(adapter.completion_ready(store, 'p', 'r', {'quality': asdict(c)}, execution_mode='LEGACY'))
            self.assertEqual(adapter.load(store, 'another-project', 'r')['nodes'], {})
            obs['quality_delta'] = Observation(0.2, e)
            adapter.record_acceptance(store, 'p', 'r', 'work', c, obs, object_versions={'a': '1'},
                checker_versions={'checker': '1'}, strategy_capabilities=('ranking',), execution_mode='LEGACY')
            self.assertTrue(adapter.completion_ready(store, 'p', 'r', {'quality': asdict(c)}, execution_mode='LEGACY'))
            adapter.record_phase(store, 'p', 'r', 'work', 'EXECUTED', execution_status='PASS', execution_mode='LEGACY')
            self.assertFalse(adapter.completion_ready(store, 'p', 'r', {'quality': asdict(c)}, execution_mode='LEGACY'))

    def test_legacy_tree_load(self):
        raw = CapabilityTree('goal', ()).as_dict()
        raw['nodes'] = [{'id': 'historical', 'status': 'ACCEPTED'}]
        tree = CapabilityTree.from_dict(raw)
        self.assertTrue(tree.nodes[0].config['capability_gates']['legacy_imported'])
        self.assertEqual(tree.nodes[0].config['capability_gates']['utility_status'], 'NOT_TESTED')

    def test_verified_skill_instantiates_existing_edits_then_budget_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            m = SkillManifest('demo', '1', 'write', 'Improve quality', 'demo',
                inputs=('source',), outputs=('output',),
                strategy_steps=({'operation': 'add_node', 'node_id': 'demo.write',
                                 'payload': {'capability_ref': 'demo.write@1', 'config': catalog()['demo.write@1']['config']}},),
                block_refs=('demo.write@1',), port_contract_refs=('output',),
                capability_contract_refs=('quality',), acceptance_refs=('quality',),
                dependency_versions={'demo.write@1': '1'}, dependency_contract_hashes={'quality': 'A', 'output': 'A'},
                created_from_tree_branch='demo.write')
            validations = [SkillValidation(str(i), 'demo', str(i), m.strategy_hash,
                CapabilityGateState('PASS', 'PASS', 'PASS', 'PASS'), ('receipt:' + str(i),), True, True) for i in range(2)]
            registry = SkillRegistry(folder, execution_mode='LEGACY')
            registry.register(replace(m, status='VERIFIED'), validations)
            context = AgentDecisionContext('demo', 'r', 'goal', 1, CapabilityTree('goal', ()),
                                           ('demo.write@1',), catalog(), {}, {})
            task = dict(task_family='write', capability_id='quality', inputs=('source',), outputs=('output',),
                        dependency_versions=m.dependency_versions, dependency_contract_hashes=m.dependency_contract_hashes,
                        capability_claim={'target_capability_id': 'quality', 'target_gap_id': 'gap'})
            decision = adapter.skill_decision(SkillMatcher(registry), task, context)
            self.assertEqual(len(decision.edits), 1)
            p = replace(proposal([{'operation': e.operation, 'node_id': e.node_id, 'payload': dict(e.payload)}
                                  for e in decision.edits]), **task['capability_claim'])
            rejected = admit_proposal(context.tree, 1, p, known_capabilities={'demo.write@1'},
                                      catalog=catalog(), policy=replace(policy(), budget_state='BLOCKED'))
            self.assertEqual(rejected.code, 'BUDGET_BLOCKED')


if __name__ == '__main__':
    unittest.main()
