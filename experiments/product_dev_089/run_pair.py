"""One authorized DEV pair only. Default is read-only preflight, never payment."""
import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from .packet import ROOT,OLD,save,sha
from .budget_policy import BoundedClient,ledger_cost
from .conformance import IMAGE
from .runner import run_route
from .isolation import verify_audit

def validate(packet):
    seal=json.loads((packet/'freeze.json').read_text(encoding='utf-8'))
    for path,digest in seal['files'].items():
        if sha(Path(path))!=digest:raise RuntimeError('FREEZE_MISMATCH: '+path)
    if seal['reference_validation']!='PASS':raise RuntimeError('REFERENCE_NOT_READY')
    return seal

def main():
    p=argparse.ArgumentParser();p.add_argument('--packet',type=Path,default=ROOT/'dev-packet');p.add_argument('--authorization',type=Path);p.add_argument('--execute',action='store_true');a=p.parse_args()
    seal=validate(a.packet)
    if not a.execute:
        print(json.dumps({'status':'LOCAL_PREFLIGHT_PASS','paid_calls':0,'paid_authorization':False,'cost_plan':str(a.packet/'cost-plan.json')}));return
    if a.authorization is None:raise RuntimeError('ITER089_PAID_AUTHORIZATION_REQUIRED')
    auth=json.loads(a.authorization.read_text(encoding='utf-8'));plan=json.loads((a.packet/'cost-plan.json').read_text())
    if not auth.get('approved') or not auth.get('user_authorization_reference') or auth.get('stage')!=plan['stage']:raise RuntimeError('ITER089_PAID_AUTHORIZATION_REQUIRED')
    for key in ['route_cap_cny','pair_hard_cap_cny','cumulative_cap_cny']:
        if auth[key]!=plan[key]:raise RuntimeError('AUTHORIZATION_PLAN_MISMATCH')
    if float(ledger_cost(OLD/'global-provider-budget.json'))+plan['pair_hard_cap_cny']>plan['cumulative_cap_cny']+1e-8:raise RuntimeError('PAIR_NOT_FUNDED')
    out=ROOT/'dev-pair-v1';out.mkdir(exist_ok=False)
    with zipfile.ZipFile(a.packet/'initial.zip') as z:
        initial={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    public={p.name:p.read_bytes() for p in (a.packet/'public').iterdir() if p.is_file()}
    results=[]
    for route,suffix in [('R_DIRECT','direct'),('R_CGNK','cgnk')]:
        validate(a.packet)
        run_id='dev089-video-'+suffix;d=out/run_id;d.mkdir()
        client=BoundedClient('D:/cgkn-provider-api-lab',OLD/'global-provider-budget.json',d/'provider',run_id,run_cap_cny=plan['route_cap_cny'],honor_reasoning_none=True,authorization=a.authorization)
        goal='Complete the public user task in /input/task.json using the existing project in /workspace. Independently explore, develop, test and hand off reproducible operation instructions. Public scoring semantics are in /input/scoring-contract.json and execution limits/contracts are in /input/execution-policy.json. No host business assistance.'
        b,receipt=run_route(root=d/'run',run_id=run_id,route=route,image=IMAGE,client=client,goal=goal,public_files=public,initial_files=initial,mode='DEV')
        value={'receipt':receipt,'calls':client.calls,'upper_tariff_cost_cny':client.run_cost,'audit':verify_audit(b.root/'audit.jsonl'),'new_formal_runs':0,'milestones':'To be independently assessed from actions and frozen candidate, not file counts','acceptance':'PENDING_INDEPENDENT_GUI_AND_MEDIA'}
        save(d/'dev-result.json',value)
        frozen=subprocess.run([sys.executable,'experiments/product_eval_076_v8/freeze_candidate.py','--dev-root',str(d),'--output',str(d/'frozen'),'--image',IMAGE],capture_output=True,text=True,timeout=150)
        save(d/'freeze-command.json',{'exit':frozen.returncode,'stdout':frozen.stdout,'stderr':frozen.stderr})
        results.append(value);save(out/'results.json',results)
        # No repeat/repair loop, even on deterministic framework errors. The other
        # authorized route remains independent and proceeds once.
    print(json.dumps({'attempts':len(results),'next':'Independent operator follows frozen acceptance protocol on each frozen snapshot; no private feedback to development.'}))
if __name__=='__main__':main()
