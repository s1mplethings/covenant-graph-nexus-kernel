"""Append truthful accounting after a controller interruption, without replay.

Requires the development container to be absent. Original ledger entries and
candidate files are never changed. Unknown usage retains its reservation.
"""
import argparse
import hashlib
import json
import subprocess
import time
from decimal import Decimal
from pathlib import Path
from .budget_policy import ledger_cost
from experiments.product_dev_089.isolation import verify_audit


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',required=True,type=Path)
    p.add_argument('--prior',required=True,type=Path)
    p.add_argument('--run-id',required=True)
    p.add_argument('--reason',required=True)
    a=p.parse_args()
    if (a.stage/'dev-result.json').exists():raise RuntimeError('original receipt already exists')
    if subprocess.run(['docker','inspect','eval076-'+a.run_id],capture_output=True).returncode==0:
        raise RuntimeError('development environment still exists')
    prior=json.loads(a.prior.read_text())
    ledger=Path('F:/CGKN-ITER-076/global-provider-budget.json')
    calls={r['request_identity']:r for r in json.loads(ledger.read_text())['calls']}
    tokens=0;cost=Decimal(0);rows=[]
    requests=sorted((a.stage/'provider').glob('*.request.json'))
    for request in requests:
        payload=json.loads(request.read_text())
        number=int(request.name.split('.')[0].split('-')[1])
        key=hashlib.sha256(('dev113-cgnk-continuous'+str(number-1)+json.dumps(payload)).encode()).hexdigest()
        row=calls[key]
        i=row['input_tokens'] if isinstance(row['input_tokens'],int) else row['reserved_input_tokens']
        o=row['output_tokens'] if isinstance(row['output_tokens'],int) else row['reserved_output_tokens']
        tokens+=i+o;cost+=(Decimal(i)*20+Decimal(o)*60)/1000000
        rows.append({'call_id':row['call_id'],'status':row['status'],'request_file':request.name})
    resource={**prior,'calls':prior['calls']+len(rows),'tokens':prior['tokens']+tokens,
        'cost':float(Decimal(str(prior['cost']))+cost),'ledger_cost':str(ledger_cost(ledger)),
        'development_seconds':prior['development_seconds']+time.time()-min(p.stat().st_mtime for p in requests),
        'reconstruction':'per-request canonical ledger identities; unknown reservations retained; wall time upper estimate'}
    receipt={'run_id':a.run_id,'route':'R_CGNK','mode':'DEV',
        'result':{'status':'FRAMEWORK_REPAIR_REQUIRED','reason':a.reason,'host_interruption':True},'model_calls':len(rows)}
    for name,value in [('resources.json',resource),('dev-result.json',{'receipt':receipt,'resources':resource,
        'audit':verify_audit(a.stage/'run/audit.jsonl'),'call_attribution':rows,'new_conservative_cny':str(cost),
        'business_code_written_by_host':False})]:
        (a.stage/name).write_text(json.dumps(value,indent=2))
    print(json.dumps(resource))


if __name__=='__main__':main()
