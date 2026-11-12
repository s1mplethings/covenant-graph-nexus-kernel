"""Protocol adapters for existing AgentComposer and LLMExecutor boundaries."""
import json
from collections.abc import Mapping
from dataclasses import replace
from .compiler import TableSnapshot,compile_worker,compile_planner,ACTIONS,KINDS
from .normalization import digest,ContractError
from .exchange import exchange
from .admission import PLANNER_SCHEMA


def public_value(value):
    """Serialize canonical immutable mappings even when nested in lists."""
    if isinstance(value,Mapping):return {k:public_value(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [public_value(v) for v in value]
    return value


def usage_summary(final,stats):
    usage=dict(final.usage)
    for key,alias in [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens'),('total_tokens','total_tokens')]:
        values=[c['usage'].get(key,c['usage'].get(alias)) for c in stats['calls']]
        if any(v is not None for v in values):usage[key]=sum(values) if all(type(v) in (int,float) for v in values) else None
    usage.update(semantic_decision_attempts=1,schema_repair_attempts=stats['schema_repair_attempts'],
        admission_correction_attempts=stats.get('admission_correction_attempts',0),repair_action_corrections=stats.get('repair_action_corrections',0),context_expansion_attempts=stats.get('context_expansion_attempts',0),semantic_calls=stats['calls'])
    return usage


class SemanticWorkerClient:
    def __init__(self,client,trace):self.client=client;self.trace=trace
    def complete(self,**kwargs):
        from .context_pack import project_worker_observations
        raw=project_worker_observations(json.loads(kwargs['user']));contract=raw['config']['leaf_contract']
        if contract.get('component_roots'):
            from .exchange import complete_with_context
            from .adaptive_context import public_role_resolver
            return complete_with_context(self.client,resolver=public_role_resolver(raw),**kwargs)
        writable=set(contract['target_scope']);readable=writable|set(contract.get('read_scope',[]))
        observed={x['path']:digest(x['content'].encode('utf8'))
                  for x in raw.get('observations',[]) if isinstance(x,dict)
                  and x.get('action')=='read_file' and isinstance(x.get('content'),str)
                  and isinstance(x.get('path'),str) and not x.get('error') and not x.get('truncated')}
        table={'paths':[{'path':p,'readable':True,'writable':p in writable,
            **({'observed_content_sha256':observed[p]} if p in observed else {})} for p in sorted(readable)]}
        table['allow_local_tests']='local_process' in contract.get('effect_domains',())
        strategy=raw['config'].get('repair_contract',{}).get('strategy_semantics',{})
        if raw.get('bounded_patch_policy',{}).get('mode') == 'patch_only':
            table['allowed_write_operations']=[3]
            table['patch_batch_limit']=8
        elif strategy.get('full_file_write') is True:
            table['allowed_write_operations']=[2]
        snapshot=TableSnapshot(table)
        context={'goal':raw['goal'],'interfaces':raw['config'].get('interfaces'),
            'expected':contract.get('expected_delta'),'acceptance':raw['config'].get('semantic_acceptance',raw.get('acceptance',[])),
            'constraints':raw.get('constraints',[]),'observations':raw.get('observations',[]),
            'dependency_outputs':raw.get('dependency_results',{})}
        if raw['config'].get('action_version')==2:
            from .context_pack import worker_contract_pack
            context=worker_contract_pack(raw)
        attempt=digest({'node':raw['node_id'],'context':context,'table':snapshot.hash})
        from .adaptive_context import public_role_resolver
        resolver=public_role_resolver(raw)
        compiled,final,stats=exchange(self.client,kwargs['config'],system='You are a bounded Worker. Return one JSON object: {"op": integer, "path": integer, "payload": content}. Operation IDs: 0 read file, 1 list files, 2 write full file, 3 exact patch, 4 local tests (only when table.allow_local_tests), 5 submit current candidate (omit path and payload). Obey table.allowed_write_operations when present: [3] permits exact bounded patches only and rejects full-file writes; [2] requires a full-file write. The caller-bound patch policy takes precedence over a conflicting proposed strategy. For read/list omit payload. For patch payload is {"find": string,"replace": string}. When table.patch_batch_limit is present, payload may instead be an array of up to that many find/replace objects for nonoverlapping regions of the SAME registered path, all anchored to the original observed source. The caller preflights the entire batch atomically against its source hash/ranges before any write. Use this batch for separated functions or DOM sections; never bridge frozen intervening code with a larger patch. Writes and patches continue the same delegation. Inspect local observations, repair within scope, then explicitly submit with op=5. Local tests never replace independent acceptance. Never use a full-file write under patch-only policy. Referenced verified dependencies remain readable on demand; their full bodies are not automatically in context during repair. An identical write is rejected as no implementation change; changed bytes still require independent business verification. Use only current PATH table IDs. Never change the goal, graph, or permissions. Code payload is literal file content, not double-escaped text. Read observations are returned in the next bounded round. A path with observed_content_sha256 already has its complete content in context observations; do not reread that unchanged file. Use its visible content, read a different missing source, or escalate with a concrete missing prerequisite. Optional expected_local_effect is a short observable result. To escalate, return only escalation=true and expected_local_effect explaining the missing prerequisite.',
            context=context,snapshot=snapshot,semantic_attempt_id=attempt,
            compiler=lambda packet,bound:compile_worker(packet,snapshot,bound_hash=bound,node_id=raw['node_id']),
            normalization={'integer_fields':['op','path'],'aliases':{'operation':'op'}},trace=self.trace,context_resolver=resolver)
        return replace(final,text=json.dumps(compiled,ensure_ascii=False),usage=usage_summary(final,stats),attempts=sum(c['provider_attempts'] for c in stats['calls']))


def semantic_decide(composer,context):
    from cgkn.orchestration.admission import AgentDecision,AgentDecisionValidationError
    from cgkn.providers import ProviderCompletion
    snapshot=composer.semantic_tables(context)
    if not isinstance(snapshot,TableSnapshot):raise TypeError('server-owned immutable table snapshot required')
    request_id=f'{context.project_id}:{context.run_id}:decision:{context.decision_number}'
    visible=context.as_dict()
    failures={k:({kk:vv for kk,vv in v.items() if kk not in {'raw_response','model','request_id'}} if isinstance(v,dict) else v)
        for k,v in list(visible['failure_details'].items())[-6:]}
    public={'goal':context.goal,'failure_details':failures,
        'run_summary':visible['run_summary'],
        'goal_acceptance':visible['goal_acceptance'],'task_feedback':visible['task_feedback'],
        'action_table':ACTIONS,'task_kind_table':KINDS,'semantic_schema':PLANNER_SCHEMA,
        'recent_progress':list(visible.get('execution_results',{}).items())[-4:]}
    version2=snapshot.document.get('action_version')==2
    if version2:
        from .repair import ACTIONS_V2,ACTION_RULES,planner_schema_v2
        from .context_pack import failure_context,expand_failures
        public=failure_context(context,evidence_ref=snapshot.document.get('context_raw_ref'),
            failures=expand_failures(snapshot.document.get('repair_context',{})),
            previous_attempts=snapshot.document.get('repair_context',{}).get('previous_repair_attempts',[]))
        public.update(action_table=ACTIONS_V2,action_rules=ACTION_RULES,task_kind_table=KINDS,semantic_schema=planner_schema_v2())
    public['project_intent'] = public_value(context.project_intent)
    public['task_kind_usage']={2:'AUTHOR FILES: implement source code, write test source, or write documentation. Writing tests/test_*.py is task_kind=2.',
        3:'REPAIR existing implementation after observed business failure, preserving the original public contract.',
        4:'EXECUTE a registered independent measurement against already materialized artifacts. This cannot create test files or documentation. If no such capability is admitted, materialize the missing artifacts first.'}
    def compile_packet(packet,bound):
        result=compile_planner(packet,snapshot,bound_hash=bound,tree=context.tree,context_identity=request_id)
        return {**result,'edits':[{'edit_id':e.edit_id,'operation':e.operation,'node_id':e.node_id,'payload':dict(e.payload),'provenance':dict(e.provenance)} for e in result['edits']]}
    events=[]
    def trace(event):
        # Thaw canonical immutable values before writing receipts.
        event=public_value(event);events.append(event);composer.protocol_trace(event)
    try:
        compiled,final,stats=exchange(composer.client,composer.config,
            system=('You are the high-capability project Planner. Use shared action_table/action_rules and numeric snapshot IDs. Return JSON with action; bounded leaf actions also need task_kind,target,goal,scope,expected,accept,deps. For ADD_TASK=1 select capability as the numeric ID from the current capabilities table whenever multiple compatible choices remain; this includes independent TEST measurements with different goal bindings on the same scope. task_kind=4 alone cannot choose which acceptance goal to measure. Match capability description to the intended unmet goal and keep every scope within its allowed_scope_ids. Capability omission is allowed only when the compatibility table identifies exactly one candidate. If admission reports missing capability, add only that field; do not change goal, scope, expected, accept or deps during correction. REPAIR_IMPLEMENTATION=4 updates an existing implementation target after observed acceptance failure, using task_kind=3. Imported artifacts without a writer may use ADD_TASK=1 with task_kind=3 only after current independent business failure evidence; no evidence means measure first. RETRY_EXECUTION=3 uses only action and target (optional confidence/needs_user); omit task_kind, goal, scope, expected, accept and deps entirely. It reuses the existing leaf contract unchanged and is not business repair. Tests are task_kind=4; writing test source is implementation. FINISH=9; ESCALATE=10 with goal. Never weaken public contract or acceptance. Do not claim VERIFIED: independent GoalAcceptance decides.' if version2 else 'You are the high-capability project Planner. Choose business intent using current local ID tables. Return one JSON object with action, task_kind, target (integer node row id), goal, scope (integer scope row ids), expected (observable text list), accept (business acceptance text list), deps (integer node row ids). Example shape: {"action":1,"task_kind":2,"target":0,"goal":"your bounded goal","scope":[0],"expected":["your observable result"],"accept":["your business predicate"],"deps":[]}. Every reference is the numeric id shown in the table, never a path or internal node/capability name. Infer capability from task kind and allowed scope pairs; only select the optional numeric capability when multiple compatible choices remain. Every scope must be in that capability’s allowed_scope_ids. Return only the listed semantic fields. For retry use only action=3,target; finish action=7; escalate action=8,goal explaining unresolved need. KEEP=0 executes existing ready work. Do not invent IDs or requirements. Do not claim verification; existing independent acceptance decides completion.'),
            context=public,snapshot=snapshot,semantic_attempt_id=request_id,compiler=compile_packet,
            normalization={'integer_fields':['action','task_kind','target','capability'],'list_fields':['scope','deps','sources'],'aliases':{'acceptance':'accept','dependencies':'deps'}},trace=trace,
            previous_rejection=visible['failure_details'].get('decision_validation',{}).get('protocol_error'),
            context_resolver=getattr(composer,'context_resolver',None),context_policy=getattr(composer,'context_policy',None))
    except ContractError as exc:
        last=events[-1] if events else {}
        completion=ProviderCompletion(last.get('raw_text',''),last.get('model','UNKNOWN'),last.get('request_id',''),last.get('usage',{}))
        failure=AgentDecisionValidationError(exc,completion);failure.feedback.update(protocol_error=exc.as_dict(),semantic_decision_attempts=1,
            schema_repair_attempts=sum(e.get('call_kind')=='schema_repair_attempt' for e in events),
            admission_correction_attempts=sum(e.get('call_kind')=='admission_correction_attempt' for e in events))
        failure.feedback['repair_action_corrections']=sum(e.get('call_kind')=='repair_action_correction' for e in events)
        raise failure from exc
    from cgkn.orchestration.tree_edits import TreeEdit
    edits=tuple(TreeEdit(**e) for e in compiled['edits'])
    audit={'alternatives_considered':list((ACTIONS_V2 if version2 else ACTIONS).values()),'expected_outcome':compiled['reason']}
    governance=context.task_feedback.get('capability_governance')
    if edits and governance:
        # Numeric semantic selection already identifies the registered capability.
        # Bind it mechanically only to a unique, explicitly authorized goal gap;
        # never invent an exploration grant or choose among competing goals.
        selected=set()
        for edit in edits:
            existing=context.tree.by_id.get(edit.node_id)
            config=edit.payload.get('config',{})
            capability=(config.get('capability_contract_id') or edit.payload.get('capability_ref')
                or (existing.config.get('capability_contract_id',existing.capability_ref) if existing else ''))
            if capability:selected.add(capability)
        contracts=governance.get('contracts',{})
        bindings=[(gap['gap_id'],cap) for gap in governance.get('goal_gaps',())
            if gap.get('status','OPEN')=='OPEN' for cap in selected
            if cap in contracts and cap in gap.get('capability_ids',())]
        if not selected or not selected<=set(contracts) or len(bindings)!=1:
            raise ContractError('CAPABILITY_GOAL_BINDING_REQUIRED',details={
                'failure_domain':'ADMISSION','correction_path_terminated':True,
                'selected_capabilities':sorted(selected),'candidate_bindings':bindings,
                'reason':'semantic selection needs one explicit goal-gap binding; no exploration grant inferred'})
        gap,cap=bindings[0]
        audit['capability_claim']={'target_capability_id':cap,'target_gap_id':gap,'strategy_capabilities':sorted(selected)}
    return AgentDecision(compiled['decision_id'],compiled['reason'],compiled['reason'],edits,
        compiled['request_run'],compiled['finish'],compiled['needs_escalation'],compiled['reason'] if compiled['needs_escalation'] else '',
        {'model':final.model,'routing':dict(final.routing),'request_id':final.request_id,'usage':usage_summary(final,stats),'attempts':sum(c['provider_attempts'] for c in stats['calls'])},
        digest(public),len(json.dumps(public)),decision_audit=audit)
