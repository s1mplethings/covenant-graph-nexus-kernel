"""API Lab transport + canonical budget ledger + raw response observation.

The service owns credential resolution. This adapter never logs headers/keys,
repairs JSON, retries a semantic failure, or invents the returned model ID.
Per-request adapter injection avoids process-global monkeypatching.
"""
import dataclasses
import hashlib
import json
import os
import pathlib
import sys
import time
import threading
from urllib import request
from cgkn.providers import ProviderCompletion
from scripts import provider_api_budget as budget

class LiveClient:
    is_replay=False
    def __init__(self,lab_root,ledger,log_root,run_id,run_cap_cny=10,honor_reasoning_none=False):
        sys.path.insert(0,str(pathlib.Path(lab_root)/'src'))
        from cgkn_provider_lab.storage import ProviderConfigStore
        from cgkn_provider_lab.service import ProviderComparisonService
        self.providers={p.provider_id:p for p in ProviderConfigStore().load()}
        for alias,model,host in [('qwen','qwen3.8-max','dashscope.aliyuncs.com'),('deepseek','deepseek-flash','api.deepseek.com'),('grok','grok-4.7','api.x.ai')]:
            from urllib.parse import urlsplit
            p=self.providers[alias]
            if p.model!=model or urlsplit(p.base_url).hostname!=host:raise RuntimeError('Unpriced provider configuration')
        self.service=ProviderComparisonService()
        self.root=pathlib.Path(log_root);self.root.mkdir(parents=True,exist_ok=False)
        self._admission_lock=threading.RLock()
        self.run_id=run_id;self.calls=0;self.tokens=0;self.started=time.monotonic();self.run_cost=0;self.cap=run_cap_cny
        self.ledger=pathlib.Path(ledger)
        authority_path=self.ledger.parent/'budget-authorization-v8.json'
        authority=json.loads(authority_path.read_text(encoding='utf-8')) if authority_path.exists() else {}
        self.global_cap=min(100,authority.get('cumulative_api_cap_cny',100))
        self.development_ceiling=min(80,authority.get('development_ceiling_cny',80))
        self.acceptance_reserve=self.global_cap-self.development_ceiling
        self.honor_reasoning_none=honor_reasoning_none
        # CNY upper-bound tariff exceeds the verified Qwen domestic 12/36 and
        # DeepSeek peak USD .30/1.20 even at 10 CNY/USD. No cache discount assumed.
        values={'CGKN_PROVIDER_BUDGET_LEDGER':str(ledger),'CGKN_PROVIDER_MAX_API_CALLS':'3520','CGKN_PROVIDER_MAX_INPUT_TOKENS':'44000000','CGKN_PROVIDER_MAX_OUTPUT_TOKENS':'44000000','CGKN_PROVIDER_MAX_ESTIMATED_COST':str(self.development_ceiling),'CGKN_PROVIDER_INPUT_COST_PER_MILLION':'20','CGKN_PROVIDER_OUTPUT_COST_PER_MILLION':'60'}
        os.environ.update(values)
        (self.root/'billing-policy.json').write_text(json.dumps({'unit':'CNY','global_authorized':self.global_cap,'development_ceiling':self.development_ceiling,'acceptance_reserved':self.acceptance_reserve,'input_upper_per_million':20,'output_upper_per_million':60,'actual_bill':'NOT_QUERIED','sources':['https://help.aliyun.com/zh/model-studio/qwen3-8-max','https://api-docs.deepseek.com/quick_start/pricing/'],'run_cap':run_cap_cny},indent=2))
    def complete(self,*,system,user,schema_name,schema,config):
        from cgkn_provider_lab.models import ComparisonOptions
        with self._admission_lock:
            if not getattr(self,"accounting_only",False) and (self.calls>=getattr(self,"max_requests",80) or self.tokens>=getattr(self,"max_tokens",1_000_000) or time.monotonic()-self.started>=3600):raise RuntimeError('RUN_RESOURCE_LIMIT')
            provider=dataclasses.replace(self.providers[config.model],timeout_seconds=min(config.timeout_seconds,300))
            estimated=len((system+user+json.dumps(schema)).encode())+4096
            if estimated>100000 and not getattr(self,'accounting_only',False):raise RuntimeError('PRICED_CONTEXT_LIMIT')
            reserved_cost=(estimated*20+config.max_output_tokens*60)/1e6
            if not getattr(self,"accounting_only",False) and (self.run_cost+reserved_cost>self.cap or self.tokens+estimated+config.max_output_tokens>getattr(self,"max_tokens",1_000_000)):raise RuntimeError('RUN_BUDGET_EXHAUSTED')
            payload={'system':system,'user':user,'schema_name':schema_name,'schema':schema,'role':config.role,'semantic_role':'observer' if schema_name=='cgkn_observer' else config.role,'model_alias':config.model,'requested_model':provider.model,'max_output_tokens':config.max_output_tokens,'reasoning_effort_requested':config.reasoning_effort,'honor_reasoning_none':self.honor_reasoning_none}
            identity=hashlib.sha256((self.run_id+str(self.calls)+json.dumps(payload)).encode()).hexdigest()
            reservation=budget.reserve_call(case_id=self.run_id,purpose='planning' if config.role=='agent' else 'generation',model=provider.model,request_identity=identity,estimated_input_tokens=estimated,requested_output_tokens=config.max_output_tokens,retry_count=0,run_id=self.run_id,provider=provider.provider_id,execution_policy="accounting_only" if getattr(self,"accounting_only",False) else "limited",authorization_reference=getattr(self,"authorization",{}).get("user_authorization_reference"))
            self.calls+=1
            self.tokens+=estimated+config.max_output_tokens
            self.run_cost+=reserved_cost
            stem=self.root/f'call-{self.calls:03}'
        stem.with_suffix('.request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        observed={};original=getattr(self,"urlopen",None) or request.urlopen
        class ObservedResponse:
            def __init__(self,response):self.response=response;self.headers=response.headers
            def __enter__(self):return self
            def __exit__(self,*args):self.response.close()
            def read(self,*args):
                raw=self.response.read(*args)
                observed['raw']=raw
                return raw
        def observe(req,*args,**kwargs):
            emitted=json.loads(req.data)
            if self.honor_reasoning_none and config.reasoning_effort=='none':
                if provider.provider_id=='qwen':emitted['enable_thinking']=False
                elif provider.provider_id=='deepseek':emitted['thinking']={'type':'disabled'}
                elif provider.provider_id=='grok':
                    emitted['reasoning_effort']='low'
                    emitted['max_completion_tokens']=emitted.pop('max_tokens')
                req.data=json.dumps(emitted,ensure_ascii=False).encode('utf-8')
            # Body only; authorization headers never enter evidence.
            stem.with_suffix('.transport-request.json').write_text(json.dumps(emitted,ensure_ascii=False,indent=2),encoding='utf-8')
            return ObservedResponse(original(req,*args,**kwargs))
        if hasattr(self,"bind_attempt"):self.bind_attempt(reservation,estimated,config.max_output_tokens)
        budget.mark_request_started(reservation)
        try:
            # API Lab builds the request and resolves credentials; only response
            # bytes are observed to retain the upstream identity it otherwise drops.
            from cgkn_provider_lab.adapters import OpenAIChatAdapter
            from cgkn_provider_lab.service import ProviderComparisonService
            scoped=ProviderComparisonService(secret_manager=self.service.secret_manager,adapters={provider.adapter:OpenAIChatAdapter(urlopen=observe)})
            result=scoped.invoke_one(provider,user,ComparisonOptions(temperature=0,max_tokens=config.max_output_tokens,system_prompt=system,response_format={'type':'json_schema','json_schema':{'name':schema_name,'strict':True,'schema':schema}},defer_structured_validation=True,max_concurrency=1))
            raw=observed.get('raw')
            if raw:stem.with_suffix('.response.json').write_bytes(raw)
            try:doc=json.loads(raw) if raw else {}
            except (ValueError,TypeError):
                budget.finalize_call(reservation,usage=None,http_status=200,status="FAILED")
                raise RuntimeError("INCOMPLETE_PROVIDER_OUTPUT: malformed response") from None
            usage=doc.get('usage') or {}
            actual=doc.get('model')
            normalized=result.to_dict()
            normalized.update(upstream_model=actual,requested_model=provider.model)
            stem.with_suffix('.result.json').write_text(json.dumps(normalized,ensure_ascii=False,indent=2),encoding='utf-8')
            budget.mark_response_received(reservation,response=doc,http_status=200 if raw else 'UNKNOWN')
            normalized_usage=dict(usage)
            if isinstance(usage.get('total_tokens'),int) and isinstance(usage.get('prompt_tokens'),int):
                normalized_usage['completion_tokens']=max(usage.get('completion_tokens') or 0,usage['total_tokens']-usage['prompt_tokens'])
            budget.finalize_call(reservation,usage=normalized_usage,http_status=200 if raw else 'UNKNOWN',status='PASS' if result.status=='ok' else 'FAILED')
            inp=normalized_usage.get('prompt_tokens');output=normalized_usage.get('completion_tokens')
            if isinstance(inp,int) and isinstance(output,int):
                with self._admission_lock:
                    self.tokens+=inp+output-estimated-config.max_output_tokens;self.run_cost+=(inp*20+output*60)/1e6-reserved_cost

            if result.status!='ok':raise RuntimeError('PROVIDER_TRANSPORT_FAILED: '+result.error)
            if not actual:raise RuntimeError('ACTUAL_MODEL_ID_MISSING')
            if normalized.get('metadata',{}).get('finish_reason') not in ('stop', None):raise RuntimeError('INCOMPLETE_PROVIDER_OUTPUT: '+str(normalized.get('metadata',{}).get('finish_reason')))
            return ProviderCompletion(result.text,actual,doc.get('id') or result.request_id,usage,1)
        except Exception:
            # Nonterminal reservation remains conservative; never release an
            # unknown-outcome paid request or retry automatically.
            raise
