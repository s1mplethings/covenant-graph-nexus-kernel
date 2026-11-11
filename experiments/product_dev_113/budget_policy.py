"""v1: same conservative tariff, bounded real output; no semantic compaction."""
import dataclasses
import json
import os
import threading
_SERIAL = threading.RLock()
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from .live_provider import LiveClient

MIN_OUTPUT=1024
def choose_output(*,input_upper,requested,remaining):
    amount=Decimal(str(remaining)) - Decimal(input_upper)*20/1000000
    affordable=int((amount*1000000/60).to_integral_value(rounding=ROUND_FLOOR))
    limit=min(requested,affordable)
    if limit<MIN_OUTPUT:raise RuntimeError('MINIMUM_REQUEST_UNAFFORDABLE')
    return limit

def ledger_cost(path):
    if not Path(path).exists():return Decimal('0')
    rows=json.loads(Path(path).read_text())['calls']
    total=Decimal('0')
    for c in rows:
        if c.get('status')=='CANCELLED_BEFORE_SEND':continue
        i=c.get('input_tokens');o=c.get('output_tokens')
        total+=(Decimal(i if isinstance(i,int) else c['reserved_input_tokens'])*20+Decimal(o if isinstance(o,int) else c['reserved_output_tokens'])*60)/1000000
    return total

class BoundedClient(LiveClient):
    """Explicit stage authorization is mandatory before touching credential APIs.

    Only actual config.max_output_tokens changes. The inherited adapter uses it
    in reservation, request record AND ComparisonOptions passed to API Lab.
    Serial pair execution preserves the canonical ledger's concurrency checks.
    """
    def __init__(self,*args,authorization=None,**kwargs):
        if authorization is None:raise RuntimeError('ITER113_PAID_AUTHORIZATION_REQUIRED')
        auth=json.loads(Path(authorization).read_text(encoding='utf-8'))
        if auth.get('stage')!='ITER-113-ACV-MULTI-API' or auth.get('approved') is not True or not auth.get('user_authorization_reference'):
            raise RuntimeError('ITER113_PAID_AUTHORIZATION_REQUIRED')
        self.transport_retries=0
        self.accounting_only=auth.get("execution_policy")=="accounting_only"
        self.unavailable=set() if self.accounting_only else {"qwen"}
        self.authorization=auth
        self.max_requests=int(auth.get("max_requests",80))
        if self.max_requests<1:raise RuntimeError("INVALID_REQUEST_LIMIT")
        self.max_tokens=int(auth.get("max_tokens",1_000_000))
        if self.max_tokens<1:raise RuntimeError("INVALID_TOKEN_LIMIT")
        super().__init__(*args,**kwargs)
        self.global_cap=None if self.accounting_only else float(auth['cumulative_cap_cny']);self.development_ceiling=self.global_cap;self.acceptance_reserve=0
        if not self.accounting_only:os.environ['CGKN_PROVIDER_MAX_ESTIMATED_COST']=str(self.global_cap)
        if not self.accounting_only and self.cap>auth['route_cap_cny']:raise RuntimeError('ROUTE_CAP_EXCEEDS_AUTHORIZATION')
        (self.root/'stage-billing-policy.json').write_text(json.dumps(auth,indent=2),encoding='utf-8')
    def complete(self, **kwargs):
        # Process-global adapter interception cannot overlap safely. Admission,
        # transport and settlement are one critical section; never oversubscribe.
        with _SERIAL:
            chosen=kwargs['config'].model
            if chosen in self.unavailable:
                remaining=[m for m in ('deepseek','grok') if m not in self.unavailable]
                if not remaining:raise RuntimeError('NO_AVAILABLE_PROVIDER')
                kwargs={**kwargs,'config':dataclasses.replace(kwargs['config'],model=remaining[0])}
            try:
                return self._complete(**kwargs)
            except RuntimeError as exc:
                if not str(exc).startswith('PROVIDER_TRANSPORT_FAILED:'):raise
                failed=kwargs['config'].model
                self.unavailable.add(failed)
                alternatives=[m for m in ('deepseek','grok') if m not in self.unavailable]
                with (self.root/'provider-switch.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'from':failed,'to':alternatives[0] if alternatives else None,'reason':str(exc),'state':'same bounded task and raw evidence; no tool replay','prior_reservation_retained':True})+'\n')
                if not alternatives:raise
                return self._complete(**{**kwargs,'config':dataclasses.replace(kwargs['config'],model=alternatives[0])})

    def _complete(self,*,system,user,schema_name,schema,config):
        if config.model in self.unavailable:raise RuntimeError('PROVIDER_UNAVAILABLE_AFTER_SUSTAINED_TRANSPORT_FAILURE')
        if self.accounting_only:
            return super().complete(system=system,user=user,schema_name=schema_name,schema=schema,config=config)
        estimated=len((system+user+json.dumps(schema)).encode())+4096
        remaining=min(Decimal(str(self.cap))-Decimal(str(self.run_cost)),Decimal(str(self.global_cap))-ledger_cost(self.ledger))
        record={'version':'iter113-output-admission-v1','input_upper_tokens':estimated,'requested_output':config.max_output_tokens,'remaining':str(remaining),'transmitted':False}
        try:
            output=choose_output(input_upper=estimated,requested=config.max_output_tokens,remaining=remaining)
            record['admitted_output']=output
        except RuntimeError as e:
            record['reason']=str(e)
            with (self.root/'admission.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
            raise
        with (self.root/'admission.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
        try:
            return super().complete(system=system,user=user,schema_name=schema_name,schema=schema,config=dataclasses.replace(config,max_output_tokens=output))
        except RuntimeError as exc:
            if str(exc).startswith('PROVIDER_TRANSPORT_FAILED:') and self.transport_retries < 1 and not (self.root/f'call-{self.calls:03}.response.json').exists() and any(t in str(exc).lower() for t in ('urlopen error','timed out','connection','winerror')):
                self.transport_retries += 1
                with (self.root/'transport-retry.jsonl').open('a') as f:f.write(json.dumps({'prior_call':self.calls,'reason':str(exc),'retry':1,'old_reservation_retained':True})+'\n')
                return self.complete(system=system,user=user,schema_name=schema_name,schema=schema,config=config)
            raise
        finally:
            import time
            (self.root/'resource-state.json').write_text(json.dumps({'calls':self.calls,'tokens':self.tokens,'cost':self.run_cost,'development_seconds':time.monotonic()-self.started,'transport_retries':self.transport_retries}))
