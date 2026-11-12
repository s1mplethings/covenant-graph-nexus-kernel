"""Project bounded request facts to novelty dimensions; no provider or ledger."""
import json
from veriarbor.model import stable_hash
from veriarbor.dedup import provider_disposition

_VOLATILE = frozenset({'semantic_attempt_id', 'attempt_id', 'request_id',
    'decision_number', 'started_at', 'ended_at', 'timestamp', 'created_at',
    'elapsed_seconds', 'seconds', 'context_raw_ref', 'raw_evidence_refs',
    'raw_evidence_bytes', 'raw_evidence_bytes_inlined', 'table_hash', 'repeat_count'})


def _normalize(value):
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def request_novelty(public, role, execution=None):
    """Different call IDs, timestamps or models alone are not novel facts.

    All requests get a proof, including non-semantic callers with an opaque
    exact input contract. Semantic requests expose more useful dimensions.
    This projection does not judge natural-language semantic equivalence.
    """
    user = public.get('user', '')
    try:
        packed = json.loads(user)
    except (ValueError, TypeError):
        packed = {'opaque_request': user}
    if not isinstance(packed, dict):
        packed = {'opaque_request': packed}
    if packed.get('context_values'):
        from cgkn.protocol.adaptive_context import ContextPacker
        packed = ContextPacker.restore(packed)
    context = packed.get('context') or {}
    if not isinstance(context, dict):
        context = {'opaque': context}
    tables = packed.get('tables') or {}
    if not isinstance(tables, dict):
        tables = {'opaque': tables}
    context = _normalize(context)
    tables = _normalize(tables)
    continuation = context.get('continuation_requirements') or {}
    def select(source, keys):
        return {k: source[k] for k in keys if k in source}
    variant = select(context, ('strategy', 'strategy_fingerprint', 'hypothesis', 'leaf_goal', 'expected_delta'))
    variant['nodes'] = tables.get('nodes', [])
    artifacts = select(context, ('observations', 'relevant_source_refs', 'current_source_hashes', 'milestone_context_snapshot'))
    artifacts.update(select(tables, ('paths', 'artifact_readiness', 'milestone_dependency_inputs')))
    contracts = select(context, ('goal', 'project_intent', 'public_contracts', 'expected_behavior', 'acceptance', 'allowed_read_paths', 'allowed_write_paths'))
    contracts.update(select(tables, ('public_contract_registry', 'strategy_constraints', 'scopes', 'goals')))
    contracts['protocol'] = {k: public.get(k) for k in ('schema_name', 'schema', 'system')}
    contracts['user_requirement'] = continuation.get('milestone_completion_request')
    if 'opaque_request' in packed:
        contracts['opaque_request'] = packed['opaque_request']
    evidence = select(context, ('actual_behavior', 'failure_common', 'failures', 'previous_rejection',
        'previous_repair_attempts', 'evidence_refs', 'acceptance_states', 'goal_state', 'recent_results',
        'error', 'rejection', 'invalid_payload', 'failed_acceptance_ids', 'expansions'))
    evidence['diagnosis'] = continuation.get('fresh_runtime_diagnosis')
    # Correction packets expose observations outside the context field.
    evidence['correction'] = _normalize({k:v for k,v in packed.items()
        if k not in {'context','context_values','tables','semantic_attempt_id','table_hash'}})
    qualification = select(context, ('checker_refs', 'contract_integrity_status', 'integrity_receipt'))
    return {'scope': {'role': role, 'node_id': (execution or {}).get('node_id'),
                      'schema_name': public.get('schema_name')},
            **{k:stable_hash(v) for k,v in {'variant':variant, 'artifacts':artifacts,
                'contracts':contracts, 'evidence':evidence, 'checker_qualification':qualification}.items()}}


def novelty_disposition(previous, candidate):
    same_scope = [p for p in previous if p.get('scope') == candidate.get('scope')]
    return provider_disposition(same_scope, candidate)
