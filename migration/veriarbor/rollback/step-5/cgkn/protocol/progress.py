"""Deterministic repair admission over existing evidence; no execution authority."""
from .normalization import ContractError, digest


class ProgressGuidedBacktracking:
    """Compare bounded observations and suggest the existing Agent's next action."""
    @staticmethod
    def assess(before, after):
        verified_before=set(before.get('verified',[]));verified_after=set(after.get('verified',[]))
        failed_before=set(before.get('failed',[]));failed_after=set(after.get('failed',[]))
        if verified_before-verified_after or failed_after-failed_before or after.get('contract_drift'):
            status,operation='REGRESSION','AFFECTED_SUBGRAPH_REPLAN'
        elif (verified_after-verified_before or failed_before-failed_after
              or after.get('artifact_delta_validated')
              or set(after.get('evidence',[]))-set(before.get('evidence',[]))):
            status,operation='PROGRESS','CONTINUE'
        else:
            status,operation='NO_PROGRESS','LOCAL_STRATEGY_SWITCH'
        return {'status':status,'next_operation':operation,
                'acceptance_frontier_before':sorted(verified_before),
                'acceptance_frontier_after':sorted(verified_after),
                'newly_verified':sorted(verified_after-verified_before),
                'invalidated':sorted(verified_before-verified_after),
                'authority':'Agent advice only; no mutation, rollback, or acceptance grant'}


def strategy_fingerprint(strategy):
    if (not isinstance(strategy, dict) or not strategy.get('problem')
            or len(strategy) < 3):
        raise ContractError('SEMANTIC_STRATEGY_REQUIRED', fields=('strategy',), repair_class='R5', details={
            'admission_status':'REPAIRABLE_SEMANTIC', 'minimum_properties':3,
            'required_property':'problem',
            'semantic_patch_policy':{'allowed_paths':[['strategy']],
                'immutable_paths':[['action'],['target'],['goal'],['scope'],['deps'],['hypothesis'],
                                   ['capability'],['expected'],['accept']]},
            'instruction':'Replace only strategy with an object containing problem and at least TWO additional named implementation-mechanism dimensions at the same level (at least THREE keys total). A two-key problem/mechanism object is incomplete. Choose meaningful dimensions for the existing task; do not use prompt/code/rationale/timestamp padding or change the task, hypothesis or evidence.'})
    from veriarbor.learning import strategy_fingerprint as fingerprint, StrategyError
    try:
        return fingerprint(strategy)
    except StrategyError as error:
        raise ContractError(str(error)) from error


def admit_progress(packet, failures, history):
    strategy = strategy_fingerprint(packet.get('strategy'))
    hypothesis = packet.get('hypothesis', {})
    required = ('previous', 'falsifying_evidence', 'new', 'expected_novel_delta')
    if not isinstance(hypothesis, dict) or any(not hypothesis.get(k) for k in required):
        raise ContractError('FALSIFIED_HYPOTHESIS_REQUIRED', fields=('hypothesis',), repair_class='R6')
    if ' '.join(str(hypothesis['previous']).casefold().split()) == ' '.join(str(hypothesis['new']).casefold().split()):
        raise ContractError('HYPOTHESIS_UNCHANGED', fields=('hypothesis',), repair_class='R6')
    available = {digest(ref) for f in failures for ref in f.get('evidence_refs', [])}
    refs = hypothesis['falsifying_evidence']
    if not isinstance(refs, list) or not refs or any(digest(ref) not in available for ref in refs):
        raise ContractError('HYPOTHESIS_EVIDENCE_UNBOUND', fields=('hypothesis',), repair_class='R5',details={
            'admission_status':'REPAIRABLE_SEMANTIC',
            'semantic_patch_policy':{
                'allowed_paths':[['hypothesis','falsifying_evidence']],
                'immutable_paths':[['action'],['target'],['strategy'],
                    ['hypothesis','previous'],['hypothesis','new'],['hypothesis','expected_novel_delta']]},
            'allowed_evidence_refs':[ref for f in failures for ref in f.get('evidence_refs',[])],
            'instruction':'Keep strategy and all other packet fields unchanged. In hypothesis.falsifying_evidence copy at least one exact allowed_evidence_refs value, including its path and receipt_hash/sha256 fields. A related observation path alone is not the current bound failure receipt. Preserve previous/new/expected_novel_delta text.'})
    fingerprint = digest([{k: f.get(k) for k in ('acceptance_id', 'failure_code', 'object_identity', 'actual')}
                          for f in failures])
    from veriarbor.learning import repeated_no_progress
    if repeated_no_progress(strategy, fingerprint, available, history):
        raise ContractError('REPEATED_REPAIR_NO_PROGRESS', fields=('strategy',), repair_class='R6',
                            details={'next_operation': 'LOCAL_STRATEGY_SWITCH',
                                     'correction_path_terminated': True})
    return {'strategy_fingerprint': strategy, 'strategy_semantics': packet['strategy'],
            'failure_fingerprint': fingerprint, 'failure_evidence_hashes': sorted(available),
            'hypothesis': hypothesis, 'expected_novel_delta': hypothesis['expected_novel_delta']}


def check_strategy_constraints(strategy, paths, constraints):
    for rule in constraints:
        if not set(paths).intersection(rule.get('scope_paths',[])):
            continue
        if not isinstance(strategy,dict) or any(k not in strategy for k in rule.get('required_dimensions',[])):
            raise ContractError('STRATEGY_DIMENSIONS_REQUIRED',fields=('strategy',),repair_class='R6',
                                details={'required_dimensions':rule.get('required_dimensions',[])})
        for key,kind in rule.get('dimension_types',{}).items():
            if (kind=='boolean' and type(strategy.get(key)) is not bool) or (kind=='string' and not isinstance(strategy.get(key),str)):
                raise ContractError('STRATEGY_DIMENSION_TYPE',fields=('strategy',),repair_class='R6',details={'dimension':key,'required_type':kind})
        for pattern in rule.get('forbidden_patterns',[]):
            if pattern and all(strategy.get(k)==v for k,v in pattern.items()):
                raise ContractError('FALSIFIED_STRATEGY_FAMILY',fields=('strategy',),repair_class='R6',
                                    details={'pattern':pattern,'evidence_refs':rule.get('evidence_refs',[])})
