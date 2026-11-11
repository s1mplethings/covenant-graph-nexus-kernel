"""Explicit application bindings to the canonical leaf/checker/goal contracts.

This adapter only constructs new proposals. Historical trees are never upgraded.
Source delivery checks syntax and declared interfaces; business completion still
requires the independent external acceptance on the current project snapshot.
"""
import ast
from dataclasses import replace
from pathlib import Path

from cgkn.execution.deliverables import FileDeliverableChecker, SubjectDeliverableChecker
from cgkn.executors import ExecutorResolutionError
from cgkn.orchestration import CapabilityTree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.state.acceptance import GoalAcceptance, identity
from .snapshot import snapshot_project


def new_contract(node_id, config, dependencies=()):
    executor = config['executor_ref']
    unit = config.get('work_unit_contract', {})
    targets = list(unit.get('target_paths', config.get('target_paths', ())))
    writing = executor in {'llm.cheap@1', 'project.obligation-worker@1'}
    compiler = executor == 'project.contract-test-compiler@1'
    if compiler:
        artifact = canonical_tests(config)
        targets = [artifact.path, 'tests/contract_test_manifest.json']
        writing = True
    if writing and not targets:
        raise ValueError('application worker needs explicit target paths')
    details = {'adapter_source_schema': 'CGKNApplicationProposal/1.0'}
    if writing:
        details.update(expected_delta='materialize syntax-valid declared sources and interfaces',
                       read_scope=list(unit.get('allowed_read_paths', config.get('allowed_paths', ()))),
                       interface_config={k: config[k] for k in (
                           'executable_interface_contracts', 'interface_contract_set_hash',
                           'dependency_interface_contracts') if k in config})
        if compiler:
            from cgkn.application.materialization import materialize_json
            details['compiler_config'] = materialize_json(config)
    else:
        details.update(subject='current project snapshot', expected_observation=str(config.get('goal', node_id)),
                       pass_fail_rule='typed execution measurement bound to unchanged project and raw receipt')
    return build_leaf_contract(goal=str(config.get('goal', node_id)),
        kind='IMPLEMENTATION' if writing else 'TEST' if executor in {
            'local.command@1', 'local.python-test@1', 'project.acceptance@1',
            'project.obligation-oracle@1'} else 'INSPECTION',
        scope=targets if writing else ['project-observation/' + node_id],
        acceptance=['canonical-tests'] if compiler else ['source-delivery'] if writing else ['project-measurement'],
        checker='project-files' if writing else 'project-measurements',
        output_identity='application/' + node_id, effect_domains=(
            ['filesystem','external_network'] if executor=='llm.cheap@1' else
            ['project-files'] if executor=='project.obligation-worker@1' else
            ['local_process'] if executor in {'local.command@1','local.python-test@1','project.acceptance@1','project.obligation-oracle@1'} else
            ['filesystem']),
        executor=executor, dependencies=dependencies, **details)


def canonical_tests(config):
    from cgkn.application.verification.contract_test_compiler import ContractTestCompiler
    from cgkn.application.verification.contract_test_renderer import ContractTestRenderer
    from cgkn.application.requirements.obligation import ObligationSet
    from cgkn.application.requirements.policy import DependencyPolicy
    from cgkn.application.verification.contracts import OraclePlan
    policy = DependencyPolicy.from_dict(config['dependency_policies'][0])
    plan = ContractTestCompiler().compile(ObligationSet.from_dict(config['obligation_set']), OraclePlan.from_dict(config['oracle_plan']), policy)
    return ContractTestRenderer().render(plan, policy)


def canonical_test_delivery(root, contract):
    import json
    artifact = canonical_tests(contract['compiler_config'])
    actual = (root / artifact.path).read_text(encoding='utf-8')
    manifest = json.loads((root / 'tests/contract_test_manifest.json').read_text(encoding='utf-8'))
    passed = actual == artifact.source and manifest == artifact.manifest.as_dict()
    return {'passed': passed, 'observed': {'source_hash': identity(actual), 'manifest': manifest},
            'artifacts': list(contract['target_scope']) if passed else []}


def source_delivery(root, contract):
    observed, candidate = {}, {}
    passed = True
    for name in contract['target_scope']:
        path = root / name
        try:
            content = path.read_text(encoding='utf-8')
            if name.endswith('.py'):
                ast.parse(content, filename=name)
            elif not content.strip():
                raise ValueError('empty document')
            candidate[name] = content
            observed[name] = {'syntax': 'VALID', 'bytes': path.stat().st_size}
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            passed = False
            observed[name] = {'error': str(exc)}
    interface = contract.get('interface_config', {})
    if passed and interface.get('executable_interface_contracts'):
        from cgkn.application.requirements.execution import ObligationWorkUnitExecutor
        from types import SimpleNamespace
        planned = [SimpleNamespace(relative=k, content=v.encode()) for k,v in candidate.items()]
        rejects = ObligationWorkUnitExecutor._interface_rejections(interface, candidate, planned)
        observed['interfaces'] = {'rejections': rejects}
        passed = not rejects
    return {'passed': passed, 'observed': observed,
            'artifacts': list(contract['target_scope']) if passed else []}


class MeasuredExecutor:
    """Bind a deterministic observation to its exact input project version."""
    def __init__(self, executor, root, acceptance=None, condition=None, store=None):
        self.executor, self.root = executor, root
        self.descriptor = executor.descriptor
        self.acceptance, self.condition = acceptance, condition
        self.store = store

    def execute(self, request):
        before = snapshot_project(self.root).project_tree_hash
        executor = self.executor
        if request.executor_ref == 'project.obligation-oracle@1':
            from copy import copy
            import shutil
            directory = self.store.run_dir(request.project_id, request.run_id) / 'measurements' / request.node_id / request.attempt_id
            shutil.copytree(self.root, directory)
            if snapshot_project(directory).project_tree_hash != before:
                raise ValueError('measurement copy identity mismatch')
            executor = copy(executor)
            executor.workspace = directory
        result = executor.execute(request)
        after = snapshot_project(self.root).project_tree_hash
        out = dict(result.outputs)
        out['measurement_binding'] = {'before': before, 'after': after,
            'executor_ref': request.executor_ref, 'node_id': request.node_id}
        if self.acceptance is not None:
            # The private evaluator remains authoritative. Only its public result
            # and exact tested object are attached; hidden code is never feedback.
            self.acceptance.bind_subjects({'project': after})
            valid = before == after and out.get('status') == 'PASS' and bool(out.get('snapshot_hash'))
            out['goal_check'] = {'goal_id': 'project', 'condition_hash': identity(self.condition),
                'subjects': {'project': after}, 'execution': 'VALID' if before == after else 'INVALID',
                'verdict': 'VERIFIED' if valid else 'FAILED', 'observed': dict(result.outputs),
                'evidence_refs': ['external-acceptance:' + request.attempt_id]}
        return replace(result, outputs=out)


def install(registry, store, root, project_id, run_id, condition):
    root = Path(root).resolve()
    acceptance = GoalAcceptance(store, project_id, run_id, {'R-project': {'must': True}},
                                {'external': 'project.acceptance@1'})
    acceptance.bind_subjects({'project': snapshot_project(root).project_tree_hash})
    acceptance.commit(acceptance.propose({'phases': [{'id': 'usable', 'depends_on': []}],
        'goals': [{'id': 'project', 'phase_id': 'usable', 'requirement_refs': ['R-project'],
                   'acceptance': condition, 'subject_refs': ['project'], 'checker': 'external',
                   'task_refs': []}]}, CapabilityTree(condition, ())))
    for ref, capability in [('local.file@1','workspace.inspect@1'),
            ('local.command@1','project.python.compile@1'), ('local.python-test@1','project.python.pytest@1'),
            ('project.snapshot@1','project.snapshot@1'), ('project.acceptance@1','project.acceptance.external@1'),
            ('project.obligation-oracle@1','project.obligation-oracle-plan@1')]:
        try:
            executor = registry.resolve(ref, capability)
        except ExecutorResolutionError:
            continue
        registry.unregister(ref)
        registry.register(MeasuredExecutor(executor, root,
            acceptance if ref == 'project.acceptance@1' else None, condition, store))
    registry.register(FileDeliverableChecker(root, {'source-delivery': source_delivery, 'canonical-tests': canonical_test_delivery}))

    def measure(request, contract):
        out = request.as_dict()['input_values']['execution_receipt']['outputs']
        binding = out.get('measurement_binding', {})
        current = snapshot_project(root).project_tree_hash
        executor = contract['executor_ref']
        passed = (binding.get('after') == current and binding.get('node_id') == request.node_id
                  and binding.get('executor_ref') == executor)
        passed = passed and binding.get('before') == current
        if executor == 'project.snapshot@1':
            passed = passed and out.get('project_tree_hash') == current and bool(out.get('files'))
        elif executor == 'project.acceptance@1':
            snaps = [v for v in request.task_context.dependency_results.values() if v.get('snapshot_hash')]
            passed = passed and len(snaps) == 1 and out.get('snapshot_hash') == snaps[0]['snapshot_hash'] and snaps[0].get('project_tree_hash') == current
            passed = passed and out.get('status') == 'PASS' and out.get('goal_check', {}).get('subjects') == {'project': current}
        elif executor == 'local.python-test@1':
            tests=out.get('test_observation',{})
            passed = passed and tests.get('status')=='PASS' and tests.get('passed',0)>0 and bool(tests.get('report_sha256')) and bool(tests.get('files'))
        elif executor == 'project.obligation-oracle@1':
            passed = passed and bool(out.get('evidence')) and all(e.get('status') == 'PASS' for e in out['evidence'])
        elif executor == 'local.file@1':
            passed = passed and isinstance(out.get('files'), (tuple,list))
        elif executor == 'local.command@1':
            passed = passed and out.get('returncode') == 0
        else:
            passed = False
        return {'passed': bool(passed), 'observed': out,
                'evidence_refs': [dict(request.input_values['execution_receipt_ref'])]}

    registry.register(SubjectDeliverableChecker(
        lambda c: {n: snapshot_project(root).project_tree_hash for n in c['target_scope']},
        {'project-measurement': measure}))
    return acceptance, {'project-files': 'deliverable.files@1', 'project-measurements': 'deliverable.subjects@1'}
