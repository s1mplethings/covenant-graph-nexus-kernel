"""Capability policy projections in the existing FileRunStore, never a new tree.

Only the host acceptance authority calls record_acceptance with qualified
observations. Agent configs and worker outputs cannot grant quality PASS.
"""
from dataclasses import asdict, replace
import json

from veriarbor.capability import (CapabilityContract, CapabilityGateState,
                                 RUNTIME_STATES, close_feedback, evaluate_capability, validate_evidence)
from veriarbor.model import Evidence
from veriarbor.execution_authority import ExecutionMode


def _mode(store, project_id, run_id, mode):
    mode = ExecutionMode(mode)
    if mode == ExecutionMode.LEGACY:
        from veriarbor.governance import require_legacy
        require_legacy(project_id=project_id,run_id=run_id)
        import warnings
        warnings.warn('LEGACY execution has no governed lineage', RuntimeWarning, stacklevel=3)
    return mode


def _path(store, project_id, run_id):
    return store.run_dir(project_id, run_id) / 'capability_governance.json'


from cgkn.state.capability_ledger import load


def record_phase(store, project_id, run_id, node_id, phase, *, execution_status=None, invalidate_nodes=(),
                 execution_mode='GOVERNED', commit_receipt_id=None):
    if ExecutionMode(execution_mode)=='GOVERNED' and execution_status=='PASS':
        from cgkn.runtime.node_authority import ExecutionAuthority
        ExecutionAuthority(store,project_id,run_id).validate_receipt(commit_receipt_id,node_id=node_id)
    if phase not in RUNTIME_STATES:
        raise ValueError('invalid capability runtime phase')
    path = _path(store, project_id, run_id)
    with store.exclusive_file(path.with_suffix('.lock'), wait_seconds=2):
        value = load(store, project_id, run_id)
        row = value['nodes'].setdefault(node_id, {})
        row['runtime_state'] = phase
        if phase in {'ADMITTED', 'EXECUTING'}:
            row['gates'] = CapabilityGateState().as_dict()
        for affected in invalidate_nodes:
            if affected in value['nodes']:
                value['nodes'][affected]['gates'] = CapabilityGateState().as_dict()
        if execution_status:
            # Every new execution invalidates old quality, even if it succeeded.
            row['gates'] = CapabilityGateState('PASS', execution_status).as_dict()
        store.atomic_json(path, value)


def record_acceptance(store, project_id, run_id, node_id, contract, observations, *,
                      object_versions, checker_versions, strategy_capabilities,
                      artifact_after=None, acceptance_delta=None, execution_mode='GOVERNED',
                      commit_receipt_id=None, outcome_receipt_ids=()):
    mode = _mode(store, project_id, run_id, execution_mode)
    receipt = None
    if mode == ExecutionMode.GOVERNED:
        from cgkn.runtime.node_authority import ExecutionAuthority
        receipt = ExecutionAuthority(store, project_id, run_id).validate_receipt(
            commit_receipt_id, node_id=node_id, capability_id=contract.capability_id,
            contract_hash=contract.fingerprint)
        authority=ExecutionAuthority(store,project_id,run_id)
        observations,object_versions,checker_versions,evaluation_scopes=authority.acceptance_observations(
            commit_receipt_id,outcome_receipt_ids)
    elif mode == ExecutionMode.IMPORTED_UNMANAGED:
        raise ValueError('IMPORTED_UNMANAGED_IS_AUDIT_ONLY')
    gates = evaluate_capability(contract, observations, project_id=project_id,
                                object_versions=object_versions, checker_versions=checker_versions,
                                strategy_capabilities=strategy_capabilities,
                                critical_check_results=receipt.critical_check_results if receipt else ())
    if receipt:
        for metric in contract.acceptance_metrics:
            if metric.stage in {'UTILITY_VERIFIED','GENERALIZATION_VERIFIED'} and metric.metric_id in observations:
                binding=evaluation_scopes.get(metric.metric_id)
                if not binding or not binding[0].allows(metric.stage,binding[1]):
                    raise ValueError('EVALUATION_SCOPE_VIOLATION:'+metric.metric_id)
        # Worker observations cannot override a missing/unknown critical check.
        statuses = [r['status'] for r in receipt.critical_check_results]
        semantic = 'FAIL' if 'FAIL' in statuses else 'UNKNOWN' if 'UNKNOWN' in statuses else 'PASS'
        if receipt.gate_snapshot.get('semantic_status') in {'FAIL','BLOCKED','UNKNOWN'}:
            semantic=receipt.gate_snapshot['semantic_status']
        if contract.critical_checks and semantic != 'PASS':
            gates = replace(gates, semantic_status=semantic,
                            utility_status='BLOCKED', generalization_status='BLOCKED')
    path = _path(store, project_id, run_id)
    with store.exclusive_file(path.with_suffix('.lock'), wait_seconds=2):
        input_code = validate_inputs(store, project_id, run_id, node_id, execution_mode=mode)
        if input_code != 'VALID':
            raise ValueError(input_code)
        value = load(store, project_id, run_id)
        value['nodes'][node_id] = {**value['nodes'].get(node_id, {}),
            'capability_id': contract.capability_id, 'contract_hash': contract.fingerprint,
            'runtime_state': 'GATED', 'gates': gates.as_dict(),
            'execution_mode': mode.value, 'commit_receipt_id': commit_receipt_id,
            'object_versions': dict(object_versions), 'checker_versions': dict(checker_versions),
            'observations': {k: asdict(v) for k, v in observations.items()}}
        resources, repairs = close_feedback(value['resource_decisions'], value['failure_repair_traces'],
            capability_id=contract.capability_id, gates=gates,
            artifact_after=artifact_after, acceptance_delta=acceptance_delta,permit_id=receipt.permit_id if receipt else None)
        value.update(resource_decisions=resources, failure_repair_traces=repairs)
        store.atomic_json(path, value)
    if receipt:
        authority.record_acceptance_event(receipt.receipt_id,gates,acceptance_delta=acceptance_delta)
    return gates


def bind_inputs(store, project_id, run_id, node_id, bindings, *, contract=None):
    """Freeze consumer bindings using host-authenticated evidence before dispatch."""
    path = _path(store, project_id, run_id)
    with store.exclusive_file(path.with_suffix('.lock'), wait_seconds=2):
        value = load(store, project_id, run_id)
        row = value['nodes'].setdefault(node_id, {})
        existing = row.get('input_bindings')
        if existing is not None and [b['requirements'] for b in existing] != [b['requirements'] for b in bindings]:
            raise ValueError('CONTEXT_BINDING_REJECT: frozen consumer requirements changed')
        if existing != bindings:
            row['gates'] = CapabilityGateState().as_dict()
        row['input_bindings'] = bindings
        if contract is not None:
            row['allow_imported_unmanaged'] = contract.evidence_requirements.get('allow_imported_unmanaged',False) is True
        store.atomic_json(path, value)


def record_feedback(store, project_id, run_id, *, resource_decision=None, repair_trace=None):
    path = _path(store, project_id, run_id)
    with store.exclusive_file(path.with_suffix('.lock'), wait_seconds=2):
        value = load(store, project_id, run_id)
        for key, row in (('resource_decisions', resource_decision), ('failure_repair_traces', repair_trace)):
            if row is not None:
                if not row.get('capability_id') or not row.get('id'):
                    raise ValueError('feedback needs id and capability_id')
                existing = next((r for r in value[key] if r['id'] == row['id']), None)
                if existing is not None and existing != row:
                    raise ValueError('conflicting feedback identity')
                if existing is None:
                    value[key].append(dict(row))
        store.atomic_json(path, value)


def validate_inputs(store, project_id, run_id, node_id, *, execution_mode='GOVERNED'):
    """Input bindings are host-owned, never taken from worker-supplied metadata."""
    row = load(store, project_id, run_id)['nodes'].get(node_id, {})
    mode = _mode(store, project_id, run_id, execution_mode)
    for binding in row.get('input_bindings', ()):
        if mode == ExecutionMode.GOVERNED:
            from cgkn.runtime.node_authority import ExecutionAuthority, file_hash
            try:
                if binding.get('execution_mode') == 'IMPORTED_UNMANAGED':
                    if not row.get('allow_imported_unmanaged'):
                        return 'IMPORTED_INPUT_NOT_ALLOWED'
                    if binding.get('commit_receipt_id'):
                        return 'IMPORTED_INPUT_CANNOT_CLAIM_RECEIPT'
                else:
                    path = binding.get('artifact_path')
                    if not path: return 'COMMIT_RECEIPT_REQUIRED'
                    ExecutionAuthority(store, project_id, run_id).validate_receipt(
                        binding.get('commit_receipt_id'), output_path=path,
                        output_hash=file_hash(path), **binding.get('producer_binding', {}))
            except ValueError as exc:
                return str(exc)
        requirements = dict(binding['requirements'])
        requirements['required_scope'] = {**requirements.get('required_scope', {}), 'PROJECT': project_id}
        raw = binding.get('evidence')
        if raw is None:
            return 'PORT_EVIDENCE_SCOPE_REJECT'
        code = validate_evidence(Evidence(**raw), **requirements)
        if code != 'VALID':
            return code
    return 'VALID'


def completion_ready(store, project_id, run_id, contracts, *, execution_mode='GOVERNED'):
    mode = ExecutionMode(execution_mode)
    if mode == ExecutionMode.IMPORTED_UNMANAGED:return False
    rows = load(store, project_id, run_id)['nodes'].values()
    if mode == ExecutionMode.GOVERNED:
        from cgkn.runtime.node_authority import ExecutionAuthority
        authority=ExecutionAuthority(store,project_id,run_id)
        verified=[]
        for row in rows:
            try:
                authority.validate_receipt(row.get('commit_receipt_id'),
                    capability_id=row.get('capability_id'),contract_hash=row.get('contract_hash'))
                verified.append(row)
            except ValueError:pass
        rows=verified
    for raw in contracts.values():
        contract = CapabilityContract(**raw)
        if contract.critical and not any(
                row.get('capability_id') == contract.capability_id
                and row.get('contract_hash') == contract.fingerprint
                and (mode == ExecutionMode.LEGACY or
                     (row.get('execution_mode') == 'GOVERNED' and row.get('commit_receipt_id')))
                and row.get('gates', {}).get('semantic_status') == 'PASS'
                and row.get('gates', {}).get('utility_status') == 'PASS' for row in rows):
            return False
    return True


def skill_decision(matcher, task, context, *, compiler=None, manifest=None, trial=False):
    """Compile portable strategies through the same public interface as Agent work."""
    from cgkn.orchestration.admission import AgentDecision
    from cgkn.orchestration.tree_edits import TreeEdit
    from veriarbor.model import stable_hash
    from copy import deepcopy
    matching={k:v for k,v in task.items() if k not in {'capability_claim','requirement_refs'}}
    if manifest is None:
        loaded=matcher.load(project_id=context.project_id,**matching)
        if not loaded:return None
        manifest,_=loaded[0]
    if any(step['operation']=='add_node' and step['node_id'] in context.tree.by_id for step in manifest.strategy_steps):
        return None
    raw={'schema_version':'1.0','decision_id':f'skill:{manifest.skill_id}:{context.decision_number}',
         'summary':manifest.semantic_goal,'reason':'Current-context skill qualification trial' if trial else 'Reuse a compatible verified strategy',
         'edits':[{**deepcopy(step),'edit_id':f'skill:{manifest.skill_id}:{i}',
                   'provenance':{'skill_id':manifest.skill_id,'skill_version':manifest.version}}
                  for i,step in enumerate(manifest.strategy_steps)],
         'request_run':True,'finish':False,'needs_escalation':False,'escalation_reason':'',
         'decision_audit':{'alternatives_considered':['dynamic planning'],'expected_outcome':manifest.semantic_goal,
             'requirement_refs':task.get('requirement_refs',[]),'capability_claim':task.get('capability_claim',{})}}
    if compiler is not None:
        if hasattr(compiler,'prepare_context'):context=compiler.prepare_context(context)
        raw=compiler._normalize_decision(raw,context)
    for step in raw['edits']:
        if step['operation']=='add_node':
            step['payload']['config']['skill_binding']={'skill_id':manifest.skill_id,'version':manifest.version,
                'strategy_hash':manifest.strategy_hash,'qualification_trial':trial}
    return AgentDecision(decision_id=raw['decision_id'],summary=raw['summary'],reason=raw['reason'],
        edits=tuple(TreeEdit(**step) for step in raw['edits']),request_run=True,finish=False,needs_escalation=False,
        escalation_reason='',provider={},context_hash=stable_hash(context.as_dict()),
        context_chars=len(json.dumps(context.as_dict())),decision_audit=raw['decision_audit'])

