"""Independent deliverable checks through the existing Executor boundary.

Checks are installed by trusted application code. A worker chooses a registered
contract, never supplies checker code or a self-attested verdict.
"""
from dataclasses import replace
import hashlib
from pathlib import Path

from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.execution.contracts import ExecutorDescriptor
from cgkn.orchestration.leaf_contract import WRITING
from cgkn.artifacts.evidence_identity import digest


def _progress_measurements(observed):
    values={}
    for observation in observed.values():
        for key,value in observation.get('progress_measurements',{}).items():
            if key in values and values[key]!=value:
                raise ValueError('conflicting independent progress measurements')
            values[key]=value
    return values


def verified_proof(checked, request, checker, contract):
    proof=checked.as_dict()['outputs'].get('deliverable_check',{})
    current=checker.snapshot(contract)
    valid=(checked.succeeded and proof.get('verdict')=='VERIFIED'
        and (checked.project_id,checked.run_id,checked.node_id,checked.attempt_id,checked.executor_ref)
            == (request.project_id,request.run_id,request.node_id,request.attempt_id,checker.descriptor.executor_ref)
        and proof.get('subject_hash')==digest(current) and proof.get('subjects')==current
        and proof.get('condition_hash')==digest(list(contract['acceptance']))
        and proof.get('output_identity')==contract['output_identity'] and bool(proof.get('evidence_refs')))
    if valid:
        for ref in proof['evidence_refs']:
            if not isinstance(ref,dict) or not ref.get('path') or not ref.get('sha256'):
                valid=False;break
            path=Path(ref['path'])
            if not path.is_absolute():
                if not hasattr(checker,'root'):valid=False;break
                path=(checker.root/path).resolve()
                if checker.root not in path.parents:valid=False;break
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:
                valid=False;break
    if getattr(checker,'public_exports',None) and proof.get('public_export_contract_hash') != digest(checker.public_exports):
        valid=False
    return valid,proof


class SubjectDeliverableChecker:
    """Independent checks for bounded non-file objects using the same proof envelope.

    Trusted application callbacks provide current subject versions and observations.
    Neither an executor's status nor its claimed verdict is an acceptance oracle.
    Snapshot callbacks must be read-only and return one version/hash per named object.
    """
    descriptor = ExecutorDescriptor('deliverable.subjects@1', 'deterministic_checker',
                                    ('deliverable.check@1',), ())

    def __init__(self, snapshot, checks):
        self._snapshot = snapshot
        self.checks = dict(checks)

    def snapshot(self, contract):
        values = dict(self._snapshot(contract))
        if set(values) != set(contract['target_scope']):
            raise ValueError('subject snapshot does not bind exact target scope')
        if any(v is not None and (not isinstance(v,str) or not v) for v in values.values()):
            raise ValueError('subject versions must be nonempty strings or absent')
        return values

    def validate_contract(self, contract):
        if not set(contract['acceptance']) <= self.checks.keys():
            raise ValueError('unregistered deliverable acceptance')
        self.snapshot(contract)

    def execute(self, request):
        c = request.task_context.node_config['leaf_contract']
        self.validate_contract(c)
        current = self.snapshot(c)
        observed = {name:self.checks[name](request, c) for name in c['acceptance']}
        for value in observed.values():
            if (not isinstance(value,dict) or type(value.get('passed')) is not bool
                    or not value.get('observed') or not value.get('evidence_refs')):
                raise ValueError('checker requires explicit observations and raw evidence references')
        if current != self.snapshot(c):
            raise ValueError('subject changed during independent measurement')
        before = dict(request.input_values['before'])
        delta = {k:{'before':before.get(k),'after':v} for k,v in current.items() if before.get(k)!=v}
        passed = all(v['passed'] for v in observed.values()) and all(current.values())
        if c['task_kind'] in WRITING and not delta:
            passed = False
        proof = dict(schema_version='1.0', verdict='VERIFIED' if passed else 'FAILED',
            subjects=current, subject_hash=digest(current), artifact_delta={}, non_file_delta=delta,
            condition_hash=digest(list(c['acceptance'])), observed=observed,
            evidence_refs=[ref for v in observed.values() for ref in v['evidence_refs']],
            output_identity=c['output_identity'],progress_measurements=_progress_measurements(observed))
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
            node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=self.descriptor.executor_ref,
            status=BlockStatus.SUCCEEDED, outputs={'deliverable_check':proof})


class FileDeliverableChecker:
    descriptor = ExecutorDescriptor('deliverable.files@1', 'deterministic_checker',
                                    ('deliverable.check@1',), ('filesystem.read',))

    def __init__(self, root, checks, *, public_exports=None):
        self.root = Path(root).resolve()
        self.checks = dict(checks)
        from copy import deepcopy
        self.public_exports = deepcopy(public_exports or {})

    def snapshot(self, contract):
        values = {}
        from .file_actions import candidate_files
        for name in candidate_files(self.root, contract):
            path = (self.root / name).resolve()
            if self.root not in path.parents: raise ValueError('deliverable path escapes root')
            values[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        return values

    def validate_contract(self, contract):
        if not set(contract['acceptance']) <= self.checks.keys():
            raise ValueError('unregistered deliverable acceptance')
        self.snapshot(contract)

    def execute(self, request):
        c = request.task_context.node_config['leaf_contract']
        self.validate_contract(c)
        current = self.snapshot(c)
        observed = {}
        for name in c['acceptance']:
            # Registered code must give observations, not merely exit 0.
            value = self.checks[name](self.root, c)
            if not isinstance(value, dict) or type(value.get('passed')) is not bool or not value.get('observed'):
                raise ValueError('checker omitted explicit observation')
            observed[name] = value
        export_failed = set()
        if self.public_exports:
            from .python_exports import python_export_declarations
            for name in c['target_scope']:
                if name in self.public_exports:
                    row = python_export_declarations(self.root/name, self.public_exports[name])
                    observed['declared_exports:'+name] = row
                    if not row['passed']:export_failed.add(name)
        after = self.snapshot(c)
        if current != after: raise ValueError('checker mutated its subject')
        before = dict(request.input_values['before'])
        delta = {k: {'before': before.get(k), 'after': v} for k,v in current.items() if before.get(k) != v}
        passed = all(v['passed'] for v in observed.values()) and all(current.values())
        if c['task_kind'] in WRITING and not delta: passed = False
        proof = {'schema_version':'1.0', 'verdict':'VERIFIED' if passed else 'FAILED',
                 'subject_hash':digest(current), 'subjects':current, 'artifact_delta':delta,
                 'condition_hash':digest(list(c['acceptance'])), 'observed':observed,
                 'evidence_refs':[{'path':k,'sha256':v} for k,v in current.items() if v],
                 'output_identity':c['output_identity'],'progress_measurements':_progress_measurements(observed)}
        verified_names = {name for observation in observed.values() if observation['passed']
                          for name in observation.get('artifacts',[]) if name in current and current[name]}
        for observation in observed.values():
            verified_names.update(name for name,verdict in observation.get('artifact_verdicts',{}).items()
                                  if verdict is True and name in current and current[name])
        proof['verified_artifacts'] = {name:{'path':str(self.root/name),'sha256':current[name]} for name in verified_names - export_failed}
        if self.public_exports:proof['public_export_contract_hash']=digest(self.public_exports)
        return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,
            node_id=request.node_id,attempt_id=request.attempt_id,executor_ref=self.descriptor.executor_ref,
            status=BlockStatus.SUCCEEDED,outputs={'deliverable_check':proof})


def progress_record(contract, proof, *, node_id=None):
    # Only independent measurements may populate semantic/test deltas. Missing
    # measurements remain unknown, never inferred from exit status or file size.
    measures = proof.get('progress_measurements', {})
    if contract['task_kind'] not in WRITING: verdict = 'NOT_APPLICABLE'
    elif measures.get('regressions'): verdict = 'REGRESSION'
    elif proof.get('verdict') == 'VERIFIED': verdict = 'MEANINGFUL_PROGRESS'
    elif proof.get('artifact_delta') or proof.get('non_file_delta'): verdict = 'PARTIAL_PROGRESS'
    else: verdict = 'NO_IMPLEMENTATION_PROGRESS'
    return {'schema_version':'1.1','goal':contract['leaf_goal'],'verdict':verdict,
            'goals':[contract['leaf_goal']], 'executed_leaves':[node_id] if node_id else measures.get('executed_leaves',[]),
            'business_artifact_delta':proof.get('artifact_delta',{}),
            'semantic_delta':measures.get('semantic_delta','UNKNOWN'),
            'expected_delta':contract.get('expected_delta','NOT_APPLICABLE'),
            'test_count_delta':measures.get('test_count_delta','UNKNOWN'),
            'targeted_pass_delta':measures.get('targeted_pass_delta','UNKNOWN'),
            'targeted_fail_delta':measures.get('targeted_fail_delta','UNKNOWN'),
            'newly_verified':measures.get('newly_verified',[]),
            'regressions':measures.get('regressions',[]),
            'api_schema_ui_delta':measures.get('api_schema_ui_delta','UNKNOWN'),
            'non_file_delta':proof.get('non_file_delta',{}),
            'artifact_delta':proof.get('artifact_delta',{}),'test_delta':'UNKNOWN',
            'acceptance_delta':proof.get('verdict'),'evidence_refs':proof.get('evidence_refs',[]),
            'strategy_hash':digest({k:v for k,v in dict(contract).items() if k != 'output_identity'}),
            'observation_hash':digest({'observed':proof.get('observed',{}),'subjects':proof.get('subjects',{}),
                                     'measurements':measures}),
            'suggested_actions':[] if verdict in {'MEANINGFUL_PROGRESS','NOT_APPLICABLE'} else
                ['inspect','split','change_route','different_strategy']}


def parent_projection(tree, results, own_acceptance):
    """Read-only projection. GoalAcceptance remains the acceptance authority."""
    projected = {}
    def visit(node):
        children = [n for n in tree.nodes if n.parent_id == node.id]
        if not children:
            r = results.get(node.id)
            from cgkn.orchestration.execution_dag import _thaw
            bound = digest(_thaw(node.config.get('leaf_contract',{})))
            return 'VERIFIED' if r and r.metadata.get('deliverable_verdict') == 'VERIFIED' and r.metadata.get('leaf_contract_hash')==bound else 'MISSING_OR_FAILED'
        child_states = {n.id:visit(n) for n in children}
        required = [n.id for n in children if n.config.get('required',True)]
        goal_id=node.config.get('acceptance_goal_id',node.id)
        own=own_acceptance.get(goal_id,'MISSING') if isinstance(goal_id,str) and goal_id else 'MISSING'
        valid = bool(required) and all(child_states[n]=='VERIFIED' for n in required) and own=='VERIFIED'
        projected[node.id] = {'verdict':'VERIFIED' if valid else 'BLOCKED',
            'children':child_states,'not_required':[n.id for n in children if not n.config.get('required',True)],
            'acceptance_goal_id':goal_id,'own_acceptance':own}
        return projected[node.id]['verdict']
    for n in tree.nodes:
        if not n.parent_id: visit(n)
    return projected
