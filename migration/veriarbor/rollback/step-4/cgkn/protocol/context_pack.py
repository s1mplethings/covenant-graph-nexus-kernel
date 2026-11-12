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


def public_requirements(value):
    """Keep controller instructions exact; the adaptive envelope owns budgeting.

    Summarizing executable requirements can silently remove the recovery action.
    Raw payload fields remain references, never inline private observations.
    """
    value = plain(value)
    if isinstance(value, dict):
        return {k:({'sha256':digest(v),'bytes':token_bound(v),'inline':False}
                   if k in RAW_KEYS else public_requirements(v)) for k,v in value.items()}
    if isinstance(value, list):
        return [public_requirements(v) for v in value]
    return value


from cgkn.adapters.veriarbor.tree_adapter import dependency_ready_goals



def unresolved_effect_paths(context):
    paths=set()
    for node in context.tree.nodes:
        result=context.execution_results.get(node.id,{})
        error=result.get('error') or {}
        if result.get('status') in {'UNKNOWN','INTERRUPTED_UNKNOWN','RUNNING'} or error.get('details',{}).get('outcome_unknown') is True:
            paths.update(node.config.get('leaf_contract',{}).get('target_scope',[]))
    return paths


from cgkn.adapters.veriarbor.tree_adapter import task_readiness_projection



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
        'acceptance_states':[({'goal_id':g['id'],'verdict':'VERIFIED','stable_ref':evidence_ref,
            'receipt_hash':(g.get('evidence') or {}).get('receipt_hash')}
            if g.get('verdict')=='VERIFIED' and g.get('milestone_contract') else
            {'goal_id':g['id'],'acceptance':g['acceptance'],'verdict':g.get('verdict'),
            'evidence':plain(g.get('evidence'))}) for g in goal_state.get('goals',[])],
        'evidence_policy':'INSUFFICIENT_EVIDENCE means not yet verified, not FAILED. Only observed business failures authorize implementation repair. Run registered independent measurements for materialized goals without evidence; preserve already VERIFIED goals.',
        'current_milestone_requirements':sorted({r for g in dependency_ready_goals(goal_state.get('goals',[])) for r in g.get('requirement_refs',[])}),
        'milestone_policy':'New bounded work addresses current unverified milestone requirements. Verified milestone artifacts are dependencies to reuse/read, not work to regenerate or merge into a whole-product leaf. Choose an available numeric node target, and the current artifact scope.',
        **share_failures(failures or []),'public_contracts':plain(contracts or {}),
        'recent_results':[{ 'node_id':k,'status':v.get('status'),'error':compact(v.get('error'))}
            for k,v in list(source.get('execution_results',{}).items())[-8:]],
        'previous_repair_attempts':[compact(x) for x in previous_attempts[-4:]],
        'previous_rejection':public_requirements({k:v for k,v in source.get('failure_details',{}).get('decision_validation',{}).get('protocol_error',{}).items()
            if k in {'code','fields','field','current_value','allowed_values','instruction','allowed_action_ids','existing_measurements','existing_dependency_targets','fingerprint','repeat_count','repetition_status','correction_path_terminated'}}),
        'finish_rejection':{'goal_error':source.get('failure_details',{}).get('goal_acceptance',{}).get('error'),
            'parent_verdicts':{k:v.get('verdict') for k,v in source.get('failure_details',{}).get('parent_acceptance',{}).items()},
            'finish_allowed':goal_state.get('complete',False),
            'instruction':'FINISH requires complete=true from independent GoalAcceptance. Successful file-writing nodes are not goal verification. For materialized pending goals, add TEST=4 tasks selecting the corresponding registered independent checker capability, then use its observations.'},
        'continuation_requirements':public_requirements(source.get('failure_details',{}).get('continuation_requirements',{})),
        'raw_evidence_refs':[evidence_ref],
        'raw_evidence_bytes':token_bound(source),'raw_evidence_bytes_inlined':0}
    validation=source.get('failure_details',{}).get('decision_validation',{})
    if validation and not validation.get('protocol_error'):
        import re
        message=str(validation.get('error',''))
        pack['decision_rejection']={k:validation[k] for k in ('error','error_type','decision_ref') if k in validation}
        pack['decision_rejection'].update(
            failure_domain='GRAPH_ADMISSION_NOT_BUSINESS_FAILURE',
            referenced_node_targets=[i for i,node in enumerate(source.get('tree',{}).get('nodes',[]))
                if re.search(r'(?<![A-Za-z0-9_-])'+re.escape(node['id'])+r'(?![A-Za-z0-9_-])',message)],
            instruction='The graph change was rejected before execution. Inspect the referenced numeric node targets and current artifact readiness. Correct graph/recovery strategy; this is not evidence of a business failure or permission to rewrite successful artifacts.')
        if message.startswith('OBJECT_VERSION_MISMATCH: explicit affected-subgraph retry required '):
            nodes=source.get('tree',{}).get('nodes',[])
            measurements=[i for i in pack['decision_rejection']['referenced_node_targets']
                if nodes[i].get('config',{}).get('leaf_contract',{}).get('task_kind') in {'TEST','INSPECTION'}]
            if measurements:
                pack['decision_rejection']['recovery_options']=[{'action':3,'target':i} for i in measurements]
                pack['decision_rejection']['instruction']='The existing measurement is bound to an older object version. Select an explicit RETRY_EXECUTION action=3 with one listed numeric target and no semantic changes to refresh that same measurement. Do not ADD_TASK a duplicate checker or REPAIR_IMPLEMENTATION the checker. A new observation is required before business diagnosis; this option does not authorize rewriting artifacts or automatic replay.'
    pack['metrics']={'raw_bytes':token_bound(source),'inline_bytes':token_bound(pack),
        'failed_acceptance_retained':len(pack['failures']),'failed_acceptance_total':len(failures or []),
        'token_count_method':'bytes only; token estimate and vendor usage in request receipt'}
    pack['milestone_context_snapshot']={'kind':'MilestoneContextSnapshot',
        'goal':source['goal'],'verified_frontier':pack['goal_state']['verified'],
        'active_requirements':pack['current_milestone_requirements'],
        'active_failures':[f.get('acceptance_id') for f in (failures or [])],
        'rejected_strategy_fingerprints':[r.get('strategy_fingerprint') for r in previous_attempts
            if r.get('status') in {'REPAIR_NO_PROGRESS','REPAIR_REGRESSION'}],
        'current_source_hashes':plain(goal_state.get('subject_identities',{})),
        'raw_evidence_ref':evidence_ref}
    pack['metrics']['inline_bytes']=token_bound(pack)
    return pack


def project_worker_observations(raw):
    """Reference verified dependency bodies for repair; explicit reads stay inline."""
    config=raw.get('config',{});leaf=config.get('leaf_contract',{})
    if config.get('action_version')!=2 or not config.get('repair_contract'):
        return raw
    observations=[];refs=list(raw.get('verified_dependency_refs',[]))
    for observation in raw.get('observations',[]):
        path=observation.get('path');content=observation.get('content')
        expected=leaf.get('read_subjects',{}).get(path)
        if (observation.get('input_origin')=='verified_milestone_dependency'
                and path in leaf.get('read_scope',[]) and path not in leaf.get('target_scope',[])
                and isinstance(content,str) and expected
                and observation.get('sha256')==expected==digest(content.encode('utf8'))
                and not observation.get('error') and not observation.get('truncated')):
            ref={'path':path,'sha256':expected,'utf8_bytes':len(content.encode('utf8')),
                 'availability':'Verified read-only input; use a read operation if its implementation is needed.'}
            if ref not in refs:refs.append(ref)
        else:
            observations.append(observation)
    return {**raw,'observations':observations,'verified_dependency_refs':refs}


def worker_contract_pack(raw):
    raw=project_worker_observations(raw)
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
        'strategy_semantics':plain(repair.get('strategy_semantics',{})),
        'hypothesis':plain(repair.get('hypothesis',{})),
        'allowed_read_paths':sorted(set(leaf['target_scope'])|set(leaf.get('read_scope',[]))),
        'allowed_write_paths':plain(leaf['target_scope']),
        'immutable_areas':['original goal','public contract registry','original acceptance','non-writable paths'],
        'relevant_source_refs':plain(leaf.get('read_scope',[])),
        'relevant_test_refs':plain(config.get('test_refs',[])),
        'previous_repair_attempts':plain(config.get('previous_repair_attempts',[]))[-2:],
        'checker_refs':[leaf['checker_ref']], 'evidence_refs':repair.get('evidence_refs',[]),
        'observations':plain(raw.get('observations',[])),
        'verified_dependency_refs':plain(raw.get('verified_dependency_refs',[]))}
    # Source reads are necessary expansions, not duplicated dependency outputs.
    pack['expansions']=[{'reason':'Worker explicitly requested bounded source read','path':x.get('path'),
        'sha256':digest(x),'bytes':token_bound(x)} for x in pack['observations']]
    return pack
