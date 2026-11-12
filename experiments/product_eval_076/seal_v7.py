"""One-time immutable registration of ITER-076's calibrated benchmark."""
import hashlib,json,pathlib,subprocess,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from experiments.product_eval_076.routes import TOOL_POLICY
from experiments.product_eval_076.formal_contract import validate

def main():
 root=pathlib.Path('F:/CGKN-ITER-076');bench=root/'benchmark-v5';src=pathlib.Path(__file__).parent
 out=bench/'freeze-v7.json'
 if out.exists():raise RuntimeError('Immutable seal already exists')
 def read(p):return json.loads(p.read_text(encoding='utf-8'))
 def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
 def save(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
 conf=read(root/'conformance-v7-01/conformance.json')
 assert len(conf['results'])==2 and all(x['status']=='PASS' for x in conf['results'])
 critical=['runner.py','routes.py','isolation.py','browser.py','sidecar.py','controlled_target.py','live_provider.py','formal_contract.py','formal_run.py','freeze_candidate.py']
 for n in critical:assert sha(src/n)==conf['source_hashes'][n],n
 cleanup=subprocess.run(['docker','rm','-f','eval076-private-reference-target','eval076-private-reference'],capture_output=True,text=True)
 save(bench/'private/validation/cleanup.json',{'exit':cleanup.returncode,'stdout':cleanup.stdout,'stderr':cleanup.stderr})
 assert cleanup.returncode==0
 dev=read(root/'dev-admission.json');assert len(dev['runs'])==12
 results=[]
 for run in dev['runs']:
  p=root/run/'dev-result.json'
  if not p.exists():
   matches=list(root.glob('**/'+run+'/dev-result.json'));assert len(matches)==1,(run,matches);p=matches[0]
  results.append({'run_id':run,'path':str(p),'sha256':sha(p),'result':read(p)})
 calibration={'status':'PASS','scope':'Calibration executed and limits fixed, NOT product success or all DEV passes','dev_count':12,'results':results,'known_gap':'Earlier CGNK DEV lacked lifecycle text in serialized Agent goal. v7 forwards identical generic tool policy; verified through actual route replay, not a new paid DEV. Original failures retained.','paid_extra_dev_after_12':0,'formal_cap_cny':6,'global_cap_cny':50,'acceptance_reserve_cny':10}
 save(bench/'dev-calibration-v7.json',calibration)
 rows=read(bench/'matrix.json')['rows']
 for r in rows:
  cardpath=bench/'public'/r['task_id']/'task.json';card=read(cardpath)
  card['formal_frozen']=True
  if card['kind']=='SELF_EVOLVE':
   o={'id':card['task_id']+'-evolution','must':True,'requirement':card['new_requirement'],'primary_score':'F1'}
   card['public_requirements'].append(o);card['score_mapping']['F1']['obligations'].append(o['id'])
  save(cardpath,card)
  r.update(run_id=f"formal-{r['order']:03d}-"+('direct' if r['route']=='R_DIRECT' else 'cgnk'),task_path=str(cardpath),initial_snapshot=str(bench/card['initial_snapshot']))
  names=['speech-a.mp4','bad-video.mp4'] if card['domain']=='video' else ['project-source.zip','release-before.json','release-after.json']
  if card['domain']=='video' and card['level']!='B-2':names.append('speech-b.mp4')
  r['inputs']={n:str(root/'formal-input-v5'/n) for n in names}
 for r in rows:
  if r['task_id'].startswith('SELF_EVOLVE'):
   task=r['task_id'].replace('SELF_EVOLVE','TAKEOVER');r['predecessor_run_id']=next(x['run_id'] for x in rows if x['task_id']==task and x['route']==r['route'])
 contract=read(bench/'scoring-contract.json');contract['formal_frozen']=True;save(bench/'scoring-contract.json',contract)
 oracle=read(bench/'private/evaluator-contract.json');oracle['status']='FROZEN';save(bench/'private/evaluator-contract.json',oracle)
 evidence_paths={'route_conformance':root/'conformance-v7-01/conformance.json','initial_snapshot_validation':root/'initial-check-v5/receipt.json','reference_behavior':bench/'private/validation/reference-checks.json','negative_variants':bench/'private/validation/reference-checks.json','dev_calibration':bench/'dev-calibration-v7.json'}
 assert read(evidence_paths['reference_behavior'])['status']=='PASS'
 artifacts=list((bench/'public').glob('*/task.json'))+[bench/n for n in ['initial.zip','initial-legacy.zip','neutral.zip','scoring-contract.json','private/evaluator-contract.json','dev-calibration-v7.json']]
 artifacts+=list((bench/'private/validation').glob('*'))
 artifacts+=[pathlib.Path(p) for r in rows for p in r['inputs'].values()]
 artifacts+=[root/'formal-input-v5/media-validation.json']
 seal={'status':'FROZEN','benchmark_version':'ITER-076-v7','source_head':'0bd7134ade87cb6ece13f8f7868860cd2c3ba67c','image':conf['image'],'seed':7601,'tool_policy':TOOL_POLICY,'global_cap_cny':50,'development_ceiling_cny':40,'per_run_cost_cap_cny':6,'single_run_limits':{'seconds':3600,'requests':80,'input_plus_output_tokens':1000000,'tool_seconds':120},'model_routes':{'R_DIRECT':'Qwen agent requested qwen; observed qwen3.8-max','R_CGNK':'Qwen AgentComposer plus deepseek worker; observed qwen3.8-max/deepseek-flash; whole-system comparison'},'rules':{'transport_retries':0,'host_semantic_assistance':False,'private_feedback_to_development':False,'operator_recheck':1,'paired_replacement':'If evaluator invalid, retain original, version benchmark, rerun both only within remaining budget; no selective replacement','clarification':'Frozen public FAQ verbatim or model declares assumption; no implementation guidance','stop':'Global or single-run limits, verified environment/permission/isolation/integrity blocker, or predecessor failure. Preserve all not-run cells.','real_publication':'Not authorized; controlled target only. G5 BLOCKED_DEP.','domain_review':'Human review pending; automated checks do not complete it.'},'evidence':{k:{'status':'PASS','path':str(p),'sha256':sha(p)} for k,p in evidence_paths.items()},'source_hashes':{n:sha(src/n) for n in critical},'artifact_hashes':{str(p):sha(p) for p in artifacts if p.is_file()},'matrix':rows}
 save(out,seal)
 for r in rows:validate(out,r['run_id'],r['route'])
 print(json.dumps({'seal':str(out),'sha256':sha(out),'registered':len(rows),'paid_calls':0}))
if __name__=='__main__':main()
