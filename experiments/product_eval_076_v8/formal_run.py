"""Mechanical frozen-matrix runner. No semantic host intervention."""
import argparse,hashlib,json,pathlib,sys,subprocess,zipfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from experiments.product_eval_076_v8.formal_contract import validate
from experiments.product_eval_076_v8.runner import run_route
from experiments.product_eval_076_v8.live_provider import LiveClient
from experiments.product_eval_076_v8.isolation import verify_audit
from scripts import provider_api_budget as budget

def unzip(path):
 with zipfile.ZipFile(path) as z:
  files={}
  for item in z.infolist():
   name=item.filename;rel=pathlib.PurePosixPath(name)
   if item.is_dir():continue
   if rel.is_absolute() or '..' in rel.parts or ':' in name or (item.external_attr>>16)&0o170000==0o120000:raise RuntimeError('Unsafe frozen snapshot')
   files[name]=z.read(item)
  return files
def main():
 p=argparse.ArgumentParser();p.add_argument('--seal',required=True,type=pathlib.Path);p.add_argument('--root',required=True,type=pathlib.Path);p.add_argument('--ledger',required=True,type=pathlib.Path);p.add_argument('--lab-root',required=True);a=p.parse_args()
 seal=json.loads(a.seal.read_text());root=a.root.resolve();root.mkdir(exist_ok=True)
 state_path=root/'matrix-state.json'
 if state_path.exists():state=json.loads(state_path.read_text())
 else:
  state={'seal_sha256':hashlib.sha256(a.seal.read_bytes()).hexdigest(),'rows':[{**r,'status':r.get('status','NOT_RUN')} for r in seal['matrix']]};state_path.write_text(json.dumps(state,indent=2))
 if state['seal_sha256']!=hashlib.sha256(a.seal.read_bytes()).hexdigest():raise RuntimeError('FORMAL_SEAL_CHANGED')
 remaining=[r for r in state['rows'] if r['status']=='NOT_RUN']
 if not remaining:print('ALL_REGISTERED_ROWS_TERMINAL');return
 pair=remaining[:2]
 if len(pair)!=2 or pair[0]['task_id']!=pair[1]['task_id']:raise RuntimeError('PAIR_INTEGRITY_FAILURE')
 for row in pair:validate(a.seal,row['run_id'],row['route'])
 cap=seal['per_run_cost_cap_cny']
 with budget._locked(a.ledger):
  ledger=json.loads(a.ledger.read_text());used=ledger['totals']['estimated_cost']
  # Pre-registered symmetric tail allocation: release unused reserve and shrink
  # both members equally from remaining authorization, never based on results.
  cap=min(cap,max(0,(seal['development_ceiling_cny']-used)/2))
  if cap<seal['minimum_admissible_run_cap_cny']:
   block={'reason':'PAIR_BUDGET_RESERVATION_UNAVAILABLE','used_upper_cny':used,'required_pair_reserve_cny':2*cap,'development_ceiling_cny':seal['development_ceiling_cny'],'global_cumulative_cap_cny':seal['global_cap_cny'],'acceptance_reserved_cny':seal['global_cap_cny']-seal['development_ceiling_cny'],'pair':[r['run_id'] for r in pair]}
   (root/'budget-stop.json').write_text(json.dumps(block,indent=2));print(json.dumps(block));return
 (root/('pair-budget-'+pair[0]['run_id']+'.json')).write_text(json.dumps({'used_before':used,'equal_cap_each':cap,'rule':'min(frozen_cap, remaining_global/2)','acceptance_reserve':0},indent=2))
 for row in pair:
  run=root/row['run_id'];run.mkdir(exist_ok=False)
  card=json.loads(pathlib.Path(row['task_path']).read_text(encoding='utf-8'))
  if card['kind']=='SELF_EVOLVE':
   # Refuse implicit predecessor replacement. Only a separately verified whitelist may enter.
   pred=root/row['predecessor_run_id'];ready=pred/'public-predecessor.json'
   if not ready.exists():row['status']='BLOCKED_BY_PREDECESSOR';state_path.write_text(json.dumps(state,indent=2));continue
   manifest=json.loads(ready.read_text());initial=unzip(pathlib.Path(manifest['snapshot']))
  else:initial=unzip(pathlib.Path(row['initial_snapshot']))
  public={'task.json':json.dumps(card,ensure_ascii=False,indent=2),'tool-policy.txt':seal['tool_policy']}
  for name,path in row['inputs'].items():public[name]=pathlib.Path(path).read_bytes()
  if card['domain']=='promotion':public['target.json']=json.dumps({'kind':'CONTROLLED_TEST_TARGET_NOT_REAL_PLATFORM','base_url':'http://127.0.0.1:9001','account':row['run_id'],'api':'POST /posts JSON account,correlation,text,media,version; media must carry actual image bytes as a base64 data URI, not a local filename. GET /receipts?correlation=... independently reads accepted payloads; GET /health. No platform statistics are supported. Errors may occur; never assume request failure proves no remote write.','real_platform_authorized':False})
  goal='Implement the public business task in /input/task.json using the supplied project and raw inputs. Independently explore, plan, implement, test and debug. Preserve required existing data and workflows. Deliver the saved project with GUI startup/use instructions, your own tests and truthful limitations. No host implementation help is available.'
  goal+=' Your own complete public protocol-calibration request/response record is in /input/own-protocol-calibration.json; it contains no formal evaluation feedback.'
  if card['kind']=='SELF_EVOLVE':goal+=' Apply the new_requirement to your specified first B0 predecessor; do not substitute another starting product.'
  row['status']='STARTED';state_path.write_text(json.dumps(state,indent=2))
  (run/'assembly.json').write_text(json.dumps({'public_hashes':{n:hashlib.sha256(v if isinstance(v,bytes) else v.encode()).hexdigest() for n,v in public.items()},'initial_hashes':{n:hashlib.sha256(v).hexdigest() for n,v in initial.items()},'goal':goal,'seal_sha256':state['seal_sha256']},indent=2))
  client=LiveClient(a.lab_root,a.ledger,run/'provider',row['run_id'],run_cap_cny=cap,honor_reasoning_none=True)
  b,receipt=run_route(root=run/'run',run_id=row['run_id'],route=row['route'],image=seal['image'],client=client,goal=goal,public_files=public,initial_files=initial,controlled_target=card['domain']=='promotion',mode='FORMAL',formal_seal=a.seal)
  result={'receipt':receipt,'calls':client.calls,'tokens_budget_accounted':client.tokens,'upper_tariff_cost_cny':client.run_cost,'actual_bill':'NOT_QUERIED','audit':verify_audit(b.audit_path),'host_semantic_assistance_count':0,'product_acceptance':'UNTESTED'}
  (run/'formal-result.json').write_text(json.dumps(result,indent=2));row.update(status='DEVELOPMENT_ENDED',result=str(run/'formal-result.json'));state_path.write_text(json.dumps(state,indent=2))
  frozen=run/'frozen';x=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('freeze_candidate.py')),'--dev-root',str(run),'--output',str(frozen),'--image',seal['image'],'--receipt-name','formal-result.json'],capture_output=True,text=True,timeout=180)
  (run/'freeze-command.json').write_text(json.dumps({'exit':x.returncode,'stdout':x.stdout,'stderr':x.stderr},indent=2))
  if x.returncode:raise RuntimeError('CANDIDATE_FREEZE_FAILED')
  print(json.dumps({'run_id':row['run_id'],'end':receipt['result'],'calls':client.calls,'cost_upper':client.run_cost}),flush=True)
if __name__=='__main__':main()
