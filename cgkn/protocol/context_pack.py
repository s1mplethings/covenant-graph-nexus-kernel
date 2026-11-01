"""Reference-first bounded views. Raw evidence remains in FileRunStore."""
import json
from .normalization import ContractError,digest
from .repair import plain

RAW_KEYS={'stdout','stderr','raw_text','raw_response','source','content','provider_calls','semantic_calls'}


def share_failures(failures):
    rows=plain(failures)
    common={}
    if len(rows)>1:
        for key in ('failure_domain','artifact_paths','target_leaf_refs','evidence_refs','object_identity','actual'):
            if key in rows[0] and all(x.get(key)==rows[0][key] for x in rows):common[key]=rows[0][key]
    return {'failure_common':common,'failures':[{k:v for k,v in row.items() if k not in common} for row in rows]}


def expand_failures(pack):
    return [{**pack.get('failure_common',{}),**row} for row in pack.get('failures',[])]


def token_bound(value):
    # Historical API name retained for callers; this measures bytes, NOT tokens.
    # AdaptiveContextEnvelope uses a separate labeled token estimate.
    return len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf8'))


def compact(value,*,limit=512):
    value=plain(value)
    if isinstance(value,dict):
        return {k:({'sha256':digest(v),'bytes':token_bound(v),'inline':False} if k in RAW_KEYS else compact(v,limit=limit)) for k,v in value.items()}
    if isinstance(value,list):return [compact(v,limit=limit) for v in value[:24]]
    if isinstance(value,str) and len(value.encode())>limit:
        return {'excerpt':value[:limit//4],'sha256':digest(value),'bytes':len(value.encode()),'truncated':True}
    return value


def failure_context(context,*,evidence_ref,contracts=None,failures=None,previous_attempts=()):
    """Caller binds the full context to a durable ref before requesting a model."""
    source=context.as_dict() if hasattr(context,'as_dict') else plain(context)
    if not evidence_ref:raise ContractError('FAILURE_CONTEXT_RAW_REF_REQUIRED')
    goal_state=source.get('goal_acceptance',{})
    obligations=goal_state.get('obligations',{})
    pack={'kind':'FailureContextPack','goal':source['goal'],
        'goal_state':{'verified':[k for k,v in obligations.items() if v.get('verdict')=='VERIFIED'],
            'failed':[k for k,v in obligations.items() if v.get('verdict')=='FAILED'],
            'missing':[k for k,v in obligations.items() if v.get('verdict') not in {'VERIFIED','FAILED'}],
            'complete':goal_state.get('complete',False)},
        **share_failures(failures or []),'public_contracts':plain(contracts or {}),
        'recent_results':[{ 'node_id':k,'status':v.get('status'),'error':compact(v.get('error'))}
            for k,v in source.get('execution_results',{}).items()],
        'previous_repair_attempts':[compact(x) for x in previous_attempts[-4:]],
        'previous_rejection':compact({k:v for k,v in source.get('failure_details',{}).get('decision_validation',{}).get('protocol_error',{}).items()
            if k in {'code','fields','allowed_action_ids','fingerprint','repeat_count','repetition_status','correction_path_terminated'}}),
        'raw_evidence_refs':[evidence_ref],
        'raw_evidence_bytes':token_bound(source),'raw_evidence_bytes_inlined':0}
    pack['metrics']={'raw_bytes':token_bound(source),'inline_bytes':token_bound(pack),
        'failed_acceptance_retained':len(pack['failures']),'failed_acceptance_total':len(failures or []),
        'token_count_method':'bytes only; token estimate and vendor usage in request receipt'}
    return pack


def worker_contract_pack(raw):
    config=raw['config'];leaf=config['leaf_contract'];contracts=plain(config.get('public_contracts',{}))
    if not contracts.get('entries'):raise ContractError('WORKER_REQUIRED_CONTRACT_MISSING')
    for entry in contracts['entries']:
        if any(not entry.get('definition',{}).get(k) for k in entry.get('required_sections',[])):
            raise ContractError('WORKER_REQUIRED_CONTRACT_MISSING')
    from .contract_integrity import ContractIntegrityChecker
    integrity=ContractIntegrityChecker.require(contracts,leaf=leaf)
    repair=plain(config.get('repair_contract',{}))
    pack={'kind':'WorkerContractPack','version':2,'contract_integrity_status':integrity['status'],'integrity_receipt':integrity,'leaf_goal':raw['goal'],'public_contracts':contracts,
        'failed_acceptance_ids':repair.get('failed_acceptance_ids',[]),
        'expected_behavior':repair.get('expected_behavior',[]),'actual_behavior':repair.get('observed_actual',[]),
        'expected_delta':leaf.get('expected_delta'),'acceptance':plain(config.get('semantic_acceptance',[])),
        'allowed_read_paths':sorted(set(leaf['target_scope'])|set(leaf.get('read_scope',[]))),
        'allowed_write_paths':plain(leaf['target_scope']),
        'immutable_areas':['original goal','public contract registry','original acceptance','non-writable paths'],
        'relevant_source_refs':plain(leaf.get('read_scope',[])),
        'relevant_test_refs':plain(config.get('test_refs',[])),
        'previous_repair_attempts':plain(config.get('previous_repair_attempts',[]))[-2:],
        'checker_refs':[leaf['checker_ref']], 'evidence_refs':repair.get('evidence_refs',[]),
        'observations':plain(raw.get('observations',[]))}
    # Source reads are necessary expansions, not duplicated dependency outputs.
    pack['expansions']=[{'reason':'Worker explicitly requested bounded source read','path':x.get('path'),
        'sha256':digest(x),'bytes':token_bound(x)} for x in pack['observations']]
    return pack
