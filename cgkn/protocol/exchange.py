"""Bounded semantic correction inside a single existing executor/Agent turn."""
from __future__ import annotations
import json
from .normalization import ContractError,normalize,preserve_valid_fields,digest
from .admission import InvalidDecisionTracker,strip_proven_mechanical

MAX_CONTEXT_EXPANSIONS = 3

def complete_with_context(client, *, resolver, max_context_expansions=MAX_CONTEXT_EXPANSIONS, **request):
    """Fetch scoped context using the same client, Permit and request ledger."""
    from dataclasses import replace
    from .adaptive_context import encoded,ContextPacker,resolve_response_refs
    catalog=resolver.catalog()
    if not catalog:return client.complete(**request)
    if type(max_context_expansions) is not int or not 0<=max_context_expansions<=MAX_CONTEXT_EXPANSIONS:
        raise ValueError('invalid context acquisition budget')
    prompt=json.loads(request['user']);prompt['available_context']=catalog
    system=request['system']+' Optional public observations can be fetched by returning only context_operation, ref and reason from available_context. A fetch is not a business decision.'
    fetched=set();usage={};attempts=0;usage_rows=[]
    for index in range(max_context_expansions+1):
        prompt['available_context']=[row for row in catalog if row['ref'] not in fetched]
        control=resolver.request_schema(fetched) if index<max_context_expansions else None
        schema={'anyOf':[request['schema'],control]} if control else request['schema']
        turn_system=system if index<max_context_expansions else request['system']+' Context acquisition allowance is exhausted. Return the original business response using the available evidence, or report missing information through its normal escalation fields.'
        packed_system,packed,_=ContextPacker().assemble(turn_system,prompt,request['config'])
        completion=client.complete(**{**request,'system':packed_system,'user':encoded(packed),'schema':schema})
        usage_rows.append(dict(completion.usage))
        # A missing measurement in any call remains unknown, never a partial
        # total presented as complete usage for this decision.
        for key in set().union(*(row.keys() for row in usage_rows)):
            values=[row.get(key) for row in usage_rows]
            usage[key]=sum(values) if all(type(v) in (int,float) for v in values) else None
        attempts+=completion.attempts
        try:value=json.loads(completion.text)
        except ValueError:return replace(completion,usage=usage,attempts=attempts)
        if not isinstance(value,dict) or 'context_operation' not in value:
            value,restoration=resolve_response_refs(value,packed)
            return replace(completion,text=encoded(value) if restoration['resolved_refs'] else completion.text,usage=usage,attempts=attempts)
        if index>=max_context_expansions:raise ContractError('CONTEXT_EXPANSION_BUDGET_EXHAUSTED')
        entry=resolver.resolve(value)
        if entry['ref'] in fetched:raise ContractError('CONTEXT_EXPANSION_REPEATED')
        fetched.add(entry['ref']);prompt.setdefault('fetched_context',{})[entry['ref']]=entry

class SchemaRepairFailed(ContractError):
    def __init__(self,attempts,last_error):
        super().__init__('SCHEMA_REPAIR_FAILED',fields=last_error.fields,repair_class='R6',vector_key='missing_semantic_fields')
        self.attempts=attempts;self.semantic_calls=attempts;self.last_error=last_error.as_dict()


def exchange(client,config,*,system,context,snapshot,semantic_attempt_id,compiler,normalization,trace,max_corrections=2,max_admission_corrections=2,previous_rejection=None,context_resolver=None,context_policy=None,max_context_expansions=3,declaration=False,max_declaration_corrections=2,semantic_patch_policy=None):
    from .adaptive_context import ContextPacker,encoded
    if type(max_context_expansions) is not int or max_context_expansions<0:raise ValueError('invalid expansion call budget')
    if type(max_declaration_corrections) is not int or max_declaration_corrections<0:raise ValueError('invalid declaration correction budget')
    if type(max_corrections) is not int or not 0<=max_corrections<=2:raise ValueError('correction bound must be 0..2')
    if type(max_admission_corrections) is not int or not 0<=max_admission_corrections<=2:raise ValueError('admission correction bound must be 0..2')
    initial={'semantic_attempt_id':semantic_attempt_id,'call_kind':'semantic_decision_attempt',
        'context':context,'tables':snapshot.public_document,'table_hash':snapshot.hash}
    prompt=initial;prior=None;invalid=[];calls=[];receipts=[];patch_base=None;patch_policy=None
    if context_resolver:
        initial['available_context']=context_resolver.catalog()
        system+=' To fetch scoped public context, return only {"context_operation":"fetch_contract|fetch_artifact|fetch_evidence|fetch_dependency_result|request_more_context","ref":"catalog ref","reason":"why needed"}. This continues the same decision.'
    packer=ContextPacker(context_policy);expanded=set()
    history_key=(config.model,config.model_id,config.role)
    history=getattr(client,'_cgkn_context_successes',{}).get(history_key,[])
    counters={'schema_repair_attempts':0,'admission_correction_attempts':0,'repair_action_corrections':0,'context_expansion_attempts':0,'declaration_correction_attempts':0}
    tracker=InvalidDecisionTracker();call_kind='semantic_decision_attempt'
    if previous_rejection and previous_rejection.get('fingerprint'):
        tracker.counts[previous_rejection['fingerprint']]=previous_rejection.get('repeat_count',0)
    for attempt in range(max_corrections+max_admission_corrections+3+max_context_expansions+max_declaration_corrections):
        packet={}
        packed_system,packed,packing=packer.assemble(system,prompt,config,recent_successes=[x['input_tokens'] for x in history])
        packing['recent_success_refs']=[{'request_id':x['request_id'],'actual_model':x['actual_model']} for x in history]
        try:
            completion=client.complete(system=packed_system,user=encoded(packed),
                schema_name='cgkn_semantic_v1',schema=None,config=config)
        except Exception as exc:
            from cgkn.providers.gateway_client import GatewayCompletionError,MAX_REQUEST_BYTES
            if isinstance(exc,GatewayCompletionError) and exc.category=='request_too_large' and not exc.outcome_unknown:
                error=ContractError('GATEWAY_HARD_LIMIT',details={'failure_domain':'RESOURCE_LIMIT',
                    'source':'cgkn/providers/gateway_client.py:MAX_REQUEST_BYTES','hard_ceiling_bytes':MAX_REQUEST_BYTES,
                    'measurement':'native complete serialized HTTP payload','packing_receipt':packing,
                    'provider_dispatched':False,'correction_path_terminated':True})
                trace({'status':'RESOURCE_LIMIT','semantic_attempt_id':semantic_attempt_id,'call_kind':call_kind,'error':error.as_dict()})
                raise error from exc
            trace({'status':'PROVIDER_CALL_ERROR','semantic_attempt_id':semantic_attempt_id,'call_kind':call_kind,
                'packing_receipt':packing,'error_type':type(exc).__name__,'outcome_unknown':getattr(exc,'outcome_unknown',False),
                'provider_dispatched':'UNKNOWN; consult canonical call receipt'})
            raise
        call={'semantic_attempt_id':semantic_attempt_id,'schema_repair_attempt':counters['schema_repair_attempts'],'admission_correction_attempt':counters['admission_correction_attempts'],'call_kind':call_kind,
            'model':completion.model,'request_id':completion.request_id,'usage':dict(completion.usage),
            'routing':dict(completion.routing),'provider_attempts':completion.attempts,'raw_finish_reason':completion.raw_finish_reason}
        call['repair_action_correction']=counters['repair_action_corrections']
        call['context_expansion_attempt']=counters['context_expansion_attempts']
        call['declaration_correction_attempt']=counters['declaration_correction_attempts']
        packing['provider_dispatched']=True
        packing['envelope']['actual_model']=completion.model
        call['packing_receipt']=packing
        call['context_metrics']={'serialized_utf8_bytes':packing['after_bytes'],
                'token_estimate':packing['token_estimate'],
                'vendor_input_tokens':completion.usage.get('input_tokens',completion.usage.get('prompt_tokens')),
                'raw_evidence_bytes_inlined':context.get('raw_evidence_bytes_inlined',0),
                'raw_evidence_bytes_referenced':context.get('raw_evidence_bytes',0)}
        calls.append(call)
        event={**call,'raw_text':completion.text,'table_hash':snapshot.hash,'prompt_hash':digest(prompt)}
        try:
            if declaration:
                from cgkn.providers.finish_reason import classify_finish
                finish=classify_finish(completion.raw_finish_reason)
                if finish!='MODEL_STOP':
                    domain='RESOURCE_LIMIT' if finish=='OUTPUT_TOKEN_LIMIT' else 'TRANSPORT' if finish in {'TRANSPORT_INTERRUPTED','STREAM_TRUNCATED','TIMEOUT','PROVIDER_ERROR'} else 'UNKNOWN'
                    raise ContractError('DECLARATION_COMPLETION_INCOMPLETE',details={
                        'failure_domain':domain,'finish_reason':finish,'raw_finish_reason':completion.raw_finish_reason,
                        'outcome_unknown':domain in {'TRANSPORT','UNKNOWN'},'automatic_replay':False,
                        'correction_path_terminated':True,'instruction':'Inspect or reconcile the recorded completion; this is not a business failure or permission to resend.'})
            # Expansion is a public context operation, not a planner action or
            # schema correction. Its receipt and usage belong to this decision.
            try:expansion=json.loads(completion.text)
            except (ValueError,TypeError):expansion=None
            if isinstance(expansion,dict) and 'context_operation' in expansion:
                expansion,_=normalize(completion.text)
                if context_resolver is None:raise ContractError('CONTEXT_EXPANSION_UNAVAILABLE')
                if counters['context_expansion_attempts']>=max_context_expansions or expansion.get('ref') in expanded:
                    raise ContractError('CONTEXT_EXPANSION_EXHAUSTED')
                fetched=context_resolver.resolve(expansion)
                expanded.add(fetched['ref']);counters['context_expansion_attempts']+=1
                event.update(status='CONTEXT_EXPANDED',expansion_receipt=fetched)
                trace(event);receipts.append(event)
                call_kind='context_expansion_attempt'
                prompt={**prompt,'call_kind':call_kind,'context_expansion_attempts':counters['context_expansion_attempts'],
                    'context_expansions':[*prompt.get('context_expansions',[]),fetched]}
                continue
            if declaration:
                from .declaration import extract_declaration
                packet,receipt=extract_declaration(completion.text)
            else:
                packet,receipt=normalize(completion.text,**normalization)
            from .adaptive_context import resolve_response_refs
            packet,alias_receipt=resolve_response_refs(packet,packed)
            event['context_reference_normalization']=alias_receipt
            event['normalization']=receipt;event['semantic_packet']=packet
            if patch_base is not None:
                from .declaration import apply_semantic_patch
                packet, patch_receipt = apply_semantic_patch(patch_base, packet, **patch_policy)
                event['semantic_patch_receipt'] = patch_receipt
                event['patched_semantic_packet'] = packet
            if prior is not None:
                if 'capabilities' in snapshot.document:
                    packet,mechanical=strip_proven_mechanical(packet,snapshot)
                    event['mechanical_normalization']=mechanical
                event['semantic_diff']=preserve_valid_fields(prior,packet,invalid)
            compiled=compiler(packet,snapshot.hash)
            event.update(status='COMPILED',canonical_output=compiled,repair_class='R4')
            trace(event);receipts.append(event)
            # Ephemeral advisory cache only. Canonical recorded calls remain
            # the evidence/accounting authority; this never marks business PASS.
            usage=completion.usage.get('input_tokens',completion.usage.get('prompt_tokens'))
            if type(usage) is int and usage>0:
                cache=dict(getattr(client,'_cgkn_context_successes',{}))
                cache[history_key]=[*history,{'input_tokens':usage,'request_id':completion.request_id,'actual_model':completion.model}][-16:]
                try:setattr(client,'_cgkn_context_successes',cache)
                except (AttributeError,TypeError):pass
            return compiled,completion,{'semantic_decision_attempts':1,**counters,'transport_retry':0,'reconcile_attempt':0,'calls':calls,'receipts':receipts}
        except ContractError as error:
            repeat=tracker.observe(packet if 'packet' in locals() else {},error)
            event.update(status='REJECTED',error=error.as_dict());trace(event);receipts.append(event)
            error.semantic_calls=list(calls)
            if declaration and error.details.get('declaration_correction'):
                if counters['declaration_correction_attempts']>=max_declaration_corrections or repeat>=3:
                    raise SchemaRepairFailed(calls,error) from error
                counters['declaration_correction_attempts']+=1
                call_kind='declaration_correction_attempt'
                if patch_base is not None:
                    # A malformed patch does not revoke the existing canonical
                    # object or authorize a complete declaration replacement.
                    prompt={**prompt,'call_kind':call_kind,**counters,
                            'rejected_response':completion.text,'exact_error':error.as_dict(),
                            'instruction':'Return one valid JSON patches object using only the listed allowed_patches. The server-owned canonical object remains unchanged. Do not return a complete declaration or immutable fields.'}
                    continue
                # No complete declaration was admitted. Retain the original
                # semantic context and rejected bytes, never pick/merge objects.
                prompt={**initial,'call_kind':call_kind,**counters,
                        'rejected_response':completion.text,'exact_error':error.as_dict(),
                        'instruction':'Return exactly one complete declaration object for the unchanged original goal. No implementation. No commentary, wrapper, second object or missing semantic field.'}
                prior=None
                continue
            if error.repair_class!='R5':raise
            repair_action=error.details.get('admission_status')=='REPAIR_ACTION_CORRECTION'
            admission=error.details.get('admission_status')=='REPAIRABLE_SEMANTIC'
            counter='repair_action_corrections' if repair_action else 'admission_correction_attempts' if admission else 'schema_repair_attempts'
            limit=2 if repair_action else max_admission_corrections if admission else max_corrections
            if repeat>=3 or counters[counter]>=limit:
                terminal=SchemaRepairFailed(calls,error)
                terminal.details.update(error.details,budget=dict(counters))
                raise terminal from error
            # Syntax/unknown errors cannot reach this branch; only the precise
            # invalid top-level fields may change in the next bounded packet.
            if 'packet' not in locals():raise
            prior=dict(packet)
            for receipt in error.details.get('mechanical_receipts',[]):
                for field in receipt['fields']:prior.pop(field,None)
            invalid=[{'paths':'path','nodes':'target','scopes':'scope','capabilities':'capability'}.get(k,k) for k in error.fields]
            if repair_action:
                invalid=list(error.fields)
                if error.details.get('repair_fields_required'):
                    invalid+=['task_kind','goal','scope','expected','accept','deps','failed_acceptance_ids']
            counters[counter]+=1
            call_kind='repair_action_correction' if repair_action else 'admission_correction_attempt' if admission else 'schema_repair_attempt'
            # A trusted compiler may narrow a semantic correction to an exact
            # field. Reuse the existing patch engine and retain the canonical
            # packet server-side instead of asking for unrelated fields again.
            compiler_patch_policy=error.details.get('semantic_patch_policy')
            if semantic_patch_policy is not None or compiler_patch_policy is not None:
                import copy
                patch_policy = (semantic_patch_policy(copy.deepcopy(packet), error)
                    if semantic_patch_policy is not None else copy.deepcopy(compiler_patch_policy))
                if (not isinstance(patch_policy,dict) or not patch_policy.get('allowed_paths')
                        or set(patch_policy)-{'allowed_paths','immutable_paths'}):
                    raise ContractError('SEMANTIC_PATCH_POLICY_UNAVAILABLE') from error
                patch_base=copy.deepcopy(packet);prior=None
                fragments=[]
                for path in patch_policy['allowed_paths']:
                    value=patch_base
                    try:
                        for key in path:value=value[key]
                        exists=True
                    except (KeyError,IndexError,TypeError):value=None;exists=False
                    fragments.append({'path':path,'exists':exists,'required_op':'replace' if exists else 'add','current_value':value})
                prompt={'semantic_attempt_id':semantic_attempt_id,'call_kind':call_kind,**counters,
                    'canonical_object_hash':digest(patch_base),'exact_error':error.as_dict(),
                    'allowed_patches':fragments,
                    'task_anchor':{key:copy.deepcopy(patch_base[key]) for key in ('goal','expected','strategy','hypothesis') if key in patch_base},
                    'task_anchor_policy':'Read-only original task semantics. Correct the listed fields for this task, not the planning protocol. Patch authority is unchanged.',
                    'instruction':'Return only {"patches":[{"op":"add|replace","path":[field names or list offsets],"value":corrected semantic value}]}. Use exactly the required_op for each listed path: replace existing fields, add absent fields. Use only listed paths, at most four patches. Do not return the full declaration. Immutable fields remain in the server-owned original and cannot be changed. No implementation or hidden reasoning.'}
                continue
            prompt={'semantic_attempt_id':semantic_attempt_id,'call_kind':call_kind,**counters,
                'previous_packet':prior,'exact_error':error.as_dict(),'invalid_fields':invalid,
                'immutable_fields':sorted(set(prior)-set(invalid)), 'tables':snapshot.public_document,'table_hash':snapshot.hash,
                'instruction':'Return only corrected packet. Preserve every field not explicitly listed invalid. Do not replan or change valid business intent.'}
            if repair_action:
                prompt.pop('tables')
                prompt['instruction']='Preserve repair intent. Change only action to REPAIR_IMPLEMENTATION=4 (or explicit strategy=5/replan=8) and fields listed invalid. Original goal and public acceptance are immutable. No implementation patch is supplied by the host.'
                prompt['repair_action_table']={4:'REPAIR_IMPLEMENTATION',5:'CHANGE_STRATEGY',8:'REPLAN'}
                if error.details.get('repair_fields_required'):prompt['tables']=snapshot.public_document
    raise AssertionError('bounded loop exhausted unexpectedly')
