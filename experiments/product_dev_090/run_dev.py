"""Single CGNK engineering DEV, with explicitly linked same-budget continuations."""
import argparse,json,zipfile,subprocess,sys,time,hashlib
from pathlib import Path
from .packet import ROOT,IMAGE,save
from .budget_policy import BoundedClient,ledger_cost
from .runner import run_route
from experiments.product_dev_089.isolation import verify_audit

def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--freeze',default='freeze-v2.json');p.add_argument('--packet',type=Path,default=ROOT/'packet-v1');p.add_argument('--stage',type=int,default=1);p.add_argument('--feedback',type=Path);a=p.parse_args()
 packet=a.packet;seal=json.loads((packet/a.freeze).read_text(encoding='utf-8'))
 for path,h in seal['files'].items():
  if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=h:raise RuntimeError('FREEZE_MISMATCH '+path)
 if not a.execute:print('LOCAL_CONFIG_VALID; no paid calls');return
 auth=json.loads((ROOT/'authorization.json').read_text());stage=ROOT/f'dev-stage-{a.stage:02d}';stage.mkdir(exist_ok=False)
 initial=packet/'initial.zip';previous=None
 if a.stage>1:
  prior=ROOT/f'dev-stage-{a.stage-1:02d}';previous=json.loads((prior/'resources.json').read_text());initial=prior/'frozen/candidate.zip'
  if a.feedback is None:raise RuntimeError('Linked public feedback required')
 public={p.name:p.read_bytes() for p in (packet/'public').iterdir() if p.is_file()}
 if a.feedback:public['exposed-feedback.json']=a.feedback.read_bytes()
 if previous:
  public['previous-development.json']=json.dumps({'source_stage':a.stage-1,'raw_provider_records':{f.name:json.loads(f.read_text(encoding='utf-8')) for f in (prior/'provider').glob('*.request.json')},'raw_model_results':{f.name:json.loads(f.read_text(encoding='utf-8')) for f in (prior/'provider').glob('*.result.json')}},ensure_ascii=False).encode()
 with zipfile.ZipFile(initial) as z:files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
 run_id=f'dev090-cgnk-stage-{a.stage:02d}'
 client=BoundedClient('D:/cgkn-provider-api-lab','F:/CGKN-ITER-076/global-provider-budget.json',stage/'provider','dev090-cgnk-continuous',run_cap_cny=auth['route_cap_cny'],honor_reasoning_none=True,authorization=ROOT/'authorization.json')
 if previous:
  client.calls=previous['calls'];client.tokens=previous['tokens'];client.run_cost=previous['cost'];client.started=time.monotonic()-previous['development_seconds'];client.transport_retries=previous['transport_retries']
 task=json.loads(public['task.json'])
 public_goal={k:v for k,v in task.items() if k not in {'score_mapping','FAQ','future_self_evolve','milestones'}}
 goal='Complete the whole public Source Cabinet video project, including effective own tests and handoff. Original archive capabilities are existing, not new credit. Develop under CGNK using bounded workers and isolated tools. You own decomposition and implementation decisions. Full immutable requirements follow: '+json.dumps(public_goal,ensure_ascii=False)
 if a.feedback:goal+=' This is continuation of your own last candidate, not a fresh attempt. Your own raw previous requests/results are available at /input/previous-development.json. Read /input/exposed-feedback.json for raw public acceptance or framework feedback and continue self-repair within the same resource budget.'
 b,receipt=run_route(root=stage/'run',run_id=run_id,route='R_CGNK',image=IMAGE,client=client,goal=goal,public_files=public,initial_files=files,mode='DEV')
 resource={'calls':client.calls,'tokens':client.tokens,'cost':client.run_cost,'development_seconds':time.monotonic()-client.started,'transport_retries':client.transport_retries,'ledger_cost':str(ledger_cost(client.ledger))}
 save(stage/'resources.json',resource);save(stage/'dev-result.json',{'receipt':receipt,'resources':resource,'audit':verify_audit(b.audit_path),'source_version':seal['version'],'initial':str(initial),'feedback':str(a.feedback) if a.feedback else None})
 cmd=[sys.executable,'experiments/product_eval_076_v8/freeze_candidate.py','--dev-root',str(stage),'--output',str(stage/'frozen'),'--image',IMAGE]
 r=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=150)
 save(stage/'freeze-command.json',{'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
 print(json.dumps({'stage':a.stage,'receipt':receipt,'resource':resource,'freeze_exit':r.returncode}))
if __name__=='__main__':main()
