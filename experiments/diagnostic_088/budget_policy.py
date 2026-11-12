"""v1: same conservative tariff, bounded real output; no semantic compaction."""
import dataclasses
import json
import os
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from experiments.product_eval_076_v8.live_provider import LiveClient

MIN_OUTPUT=1024
def choose_output(*,input_upper,requested,remaining):
    amount=Decimal(str(remaining)) - Decimal(input_upper)*20/1000000
    affordable=int((amount*1000000/60).to_integral_value(rounding=ROUND_FLOOR))
    limit=min(requested,affordable)
    if limit<MIN_OUTPUT:raise RuntimeError('MINIMUM_REQUEST_UNAFFORDABLE')
    return limit

def ledger_cost(path):
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
        if authorization is None:raise RuntimeError('ITER088_PAID_AUTHORIZATION_REQUIRED')
        auth=json.loads(Path(authorization).read_text(encoding='utf-8'))
        if auth.get('stage')!='ITER-088-DEV-PAIR' or auth.get('approved') is not True or not auth.get('user_authorization_reference'):
            raise RuntimeError('ITER088_PAID_AUTHORIZATION_REQUIRED')
        self.authorization=auth
        super().__init__(*args,**kwargs)
        self.global_cap=float(auth['cumulative_cap_cny']);self.development_ceiling=self.global_cap;self.acceptance_reserve=0
        os.environ['CGKN_PROVIDER_MAX_ESTIMATED_COST']=str(self.global_cap)
        if self.cap>auth['route_cap_cny']:raise RuntimeError('ROUTE_CAP_EXCEEDS_AUTHORIZATION')
        (self.root/'stage-billing-policy.json').write_text(json.dumps(auth,indent=2),encoding='utf-8')
    def complete(self,*,system,user,schema_name,schema,config):
        estimated=len((system+user+json.dumps(schema)).encode())+4096
        remaining=min(Decimal(str(self.cap))-Decimal(str(self.run_cost)),Decimal(str(self.global_cap))-ledger_cost(self.ledger))
        record={'version':'iter088-output-admission-v1','input_upper_tokens':estimated,'requested_output':config.max_output_tokens,'remaining':str(remaining),'transmitted':False}
        try:
            output=choose_output(input_upper=estimated,requested=config.max_output_tokens,remaining=remaining)
            record['admitted_output']=output
        except RuntimeError as e:
            record['reason']=str(e)
            with (self.root/'admission.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
            raise
        with (self.root/'admission.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
        return super().complete(system=system,user=user,schema_name=schema_name,schema=schema,config=dataclasses.replace(config,max_output_tokens=output))
