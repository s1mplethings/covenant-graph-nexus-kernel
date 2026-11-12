"""The original two calibration responses through actual isolated route, no API."""
import json
from .capture import ROOT,OLD,save
from .replay import RecordedClient
from .offline import no_provider
from experiments.product_eval_076_v8.runner import run_route
from experiments.product_eval_076_v8.isolation import verify_audit
IMAGE='sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20'

def main():
    out=ROOT/'actual-route-replay-v2';out.mkdir(exist_ok=False)
    rows=[]
    with no_provider(ROOT/'forbidden-provider.jsonl'):
        for route,suffix in [('R_CGNK','cgnk'),('R_DIRECT','direct')]:
            source=OLD/('protocol-v8-r-'+suffix)
            result=json.loads((source/'protocol-result.json').read_text())
            b,r=run_route(root=out/suffix,run_id='diag088-'+suffix,route=route,image=IMAGE,client=RecordedClient(source),goal=result['goal'],public_files={'probe.txt':(source/'run/public/probe.txt').read_bytes()},mode='HARNESS_CONFORMANCE_ONLY')
            rows.append({'receipt':r,'audit':verify_audit(b.root/'audit.jsonl'),'paid_calls':0,'candidate_product_credit':False})
    save(out/'results.json',rows);print(json.dumps(rows,indent=2))
if __name__=='__main__':main()
