"""Advisory context packing and sourced limits; no planning/state authority."""
from __future__ import annotations
import copy,json,math,os,statistics
from pathlib import Path
from .normalization import ContractError,digest

def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def byte_size(value):return len(encoded(value).encode('utf8'))

def load_policy():
    path=Path(os.environ.get('CGKN_CONTEXT_POLICY_PATH',Path(__file__).resolve().parents[2]/'config/context_envelope_policy.json'))
    return json.loads(path.read_text(encoding='utf8')) if path.is_file() else {}

def estimate_tokens(text,policy=None,tokenizer=None):
    if tokenizer is not None:
        count=tokenizer(text)
        if type(count) is not int or count<0:raise ValueError('invalid tokenizer result')
        return {'lower':count,'upper':count,'exact':True,'source':'caller supplied model tokenizer'}
    policy=policy or {};ascii_count=sum(ord(x)<128 for x in text);unicode_count=len(text)-ascii_count
    # Character classes, not serialized bytes. This range is advisory, not a
    # vendor token count. Source and configurable assumptions remain explicit.
    low=math.ceil(ascii_count/policy.get('ascii_chars_per_token_low_density',6)+unicode_count/policy.get('unicode_chars_per_token_low_density',2))
    high=math.ceil(ascii_count/policy.get('ascii_chars_per_token_high_density',1)+unicode_count*policy.get('unicode_tokens_per_char_high_density',4))
    return {'lower':low,'upper':high,'exact':False,'source':'configurable character-class estimate; vendor usage remains authoritative'}

class AdaptiveContextEnvelope:
    def __init__(self,policy=None):self.policy=copy.deepcopy(policy if policy is not None else load_policy())
    def derive(self,config,*,role=None,task_family='unspecified',contract_size=0,evidence_count=0,estimate=None,recent_successes=(),compression_ratio=1):
        policy=self.policy;role=role or config.role;model=config.model_id
        model_policy=policy.get('models',{}).get(config.model,{}).get(model or '',{})
        role_policy=policy.get('roles',{}).get(role,policy.get('roles',{}).get(config.role,{}))
        role_policy={**role_policy,**policy.get('task_families',{}).get(task_family,{})}
        output=config.max_output_tokens;limits=[]
        for item in model_policy.get('limits',[])+policy.get('transport_limits',[])+policy.get('resource_limits',[]):
            if item.get('kind') not in {'PROVIDER_CONTEXT_LIMIT','PROVIDER_REQUEST_SIZE_LIMIT','GATEWAY_HARD_LIMIT','RUNTIME_MEMORY_LIMIT','USER_RESOURCE_CEILING'} or not item.get('source') or type(item.get('value')) is not int or item['value']<=0:
                raise ValueError('hard limit requires kind, positive value, units and a real source')
            if item.get('unit') not in {'tokens','bytes'}:raise ValueError('hard limit unit must be explicit')
            limits.append(copy.deepcopy(item))
        capacities=[x['value'] for x in limits if x['kind']=='PROVIDER_CONTEXT_LIMIT' and x['unit']=='tokens']
        capacity=min(capacities) if capacities else None
        if capacity is not None and output>=capacity:
            raise ContractError('PROVIDER_CONTEXT_LIMIT',details={'reason':'output reserve leaves no input capacity','source_limits':limits,'provider_dispatched':False,'failure_domain':'RESOURCE_LIMIT','correction_path_terminated':True})
        if model_policy.get('max_output_tokens') and output>model_policy['max_output_tokens']:
            raise ContractError('PROVIDER_CONTEXT_LIMIT',details={'reason':'requested output exceeds documented output maximum','source':model_policy.get('output_source'),'provider_dispatched':False,'failure_domain':'RESOURCE_LIMIT','correction_path_terminated':True})
        available=max(0,capacity-output) if capacity is not None else None
        complexity=1+role_policy.get('complexity_weight',0.2)*math.log1p(evidence_count+math.log1p(contract_size))
        history=[x for x in recent_successes if type(x) is int and x>0]
        history+=model_policy.get('recent_successful_input_tokens',{}).get(config.role,[])
        # Ratios tune a soft working set only. None is used as a universal cap.
        demand=(estimate or {}).get('upper',0)
        if history:base=statistics.median(history)*role_policy.get('history_growth_ratio',1.25)
        elif available is not None:base=available*role_policy.get('context_share',0.05)
        else:base=demand*role_policy.get('unknown_capacity_demand_ratio',0.8)
        recommended=max(1,math.ceil(base*complexity*max(compression_ratio,role_policy.get('minimum_compression_weight',0.25))))
        if available is not None:recommended=min(recommended,math.floor(available*(1-role_policy.get('headroom_ratio',0.1))))
        return {'kind':'AdaptiveContextEnvelope','provider':config.model,'requested_model':model,'bound_model':model,
            'actual_model':'NOT_OBSERVED_BEFORE_CALL','role':role,'task_family':task_family,'policy_hash':digest(policy),
            'recommended_input_envelope':recommended,'soft_budget':recommended,'expandable_range':[recommended,available],
            'output_reserve':output,'context_capacity':capacity,'actual_hard_ceiling':limits,
            'headroom_is_soft':True,'recent_success_sample_count':len(history),'contract_size_bytes':contract_size,
            'evidence_count':evidence_count,'complexity_factor':complexity,'compression_ratio':compression_ratio,
            'fallback_mode':'UNKNOWN_LIMIT_WITH_NATIVE_GATEWAY_GUARD' if capacity is None else 'SOURCE_BOUND_MODEL_CAPACITY',
            'token_estimate':estimate,'hard_limit_uses_byte_token_equivalence':False}

class ContextPacker:
    """Deterministic exact-value folding; protected facts are never truncated."""
    def __init__(self,policy=None):self.policy=copy.deepcopy(policy if policy is not None else load_policy())
    def select(self,items,soft_budget):
        weights=self.policy.get('relevance_weights',{'acceptance_links':5,'contract_links':4,'target_match':4,'failure_relevance':4,'recency':1,'uniqueness':1,'duplication':-2})
        strategy=self.policy.get('selection_algorithm','weighted_greedy')
        if strategy not in {'weighted_greedy','dependency_first'}:raise ValueError('unknown context relevance policy')
        ranked=[]
        for item in items:
            if not all(k in item for k in ('id','tier','value','ref')) or not item['ref']:raise ValueError('context item needs identity, tier, value, raw ref')
            required=item['tier']=='A' or item.get('required') is True
            score=sum(float(item.get(k,0))*v for k,v in weights.items())-float(item.get('dependency_distance',0))
            ranked.append((required,score,item))
        ranked.sort(key=lambda x:(not x[0],float(x[2].get('dependency_distance',0)) if strategy=='dependency_first' else -x[1],str(x[2]['id'])))
        included={};deferred=[];used=0;decisions=[]
        for required,score,item in ranked:
            size=estimate_tokens(encoded(item['value']),self.policy.get('token_estimation'))['upper']
            take=required or (item['tier']!='D' and used+size<=soft_budget)
            if take:included[item['id']]=copy.deepcopy(item['value']);used+=size
            else:deferred.append({'id':item['id'],'ref':item['ref'],'sha256':digest(item['value']),'tier':item['tier']})
            decisions.append({'id':item['id'],'included':take,'required':required,'score':score,'ref':item['ref'],'value_hash':digest(item['value'])})
        return {'included':included,'deferred':deferred}, {'algorithm':strategy,'decisions':decisions,'required_preserved':all(x['included'] for x in decisions if x['required'])}
    @staticmethod
    def restore(packed):
        doc=copy.deepcopy(packed);pool=doc.pop('context_values',{})
        def walk(x):
            if isinstance(x,dict):
                if set(x)=={'$context_ref'}:return walk(copy.deepcopy(pool[x['$context_ref']]))
                return {k:walk(v) for k,v in x.items()}
            if isinstance(x,list):return [walk(v) for v in x]
            return x
        return walk(doc)
    def fold(self,prompt):
        doc=copy.deepcopy(prompt);counts={};values={}
        def reserved(x):
            return isinstance(x,dict) and ('$context_ref' in x or 'context_values' in x or any(reserved(v) for v in x.values())) or isinstance(x,list) and any(reserved(v) for v in x)
        if reserved(doc):return doc,{'removed_duplicate_bytes':0,'folded_values':0,'reason':'literal reserved keys preserved; no folding'}
        def visit(x):
            if isinstance(x,(dict,list,str)) and x:
                key=encoded(x);counts[key]=counts.get(key,0)+1;values[key]=x
            if isinstance(x,dict):
                for value in x.values():visit(value)
            elif isinstance(x,list):
                for value in x:visit(value)
        visit(doc);pool={};chosen={}
        # Use net encoding benefit instead of a fixed "large string" threshold.
        for key,count in sorted(counts.items(),key=lambda x:(-len(x[0]),x[0])):
            ident='v'+digest(values[key])[:16];ref={'$context_ref':ident}
            saving=(count-1)*len(key.encode('utf8'))-count*byte_size(ref)-len(ident)-8
            if count>1 and saving>0:chosen[key]=ident
        def walk(x):
            key=encoded(x)
            if key in chosen:
                ident=chosen[key];pool[ident]=copy.deepcopy(values[key]);return {'$context_ref':ident}
            if isinstance(x,dict):return {k:walk(v) for k,v in x.items()}
            if isinstance(x,list):return [walk(v) for v in x]
            return x
        packed=walk(doc)
        if pool:packed['context_values']=pool
        if byte_size(packed)>=byte_size(doc):return doc,{'removed_duplicate_bytes':0,'folded_values':0}
        assert self.restore(packed)==doc
        return packed,{'removed_duplicate_bytes':byte_size(doc)-byte_size(packed),'folded_values':len(pool),
            'folding_rule':'$context_ref resolves to exact value in context_values; no semantic loss'}
    def assemble(self,system,prompt,config,*,recent_successes=(),tokenizer=None):
        policy=self.policy;before=byte_size(prompt)+len(system.encode('utf8'))
        original_estimate=estimate_tokens(system+encoded(prompt),policy.get('token_estimation'),tokenizer)
        context=prompt.get('context',{});role='repair' if context.get('failed_acceptance_ids') or context.get('failures') else config.role
        contracts=context.get('public_contracts') or prompt.get('tables',{}).get('public_contract_registry',{})
        before_envelope=AdaptiveContextEnvelope(policy).derive(config,role=role,task_family=context.get('task_family',context.get('kind','semantic')),
            contract_size=byte_size(contracts),evidence_count=len(context.get('failures',[]))+len(context.get('failed_acceptance_ids',[])),
            estimate=original_estimate,recent_successes=recent_successes)
        selected=copy.deepcopy(prompt);selection=None
        if isinstance(context.get('context_items'),list):
            selected['context']['context_items'],selection=self.select(context['context_items'],before_envelope['soft_budget'])
        packed,dedup=self.fold(selected)
        added_rule=' Resolve each $context_ref using the exact value in context_values. References are lossless aliases, not missing facts.' if dedup['folded_values'] else ''
        packed_system=system+added_rule
        after=byte_size(packed)+len(packed_system.encode('utf8'))
        if after>byte_size(selected)+len(system.encode('utf8')):
            packed=selected;packed_system=system;after=byte_size(selected)+len(system.encode('utf8'))
            dedup={'removed_duplicate_bytes':0,'folded_values':0,'reason':'alias instruction overhead exceeds savings'}
        estimated=estimate_tokens(packed_system+encoded(packed),policy.get('token_estimation'),tokenizer)
        envelope=AdaptiveContextEnvelope(policy).derive(config,role=role,task_family=before_envelope['task_family'],contract_size=byte_size(contracts),
            evidence_count=before_envelope['evidence_count'],estimate=estimated,recent_successes=recent_successes,compression_ratio=after/max(before,1))
        events=[]
        if original_estimate['upper']>before_envelope['soft_budget']:events+=['SOFT_BUDGET_EXCEEDED','CONTEXT_REPACK_REQUIRED']
        if estimated['upper']>envelope['soft_budget']:
            events.append('CONTEXT_EXPANSION_ALLOWED');envelope['soft_budget']=estimated['upper']
        receipt={'kind':'RequestPackingReceipt','before_bytes':before,'after_bytes':after,'dedup':dedup,
            'old_token_estimate':original_estimate,'token_estimate':estimated,'envelope_before':before_envelope,'envelope':envelope,
            'events':events,'critical_context_preserved':(self.restore(packed) if dedup['folded_values'] else packed)==selected and (selection is None or selection['required_preserved']),
            'relevance_selection':selection,'retained_prompt_hash':digest(selected),
            'packing_policy':'exact benefit-based deduplication; current goal/contracts/failures/artifact identities/raw refs are mandatory',
            'transport_metric':'system + user bytes; native gateway validates full serialized HTTP payload',
            'provider_dispatched':False}
        for limit in envelope['actual_hard_ceiling']:
            excess=after>limit['value'] if limit['unit']=='bytes' else (estimated['exact'] and estimated['upper']+config.max_output_tokens>limit['value'])
            if excess:
                raise ContractError(limit['kind'],details={'failure_domain':'RESOURCE_LIMIT','source':limit['source'],'limit':limit,
                    'packing_receipt':receipt,'correction_path_terminated':True,'provider_dispatched':False})
        if envelope['context_capacity'] and estimated['upper']+config.max_output_tokens>envelope['context_capacity'] and not estimated['exact']:
            receipt['events'].append('UNKNOWN_LIMIT');receipt['token_uncertainty']='estimate crosses documented capacity; not a proven token-limit violation; native provider guard remains authoritative'
        return packed_system,packed,receipt

class ContextReferenceResolver:
    """Explicit public, scoped views only. Never opens model-supplied paths."""
    OPERATIONS={'request_more_context','fetch_contract','fetch_artifact','fetch_evidence','fetch_dependency_result'}
    def __init__(self,entries):self.entries=copy.deepcopy(entries)
    def catalog(self):return [{'ref':k,'kind':v['kind'],'description':v.get('description',''),'sha256':digest(v['value'])} for k,v in sorted(self.entries.items()) if v.get('public') is True]
    def resolve(self,packet):
        if set(packet)!={'context_operation','ref','reason'} or packet['context_operation'] not in self.OPERATIONS or not isinstance(packet['reason'],str) or not packet['reason'].strip():
            raise ContractError('INVALID_CONTEXT_EXPANSION_REQUEST')
        item=self.entries.get(packet['ref'])
        if not item or item.get('public') is not True:raise ContractError('CONTEXT_REF_NOT_AUTHORIZED')
        if packet['context_operation']!='request_more_context' and packet['context_operation']!='fetch_'+item['kind']:
            raise ContractError('CONTEXT_REF_KIND_MISMATCH')
        value=copy.deepcopy(item['value'])
        return {'ref':packet['ref'],'reason':packet['reason'],'kind':item['kind'],'value':value,'sha256':digest(value),'bytes':byte_size(value)}
