"""Account for every paid attempt and preserve separate benchmark versions."""
import json,pathlib,hashlib,collections,subprocess,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from experiments.product_eval_076_v8.formal_contract import validate
from experiments.product_eval_076_v8.isolation import verify_audit
root=pathlib.Path('F:/CGKN-ITER-076');out=root/'closeout-v8';out.mkdir(exist_ok=False)
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
sealpath=root/'benchmark-v8/freeze-v8.json';seal=read(sealpath);rows=[];attempts=[];pairs=[]
for row in seal['matrix']:
 validate(sealpath,row['run_id'],row['route'])
 version='v7' if row['order']<=4 else 'v8';d=root/('formal-'+version)/row['run_id'];r=read(d/'formal-result.json');a=read(d/'acceptance/acceptance.json')
 assert r['calls']>0 and a['status']=='NOT_DELIVERABLE'
 item={**row,'version':version,'status':'DEVELOPMENT_ENDED','product_status':a['status'],'calls':r['calls'],'cost_upper_cny':r['upper_tariff_cost_cny'],'raw_end':r['receipt']['result'],'acceptance':str(d/'acceptance/acceptance.json'),'engineering':a['engineering'],'confirmed_points':a['confirmed_points'],'evaluated_weight':a['evaluated_weight'],'pending_weight':a['pending_weight'],'score_range':a['possible_total_range'],'candidate_sha256':a['candidate_sha256']}
 item['registered_budget_cap_cny']=6 if version=='v7' else read(root/'formal-v8'/('pair-budget-'+seal['matrix'][(row['order']-1)//2*2]['run_id']+'.json'))['equal_cap_each']
 rows.append(item);attempts.append({'run_id':row['run_id'],'phase':'FORMAL_'+version,'route':row['route'],'calls':r['calls'],'cost':r['upper_tariff_cost_cny'],'audit':verify_audit(d/'run/audit.jsonl'),'directory':str(d)})
for d in sorted(root.glob('dev-*')):
 if not (d/'dev-result.json').exists():continue
 r=read(d/'dev-result.json');attempts.append({'run_id':d.name,'phase':'PRODUCT_DEV','route':r['receipt']['route'],'calls':r['calls'],'cost':r['upper_tariff_cost_cny'],'audit':verify_audit(d/'run/audit.jsonl'),'directory':str(d)})
for d in sorted(root.glob('protocol-v8-*')):
 if not (d/'protocol-result.json').exists():continue
 r=read(d/'protocol-result.json');attempts.append({'run_id':d.name,'phase':'PROTOCOL_CALIBRATION','route':r['receipt']['route'],'calls':r['calls'],'cost':r['cost'],'audit':verify_audit(d/'run/audit.jsonl'),'directory':str(d)})
costs=collections.defaultdict(float);calls=collections.defaultdict(int);models=set();latency=0;unknown=0
for a in attempts:
 costs[a['phase']]+=a['cost'];calls[a['phase']]+=a['calls']
 for p in (pathlib.Path(a['directory'])/'provider').glob('*.result.json'):
  r=read(p);models.add(r.get('upstream_model') or 'UNKNOWN');latency+=r.get('latency_ms',0)
  if not isinstance((r.get('usage') or {}).get('prompt_tokens'),int):unknown+=1
for i in range(0,32,2):
 p=rows[i:i+2];direct=next(r for r in p if r['route']=='R_DIRECT');cgnk=next(r for r in p if r['route']=='R_CGNK')
 assert p[0]['task_id']==p[1]['task_id'] and p[0]['registered_budget_cap_cny']==p[1]['registered_budget_cap_cny']
 pairs.append({'task_id':p[0]['task_id'],'version':p[0]['version'],'cap_each':p[0]['registered_budget_cap_cny'],'direct_calls':direct['calls'],'cgnk_calls':cgnk['calls'],'direct_cost':direct['cost_upper_cny'],'cgnk_cost':cgnk['cost_upper_cny'],'cost_difference_cgnk_minus_direct':round(cgnk['cost_upper_cny']-direct['cost_upper_cny'],8),'delivery_difference':0,'quality_difference':'UNDEFINED_NOT_FULLY_SCORED','unpaired':False})
ledger=read(root/'global-provider-budget.json');assert sum(a['calls'] for a in attempts)==ledger['totals']['api_calls'];assert abs(sum(a['cost'] for a in attempts)-ledger['totals']['estimated_cost'])<1e-8
assert ledger['totals']['estimated_cost']<=50
save(out/'matrix.json',{'rows':rows,'planned':32,'started':32,'not_run':0,'versions':{'v7':4,'v8':28}})
for kind in ['TAKEOVER','CREATE','REPEAT','SELF_EVOLVE']:save(out/(kind.lower()+'.json'),[r for r in rows if r['task_id'].startswith(kind+'-')])
save(out/'pairs.json',pairs);save(out/'all-attempts.json',attempts)
routecost={route:round(sum(a['cost'] for a in attempts if a['route']==route),8) for route in ['R_DIRECT','R_CGNK']}
runtime=subprocess.run(['docker','ps','--format','{{.Names}}'],capture_output=True,text=True);remaining=[n for n in runtime.stdout.splitlines() if n.startswith('eval076-')];assert not remaining,remaining
save(out/'cleanup.json',{'argv':['docker','ps','--format','{{.Names}}'],'exit':runtime.returncode,'stdout':runtime.stdout,'stderr':runtime.stderr,'remaining_iter076_containers':remaining})
summary={'iteration':'ITER-076','status':'ORIGINAL_MATRIX_EXECUTED_NO_AUTONOMOUS_DELIVERIES','source_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'freeze_v8_sha256':sha(sealpath),'budget_authority':read(root/'budget-authorization-v8.json'),'counts':{'product_dev':12,'protocol_calibration':2,'formal_planned':32,'formal_started_and_ended':32,'formal_inspected':32,'formal_autonomous_deliverable':0,'formal_not_deliverable':32,'formal_unverified_main_status':0,'formal_protocol_contaminated':0,'formal_not_run':0,'paid_model_attempts_total':len(attempts)},'benchmark_versions':{'v7':4,'v8':28,'warning':'Do not pool as a single unchanged frozen configuration. Report paired comparisons by version; all pair resources symmetric.'},'ledger_totals':ledger['totals'],'global_cumulative_cap_cny':50,'unused_authorization_cny':round(50-ledger['totals']['estimated_cost'],8),'acceptance_reserve_cny':0,'actual_bill':'NOT_QUERIED','cost_by_phase':dict(costs),'calls_by_phase':dict(calls),'all_attempt_cost_by_route':routecost,'actual_response_models':sorted(models),'known_missing_usage_calls':unknown,'provider_latency_sum_seconds':latency/1000,'cost_per_autonomous_delivery':'UNDEFINED_ZERO_DELIVERIES','protocol_outcome':'Direct: real model completed copy/readback and authored own protocol note in5 calls. CGNK: model supplied missing executor_ref on2nd call without host rewrite, then canonical DAG state mismatch; no copied output or note delivered.','product_outcome':'Every candidate retained only initial application/neutral scaffold, with some verbatim raw-source copies. TAKEOVER/repeat/evolution GUI startup/reopen inspected; CREATE had no application to launch. No domain workflow or candidate-authored business tests delivered.','score_scope':'B1,D1 confirmed0; evaluated weight10, pending90, range0..90 per candidate. Required conditions fail; no fabricated full scores or proxy human completion.','gates':'G2/G3 fail; CREATE G1 fail. Real platform unauthorized and human/domain quality unverified.','self_evolution':'Original first B0 snapshots only. Public minimal startup passed, despite missing domain functionality. No private scores/diagnosis transferred; no alternate baseline substituted. No new business evolution delivered.','interventions':read(root/'inspection-events-v8.json'),'regression':read(root/'regression-v8.json'),'direction_gate':read(root/'direction-gate-v8.json'),'conformance':'Both actual routes passed positive/negative/timeout/no-fallback checks in conformance-v8-01. Synthetic tail budget refusal separately tested.','stop_reason':'All32 original cells executed; no new tasks added to spend remaining money or seek a win.','next_minimal_validation':'A separately authorized DEV could test canonical incremental DAG/state compatibility and right-size task/token budgets. This completed sample must not be repaired or relabeled.','formal_semantic_assistance_count':0,'strong_model_rescue_calls':0,'private_feedback_to_formal_agents':0,'human_review':'PENDING_HUMAN','prior_records_preserved':True}
save(out/'summary.json',summary)
print(json.dumps({k:summary[k] for k in ['counts','ledger_totals','cost_by_phase','calls_by_phase','all_attempt_cost_by_route','unused_authorization_cny','provider_latency_sum_seconds']}))
